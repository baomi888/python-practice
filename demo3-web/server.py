"""Flask 后端 —— Baomi Agent 多会话管理 + 联网搜索。"""
import sys, os, json, time, uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

from client import DeepSeekClient

load_dotenv()

try:
    _ = DeepSeekClient()
except ValueError as e:
    print(f"启动失败：{e}")
    sys.exit(1)

SERPER_API_KEY = os.getenv("SERPER_API_KEY", "").strip()

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)

SESSIONS_DIR = Path(__file__).parent / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)

SERPER_URL = "https://google.serper.dev/search"


def do_web_search(query: str, num_results: int = 5) -> str:
    if not SERPER_API_KEY:
        raise RuntimeError("未配置 SERPER_API_KEY")
    try:
        resp = requests.post(
            SERPER_URL,
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            data=json.dumps({"q": query, "num": num_results}),
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("organic", [])
    except requests.RequestException as e:
        raise RuntimeError(f"搜索失败：{e}")
    if not results:
        return ""
    return "\n".join(
        f"{i}. {r.get('title','')}\n   {r.get('snippet','')}\n   来源：{r.get('link','')}"
        for i, r in enumerate(results, 1)
    )


# ========== 多会话管理 ==========
def _session_path(sid: str) -> Path:
    return SESSIONS_DIR / f"{sid}.json"


def list_sessions():
    sessions = []
    for f in sorted(SESSIONS_DIR.glob("*.json"), key=lambda p: -p.stat().st_mtime):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            sessions.append({
                "id": data.get("id"),
                "title": data.get("title", "新对话"),
                "created_at": data.get("created_at", 0),
                "msg_count": len([m for m in data.get("messages", []) if m.get("role") != "system"]),
            })
        except Exception:
            pass
    return sessions


def load_session(sid: str):
    p = _session_path(sid)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save_session(sid: str, title: str, messages: list, created_at: int = None):
    p = _session_path(sid)
    data = {
        "id": sid,
        "title": title,
        "created_at": created_at or int(time.time()),
        "messages": messages,
    }
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def delete_session(sid: str):
    p = _session_path(sid)
    if p.exists():
        p.unlink()
        return True
    return False


def new_session_id():
    return uuid.uuid4().hex[:12]


# ========== 路由 ==========
@app.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/sessions", methods=["GET"])
def api_list_sessions():
    return jsonify({"sessions": list_sessions()})


@app.route("/api/sessions", methods=["POST"])
def api_create_session():
    data = request.get_json(force=True, silent=True) or {}
    title = data.get("title", "新对话")
    sid = new_session_id()
    client = DeepSeekClient()
    save_session(sid, title, client.messages)
    return jsonify({"id": sid, "title": title})


@app.route("/api/sessions/<sid>", methods=["GET"])
def api_get_session(sid):
    sess = load_session(sid)
    if not sess:
        return jsonify({"error": "会话不存在"}), 404
    return jsonify(sess)


@app.route("/api/sessions/<sid>", methods=["DELETE"])
def api_delete_session(sid):
    ok = delete_session(sid)
    return jsonify({"ok": ok})


@app.route("/api/sessions/<sid>/rename", methods=["POST"])
def api_rename_session(sid):
    sess = load_session(sid)
    if not sess:
        return jsonify({"error": "会话不存在"}), 404
    data = request.get_json(force=True, silent=True) or {}
    title = data.get("title", sess.get("title", "新对话"))
    save_session(sid, title, sess["messages"], sess.get("created_at"))
    return jsonify({"ok": True})


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(force=True, silent=True) or {}
    sid = data.get("session_id", "").strip()
    message = data.get("message", "").strip()
    web_search = bool(data.get("web_search", False))

    if not sid:
        return jsonify({"error": "缺少 session_id"}), 400
    if not message:
        return jsonify({"error": "message 不能为空"}), 400

    sess = load_session(sid)
    if not sess:
        # 自动创建
        sess = {"id": sid, "title": "新对话", "messages": [], "created_at": int(time.time())}

    # 基于会话历史重建 DeepSeekClient
    client = DeepSeekClient()
    client.messages = list(sess.get("messages", []))

    actual_message = message
    searched = False
    if web_search:
        try:
            search_text = do_web_search(message, num_results=5)
            if search_text:
                actual_message = (
                    f"以下是我通过联网搜索找到的最新信息，请结合这些信息回答问题，"
                    f"引用信息时注明来源：\n\n{search_text}\n\n用户问题：{message}"
                )
                searched = True
        except RuntimeError as e:
            actual_message = f"[联网搜索失败：{e}]\n\n用户问题：{message}"

    try:
        reply = client.chat(actual_message)
    except PermissionError:
        return jsonify({"error": "认证失败"}), 401
    except ConnectionError:
        return jsonify({"error": "网络连接失败"}), 502
    except TimeoutError:
        return jsonify({"error": "请求超时"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # 自动生成标题（首条用户消息前 20 字）
    title = sess.get("title", "新对话")
    user_msgs = [m for m in client.messages if m.get("role") == "user"]
    if len(user_msgs) == 1 and title == "新对话":
        title = user_msgs[0].get("content", "新对话")[:20]

    save_session(sid, title, client.messages, sess.get("created_at"))

    return jsonify({
        "reply": reply,
        "model": client.model,
        "history_len": len(client.messages),
        "searched": searched,
        "title": title,
    })


@app.route("/api/sessions/<sid>/clear", methods=["POST"])
def api_clear_session(sid):
    sess = load_session(sid)
    if not sess:
        return jsonify({"error": "会话不存在"}), 404
    save_session(sid, sess.get("title", "新对话"), [], sess.get("created_at"))
    return jsonify({"ok": True})


@app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify({
        "status": "ok",
        "model": DeepSeekClient().model,
        "web_search": bool(SERPER_API_KEY),
        "sessions_count": len(list_sessions()),
    })


if __name__ == "__main__":
    print("Baomi Agent 服务启动中...")
    print("http://127.0.0.1:7860")
    app.run(host="127.0.0.1", port=7860, debug=False)
