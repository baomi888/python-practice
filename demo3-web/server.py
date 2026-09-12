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
            data=json.dumps({"q": query, "num": num_results,
                             "gl": "cn", "hl": "zh-cn",  # 🔑 关键：中国地区 + 中文语言
                             "autocorrect": True}),
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

    # --- 阶段 2：Playwright 正文抓取（可选增强，并发！） ---
    if _PLAYWRIGHT_AVAILABLE:
        BLOCKED_HOSTS = (
            "wikipedia.org", "wikimedia.org", "nobelprize.org",
            "nature.com", "science.org", "newsweek.com",
            "nytimes.com", "bbc.com", "bbc.co.uk",
            "theguardian.com", "reuters.com",
        )
        import concurrent.futures
        print(f"🔍 Playwright 正文抓取（{len(sources)} 条 × 并发 3）...")
        t0 = time.time()

        # 先准备好要抓的列表（跳过黑名单）
        to_fetch = [(i, s) for i, s in enumerate(sources)
                    if not any(bh in s["link"] for bh in BLOCKED_HOSTS)]
        blocked_count = len(sources) - len(to_fetch)

        def _fetch_one(idx, s):
            """抓一条，返回 (idx, content_or_None)"""
            content = fetch_url_text(s["link"], timeout=12)
            if content and len(content) > 50:
                return (idx, content)
            return (idx, None)

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(_fetch_one, i, s): i for i, s in to_fetch}
            for fut in concurrent.futures.as_completed(futures):
                idx, content = fut.result()
                if content:
                    sources[idx]["content"] = content
                    sources[idx]["snippet"] = content[:300] + "..."

        elapsed = time.time() - t0
        print(f"  ✅ Playwright 完成：{sum(1 for s in sources if 'content' in s)}/{len(sources)} 条有正文，耗时 {elapsed:.1f}s（跳过黑名单 {blocked_count}）")

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


# ========== 对话里自动触发联网搜索的关键词 ==========
# 不局限于用户手动勾联网搜索 —— AI 自己判断要不要搜
_SEARCH_TRIGGER_KEYWORDS = [
    "下载", "下一个", "给我", "帮我找", "帮我下", "哪里有", "在哪找", "哪里下载", "去哪下",
    "找一下", "搜一下", "查一下", "最新", "最近", "今天", "现在",
    "软件", "APP", "APK", "EXE", "工具", "程序",
    "PDF", "论文", "文献", "教程", "电子书", "资料", "电子书",
    "音乐", "视频", "电影", "图片", "壁纸",
    "官方", "官网", "版本", "release",
    "豆包", "deepseek", "kimi", "glm", "claude", "chatgpt", "gemini",
    "github", "gitlab",
]


def _auto_should_search(message: str, user_explicit_search: bool) -> tuple[bool, str]:
    """自动判断用户是否需要联网搜索 / 资源查找。

    Returns:
        (should_search, intent_tag)
        intent_tag: "resource"（找下载资源）| "info"（普通搜索）| ""（不需要）
    """
    if user_explicit_search:
        return True, "info"

    msg = message.lower()
    hit = any(kw.lower() in msg for kw in _SEARCH_TRIGGER_KEYWORDS)
    if not hit:
        return False, ""

    # 区分"下载资源"意图 vs "普通搜信息"意图
    resource_kw = ["下载", "下", "给我", "软件", "app", "apk", "exe", "工具",
                   "pdf", "论文", "文献", "电子书", "在哪里下", "去哪下", "哪里下载",
                   "下一个"]
    is_resource = any(kw in message.lower() for kw in resource_kw)
    return True, "resource" if is_resource else "info"


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

    # ========== AI 自动判断是否需要搜索 ==========
    should_search, intent_tag = _auto_should_search(message, web_search)

    # ========== 联网搜索 ==========
    sources = []
    searched = False
    if should_search:
        try:
            sources = do_web_search(message, num_results=8)  # 多拿点给 LLM 筛选
            searched = True
        except RuntimeError:
            pass

    # ========== 如果是资源查找意图，额外跑一轮 resource_search ==========
    resource_results = []
    if should_search and intent_tag == "resource":
        try:
            resource_results = _run_resource_search(message)
        except Exception:
            pass

    # ========== 文件：文本进 user_content，图片进 image_blocks ==========
    text_file_content, image_blocks = build_user_content_with_files(message, file_results)

    # ========== 组装完整 LLM user message ==========
    user_content_parts = []

    if resource_results:
        # 资源查找：用专门的格式喂给 LLM
        resource_prompt = _format_resource_results_for_llm(message, resource_results)
        user_content_parts.append(resource_prompt)
    elif sources:
        user_content_parts.append(format_sources_for_llm(sources))
    elif searched:
        user_content_parts.append("[联网检索未获得有效素材，请根据已有知识回答]")

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

    # 把 resource_results 也塞回给前端渲染成卡片
    all_sources = list(sources)
    if resource_results:
        all_sources.extend(resource_results)

    return jsonify({
        "reply": reply,
        "model": client.model,
        "history_len": len(client.messages),
        "searched": searched,
        "sources": all_sources,
        "resource_results": resource_results if resource_results else None,
        "title": title,
    })


