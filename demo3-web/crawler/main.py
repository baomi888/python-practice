"""Playwright 爬虫 CLI 入口 —— 登录会话复用 + 动态页面抓取 + 下载文件。

用法示例（在 demo3-web/crawler 目录下）：
    python main.py --headed                  # 有头运行默认配置（GitHub 公开演示）
    python main.py --headless --list-buttons # 无头扫描页面下载按钮
    python main.py --headless --pick "ZIP"   # 无头下载匹配"ZIP"的按钮
    python main.py --config config.local.json --headed   # 本地离线演示（首次登录）
    python main.py --config config.local.json --headless # 复用已保存 Cookie

合规声明：
    本程序仅为【本人账号合法访问】提供自动化：只下载本人有权获取的内容；
    不做任何绕过鉴权/伪造会员权限/破解登录的尝试（见 README『合规红线』）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# 让本目录下的兄弟模块可以被直接 import（支持 python crawler/main.py 与 -m 两种运行方式）
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Windows 控制台常为 GBK/CP936：页面里的 emoji/箭头等无法编码会导致崩溃。
# 改为"无法编码就替换"，中文不受影响，仅个别符号显示为 ?。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

from browser_ctx import BrowserSession
from download_mgr import (
    DownloadListener,
    NoDownloadError,
    PermissionGateError,
    click_and_capture,
    save_download,
)
from page_utils import (
    candidate_is_vetoed,
    close_popups,
    expand_ui,
    human_delay,
    pause_for_verification,
    scan_download_candidates,
    wait_page_ready,
)
from session import ensure_logged_in


# ======================================================================
# 路径与配置
# ======================================================================
def _abs_path(cfg: dict, key: str) -> Path:
    """把配置里相对路径解析到 crawler/ 目录下。"""
    raw = cfg.get("paths", {}).get(key, key)
    p = Path(raw)
    return p if p.is_absolute() else (ROOT / p)


def load_config(path: Path) -> dict:
    if not Path(path).exists():
        sys.exit(f"找不到配置文件: {path}\n请先复制 config.example.json 为你的站点配置。")
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg


# ======================================================================
# 候选展示与选择
# ======================================================================
def print_candidates(cands: list, limit: int = 25) -> None:
    print("\n候选下载元素（score 越高越像下载目标，idx 对应 DOM 序号）:")
    print(f"  {'idx':<5}{'score':<6}{'tag':<8} 描述")
    for c in cands[:limit]:
        desc = (c.get("text") or c.get("aria") or "")[:90]
        href = c.get("href") or ""
        if href:
            desc = f"{desc}  [{href[:70]}]"
        print(f"  {c['idx']:<5}{c['score']:<6}{c.get('tag',''):<8} {desc}")
    if len(cands) > limit:
        print(f"  ... 其余 {len(cands) - limit} 项略（可用 --list-buttons 无下载模式查看更多）")


def select_candidate(cands: list, args) -> dict:
    """按 --pick / --index / 自动(得分最高) 三种方式选出目标元素。"""
    if args.pick:
        kw = args.pick.lower()
        hit = [c for c in cands if kw in (c.get("text", "") + " " + c.get("href", "") + " " + c.get("aria", "")).lower()]
        if len(hit) == 1:
            return hit[0]
        if not hit:
            raise NoDownloadError(f"没有找到文本/链接包含 '{args.pick}' 的候选。")
        print(f"匹配 '{args.pick}' 的候选有 {len(hit)} 个，请用 --index 指定：")
        print_candidates(hit)
        raise NoDownloadError("请结合上方列表使用 --index <序号> 精确定位。")

    if args.index is not None:
        if not (0 <= args.index < len(cands)):
            raise NoDownloadError(f"--index {args.index} 越界（共 {len(cands)} 个候选）。")
        return cands[args.index]

    # 自动模式：取综合得分最高的候选
    if cands and cands[0]["score"] > 0:
        return cands[0]
    raise NoDownloadError(
        "未识别出明显的下载按钮（无候选得分>0）。\n"
        "建议：1) 检查配置 keywords/href_ext_hits 是否覆盖目标按钮文案；"
        "2) 用 --list-buttons 查看页面上到底有哪些元素。"
    )


# ======================================================================
# 主流程
# ======================================================================
def run(args) -> int:
    cfg = load_config(Path(args.config))
    storage_path = _abs_path(cfg, "storage")
    downloads_dir = _abs_path(cfg, "downloads")
    logs_dir = _abs_path(cfg, "logs")
    logs_dir.mkdir(parents=True, exist_ok=True)

    # --force-login：删除已存会话，强制走一次人工登录
    if args.force_login and storage_path.exists():
        storage_path.unlink()
        print(f"[会话] 已删除旧登录态 {storage_path.name}，本次将重新人工登录。")

    if args.save_all:
        cfg.setdefault("download", {})["auto_save_all"] = True

    session = BrowserSession(
        cfg,
        storage_path=storage_path,
        headless=args.headless,          # None=用配置；True/False=CLI 覆盖
        slow_mo=args.slow_mo,
    )
    listener = DownloadListener()
    listener.attach(session.context, session.page)

    headless_txt = "无头(headless)" if session.headless else "有头(headed)"
    print(f"[启动] {cfg.get('site', {}).get('name', '未知站点')} | {headless_txt}")
    if args.debug:
        print(f"[调试] storage={storage_path} downloads={downloads_dir}")

    try:
        # ---- 1) 登录态保障（无登录配置时直接跳过）----
        ensure_logged_in(session, cfg)

        # ---- 2) 打开目标页并等待动态内容 ----
        target = args.url or cfg.get("site", {}).get("target_url") or cfg.get("site", {}).get("home_url")
        if not target:
            raise RuntimeError("未配置 target_url/home_url，也没有用 --url 指定。")
        timeout_ms = int(cfg.get("timeouts_ms", {}).get("page_load", 45000))
        session.page.goto(target, wait_until="load", timeout=timeout_ms)
        print(f"[导航] 已打开目标页: {target}")
        human_delay(cfg)

        wait_page_ready(session.page, cfg)     # 处理 JS 动态渲染
        close_popups(session.page, cfg)        # 处理弹窗/浮层
        pause_for_verification(session.page, cfg, session.headless)  # 简单人机验证(人工)
        expand_ui(session.page, cfg)           # 展开下拉/折叠，暴露下载按钮

        # ---- 3) 扫描下载按钮 ----
        cands = scan_download_candidates(session.page, cfg)
        if not cands:
            raise NoDownloadError("页面上没有可识别的 a/button 候选元素（或全部被排除）。")

        if args.list_buttons:
            print_candidates(cands)
            return 0

        sel = select_candidate(cands, args)
        print(f"\n[选中] idx={sel['idx']} tag={sel.get('tag')} score={sel.get('score')} "
              f"text='{(sel.get('text') or '')[:60]}' href='{sel.get('href') or ''}'")

        # ---- 4) 点击前红线检查：候选自身带权限门槛则拒绝 ----
        veto = candidate_is_vetoed(cfg, sel.get("text", ""), sel.get("href", ""), sel.get("aria", ""))
        if veto:
            raise PermissionGateError(
                f"候选按钮被拦截：{veto}。\n"
                "  本程序只自动化当前账号有权执行的操作；如需该资源，请用具备权限的"
                "本人账号登录后重试，或通过站内正规渠道开通权限。"
            )

        # ---- 5) 点击 + 捕获下载事件 + 保存 ----
        # click_and_capture 内部会把候选映射成可点击 locator（含隐藏副本的可见兜底）
        download = click_and_capture(session.page, listener, sel, cfg)
        saved_path = save_download(download, downloads_dir)

        # auto_save_all：把本次运行其它被捕获的下载也一并保存
        if cfg.get("download", {}).get("auto_save_all"):
            listener.save_all(downloads_dir)

        print("\n========== 运行成功 ==========")
        print(f"[结果] 文件已保存到本地: {saved_path}")
        print("[提示] 本次仅下载了当前账号有权获取的内容，已按要求控制请求频率。")
        return 0

    except PermissionGateError as e:
        print(f"\n[合规拦截] {e}")
        print("[说明] 程序已按红线要求停止，未做任何越权操作。")
        return 3
    except (NoDownloadError, RuntimeError) as e:
        print(f"\n[失败] {e}")
        _snapshot(session, logs_dir)
        return 1
    except Exception as e:
        # 兜底：任何未预期的错误（网络超时、页面结构异常等）也给出友好提示而非裸堆栈
        print(f"\n[失败] 未预期的错误: {type(e).__name__}: {e}")
        _snapshot(session, logs_dir)
        return 1
    except KeyboardInterrupt:
        print("\n[中断] 用户手动终止。")
        return 130
    finally:
        session.close()


def _snapshot(session: BrowserSession, logs_dir: Path) -> None:
    """失败时留截图便于排查（页面结构变化/选择器过期最常见）。"""
    try:
        name = f"fail_{time.strftime('%Y%m%d_%H%M%S')}.png"
        session.screenshot(logs_dir / name)
    except Exception:
        pass


# ======================================================================
# 命令行
# ======================================================================
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Playwright 登录会话爬虫：动态页面 + 下载事件捕获（本人合法账号）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="合规红线：不绕过鉴权、不伪造会员权限、不破解登录/验证码。\n"
               "示例：\n"
               "  python main.py --headed                       # 有头（默认配置演示）\n"
               "  python main.py --list-buttons                 # 扫描并列出下载按钮\n"
               "  python main.py --pick ZIP --headless          # 自动下载匹配 ZIP 的按钮\n"
               "  python main.py --config config.local.json --headed   # 本地演示首次登录\n"
               "  python main.py --config config.local.json --headless  # 复用 Cookie 无头运行",
    )
    p.add_argument("--config", default=str(ROOT / "config.json"), help="配置文件路径（默认 config.json）")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--headless", dest="headless", action="store_true", default=None, help="无头模式（复用登录态时推荐）")
    g.add_argument("--headed", dest="headless", action="store_false", help="有头模式（首次人工登录必须）")
    p.add_argument("--slow-mo", type=int, default=None, metavar="MS", help="操作慢动作毫秒（有头调试用）")
    p.add_argument("--url", help="覆盖目标页面 URL")
    p.add_argument("--list-buttons", action="store_true", help="只扫描并列出下载按钮，不下载")
    p.add_argument("--pick", metavar="TEXT", help="按文本/href 关键字挑选下载按钮")
    p.add_argument("--index", type=int, metavar="N", help="按候选列表序号挑选（见 --list-buttons 输出）")
    p.add_argument("--force-login", action="store_true", help="删除已存会话并强制重新人工登录")
    p.add_argument("--save-all", action="store_true", help="把本次运行捕获到的所有下载都保存")
    p.add_argument("--debug", action="store_true", help="输出更多调试信息")
    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    sys.exit(run(args))
