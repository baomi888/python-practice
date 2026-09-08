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

# Playwright 可选依赖检测（爬虫模块集成）
# playwright 未安装 → 降级为纯 Serper snippet，零破坏
try:
    from playwright.sync_api import sync_playwright as _sync_pw  # noqa: F401
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False

# 文献下载可选依赖（crawler/paper_download.py）
# feedparser 未装 → /api/paper/* 路由返回友好提示
try:
    sys.path.insert(0, str(Path(__file__).parent / "crawler"))
    from paper_download import search_arxiv as _search_arxiv, download_pdf as _download_pdf
    _PAPER_AVAILABLE = True
except ImportError:
    _PAPER_AVAILABLE = False

# 文献下载目录（和 sessions/ 同级，启动时自动创建）
PAPERS_DIR = Path(__file__).parent / "papers"
PAPERS_DIR.mkdir(exist_ok=True)


def fetch_url_text(url: str, timeout: int = 8) -> str | None:
    """用 Playwright 真实浏览器打开 URL，提取页面正文文本。

    - playwright 未安装 → 返回 None（不影响主流程）
    - 启动顺序：优先本机 Edge（channel="msedge"）→ 退回 Chromium → 放弃
    - 抓取失败/超时 → 返回 None
    - 成功 → 返回清洗后的正文（去 script/style/空行，最大 2500 字符）
    """
    if not _PLAYWRIGHT_AVAILABLE:
        return None

    # 启动顺序：Edge → Chromium（Playwright 自带）
    launch_candidates = [
        {"headless": True, "channel": "msedge"},    # 优先本机 Edge（省下载）
        {"headless": True},                          # 退回 Chromium
    ]

    last_error = None
    for launch_kw in launch_candidates:
        try:
            with _sync_pw() as pw:
                browser = pw.chromium.launch(**launch_kw)
                page = browser.new_page(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"
                )
                # wait_until='load' 更稳，国内网络波动时 domcontentloaded 可能迟迟不到
                page.goto(url, timeout=max(timeout, 15) * 1000, wait_until="load")
                page.wait_for_timeout(2000)  # 等 JS 渲染（国内站点 2s 更稳）
                text = page.inner_text("body")
                browser.close()
            # 清洗：去空行 + 连续空白
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            cleaned = "\n".join(lines)
            # 去 script/style 痕迹（有时 inner_text 会残留）
            cleaned = re.sub(r'(?i)(script|style|noscript)[^>]*>', '', cleaned)
            return cleaned[:2500]  # 控制 token
        except Exception as e:
            last_error = e
            continue  # 尝试下一个浏览器

    print(f"  ⚠ Playwright 抓正文失败: {last_error}")
    return None


def do_web_search(query: str, num_results: int = 5) -> list:
    """执行联网搜索，返回结构化 sources 数组。

    两阶段：
    1. Serper API → 5 条搜索结果（title / snippet / link）
    2. Playwright（可选）→ 逐条打开链接抓网页正文 → sources.content

    playwright 未安装时自动降级为纯 Serper snippet。

    Returns:
        list[dict]: { source_id, title, snippet, link, content? }
    """
    if not SERPER_API_KEY:
        raise RuntimeError("未配置 SERPER_API_KEY")

    # --- 阶段 1：Serper 搜索 ---
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

    sources = [
        {
            "source_id": i,
            "title": r.get("title", ""),
            "snippet": r.get("snippet", ""),
            "link": r.get("link", ""),
        }
        for i, r in enumerate(results, 1)
    ]

    # --- 阶段 2：Playwright 正文抓取（可选增强） ---
    if _PLAYWRIGHT_AVAILABLE:
        # 国内网络黑名单：直连慢 / 需要翻墙的域名，跳过省时间
        BLOCKED_HOSTS = (
            "wikipedia.org", "wikimedia.org", "nobelprize.org",
            "nature.com", "science.org", "newsweek.com",
            "nytimes.com", "bbc.com", "bbc.co.uk",
            "theguardian.com", "reuters.com",
        )
        print(f"🔍 Playwright 正文抓取（共 {len(sources)} 条）...")
        t0 = time.time()
        for s in sources:
            # 总时间保护：45 秒到就停
            if time.time() - t0 > 45:
                print("  ⏱ 总时间到，停止后续抓取")
                break
            link = s["link"]
            if any(bh in link for bh in BLOCKED_HOSTS):
                print(f"  ⏭ [{s['source_id']}] {s['title'][:40]} → 黑名单域名跳过")
                continue
            content = fetch_url_text(link, timeout=12)  # 单 URL 超时 12s
            if content and len(content) > 50:  # 太短 = 没抓到有效内容
                s["content"] = content
                s["snippet"] = content[:300] + "..."
                print(f"  ✅ [{s['source_id']}] {s['title'][:40]} → {len(content)} chars")
            else:
                print(f"  ⏭ [{s['source_id']}] {s['title'][:40]} → 仅保留 Serper snippet")
        print(f"  总耗时 {time.time() - t0:.1f}s")

    return sources