# ========== 资源搜索（用于 LLM 对话里的自动查找）==========

def _run_resource_search(query: str, max_results: int = 6) -> list:
    """在对话里自动调资源搜索 —— 复用 /api/resource/search 的核心逻辑。

    直接 import 内部函数，避免 HTTP 自调用的额外开销。
    """
    if not SERPER_API_KEY:
        return []

    from urllib.parse import urlparse, unquote
    import concurrent.futures

    # 多路查询（基础 + 中文辅助词 + filetype 后缀）
    has_chinese = any('\u4e00' <= c <= '\u9fff' for c in query)
    base_queries = [query]
    if has_chinese:
        base_queries.extend([f"{query} 下载", f"{query} 官方", f"{query} 免费"])

    all_queries = list(base_queries)
    for suffix in ["filetype:pdf", "filetype:zip", "filetype:apk", "filetype:exe"]:
        all_queries.append(f"{query} {suffix}")

    all_organic = []
    seen = set()

    def _serper_one(q, engine="google"):
        try:
            payload = {"q": q, "num": 6, "gl": "cn", "hl": "zh-cn", "autocorrect": True}
            if engine != "google":
                payload["engine"] = engine
            resp = requests.post(
                SERPER_URL,
                headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json().get("organic", [])
        except Exception:
            return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        tasks = []
        for q in all_queries:
            tasks.append(pool.submit(_serper_one, q))
            tasks.append(pool.submit(_serper_one, q, "bing"))
        for fut in concurrent.futures.as_completed(tasks):
            for r in fut.result():
                url = r.get("link", "")
                if url and url not in seen:
                    seen.add(url)
                    all_organic.append(r)

    # 去盗版过滤（便宜，串行）
    candidates = []
    for r in all_organic:
        url = r.get("link", "")
        if not _is_legit_resource(url, r.get("snippet", "")):
            continue
        candidates.append(r)

    # HEAD 探测 + 打分（并发！max_workers=8）
    def _head_and_score(r):
        url = r.get("link", "")
        title = r.get("title", "")
        snippet = r.get("snippet", "")[:200]
        domain_raw = url.split("/")[2] if "://" in url else ""

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
            pass

        ft_label, ft_cat = _guess_filetype(url, ct)
        score = _score_resource(url, ct, size_kb, "")

        return {
            "title": title,
            "snippet": snippet,
            "domain": domain_raw,
            "link": url,
            "filetype_label": ft_label,
            "filetype_cat": ft_cat,
            "size_kb": size_kb,
            "score": round(score, 1),
            "resource": True,
        }

    results = []
    if candidates:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(_head_and_score, r) for r in candidates]
            for fut in concurrent.futures.as_completed(futures):
                try:
                    item = fut.result()
                    # 超小假文件拦截
                    if (item["size_kb"] is not None and 0 < item["size_kb"] < 3
                            and item["filetype_cat"] in ("app", "audio", "video")):
                        continue
                    results.append(item)
                except Exception:
                    pass

    # 信誉分排序
    results.sort(key=lambda x: x["score"], reverse=True)

    # ===== 结果太少 → 自动 fallback：换关键词再搜一轮 =====
    if len(results) < 3:
        fallback_queries = _build_fallback_queries(query)
        for fb_q in fallback_queries:
            if fb_q == query:
                continue
            fb_extra = _run_resource_search(fb_q, max_results=3)
            # 去重（按 link）
            existing_links = {r["link"] for r in results}
            for fb in fb_extra:
                if fb["link"] not in existing_links:
                    results.append(fb)
            if len(results) >= 5:
                break
        results.sort(key=lambda x: x["score"], reverse=True)

    # 截断 + 加上 fallback_suggestions（给前端和 LLM 显示替代关键词）
    final_results = results[:max_results]
    if len(final_results) < 3:
        # 结果还是少 → 告诉用户"试试换这些关键词"
        final_results.extend(_build_suggestion_cards(query, fallback_queries if 'fallback_queries' in dir() else []))
    return final_results


