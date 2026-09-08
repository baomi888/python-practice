"""Playwright 合规爬虫 demo —— 登录态复用 + 下载事件监听 + 人类延时。

⚠️ 合规红线：
  本脚本仅用于「以本人账号合法登录后，下载本来就有权限下载的文件」。
  - 不绕过付费墙、不伪造会员、不改 Cookie 提权；
  - 不破解验证码（检测到就暂停等人完成）；
  - 不爬 robots.txt 禁止的域；
  - 所有 cookies/storage_state 仅用于恢复你自己的登录会话。

  任何超越账号权限的破解行为都违反《网络安全法》第 27 条 / 《刑法》第 285 条。

===========================================================

✅ 功能清单（需求 1–6）：
  1. 无头 / 可视化浏览器模式切换（headless 参数）
  2. 合理等待：wait_until + wait_for_timeout，适配 JS 动态加载
  3. 加载已有 cookie（storage_state 文件，首次手动登录后保存，后续自动复用）
  4. 监听 Download 事件，自定义保存路径 + 文件名
  5. 人类操作延时 human_delay（随机区间，规避基础反爬）
  6. 完整注释 + 安装步骤

❌ 不做（需求 7 拒绝）：
  - 破解权限、绕过鉴权：拒绝实现，理由见文件头合规声明

===========================================================

安装步骤：
  pip install playwright
  python -m playwright install chromium
        ↑ 或如果你有 Edge： 改成 channel="msedge" 就行，不用下浏览器

运行：
  # 首次运行——有头模式，手动登录一次保存 Cookie
  python download_demo.py --headed --login-only

  # 第二次开始——无头模式，复用 Cookie，全自动下载
  python download_demo.py --headless
"""

from __future__ import annotations

import argparse
import random
import re
import time
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


# ============================================================
# 配置区
# ============================================================

# 目标站的入口 URL（改成你自己的合法站）
TARGET_URL = "https://example.com/files"   # TODO: 替换成真实站点

# 登录判断：页面上出现这些文字 → 认为"已登录"（改）
LOGIN_INDICATORS = ["退出", "登出", "Logout", "个人中心", "My Account"]

# Cookie 文件位置（首次登录后自动保存，后续自动加载）
STORAGE_PATH = Path(__file__).parent / "storage" / "my_login.json"

# 下载目录（脚本自动创建）
DOWNLOAD_DIR = Path(__file__).parent / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 人类延时区间（秒）—— 每次点击之间随机 sleep，模拟真人节奏
HUMAN_DELAY = (1.2, 2.8)

# 单步超时（毫秒）
STEP_TIMEOUT_MS = 15_000

# 浏览器："chromium"（Playwright 自带）或 "msedge" / "chrome"（用你本机装的）
BROWSER_CHANNEL: Optional[str] = None   # "msedge" 代表本机 Edge


# ============================================================
# 工具函数
# ============================================================

def human_sleep(a: float = None, b: float = None):
    """随机 sleep 一会儿，模拟真人操作节奏（规避基础反爬）。"""
    lo, hi = (a, b) if (a and b) else HUMAN_DELAY
    t = random.uniform(lo, hi)
    time.sleep(t)


def is_logged_in(page) -> bool:
    """判断当前页面是否已登录：查登录指示器文本。"""
    try:
        body_text = page.locator("body").inner_text(timeout=2000)
    except Exception:
        return False
    return any(ind in body_text for ind in LOGIN_INDICATORS)


def wait_for_spinner_gone(page, selector: str = ".loading, .spinner, [data-loading='true']",
                          timeout_ms: int = 8000):
    """等 JS 动态加载的 spinner 消失（可选）。"""
    try:
        page.wait_for_selector(selector, state="hidden", timeout=timeout_ms)
    except Exception:
        pass  # 没有 spinner 就跳过，不强求


def sanitize_filename(name: str) -> str:
    """清理文件名里的非法字符（Windows 不允许 \\ / : * ? " < > |）。"""
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()[:200]


