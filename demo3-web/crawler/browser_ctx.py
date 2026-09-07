"""浏览器会话封装 —— 基于 Playwright 同步 API。

职责：
1. 统一启动 Chromium（支持 --headless/--headed 切换、慢动作、UA/时区/语言等真实浏览器参数）；
2. 创建浏览器上下文时自动恢复已保存的登录态 storage_state（Cookie），实现『复用登录会话』；
3. 挂载 JS 对话框（alert/confirm/beforeunload）兜底处理器，防止弹窗卡死流程；
4. 提供失败截图等调试辅助。

合规边界：
- 本模块只负责『以本人账号登录后保留的会话态』的保存/恢复，绝不修改 Cookie 内容去伪造
  会员身份或提升权限（伪造/提权属于越权破解，红线禁止，见 README『合规红线』）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# 启动参数保持干净：只使用 Playwright 官方默认的 Chromium 行为。
# 刻意不做任何反检测/隐藏自动化痕迹的参数（如抹除 navigator.webdriver），
# 那属于规避网站风控的灰色对抗；需要自动化访问的站点请先确认其条款允许。
DEFAULT_ARGS = []


class BrowserSession:
    """封装 playwright 实例 / browser / context / page 的生命周期。"""

    def __init__(self, cfg: dict, storage_path: Optional[Path] = None,
                 headless: Optional[bool] = None, slow_mo: Optional[int] = None):
        """
        Args:
            cfg: 配置字典（config.json 解析结果）
            storage_path: 登录态 storage_state 文件（.json）。存在则自动恢复会话 Cookie。
            headless: 覆盖配置的无头开关；None 表示读配置
            slow_mo: 覆盖配置的慢动作毫秒数（有头调试时肉眼可见操作过程）
        """
        self.cfg = cfg
        self.storage_path = storage_path

        bcfg = cfg.get("browser", {})
        self.headless = bool(headless) if headless is not None else bool(bcfg.get("headless", False))
        self.slow_mo = slow_mo if slow_mo is not None else int(bcfg.get("slow_mo_ms", 0) or 0)

        # ---------- 启动真实 Chromium ----------
        # Playwright 同步 API：sync_playwright() 必须手动 start() / stop()。
        self._pw = sync_playwright().start()
        launch_kwargs = {
            "headless": self.headless,
            "args": DEFAULT_ARGS,
        }
        channel = bcfg.get("channel")
        if channel:  # 例如 "msedge" / "chrome"（使用本机已装浏览器）
            launch_kwargs["channel"] = channel
        if self.slow_mo:
            launch_kwargs["slow_mo"] = self.slow_mo

        self.browser = self._pw.chromium.launch(**launch_kwargs)

        # ---------- 浏览器上下文：恢复登录态 Cookie ----------
        context_kwargs = {
            "locale": bcfg.get("locale", "zh-CN"),
            "timezone_id": bcfg.get("timezone_id", "Asia/Shanghai"),
            "viewport": bcfg.get("viewport") or {"width": 1366, "height": 900},
            "accept_downloads": True,  # 允许捕获下载事件（chromium 默认开启，显式声明更清晰）
            "ignore_https_errors": False,  # 保持默认：不吞掉证书错误（安全）
        }
        ua = bcfg.get("user_agent")
        if ua:
            context_kwargs["user_agent"] = ua

        state = self._safe_load_storage(storage_path)
        if state is not None:
            context_kwargs["storage_state"] = state  # 把上次登录的 Cookie 塞进新上下文
            print(f"[会话] 已从 {storage_path.name} 恢复登录态 Cookie（避免重复登录）")

        self.context = self.browser.new_context(**context_kwargs)
        self.page = self.context.new_page()

        # 每个新开页面（含 target=_blank / 新窗口）都挂载对话框兜底处理器
        self.context.on("page", self._on_new_page)
        self._on_new_page(self.page)

    # ------------------------------------------------------------------
    @staticmethod
    def _safe_load_storage(storage_path: Optional[Path]):
        """读取 storage_state 文件；文件缺失/损坏时返回 None（降级为全新会话，不崩溃）。"""
        if not storage_path or not Path(storage_path).exists():
            return None
        try:
            return json.loads(Path(storage_path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"[警告] 登录态文件损坏，将按未登录处理：{e}")
            return None

    def _on_new_page(self, page):
        """挂载 JS 对话框兜底：alert/confirm 自动关闭，beforeunload 接受（避免卡死下载流程）。"""
        page.on("dialog", self._handle_dialog)

    def _handle_dialog(self, dialog):
        """处理 JS 弹窗。原则：不阻塞流程；beforeunload 接受，其余关闭并打日志。"""
        try:
            kind = dialog.type
            if kind == "beforeunload":
                dialog.accept()
                print(f"[弹窗] 接受 beforeunload（{dialog.message[:80]}）")
            else:
                dialog.dismiss()
                print(f"[弹窗] 已自动关闭 {kind} 弹窗（{dialog.message[:80]}）")
        except Exception:
            # 弹窗可能已被页面自动关闭，忽略竞态即可
            pass

    # ------------------------------------------------------------------
    def save_storage_state(self, storage_path: Optional[Path] = None) -> Optional[Path]:
        """把当前上下文所有 Cookie / localStorage 保存为 storage_state 文件。

        这是『登录一次、长期复用』的核心：保存的是本人账号的会话凭证，
        仅供后续运行恢复本人登录态使用，禁止篡改后用于伪造/提权。
        """
        target = storage_path or self.storage_path
        if not target:
            return None
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.context.storage_state(path=str(target))
        print(f"[会话] 登录态已保存到 {target}（含 {len(self.context.cookies())} 个 Cookie）")
        return target

    def screenshot(self, file_path: Path):
        """失败调试截图。"""
        try:
            self.page.screenshot(path=str(file_path), full_page=False)
            print(f"[调试] 已保存截图: {file_path}")
        except Exception as e:
            print(f"[警告] 截图失败: {e}")

    def close(self):
        """按顺序释放浏览器资源。"""
        try:
            self.context.close()
        finally:
            try:
                self.browser.close()
            finally:
                self._pw.stop()