def format_sources_for_llm(sources: list) -> str:
    """将 sources 数组格式化为 LLM 可见的搜索素材块。

    Playwright 增强：有 content 字段时，优先展示正文（截取前 1500 字符）；
    否则退回到 Serper snippet。这样 LLM 能拿到真正的网页内容，回答质量大幅提升。

    重要：绝对不能出现原始 URL。LLM 只看 source_id + title + 素材文本。
    """
    if not sources:
        return ""
    lines = ["以下是联网检索到的参考素材（source_id 即为引用编号）："]
    for s in sources:
        lines.append(f"[source_id={s['source_id']}] {s['title']}")
        content = s.get("content") or s.get("snippet", "")
        # content 可能很长，LLM prompt 里只展示前 1500 字符
        lines.append(f"  {content[:1500]}")
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


# ========== 文献下载（arXiv 合法免费） ==========

@app.route("/api/paper/search", methods=["POST"])
def api_paper_search():
    """只搜不下：返回 arXiv 搜索结果列表（含标题、作者、PDF 链接）。"""
    if not _PAPER_AVAILABLE:
        return jsonify({
            "error": "文献下载模块未启用，请执行: pip install feedparser"
        }), 500

    data = request.get_json(force=True) or {}
    query = (data.get("query") or "").strip()
    max_results = int(data.get("max", 5))

    if not query:
        return jsonify({"error": "缺少 query 参数"}), 400
    if max_results > 10:
        max_results = 10   # 硬上限

    try:
        results = _search_arxiv(query, max_results=max_results)
    except Exception as e:
        return jsonify({"error": f"arXiv 搜索失败: {e}"}), 502

    return jsonify({
        "query": query,
        "count": len(results),
        "results": results,
    })


@app.route("/api/paper/download", methods=["POST"])
def api_paper_download():
    """搜 arXiv + 自动下载 PDF 到 papers/ 目录。"""
    if not _PAPER_AVAILABLE:
        return jsonify({
            "error": "文献下载模块未启用，请执行: pip install feedparser"
        }), 500

    data = request.get_json(force=True) or {}
    query = (data.get("query") or "").strip()
    max_results = int(data.get("max", 3))

    if not query:
        return jsonify({"error": "缺少 query 参数"}), 400
    if max_results > 10:
        max_results = 10

    # 1. 搜
    try:
        results = _search_arxiv(query, max_results=max_results)
    except Exception as e:
        return jsonify({"error": f"arXiv 搜索失败: {e}"}), 502

    if not results:
        return jsonify({"error": "arXiv 没找到匹配论文"}), 404

    # 2. 下（用 requests Session，复用连接）
    session = requests.Session()
    session.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36")
    })

    downloaded = []
    for r in results:
        arxiv_id = r["arxiv_id"]
        filename_base = f"{arxiv_id.replace('.', '_')}_{re.sub(r'[\\/:*?"<>|]', '_', r['title'][:40])}"
        path = _download_pdf(session, r["pdf_url"], PAPERS_DIR, filename_base)
        if path:
            downloaded.append({
                "arxiv_id": arxiv_id,
                "title": r["title"],
                "filename": path.name,
                "size_kb": round(path.stat().st_size / 1024, 1),
            })
        time.sleep(0.5)  # 礼貌延时

    return jsonify({
        "query": query,
        "total": len(results),
        "downloaded_count": len(downloaded),
        "files": downloaded,
    })