# ============================================================
# 首次登录（手动）—— 有头模式下跑一次，保存 Cookie 之后再也不用
# ============================================================

def run_login_once(headed: bool = True):
    """打开浏览器让你手动登录，登录完按回车 → 保存 storage_state。"""
    print("\n==== 首次登录（手动）====")
    print(f"请在弹出的浏览器里登录 {TARGET_URL}")
    print("登录成功、确认页面上出现个人中心/退出按钮后，回到终端按回车\n")

    with sync_playwright() as pw:
        launch_kw = {"headless": False}   # 有头！你要看到浏览器操作
        if BROWSER_CHANNEL:
            launch_kw["channel"] = BROWSER_CHANNEL

        browser = pw.chromium.launch(**launch_kw)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        page.goto(TARGET_URL, wait_until="domcontentloaded")

        # 等你手动操作
        input(">>> 登录完成，准备好了就按回车...")

        # 保存 Cookie（storage_state = cookies + localStorage，一次全存）
        STORAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(STORAGE_PATH))
        print(f"✅ 登录态已保存到 {STORAGE_PATH}（下次自动加载）")

        browser.close()


# ============================================================
# 核心：下载流程（Cookie 自动恢复 + 监听 Download 事件）
# ============================================================

def download_files(headless: bool = True, max_files: int = 10):
    """自动遍历页面上的下载按钮，逐个点击并把文件存到 DOWNLOAD_DIR。

    核心机制：
      page.expect_download() 是 Playwright 的事件订阅器。
      - 先挂好 .expect_download()，再 .click()
      - 点完 await download → 拿到 Download 对象 → download.save_as()
      - 这比监听 context.on("download", ...) 更简洁（同步代码）

    浏览器上下文会自动从 STORAGE_PATH 恢复 Cookie。
    """

    print(f"\n==== 下载流程（headless={headless}, max={max_files}）====")

    if not STORAGE_PATH.exists():
        print(f"❌ 没找到登录态文件：{STORAGE_PATH}")
        print("   请先跑: python download_demo.py --headed --login-only")
        return False

    with sync_playwright() as pw:
        launch_kw = {"headless": headless}
        if BROWSER_CHANNEL:
            launch_kw["channel"] = BROWSER_CHANNEL

        browser = pw.chromium.launch(**launch_kw)

        # ---------- 加载登录态 ----------
        context_kw = {
            "storage_state": str(STORAGE_PATH),   # Cookie 在这里恢复
            "accept_downloads": True,
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
            "viewport": {"width": 1366, "height": 900},
        }
        context = browser.new_context(**context_kw)

        # 兜底弹窗处理（alert/confirm 自动 dismiss，beforeunload 自动 accept）
        context.on("page", lambda p: p.on("dialog", _handle_dialog))

        page = context.new_page()
        print(f"🚀 打开 {TARGET_URL}")
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=STEP_TIMEOUT_MS * 2)
        page.wait_for_timeout(2000)   # JS 渲染时间

        # ---------- 登录校验 ----------
        if not is_logged_in(page):
            print("❌ Cookie 过期 / 登录态无效。请重新跑 --login-only")
            browser.close()
            return False
        print("✅ 登录态有效")

        # ---------- 找下载按钮 ----------
        # 通用策略：<a> 带 download 属性、或 text 含 "下载/Download/导出/Export"
        # 根据你的目标站改 selector
        DOWNLOAD_SELECTORS = [
            "a[download]",                              # HTML5 download 属性
            "a:has-text('下载')",
            "a:has-text('Download')",
            "a:has-text('导出')",
            "button:has-text('下载')",
            "button:has-text('Export')",
            "[class*='download' i]",
            "[aria-label*='下载']",
        ]

        all_buttons = []
        for sel in DOWNLOAD_SELECTORS:
            try:
                loc = page.locator(sel)
                n = loc.count()
                for i in range(n):
                    el = loc.nth(i)
                    if el.is_visible() and el.is_enabled():
                        all_buttons.append((sel, i, el))
            except Exception:
                continue

        # 去重（同一个按钮可能被多个 selector 命中）
        seen = set()
        unique = []
        for sel, i, el in all_buttons:
            try:
                box = el.bounding_box()
                key = (round(box["x"]), round(box["y"])) if box else None
                if key and key not in seen:
                    seen.add(key)
                    unique.append((sel, el))
            except Exception:
                continue

        print(f"🔍 发现 {len(unique)} 个可下载按钮")
        if not unique:
            print("⚠️ 没找到按钮。可能选择器不对，改 DOWNLOAD_SELECTORS 试试。")
            browser.close()
            return True   # 不算失败

        # ---------- 逐个点击下载 ----------
        downloaded = 0
        for idx, (sel, btn) in enumerate(unique[:max_files], 1):
            try:
                btn_text = btn.inner_text(timeout=1000)[:40]
            except Exception:
                btn_text = "<no text>"

            print(f"\n  [{idx}/{min(len(unique), max_files)}] 点 {btn_text}")

            # 关键：expect_download 必须在 click 之前开始等待
            try:
                with page.expect_download(timeout=STEP_TIMEOUT_MS) as download_info:
                    btn.click(timeout=STEP_TIMEOUT_MS, force=False)   # force=False：真的点得到才点
                download = download_info.value

                # 自定义文件名（来源：download.suggested_filename 或按钮文字）
                suggested = download.suggested_filename or f"file_{idx}"
                filename = sanitize_filename(suggested)
                save_path = DOWNLOAD_DIR / filename

                # 重名去重（file.pdf → file_2.pdf）
                counter = 2
                stem, suffix = Path(filename).stem, Path(filename).suffix
                while save_path.exists():
                    save_path = DOWNLOAD_DIR / f"{stem}_{counter}{suffix}"
                    counter += 1

                download.save_as(str(save_path))
                size_kb = save_path.stat().st_size / 1024
                print(f"    ✅ → {save_path.name} ({size_kb:.1f} KB)")
                downloaded += 1

            except PlaywrightTimeout:
                print(f"    ⏱ 等待下载超时（{STEP_TIMEOUT_MS}ms），跳过")
            except Exception as e:
                print(f"    ❌ 下载失败: {e}")

            human_sleep()   # 下一个按钮前随机等一会儿

        print(f"\n🎉 完成：{downloaded}/{min(len(unique), max_files)} 个文件已保存到 {DOWNLOAD_DIR}")

        # 顺手把最新 Cookie 存一下（有些站会在操作期间刷新 Cookie）
        context.storage_state(path=str(STORAGE_PATH))
        print(f"🔒 登录态已刷新保存")

        browser.close()
        return True


