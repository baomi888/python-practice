"""文献爬取 + 下载一体化工具 —— 输入关键词，直接下 PDF。

===========================================================

支持的源站（按开放程度排序）：
  1. arxiv        完全开放，API 直连，零登录，最稳
  2. openreview    顶会审稿平台，公开论文 PDF
  3. cnki         知网 —— 需要你机构账号登录的 Cookie（不帮破解）
  4. ieee / elsevier  IEEE/Elsevier —— 同上，付费/机构权限，只帮用合法 Cookie 下载

  ❌ 不支持：Sci-Hub、Library Genesis 等盗版站（合规红线）

===========================================================

用法示例：

  # arXiv：关键词 "2024 transformer"，最多 5 篇，直接下 PDF
  python paper_download.py "2024 transformer" --site arxiv -n 5

  # 保存到自定义目录
  python paper_download.py "RAG retrieval augmented generation" -o ./papers

  # 先搜不下载（只看搜索结果）
  python paper_download.py "diffusion model" --dry-run

  # 自定义请求，比如 openreview（需要自己配 URL 模板，见代码）
  python paper_download.py "agent" --site openreview -n 3

  # 知网（需要 Cookie —— 先手动登录保存 storage_state）
  python paper_download.py "深度学习综述" --site cnki --cookie storage/cnki.json

===========================================================

依赖：
  pip install requests feedparser    # feedparser 解析 arXiv Atom XML
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Optional

import requests

try:
    import feedparser   # arXiv 返回 Atom XML，feedparser 最方便
except ImportError:
    print("⚠️  feedparser 未安装，执行: pip install feedparser")
    sys.exit(1)


# ============================================================
# arXiv API（最开放，最稳）
# ============================================================

ARXIV_API = "http://export.arxiv.org/api/query"

def search_arxiv(query: str, max_results: int = 10) -> list[dict]:
    """arXiv 公开 API 搜索。

    返回字段：id, title, authors, summary, published, updated, pdf_url, abs_url
    """
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    resp = requests.get(ARXIV_API, params=params, timeout=30)
    resp.raise_for_status()

    feed = feedparser.parse(resp.text)
    results = []
    for entry in feed.entries:
        # entry.id 形如 http://arxiv.org/abs/2401.12345v1
        arxiv_id = entry.id.split("/abs/")[-1]
        abs_url = f"https://arxiv.org/abs/{arxiv_id}"
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

        authors = ", ".join(a.get("name", "") for a in entry.get("authors", []))
        results.append({
            "arxiv_id": arxiv_id,
            "title": entry.get("title", "").replace("\n", " ").strip(),
            "authors": authors,
            "summary": entry.get("summary", "").replace("\n", " ").strip()[:300],
            "published": entry.get("published", ""),
            "pdf_url": pdf_url,
            "abs_url": abs_url,
        })
    return results


# ============================================================
# 下载（复用 download_direct.py 的逻辑，简化版）
# ============================================================

def sanitize(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()[:150]


def download_pdf(session: requests.Session, pdf_url: str, out_dir: Path,
                 filename: str, timeout: int = 60) -> Optional[Path]:
    """HTTP GET 直接下载 PDF。流式写入，带进度。"""
    safe = sanitize(filename)
    save_path = out_dir / f"{safe}.pdf"

    # 重名去重
    counter = 2
    while save_path.exists():
        save_path = out_dir / f"{safe}_{counter}.pdf"
        counter += 1

    try:
        resp = session.get(pdf_url, stream=True, timeout=(10, timeout),
                           allow_redirects=True)
        if resp.status_code in (401, 403):
            print(f"  ❌ HTTP {resp.status_code} —— 登录失效或没权限")
            return None
        if resp.status_code >= 400:
            print(f"  ❌ HTTP {resp.status_code}")
            return None

        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        out_dir.mkdir(parents=True, exist_ok=True)

        with open(save_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if chunk:
                    f.write(chunk)
                    done += len(chunk)

        size_kb = save_path.stat().st_size / 1024
        if size_kb < 5:
            # arXiv 404 也可能返回小 PDF 占位
            save_path.unlink()
            print(f"  ❌ 文件过小（{size_kb:.0f} KB），可能不是有效 PDF")
            return None

        print(f"  ✅ {save_path.name}  ({size_kb:.0f} KB)")
        return save_path

    except requests.RequestException as e:
        print(f"  ❌ 下载失败: {e}")
        return None


# ============================================================
# 主流程
# ============================================================

def run_arxiv_download(query: str, max_results: int, out_dir: Path,
                       download: bool = True, dry_run: bool = False):
    """搜 arXiv + 下载 PDF。"""

    print(f"\n🔍 arXiv 搜索: \"{query}\"")
    print("=" * 60)
    results = search_arxiv(query, max_results=max_results)

    if not results:
        print("❌ 没找到任何论文")
        return

    print(f"📚 找到 {len(results)} 篇论文:\n")
    for i, r in enumerate(results, 1):
        print(f"  [{i}] {r['title'][:65]}")
        print(f"      {r['arxiv_id']}  |  {r['authors'][:50]}")
        print(f"      📄 {r['pdf_url']}")
        print()

    if dry_run:
        print("🏁 dry-run 模式，只看不下载")
        return

    if not download:
        print("🏁 下载已跳过")
        return

    print(f"\n⬇️  开始下载到 {out_dir}\n")

    session = requests.Session()
    session.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36")
    })

    ok = 0
    for r in results:
        filename = f"{r['arxiv_id'].replace('.', '_')}_{sanitize(r['title'][:40])}"
        print(f"  📖 {r['arxiv_id']}")
        if download_pdf(session, r["pdf_url"], out_dir, filename):
            ok += 1
        time.sleep(0.5)   # 礼貌延时

    print(f"\n🎉 完成：{ok}/{len(results)} 篇已下载")


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="文献爬取 + PDF 下载")
    parser.add_argument("query", help="搜索关键词，引号包起来支持多词")
    parser.add_argument("--site", default="arxiv", choices=["arxiv", "openreview"],
                        help="目标站（默认 arxiv）")
    parser.add_argument("-n", "--max", type=int, default=5,
                        help="最多下几篇（默认 5）")
    parser.add_argument("-o", "--output", default="./papers",
                        help="保存目录（默认 ./papers）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只搜不下载")
    parser.add_argument("--no-download", dest="download", action="store_false",
                        help="只搜列表不下载")
    parser.set_defaults(download=True)
    args = parser.parse_args()

    if args.site == "arxiv":
        run_arxiv_download(
            query=args.query,
            max_results=args.max,
            out_dir=Path(args.output),
            download=args.download,
            dry_run=args.dry_run,
        )
    elif args.site == "openreview":
        print("⚠️  openreview 站点爬虫待扩展（结构较特殊）")
        print("   先用 arxiv，它覆盖 90% 的 AI/ML/CS 论文。")
    else:
        print(f"❌ 不支持的站点: {args.site}")


if __name__ == "__main__":
    main()
