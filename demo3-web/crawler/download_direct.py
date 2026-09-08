"""HTTP 直链下载器 —— 零浏览器、纯 requests、给链接就拉文件。

和 download_demo.py（Playwright 浏览器）的关系：
  download_demo.py   → 下载链接需要点击 JS 按钮才出现 → 打开浏览器、等页面、点按钮
  download_direct.py → 下载链接已知，直接 GET 就行    → 纯 HTTP、0 依赖、秒级完成

===========================================================

✅ 功能：
  1. 单 URL / 批量 URL（文件输入）下载
  2. 从 Playwright storage_state 恢复 Cookie（需要登录的下载链接也能用）
  3. 流式下载 + 进度条 + 重命名去重
  4. 断点续传（支持 Range 头的站）
  5. 自动从 Content-Disposition 提取原始文件名
  6. 失败自动重试（3 次，间隔递增）

❌ 不做：
  - 破解鉴权、绕过付费墙（同 download_demo.py 合规红线）
  - 自动搜下载链接——你得先给明确的 URL
  - 爬取 robots.txt 禁止的域

===========================================================

安装：
  pip install requests

运行：
  # 单文件
  python download_direct.py "https://example.com/files/report.pdf"

  # 批量（每行一个 URL，# 开头的注释会被跳过）
  python download_direct.py urls.txt

  # 需要登录的链接 —— 先拿 Cookie（用 download_demo.py --login-only 存一份）
  python download_direct.py "https://example.com/files/member.pdf" --cookie storage/my_login.json

  # 自定义输出目录 + 并发
  python download_direct.py urls.txt -o ./downloads --workers 4
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ============================================================
# Cookie 恢复：从 Playwright storage_state JSON 里抠 cookies
# ============================================================

def load_cookies_from_storage(storage_path: Path) -> dict[str, str]:
    """把 Playwright 存的 storage_state JSON 提取成 requests 能用的 cookie dict。

    Playwright storage_state 格式：
      {
        "cookies": [
          {"name": "sessionid", "value": "abc123", "domain": ".example.com", ...},
          ...
        ],
        "origins": [...]   ← localStorage（这里不处理）
      }

    requests 的 Cookie 格式：{ "sessionid": "abc123", "csrftoken": "xxx" }
    """
    if not storage_path or not Path(storage_path).exists():
        return {}
    try:
        raw = json.loads(Path(storage_path).read_text(encoding="utf-8"))
        cookies = raw.get("cookies", [])
        return {c["name"]: c["value"] for c in cookies if c.get("name") and c.get("value")}
    except Exception as e:
        print(f"⚠️  Cookie 文件解析失败: {e}")
        return {}


# ============================================================
# 文件名提取
# ============================================================

FILENAME_RE = re.compile(r"filename\s*=\s*(?:['\"]?)([^'\"]+)(?:['\"]?)", re.IGNORECASE)

def extract_filename(url: str, headers: dict) -> str:
    """从 URL 或 Content-Disposition 头里猜文件名。"""
    # 1. Content-Disposition 头优先
    cd = headers.get("Content-Disposition", "") or headers.get("content-disposition", "")
    m = FILENAME_RE.search(cd)
    if m:
        name = m.group(1).strip()
        # 有些会有编码前缀：filename*=UTF-8''%E6%95%B0%E6%8D%AE.csv
        if name.startswith("UTF-8''") or name.startswith("utf-8''"):
            from urllib.parse import unquote
            name = unquote(name.split("''", 1)[1])
        if name:
            return name

    # 2. URL 末尾的文件名
    from urllib.parse import urlparse
    path = urlparse(url).path
    tail = path.rsplit("/", 1)[-1] or "download"
    # 去掉 query
    tail = tail.split("?", 1)[0]
    if tail and "." in tail:
        return tail

    return "download"


def sanitize_filename(name: str) -> str:
    """Windows 合法文件名。"""
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()[:200]


# ============================================================
# 带重试的 Session
# ============================================================

def make_session(cookies: dict, user_agent: str, retries: int = 3) -> requests.Session:
    """构造一个 Session：内置重试 + Cookie + UA。"""
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})

    # 自动重试（urllib3 Retry + 退避）
    retry = Retry(
        total=retries,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    if cookies:
        session.cookies.update(cookies)

    return session


# ============================================================
# 单个文件下载
# ============================================================

def download_one(
    session: requests.Session,
    url: str,
    out_dir: Path,
    timeout: int = 30,
    resume: bool = True,
) -> tuple[bool, Path | None, str]:
    """下载一个 URL。返回 (成功, 保存路径, 消息)。"""

    # HEAD 先探一下（看 Content-Length / Content-Disposition）
    try:
        head = session.head(url, allow_redirects=True, timeout=timeout)
        expected_name = extract_filename(url, head.headers)
        total = int(head.headers.get("Content-Length", 0))
        accept_ranges = head.headers.get("Accept-Ranges", "") == "bytes"
    except Exception:
        expected_name = extract_filename(url, {})
        total = 0
        accept_ranges = False

    filename = sanitize_filename(expected_name)
    save_path = out_dir / filename

    # 重名去重
    counter = 2
    stem, suffix = Path(filename).stem, Path(filename).suffix
    while save_path.exists():
        save_path = out_dir / f"{stem}_{counter}{suffix}"
        counter += 1

    # 断点续传：如果文件已存在 + 服务器支持 Range
    existing = save_path.stat().st_size if save_path.exists() else 0
    headers = {}
    if resume and existing > 0 and accept_ranges:
        headers["Range"] = f"bytes={existing}-"
        print(f"  🔄 断点续传：已有 {existing//1024} KB，继续拉...")
    elif resume and existing > 0 and total and existing >= total:
        return True, save_path, "已存在"

    # 正式 GET（流式，边下边写）
    try:
        resp = session.get(url, stream=True, allow_redirects=True,
                           timeout=(10, timeout), headers=headers)

        if resp.status_code == 416:
            # Range 请求返回 416 → 已经下完了
            return True, save_path, "已完整（416 Range Not Satisfiable）"

        if resp.status_code in (401, 403):
            return False, None, f"HTTP {resp.status_code}（登录失效 / 没权限）"

        if resp.status_code >= 400:
            return False, None, f"HTTP {resp.status_code}"

        # 从响应头再确认一次文件名（防止 HEAD 不准）
        if not suffix and "Content-Disposition" in resp.headers:
            filename2 = sanitize_filename(extract_filename(url, resp.headers))
            if filename2 != filename:
                save_path = out_dir / filename2

        # 写文件（append 模式对应断点续传，否则覆盖）
        mode = "ab" if (resume and existing > 0 and resp.status_code == 206) else "wb"
        bytes_done = existing if mode == "ab" else 0
        total_size = int(resp.headers.get("Content-Length", total))
        if total_size and resp.status_code == 206:
            total_size += existing   # 206 返回的是剩余部分

        save_path.parent.mkdir(parents=True, exist_ok=True)
        start = time.time()

        with open(save_path, mode) as f:
            for chunk in resp.iter_content(chunk_size=64 * 1024):   # 64 KB
                if chunk:
                    f.write(chunk)
                    bytes_done += len(chunk)
                    _print_progress(filename, bytes_done, total_size)

        # 清除进度条
        sys.stdout.write("\r" + " " * 60 + "\r")
        sys.stdout.flush()

        elapsed = time.time() - start
        speed = bytes_done / elapsed / 1024 if elapsed > 0 else 0
        size_kb = save_path.stat().st_size / 1024

        return True, save_path, f"{size_kb:.0f} KB @ {speed:.0f} KB/s"

    except requests.RequestException as e:
        return False, None, f"网络错误: {e}"
    except Exception as e:
        return False, None, f"未知错误: {e}"


def _print_progress(name: str, done: int, total: int):
    """简易进度条（单行覆盖）。"""
    if total <= 0:
        bar = f"{done // 1024} KB"
    else:
        pct = done / total * 100
        filled = int(pct / 5)
        bar = f"[{'█' * filled}{'░' * (20 - filled)}] {pct:5.1f}%"
    sys.stdout.write(f"\r  ⬇ {name[:28]:<28} {bar}")
    sys.stdout.flush()


# ============================================================
# 批量下载
# ============================================================

def load_urls(source: str) -> list[str]:
    """解析 URL 参数或 URL 文件。自动去 UTF-8 BOM（PowerShell Out-File 会写 BOM）。"""
    # 是文件？读每行
    p = Path(source)
    if p.exists() and p.is_file():
        raw = p.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):   # UTF-8 BOM
            raw = raw[3:]
        text = raw.decode("utf-8", errors="replace")
        urls = []
        for line in text.splitlines():
            line = line.strip().lstrip("\ufeff")   # 兜底：行首也可能有残留 BOM
            if not line or line.startswith("#"):
                continue
            urls.append(line)
        return urls
    # 否则当 URL 用
    return [source.strip().lstrip("\ufeff")]


def download_batch(
    urls: Iterable[str],
    session: requests.Session,
    out_dir: Path,
    workers: int = 1,
    timeout: int = 30,
    resume: bool = True,
):
    urls = list(urls)
    print(f"\n🚀 开始下载 {len(urls)} 个文件 → {out_dir}")
    print(f"   workers={workers}, resume={'on' if resume else 'off'}")
    print("=" * 60)

    out_dir.mkdir(parents=True, exist_ok=True)
    results = []

    if workers <= 1:
        # 单线程（保持顺序，方便看进度）
        for url in urls:
            ok, path, msg = download_one(session, url, out_dir, timeout, resume)
            tag = "✅" if ok else "❌"
            print(f"  {tag} {Path(url.split('?')[0]).name[:40]:<40} → {msg}")
            results.append((ok, url, path, msg))
    else:
        # 多线程并发（快，但进度条会串行）
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(download_one, session, url, out_dir, timeout, resume): url
                       for url in urls}
            for fut in as_completed(futures):
                url = futures[fut]
                try:
                    ok, path, msg = fut.result()
                except Exception as e:
                    ok, path, msg = False, None, f"线程异常: {e}"
                tag = "✅" if ok else "❌"
                print(f"  {tag} {Path(url.split('?')[0]).name[:40]:<40} → {msg}")
                results.append((ok, url, path, msg))

    # 汇总
    ok_count = sum(1 for r in results if r[0])
    fail_count = len(results) - ok_count
    print("=" * 60)
    print(f"📊 完成：{ok_count} 成功 / {fail_count} 失败")
    if fail_count:
        print("\n失败的 URL：")
        for ok, url, path, msg in results:
            if not ok:
                print(f"  ❌ {url}  ——  {msg}")


# ============================================================
# CLI
# ============================================================

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/122.0.0.0 Safari/537.36")

def main():
    parser = argparse.ArgumentParser(
        description="HTTP 直链下载器（纯 requests，不用浏览器）")
    parser.add_argument("source", help="下载 URL 或 URL 列表文件（每行一个）")
    parser.add_argument("-o", "--output", default="./downloads",
                        help="输出目录（默认 ./downloads）")
    parser.add_argument("--cookie", default=None,
                        help="Playwright storage_state JSON 文件（需要登录的链接）")
    parser.add_argument("--workers", type=int, default=1,
                        help="并发线程数（默认 1，单线程顺序下载）")
    parser.add_argument("--timeout", type=int, default=30,
                        help="单文件超时秒数（默认 30）")
    parser.add_argument("--no-resume", action="store_true",
                        help="关闭断点续传（默认开启）")
    parser.add_argument("--ua", default=DEFAULT_UA,
                        help="自定义 User-Agent")
    args = parser.parse_args()

    # 1. 拿 URL 列表
    urls = load_urls(args.source)
    if not urls:
        print("❌ 没解析到任何 URL")
        return

    # 2. 恢复 Cookie
    cookies = {}
    if args.cookie:
        cookies = load_cookies_from_storage(Path(args.cookie))
        print(f"🍪 已加载 {len(cookies)} 个 Cookie")
        if not cookies:
            print("   ⚠️  Cookie 文件为空或无效——如果是登录链接可能 403")

    # 3. 构造 Session
    session = make_session(cookies, args.ua)

    # 4. 批量下载
    download_batch(
        urls=urls,
        session=session,
        out_dir=Path(args.output),
        workers=args.workers,
        timeout=args.timeout,
        resume=not args.no_resume,
    )


if __name__ == "__main__":
    main()