@app.route("/api/paper/list", methods=["GET"])
def api_paper_list():
    """列 papers/ 目录下所有 PDF 文件。"""
    if not PAPERS_DIR.exists():
        return jsonify({"files": []})

    files = []
    for f in PAPERS_DIR.glob("*.pdf"):
        files.append({
            "filename": f.name,
            "size_kb": round(f.stat().st_size / 1024, 1),
            "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime)),
        })
    # 按修改时间倒序
    files.sort(key=lambda x: x["mtime"], reverse=True)
    return jsonify({"papers_dir": str(PAPERS_DIR), "files": files})


@app.route("/api/paper/file/<path:filename>", methods=["GET"])
def api_paper_file(filename):
    """直接下载已下的 PDF（浏览器弹出下载 / 内嵌预览）。"""
    safe_name = os.path.basename(filename)  # 防路径遍历
    if not safe_name.endswith(".pdf"):
        return jsonify({"error": "只允许 PDF"}), 400
    return send_from_directory(str(PAPERS_DIR), safe_name, as_attachment=True)


# ========== 通用资源搜索 + 下载 ==========

RESOURCES_DIR = Path(__file__).parent / "resources"
RESOURCES_DIR.mkdir(exist_ok=True)

# 目标文件扩展名 → 类型标签（前端显示用）
EXT_TYPE_MAP = {
    ".pdf": ("📄 PDF", "doc"),
    ".epub": ("📚 EPUB", "ebook"),
    ".mobi": ("📚 MOBI", "ebook"),
    ".txt": ("📝 文本", "text"),
    ".md": ("📝 Markdown", "text"),
    ".mp3": ("🎵 MP3", "audio"),
    ".wav": ("🎵 WAV", "audio"),
    ".flac": ("🎵 FLAC", "audio"),
    ".mp4": ("🎬 MP4", "video"),
    ".mov": ("🎬 MOV", "video"),
    ".avi": ("🎬 AVI", "video"),
    ".mkv": ("🎬 MKV", "video"),
    ".zip": ("📦 ZIP", "archive"),
    ".rar": ("📦 RAR", "archive"),
    ".7z": ("📦 7Z", "archive"),
    ".tar": ("📦 TAR", "archive"),
    ".gz": ("📦 GZ", "archive"),
    ".exe": ("🔧 EXE", "app"),
    ".dmg": ("🔧 DMG", "app"),
    ".apk": ("🔧 APK", "app"),
    ".whl": ("🐍 WHL", "python"),
    ".py": ("🐍 PY", "python"),
}

# 硬盗版 / 灰色站 blocklist（只拦绝对违法的，合法站放开让用户自己判断）
PIRACY_BLOCKLIST = (
    # 学术盗版
    "sci-hub", "libgen", "library genesis", "bookzz", "scihub",
    # 盗版 BT / 磁力
    "1337x", "thepiratebay", "kickass", "rarbg", "yts.mx", "yify",
    # 盗版 MP3 converter
    "mp3juice", "mp3converter", "freemp3", "mp3skull",
    # 常见盗版后缀
    ".torrent", "magnet:",
    # 盗版网盘聚合
    "aliyundrivepan", "aliyunpan",
)