# ========== 资源查找 fallback 辅助 ==========

def _build_fallback_queries(query: str) -> list:
    """根据原始 query 生成 2~3 个替代关键词（英文 / 换后缀 / 加 github 等）。"""
    q = query.strip()
    out = []

    # 1. 去掉"下载/下一个/给我/哪里有/在哪找"等指令词，保留核心名词
    strip_words = ["下载", "下一个", "给我", "帮我", "找一下", "搜一下", "查一下",
                   "哪里有", "在哪找", "哪里下载", "去哪下", "在哪下载", "下", "找", "搜", "查"]
    core = q
    for w in strip_words:
        core = core.replace(w, " ").strip()
    if core and core != q:
        out.append(core)

    # 2. 加英文辅助后缀
    english_helpers = ["github", "official", "官网", "下载", "download", "release"]
    for h in english_helpers[:3]:
        fb = f"{core} {h}".strip()
        if fb and fb not in out:
            out.append(fb)

    # 3. 如果是中文，加英文转拼音可能不靠谱，直接保留原 query + filetype:pdf 兜底
    out.append(f"{core} filetype:pdf" if core else f"{q} filetype:pdf")
    out.append(f"{core} site:github.com" if core else f"{q} site:github.com")

    # 去重 + 去空
    seen = set()
    clean = []
    for x in out:
        x = x.strip()
        if x and x not in seen and x != q:
            seen.add(x)
            clean.append(x)
    return clean[:4]


def _build_suggestion_cards(original_query: str, fallback_queries: list) -> list:
    """当真的找不到结果时，生成「建议卡片」——前端渲染成灰色提示卡。"""
    cards = []
    # 通用建议
    tips = [
        ("换关键词试试", f"比如：{', '.join(fallback_queries[:3])}" if fallback_queries else "试试更短的关键词，或去掉「下载/给我」等指令词"),
        ("换类型试试", "如果要软件 → 加 site:github.com；要论文 → 加 filetype:pdf"),
        ("用英文搜", f'"{_to_ascii_if_chinese(original_query)}" 英文关键词在 Google 上结果通常更多'),
        ("直接说在对话框", "把需求说完整：「帮我下载豆包 Windows 客户端」比「下豆包」效果好"),
    ]
    for title, desc in tips:
        cards.append({
            "title": title,
            "snippet": desc,
            "domain": "",
            "link": "",
            "filetype_label": "💡 建议",
            "filetype_cat": "suggestion",  # 前端识别这个 type → 渲染成灰色提示卡
            "size_kb": None,
            "score": 0,
            "resource": False,
            "is_suggestion": True,
        })
    return cards


def _to_ascii_if_chinese(text: str) -> str:
    """粗转中文为 ASCII 辅助（简单拆分，真要拼音用 pypinyin 但我们不引入新依赖）。"""
    has_chinese = any('\u4e00' <= c <= '\u9fff' for c in text)
    if not has_chinese:
        return text
    # 简单策略：把中文词用空格分割，保留英文部分
    result = ""
    for c in text:
        if '\u4e00' <= c <= '\u9fff':
            result += " "
        else:
            result += c
    return result.strip() or text


def _format_resource_results_for_llm(user_query: str, resource_results: list) -> str:
    """把资源搜索结果喂给 LLM，让 LLM 来筛选 + 推荐 + 组织语言。"""
    lines = [f"[用户要找/下载: {user_query}]"]
    lines.append("")
    lines.append("[以下是联网搜索到的候选资源，你需要筛选、推荐、组织成自然语言回复给用户]")
    lines.append("")
    lines.append("候选资源列表（按信誉分从高到低排序）：")
    for i, r in enumerate(resource_results, 1):
        size = f"{r['size_kb']} KB" if r.get("size_kb") else "未知大小"
        lines.append(f"  {i}. [{r['filetype_label']}] {r['title']}")
        lines.append(f"     来源: {r['domain']}  大小: {size}  信誉分: {r['score']}")
        if r.get("snippet"):
            lines.append(f"     摘要: {r['snippet'][:120]}")
    lines.append("")
    lines.append("你的任务：")
    lines.append("1. 从候选里挑 2~4 个最可信的推荐给用户")
    lines.append("2. 优先官方源、GitHub Releases、sourceforge 等可信聚合站")
    lines.append("3. 谨慎推荐 apkpure/uptodown 这类有广告的第三方站，要提醒用户")
    lines.append("4. 每个推荐包含：名称 + 为什么推荐 + 下载入口提示")
    lines.append("5. 如果没有找到合适的资源，如实说")
    lines.append("")
    return "\n".join(lines)


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

