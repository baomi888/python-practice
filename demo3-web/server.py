"""Flask 后端 —— Baomi Agent 多会话管理 + 联网搜索 + 文件上传。"""
import sys, os, json, time, uuid, base64, re
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


def do_web_search(query: str, num_results: int = 5) -> list:
    """执行联网搜索，返回结构化 sources 数组。

    Returns:
        list[dict]: 每个元素包含 source_id、title、snippet、link
                    搜索失败或无结果时返回空列表。
    """
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
        return []
    return [
        {
            "source_id": i,
            "title": r.get("title", ""),
            "snippet": r.get("snippet", ""),
            "link": r.get("link", ""),
        }
        for i, r in enumerate(results, 1)
    ]


def format_sources_for_llm(sources: list) -> str:
    """将 sources 数组格式化为 LLM 可见的搜索素材块。

    重要：绝对不能出现原始 URL，LLM 只看 source_id + title + snippet。
    这样可以引导 LLM 只输出 source_id 角标，而不会把 URL 输出到回答里。
    """
    if not sources:
        return ""
    lines = ["以下是联网检索到的参考素材（source_id 即为引用编号）："]
    for s in sources:
        lines.append(f"[source_id={s['source_id']}] {s['title']}")
        lines.append(f"  {s['snippet']}")
    return "\n".join(lines)


# ========== 文件上传解析 ==========
SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
SUPPORTED_TEXT_EXTS = {".txt", ".md"}
SUPPORTED_DOC_EXTS = {".pdf"}
SUPPORTED_EXTS = SUPPORTED_IMAGE_EXTS | SUPPORTED_TEXT_EXTS | SUPPORTED_DOC_EXTS

IMAGE_MIME_MAP = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def parse_uploaded_file(file_storage) -> dict:
    """解析上传的单个文件，返回结构化结果。

    Returns:
        dict: { filename, ext, kind: "image"|"text"|"pdf", content,
               mimetype, size, error? }
    """
    filename = file_storage.filename or "unknown"
    ext = Path(filename).suffix.lower()
    size = 0

    if ext not in SUPPORTED_EXTS:
        return {
            "filename": filename, "ext": ext, "kind": "unsupported",
            "content": None, "mimetype": "", "size": 0,
            "error": f"不支持的文件类型 {ext}，仅支持图片(txt/md/pdf/jpg/png/gif/webp)",
        }

    raw = file_storage.read()
    size = len(raw)

    # 大小限制（10MB）
    if size > 10 * 1024 * 1024:
        return {
            "filename": filename, "ext": ext, "kind": "too_large",
            "content": None, "mimetype": "", "size": size,
            "error": "文件超过 10MB 限制",
        }

    try:
        if ext in SUPPORTED_IMAGE_EXTS:
            # 图片 → base64
            b64 = base64.b64encode(raw).decode("utf-8")
            mime = IMAGE_MIME_MAP.get(ext, "image/png")
            return {
                "filename": filename, "ext": ext, "kind": "image",
                "content": b64, "mimetype": mime, "size": size,
            }

        elif ext in SUPPORTED_TEXT_EXTS:
            # txt / md → 直接读文本
            text = raw.decode("utf-8", errors="replace")
            return {
                "filename": filename, "ext": ext, "kind": "text",
                "content": text, "mimetype": "text/plain", "size": size,
            }

        elif ext in SUPPORTED_DOC_EXTS:
            # PDF → 提取文本（延迟导入 PyPDF2）
            text = _extract_pdf_text(raw)
            return {
                "filename": filename, "ext": ext, "kind": "pdf",
                "content": text, "mimetype": "application/pdf", "size": size,
            }
    except Exception as e:
        return {
            "filename": filename, "ext": ext, "kind": "error",
            "content": None, "mimetype": "", "size": size,
            "error": f"文件解析失败：{e}",
        }


def _extract_pdf_text(raw_bytes: bytes) -> str:
    """从 PDF 字节中提取文本。延迟导入 PyPDF2 避免启动开销。"""
    import io
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        raise RuntimeError("PyPDF2 未安装，请先 pip install PyPDF2")

    reader = PdfReader(io.BytesIO(raw_bytes))
    pages = []
    for i, page in enumerate(reader.pages):
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    text = "\n".join(pages).strip()
    # 清理 PDF 常见垃圾字符
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text or "[PDF 内容为空或无法提取文本]"