# 正常网站（youtube / bilibili / iqiyi / youku / 百度文库 / CSDN 等）
# 不 block——里面有大量合法/免费/开放授权资源，让用户自己判断
# 但可以做标签提示，告诉用户"这是流媒体站，不是直链文件"


def _guess_filetype(url: str, content_type: str = "") -> tuple[str, str]:
    """从 URL 扩展名 / Content-Type 猜文件类型。"""
    from urllib.parse import urlparse, unquote
    ext = Path(unquote(urlparse(url).path)).suffix.lower()
    if ext in EXT_TYPE_MAP:
        return EXT_TYPE_MAP[ext]
    # Content-Type 兜底
    ct = content_type.lower()
    if "application/pdf" in ct: return ("📄 PDF", "doc")
    if "audio/mpeg" in ct or "audio/mp3" in ct: return ("🎵 MP3", "audio")
    if "video/mp4" in ct: return ("🎬 MP4", "video")
    if "application/zip" in ct: return ("📦 ZIP", "archive")
    if "application/epub" in ct: return ("📚 EPUB", "ebook")
    if "text/plain" in ct: return ("📝 文本", "text")
    if "application/json" in ct: return ("📄 JSON", "doc")
    return ("🔗 网页", "web")


def _classify_domain(url: str) -> str:
    """给域名打标签，帮助用户判断"这是直链文件还是流媒体页"。"""
    domain = url.split("/")[2] if "://" in url else ""
    domain = domain.lower()
    tags = []
    if any(d in domain for d in ("youtube.com", "youtu.be")):
        tags.append("▶️ YouTube")
    elif "bilibili.com" in domain:
        tags.append("▶️ B站")
    elif "iqiyi.com" in domain:
        tags.append("▶️ 爱奇艺")
    elif "youku.com" in domain:
        tags.append("▶️ 优酷")
    elif "qq.com" in domain:
        tags.append("▶️ 腾讯")
    elif "music.163.com" in domain or "163.com" in domain:
        tags.append("🎵 网易云")
    elif "kugou.com" in domain or "kuwo.cn" in domain:
        tags.append("🎵 酷狗/酷我")
    elif "baidu.com" in domain:
        tags.append("🔍 百度")
    elif "wenku.baidu.com" in domain:
        tags.append("📘 百度文库")
    elif "csdn.net" in domain:
        tags.append("💻 CSDN")
    elif "zhihu.com" in domain:
        tags.append("💬 知乎")
    elif "github.com" in domain:
        tags.append("🐙 GitHub")
    elif "gitee.com" in domain:
        tags.append("🐙 Gitee")
    elif "arxiv.org" in domain:
        tags.append("📚 arXiv")
    elif "google.com" in domain:
        tags.append("🔍 Google")
    return " · ".join(tags)


def _is_legit_resource(url: str, snippet: str = "") -> bool:
    """只拦硬盗版站，正常网站放开。"""
    hay = (url + " " + snippet).lower()
    for bad in PIRACY_BLOCKLIST:
        if bad in hay:
            return False
    return True