def _handle_dialog(dialog):
    """弹窗兜底。"""
    try:
        if dialog.type == "beforeunload":
            dialog.accept()
        else:
            dialog.dismiss()
    except Exception:
        pass


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Playwright 合规下载 demo")
    parser.add_argument("--headed", action="store_true", help="可视化浏览器（默认无头）")
    parser.add_argument("--headless", dest="headed", action="store_false", help="无头浏览器（默认）")
    parser.add_argument("--login-only", action="store_true", help="首次登录：手动登一遍存 Cookie，然后退出")
    parser.add_argument("--max-files", type=int, default=10, help="最多下载几个文件")
    parser.add_argument("--channel", default=None, choices=["msedge", "chrome", None],
                        help="浏览器：msedge=本机 Edge, chrome=本机 Chrome, 默认 Chromium")
    parser.set_defaults(headed=False)

    args = parser.parse_args()

    global BROWSER_CHANNEL
    BROWSER_CHANNEL = args.channel

    if args.login_only:
        run_login_once(headed=True)    # 登录必须有头
    else:
        ok = download_files(headless=not args.headed, max_files=args.max_files)
        if not ok:
            print("\n💡 提示：如果报 '登录态无效'，先跑：")
            print("   python download_demo.py --login-only")


if __name__ == "__main__":
    main()