def build_user_content_with_files(message: str, file_results: list) -> tuple:
    """根据文件解析结果组装 user message 和多模态 image_url 列表。

    Returns:
        (text_content: str, image_blocks: list)
        - text_content: 拼好的文本（含用户问题 + 文本型文件内容）
        - image_blocks: [{type:"image_url", image_url:{url:"data:..."}}]
          如果没有图片则为空列表
    """
    text_parts = []
    image_blocks = []

    for f in file_results:
        if f.get("error") or f["kind"] in ("unsupported", "too_large", "error"):
            continue
        if f["kind"] in ("text", "pdf"):
            text_parts.append(
                f"--- 文件 {f['filename']} 内容({f['kind']}) ---\n"
                f"{f['content']}"
            )
        elif f["kind"] == "image":
            image_blocks.append({
                "type": "image_url",
                "image_url": {"url": f"data:{f['mimetype']};base64,{f['content']}"},
            })

    text_parts.append(f"用户问题：{message}")
    text_content = "\n\n".join(text_parts)
    return text_content, image_blocks


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
    file_results = data.get("files", []) or []

    if not sid:
        return jsonify({"error": "缺少 session_id"}), 400
    if not message:
        return jsonify({"error": "message 不能为空"}), 400

    sess = load_session(sid)
    if not sess:
        sess = {"id": sid, "title": "新对话", "messages": [], "created_at": int(time.time())}

    client = DeepSeekClient()
    client.messages = list(sess.get("messages", []))
    client.ensure_system_prompt()

    # ========== 联网搜索 ==========
    sources = []
    searched = False
    if web_search:
        try:
            sources = do_web_search(message, num_results=5)
            searched = True
        except RuntimeError:
            pass

    # ========== 文件：文本进 user_content，图片进 image_blocks ==========
    text_files = [f for f in file_results if f.get("kind") in ("text", "pdf")]
    image_files = [f for f in file_results if f.get("kind") == "image" and f.get("content")]

    text_file_content, image_blocks = build_user_content_with_files(message, file_results)

    # ========== 组装完整 LLM user message ==========
    user_content_parts = []
    if sources:
        user_content_parts.append(format_sources_for_llm(sources))
    elif searched:
        user_content_parts.append("[联网检索未获得有效素材，请根据已有知识回答]")

    # 文件文本 + 用户问题（build_user_content_with_files 已把两者拼好了）
    user_content_parts.append(text_file_content)

    actual_message = "\n\n".join(user_content_parts)

    # ========== 调用 LLM ==========
    try:
        reply = client.chat_with_override(
            clean_user_message=message,
            llm_user_message=actual_message,
            sources=sources if searched else None,
            image_blocks=image_blocks if image_blocks else None,
            user_files=file_results if file_results else None,
        )
    except PermissionError:
        return jsonify({"error": "认证失败"}), 401
    except ConnectionError:
        return jsonify({"error": "网络连接失败"}), 502
    except TimeoutError:
        return jsonify({"error": "请求超时"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    title = sess.get("title", "新对话")
    user_msgs = [m for m in client.messages if m.get("role") == "user"]
    if len(user_msgs) == 1 and title == "新对话":
        title = message[:20]

    save_session(sid, title, client.messages, sess.get("created_at"))

    return jsonify({
        "reply": reply,
        "model": client.model,
        "history_len": len(client.messages),
        "searched": searched,
        "sources": sources,
        "title": title,
    })


@app.route("/api/upload", methods=["POST"])
def api_upload():
    """文件上传接口 —— multipart/form-data，支持多文件。

    Returns:
        json: { files: [ {filename, kind, content, mimetype, size, error?} ] }
        图片返回 base64，txt/md/pdf 返回提取后的文本。
    """
    uploads = request.files.getlist("files") or request.files.getlist("file")
    if not uploads:
        return jsonify({"error": "未收到文件"}), 400

    results = [parse_uploaded_file(f) for f in uploads]
    # 简化返回：前端只需知道 kind + content + 基本元信息
    simplified = []
    for r in results:
        entry = {
            "filename": r["filename"],
            "kind": r["kind"],       # image / text / pdf / unsupported / too_large / error
            "mimetype": r.get("mimetype", ""),
            "size": r["size"],
        }
        if r.get("error"):
            entry["error"] = r["error"]
        elif r.get("content") is not None:
            entry["content"] = r["content"]
        simplified.append(entry)

    return jsonify({"files": simplified})


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