@app.route("/api/resource/search", methods=["POST"])
def api_resource_search():
    """通用资源搜索：多路 Serper 并发搜 → 合并去重 → HEAD 探测类型 → 返回。

    改进点：
    1. 多路并发（不加 filetype + 加 filetype:pdf/mp3/epub）→ 中文关键词也能命中文件
    2. HEAD 失败不丢弃结果 → 退回纯 URL 扩展名猜测
    3. 域名标签（🐙GitHub / ▶️B站 / 🎵网易云）
    4. 支持中国站（baidu / wenku / csdn / zhihu）—— 不 block
    """
    if not SERPER_API_KEY:
        return jsonify({"error": "未配置 SERPER_API_KEY"}), 500

    data = request.get_json(force=True) or {}
    query = (data.get("query") or "").strip()
    filetype_filter = (data.get("filetype") or "all").strip().lower()
    max_results = min(int(data.get("max", 10)), 20)

    if not query:
        return jsonify({"error": "缺少 query 参数"}), 400

    # ===== 构造多路 Serper 查询（Google + Bing 双引擎并发）=====
    # Google Serper：英文关键词强，Bing Serper：中文关键词 + 中文站强
    has_chinese = any('\u4e00' <= c <= '\u9fff' for c in query)

    # 中文关键词：基础查询 + 加辅助词（下载/免费/官方/site:cn）提升中文站命中
    base_queries = [query]
    if has_chinese:
        base_queries.extend([
            f"{query} 下载",
            f"{query} 免费",
            f"{query} 官方",
        ])

    queries_by_engine = {}
    for eng in ["google", "bing"]:
        q_list = list(base_queries)
        if filetype_filter != "all":
            ft_suffix_map = {
                "doc":   ["filetype:pdf", "filetype:doc"],
                "ebook": ["filetype:epub", "filetype:mobi"],
                "audio": ["filetype:mp3", "filetype:wav"],
                "video": ["filetype:mp4", "filetype:mkv"],
                "archive": ["filetype:zip", "filetype:rar"],
                "app":   ["filetype:exe", "filetype:apk"],
                "python": ["filetype:py", "filetype:whl"],
                "text":  ["filetype:txt", "filetype:md"],
            }
            for suffix in ft_suffix_map.get(filetype_filter, []):
                q_list.append(f"{query} {suffix}")
        queries_by_engine[eng] = q_list

    # ===== 并发发 Serper（多引擎 × 多查询）=====
    import concurrent.futures
    all_organic = []
    seen_urls = set()

    def _serper_one(q, engine="google"):
        try:
            payload = {"q": q, "num": 8}
            if engine != "google":
                payload["engine"] = engine  # bing / duckduckgo / youtube
            resp = requests.post(
                SERPER_URL,
                headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=12,
            )
            resp.raise_for_status()
            return resp.json().get("organic", [])
        except Exception:
            return []

    tasks = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for eng, qlist in queries_by_engine.items():
            for q in qlist:
                tasks.append(pool.submit(_serper_one, q, eng))
        for fut in concurrent.futures.as_completed(tasks):
            for r in fut.result():
                url = r.get("link", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_organic.append(r)

    if not all_organic:
        return jsonify({"error": "Serper 返回空结果（可能网络问题）"}), 502

    # ===== 去盗版 + HEAD 探测 =====
    results = []
    for r in all_organic:
        url = r.get("link", "")
        if not _is_legit_resource(url, r.get("snippet", "")):
            continue

        title = r.get("title", "")
        snippet = r.get("snippet", "")[:200]
        domain_tag = _classify_domain(url)
        domain_raw = url.split("/")[2] if "://" in url else url[:30]

        # HEAD 探类型（超时 3 秒，失败继续——用 URL 扩展名兜底）
        ct = ""
        size_kb = None
        try:
            head = requests.head(url, timeout=3, allow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 Chrome/122"})
            ct = head.headers.get("Content-Type", "")
            cl = head.headers.get("Content-Length", "0")
            if cl.isdigit():
                size_kb = round(int(cl) / 1024, 1)
        except Exception:
            pass  # 失败不丢弃，下面 _guess_filetype 会用 URL 扩展名兜底

        ft_label, ft_cat = _guess_filetype(url, ct)

        # 类型过滤（用户选了 PDF 就只留 doc）
        if filetype_filter != "all" and filetype_filter != ft_cat:
            continue

        results.append({
            "title": title,
            "snippet": snippet,
            "domain": domain_raw,
            "domain_tag": domain_tag,       # 🐙 GitHub / ▶️ B站 等
            "link": url,
            "filetype_label": ft_label,     # 📄 PDF / 🔗 网页
            "filetype_cat": ft_cat,         # doc / web
            "size_kb": size_kb,
        })

        if len(results) >= max_results:
            break

    # 排序：有直链文件的放前面（非 web 类型优先）
    results.sort(key=lambda x: (x["filetype_cat"] == "web", x.get("size_kb") is None))

    return jsonify({
        "query": query,
        "count": len(results),
        "filetype_filter": filetype_filter,
        "results": results,
    })


@app.route("/api/resource/download", methods=["POST"])
def api_resource_download():
    """下载用户选中的那个文件：HTTP GET 直链 → 流式写入 resources/。"""
    data = request.get_json(force=True) or {}
    url = (data.get("url") or "").strip()
    filename = (data.get("filename") or "").strip()

    if not url or not url.startswith(("http://", "https://")):
        return jsonify({"error": "缺少有效 url"}), 400
    if not _is_legit_resource(url):
        return jsonify({"error": "该资源疑似盗版/灰色来源，合规红线禁止下载"}), 403

    try:
        session = requests.Session()
        session.headers.update({
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36")
        })

        # HEAD 先拿 Content-Disposition（优先服务器给的文件名）
        try:
            head = session.head(url, timeout=10, allow_redirects=True)
            cd = head.headers.get("Content-Disposition", "")
            cd_name = re.search(r'filename\s*=\s*(?:["\']?)([^"\';]+)', cd, re.I)
            if cd_name:
                filename = cd_name.group(1).strip()
            cl = head.headers.get("Content-Length", "0")
        except Exception:
            cl = "0"

        # 没有 filename → 从 URL 猜
        if not filename:
            from urllib.parse import urlparse, unquote
            path = unquote(urlparse(url).path)
            filename = Path(path).name or "download"

        filename = re.sub(r'[\\/:*?"<>|]', "_", filename).strip()[:150]

        # 重名去重
        save_path = RESOURCES_DIR / filename
        counter = 2
        while save_path.exists():
            stem, suffix = Path(filename).stem, Path(filename).suffix
            save_path = RESOURCES_DIR / f"{stem}_{counter}{suffix}"
            counter += 1

        # GET 流式下载
        resp = session.get(url, stream=True, timeout=(10, 120), allow_redirects=True)
        if resp.status_code in (401, 403):
            return jsonify({"error": "HTTP 403 —— 需要登录 / 没权限"}), 403
        if resp.status_code >= 400:
            return jsonify({"error": f"HTTP {resp.status_code}"}), 400

        save_path.parent.mkdir(parents=True, exist_ok=True)
        done = 0
        with open(save_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if chunk:
                    f.write(chunk)
                    done += len(chunk)

        size_kb = round(save_path.stat().st_size / 1024, 1)
        if size_kb < 3:   # 太小 = 不是真文件（可能是 HTML 错误页）
            save_path.unlink()
            return jsonify({"error": f"下载的文件过小（{size_kb} KB），可能是错误页"}), 400

        return jsonify({
            "ok": True,
            "filename": save_path.name,
            "size_kb": size_kb,
            "path": str(save_path),
        })

    except requests.RequestException as e:
        return jsonify({"error": f"下载失败: {e}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/resource/file/<path:filename>", methods=["GET"])
def api_resource_file(filename):
    """直接打开/下载已下的资源。"""
    safe = os.path.basename(filename)
    return send_from_directory(str(RESOURCES_DIR), safe, as_attachment=True)


@app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify({
        "status": "ok",
        "model": DeepSeekClient().model,
        "web_search": bool(SERPER_API_KEY),
        "playwright": _PLAYWRIGHT_AVAILABLE,
        "paper_download": _PAPER_AVAILABLE,
        "sessions_count": len(list_sessions()),
    })


if __name__ == "__main__":
    print("Baomi Agent 服务启动中...")
    print("http://127.0.0.1:7860")
    app.run(host="127.0.0.1", port=7860, debug=False)