# 盗版 / 硬违法 blocklist（绝对不能碰）
PIRACY_BLOCKLIST = (
    "sci-hub", "libgen", "library genesis", "bookzz", "scihub",
    "1337x", "thepiratebay", "kickass", "rarbg", "yts.mx", "yify",
    "mp3juice", "mp3converter", "freemp3", "mp3skull",
    ".torrent", "magnet:",
    "aliyundrivepan", "aliyunpan",
)

# 官方下载源域名（高优先级）
OFFICIAL_DOWNLOAD_DOMAINS = (
    # AI / App 官网
    "doubao.com",          # 豆包
    "doubao.com/download",
    "chatglm.cn",
    "tongyi.aliyun.com",
    "kimi.moonshot.cn",
    "xinghuo.xfyun.cn",
    "github.com",
    "gitlab.com",
    # 平台 & 官方
    "microsoft.com", "aka.ms", "visualstudio.com",
    "apple.com", "developer.apple.com", "apps.apple.com",
    "play.google.com", "developer.android.com",
    "developer.chrome.com",
    "download.com", "majorgeeks.com", "softpedia.com",
    "ninite.com", "winapps.org", "chocolatey.org", "winget.run", "scoop.sh",
    # 开发者工具
    "nodejs.org", "python.org", "anaconda.org", "pypi.org", "npmjs.com",
    "wireshark.org", "blender.org", "gimp.org", "inkscape.org",
    "jetbrains.com", "vscode.dev", "code.visualstudio.com",
    "developer.mozilla.org", "learn.microsoft.com",
    # CDN
    "cdn.jsdelivr.net", "githubusercontent.com",
    "dl.google.com", "redirector.gvt1.com",
    # 开源 / 免费资源聚合
    "sourceforge.net", "dl.sourceforge.net",
    "archive.org", "gutenberg.org", "librivox.org",
    "freemusicarchive.org", "jamendo.com",
)

# URL 路径里包含这些关键词 → 是下载页面 / 文件
_DOWNLOAD_PATH_KEYWORDS = (
    "download", "downloads", "release", "releases", "dl", "bin", "install",
    "setup", "setup.exe", "installer", "portable", ".dmg", ".exe", ".msi",
    ".apk", ".zip", ".7z", ".tar.gz",
)

# 高风险广告 / 假下载站（比 PIRACY_BLOCKLIST 更宽，拦截假 APK/EXE）
SHADY_AD_DOMAINS = (
    "apkpure.com", "apkmirror.com", "apkcombo.com", "apkmonk.com",
    "cnet.com",           # 允许但标记（因为 CNET 的 download.com 还可以）
    "softonic.com",
    "uptodown.com",
    "filehippo.com",      # 允许但标记
)


def _score_resource(url: str, ct: str, size_kb, domain_tag: str) -> float:
    """给结果打信誉分（0~100），用于排序。分越高越排前面。"""
    score = 50.0
    low = url.lower()

    # 1. 真实文件类型加分（HEAD 检测不是 application/html）
    if ct and "text/html" not in ct.lower():
        score += 15
    elif ct and "application/octet-stream" in ct.lower():
        score += 8   # 可能是文件，也可能是广告，保守

    # 2. 文件大小合理加分（软件至少几 MB，7.2 KB 的 APK 肯定是假的）
    if size_kb and size_kb > 0:
        if size_kb >= 512:        # ≥ 512 KB，基本可信
            score += 10
        elif size_kb >= 50:       # 50~512 KB，一般
            score += 3
        else:                     # < 50 KB 的 .exe/.apk —— 很可疑！
            score -= 25

    # 3. 域名在官方下载源列表
    for d in OFFICIAL_DOWNLOAD_DOMAINS:
        if d in low:
            score += 20
            break

    # 4. URL 路径含 download/release/install 等关键词
    for kw in _DOWNLOAD_PATH_KEYWORDS:
        if kw in low:
            score += 8
            break

    # 5. GitHub Release 特殊加分（最可信的开源软件源）
    if "github.com" in low and ("releases" in low or "/tag/" in low or "/download/" in low):
        score += 25

    # 6. 可疑站扣分
    for d in SHADY_AD_DOMAINS:
        if d in low:
            score -= 15
            break

    # 7. URL 里有 "ad" / "track" / "click" → 很可能是广告跳转
    if any(x in low for x in ["/ad/", "/ads/", "track", "click", "redirect"]):
        score -= 10

    return max(0.0, min(100.0, score))


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


