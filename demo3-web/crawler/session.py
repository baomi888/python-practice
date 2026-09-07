"""登录与会话管理 —— 首次手动登录，之后复用持久化 Cookie。

流程设计（与真实合规使用一致）：
1. 有已保存的登录态(storage_state) → 直接以该会话打开目标页（复用 Cookie，不重复登录）；
2. 无登录态或已失效 → 【有头】打开登录页，提示用户用【本人账号】人工完成登录
   （支持扫码、短信验证码、滑块等任何需要人参与的认证方式）；
3. 登录成功 → 立即把整份会话 Cookie 落盘，供后续运行复用。

合规红线（本模块绝不包含的实现）：
- 不保存/回填他人的账号密码、不记录密码输入；
- 不修改 Cookie 字段去伪装会员身份或提升账号权限；
- 不破解验证码、不绕过 2FA；
- 会话文件(storage/*.json)等同个人凭证，必须妥善保管、禁止提交到仓库。
"""
from __future__ import annotations

import time

from playwright.sync_api import TimeoutError as PlaywrightTimeout

from browser_ctx import BrowserSession  # noqa: F401  (类型注解用)


def _is_logged_in(page, login_cfg: dict) -> bool:
    """按配置的判定方式判断『当前页面是否处于已登录状态』。"""
    check = login_cfg.get("logged_in_check", {}) or {}
    ctype = check.get("type", "marker_present")
    if ctype == "marker_present":
        sel = check.get("selector", "")
        if not sel:
            return False
        try:
            page.locator(sel).first.wait_for(state="visible", timeout=3000)
            return True
        except PlaywrightTimeout:
            return False
    elif ctype == "marker_absent":
        # 语义：『该元素出现 = 未登录』（如"登录"入口）。等页面稳定后判断是否不存在。
        sel = check.get("selector", "")
        if not sel:
            return False
        time.sleep(1.5)
        try:
            return page.locator(sel).count() == 0
        except Exception:
            return False
    elif ctype == "url_contains":
        return bool(check.get("value")) and check["value"] in page.url
    return False


def ensure_logged_in(session: BrowserSession, cfg: dict) -> str:
    """确保进入目标站点时带有本人账号的登录会话。

    Args:
        session: BrowserSession（内部已按需加载了历史 storage_state）
        cfg: 配置字典

    Returns:
        str: 'public'（无需登录）/ 'cookie'（复用会话）/ 'manual'（本次人工登录）

    Raises:
        RuntimeError: 登录需要人工完成但处于无头模式、或等待登录超时
    """
    site = cfg.get("site", {})
    login_cfg = site.get("login", {}) or {}
    if not login_cfg.get("enabled", False):
        print("[登录] 本配置目标为公开资源，跳过登录流程。")
        return "public"

    # ---- 第一步：先到主页探测登录态（若已复用 Cookie 则直接通过）----
    home_url = site.get("home_url", "")
    timeout_ms = int(cfg.get("timeouts_ms", {}).get("page_load", 45000))
    try:
        page = session.page
        page.goto(home_url, wait_until="load", timeout=timeout_ms)
    except Exception as e:
        raise RuntimeError(f"打开首页失败：{home_url}\n  原因：{e}") from e

    # 登录态判定前多探测几次：部分站点恢复会话后会先跳转/异步渲染头像等标志，
    # 一次性探测容易误判为"未登录"。
    logged_in = False
    for _ in range(3):
        if _is_logged_in(page, login_cfg):
            logged_in = True
            break
        time.sleep(1.2)

    if logged_in:
        print("[登录] 已持有有效会话 Cookie，无需重复登录（复用成功）。")
        return "cookie"

    # ---- 第二步：需要登录 —— 必须有头窗口供用户人工操作 ----
    if session.headless:
        raise RuntimeError(
            "需要登录，但当前是无头模式（无人可见窗口）。\n"
            "请先执行一次：python main.py --headed --config <你的配置>\n"
            "用本人账号完成首次登录，脚本会保存 Cookie；之后再改用无头模式复用会话。"
        )

    login_url = login_cfg.get("login_url") or home_url
    print("\n" + "=" * 66)
    print("[登录] 未检测到有效会话，准备人工登录。")
    print(f"       登录页: {login_url}")
    tip = login_cfg.get("manual_tip") or "请在窗口中用本人账号完成登录。"
    print(f"       提示: {tip}")
    print("       ⚠ 请勿在自动化的任何环节输入他人账号；本程序不记录任何密码。")
    print("=" * 66)

    try:
        page.goto(login_url, wait_until="load", timeout=timeout_ms)
    except Exception as e:
        raise RuntimeError(f"打开登录页失败：{login_url}\n  原因：{e}") from e

    # ---- 第三步：轮询等待登录成功（用户人工完成扫码/密码/验证）----
    login_wait_ms = int(cfg.get("timeouts_ms", {}).get("login_wait", 300000))
    deadline = time.monotonic() + login_wait_ms / 1000.0
    elapsed = 0
    while time.monotonic() < deadline:
        if _is_logged_in(page, login_cfg):
            print(f"[登录] 检测到登录成功（{int(elapsed)} 秒）。")
            # 登录态落盘：后续运行可直接复用，无需再次人工登录
            session.save_storage_state()
            return "manual"
        time.sleep(1.0)
        elapsed += 1
        if elapsed % 10 == 0:
            print(f"       ...仍在等待人工登录完成（已等待 {elapsed} 秒）")

    raise RuntimeError(
        f"等待人工登录超过 {login_wait_ms // 1000} 秒仍未成功，已停止。\n"
        "请确认账号信息/网络正常后重试。"
    )