# 浏览器自身下载页（用户搜软件时 Serper 老把这些排第一，浪费位置）
BROWSER_DOWNLOAD_PAGES = (
    "google.com/chrome", "www.google.com/chrome",
    "microsoft.com/edge", "www.microsoft.com/edge",
    "firefox.com/download", "www.mozilla.org/firefox",
    "apple.com/safari",
    "opera.com/download",
    "brave.com/download",
    "vivaldi.com/download",
    "maxthon.com",
    # Google 主页（用户搜软件时不应弹 google.com 主页）
    "google.com/?", "google.com/webapp", "google.com/intl",
    "www.google.com/?", "www.google.com/webapp", "www.google.com/intl",
)


def _is_legit_resource(url: str, snippet: str = "") -> bool:
    """只拦硬盗版站 + 浏览器下载页 + Google 主页。"""
    hay = (url + " " + snippet).lower()
    for bad in PIRACY_BLOCKLIST:
        if bad in hay:
            return False
    # 浏览器下载页过滤
    low = url.lower()
    for bp in BROWSER_DOWNLOAD_PAGES:
        if bp in low:
            return False
    # google.com 空主页（不是 google.com/search/xxx）
    if low in ("https://google.com", "http://google.com",
               "https://www.google.com", "http://www.google.com"):
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
            payload = {"q": q, "num": 8, "gl": "cn", "hl": "zh-cn", "autocorrect": True}
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

    # ===== 去盗版 + HEAD 探测 + 评分（HEAD 并发 8）=====
    candidates = []
    for r in all_organic:
        url = r.get("link", "")
        if not _is_legit_resource(url, r.get("snippet", "")):
            continue
        candidates.append(r)

    def _head_process_one(r):
        url = r.get("link", "")
        title = r.get("title", "")
        snippet = r.get("snippet", "")[:200]
        domain_tag = _classify_domain(url)
        domain_raw = url.split("/")[2] if "://" in url else url[:30]

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
            pass

        ft_label, ft_cat = _guess_filetype(url, ct)

        matched = True
        if filetype_filter != "all":
            if filetype_filter == "app":
                if ft_cat == "app":
                    matched = True
                elif ft_cat == "web":
                    url_low = url.lower()
                    has_dl_kw = any(kw in url_low for kw in _DOWNLOAD_PATH_KEYWORDS)
                    has_official = any(d in url_low for d in OFFICIAL_DOWNLOAD_DOMAINS)
                    sn_low = (r.get("snippet", "") or "").lower()
                    sn_has = any(k in sn_low for k in ["download", "install", "setup", "official", "官方", "下载", "github"])
                    matched = has_dl_kw or has_official or sn_has
                else:
                    matched = False
            elif filetype_filter == "ebook":
                if ft_cat == "ebook":
                    matched = True
                elif ft_cat == "web":
                    sn_low = (r.get("snippet", "") or "").lower()
                    url_low = url.lower()
                    matched = any(d in url_low for d in ("gutenberg.org", "archive.org", "ebooks", "epub", "免费阅读", "电子书"))
                else:
                    matched = (ft_cat == "doc")
            else:
                matched = (ft_cat == filetype_filter)

        if not matched:
            return None

        if size_kb is not None and size_kb > 0 and size_kb < 3 and ft_cat in ("app", "audio", "video"):
            return None

        score = _score_resource(url, ct, size_kb, domain_tag)
        suspicious = score < 40

        return {
            "title": title,
            "snippet": snippet,
            "domain": domain_raw,
            "domain_tag": domain_tag,
            "link": url,
            "filetype_label": ft_label,
            "filetype_cat": ft_cat,
            "size_kb": size_kb,
            "score": round(score, 1),
            "suspicious": suspicious,
        }

    results = []
    if candidates:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(_head_process_one, r) for r in candidates]
            for fut in concurrent.futures.as_completed(futures):
                try:
                    item = fut.result()
                    if item is not None:
                        results.append(item)
                except Exception:
                    pass

    # 信誉分从高到低
    results.sort(key=lambda x: x["score"], reverse=True)

    # 截到 max
    results = results[:max_results]

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
