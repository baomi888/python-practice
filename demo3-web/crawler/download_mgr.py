"""下载管理 —— 识别下载按钮并捕获浏览器下载事件，保存到自定义目录。

Playwright 关键机制：
- 浏览器上下文 accept_downloads=True 后，任何会触发下载的点击/导航都会被捕获为
  Download 事件，无需关心站点用的是 <a download>、服务端 Content-Disposition
  还是 JS Blob 生成文件；
- 本模块用『上下文级事件监听器』收集所有下载（含新窗口触发的），
  并在点击后轮询捕获结果，期间持续检测『权限拒绝』文案以便及时止损。

合规红线：
- 只保存当前登录账号【有权】获取的文件；
- 若服务端返回无权限提示，立即中止并报错（PermissionGateError），
  绝不重试绕过、不伪造请求头/会员标记、不爆破接口。
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeout

from page_utils import NODES_SELECTOR, body_text, human_delay, new_deny_text


class PermissionGateError(RuntimeError):
    """目标资源超出当前账号权限（服务端已明确拒绝）→ 合规停止。"""


class NoDownloadError(RuntimeError):
    """点击后未产生任何下载且无权限提示 → 多为选择器过期或按钮非下载型。"""


# ======================================================================
# 下载事件监听器
# ======================================================================
class DownloadListener:
    """挂到 BrowserContext 上，收集所有页面的下载事件。"""

    def __init__(self):
        self._events = []
        self._saved = set()  # 已保存过的 download id

    def attach(self, context, page):
        """context 后续新开的每个页面（含新窗口）都挂上监听。"""
        context.on("page", lambda pg: pg.on("download", self._on_download))
        page.on("download", self._on_download)

    def _on_download(self, download):
        try:
            name = download.suggested_filename or "(未命名)"
            print(f"[下载事件] 捕获: {name}  <-  {download.url[:120]}")
        except Exception:
            print("[下载事件] 捕获一次下载（详情读取失败）")
        self._events.append(download)

    def count(self) -> int:
        return len(self._events)

    def latest(self):
        return self._events[-1] if self._events else None

    # ------------------------------------------------------------------
    def save_all(self, folder: Path) -> list:
        """auto_save_all 模式：把监听收集到的所有未保存下载统一落盘。"""
        saved = []
        for dl in self._events:
            if id(dl) in self._saved:
                continue
            try:
                saved.append(save_download(dl, folder, mark=self._saved))
            except Exception as e:
                print(f"[下载] 保存失败: {e}")
        return saved


# ======================================================================
# 文件名清洗 & 冲突去重
# ======================================================================
def _sanitize_name(name: str) -> str:
    """去掉 Windows/通用非法字符与空白控制符，防止路径注入。"""
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name).strip(" .")
    return name or "download"


def _unique_path(folder: Path, filename: str) -> Path:
    """同目录下重名时自动追加 _1/_2，避免覆盖已下载文件。"""
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / filename
    if not p.exists():
        return p
    stem, suffix = p.stem, p.suffix
    i = 1
    while (folder / f"{stem}_{i}{suffix}").exists():
        i += 1
    return folder / f"{stem}_{i}{suffix}"


def _guess_filename(download) -> str:
    """suggested_filename 为空时，从下载 URL 末尾推断文件名。"""
    name = (download.suggested_filename or "").strip()
    if name:
        return name
    try:
        name = Path(unquote(urlparse(download.url).path)).name
    except Exception:
        name = ""
    return name or "download"


# ======================================================================
# 保存单个下载
# ======================================================================
def save_download(download, folder: Path, mark: set = None) -> Path:
    """把 Download 对象保存到指定目录（自定义保存路径），返回最终路径。

    mark: 传入集合时把本下载 id 登记为已保存（防止 auto_save_all 重复保存）。
    """
    filename = _sanitize_name(_guess_filename(download))
    target = _unique_path(folder, filename)
    download.save_as(str(target))  # 同步等待文件完全写入
    size = target.stat().st_size if target.exists() else 0
    print(f"[下载] 已保存: {target}（{size} 字节）")
    if mark is not None:
        mark.add(id(download))
    return target


def _visible_locator_for(page, chosen: dict):
    """把候选元素映射为可点击的 locator。

    先按扫描序号直接定位；若该节点不可见（常见于同一按钮在移动端/桌面端
    重复渲染、或扫描到隐藏副本），则按『href + 文本完全一致』在可见节点中
    找同款元素兜底点击，避免误点隐藏副本导致超时。
    """
    els = page.locator(NODES_SELECTOR)
    primary = els.nth(int(chosen["idx"]))
    try:
        if primary.is_visible():
            return primary
    except Exception:
        pass

    want_text = (chosen.get("text") or "").strip()
    want_href = (chosen.get("href") or "").strip()
    total = els.count()
    for k in range(total):
        loc = els.nth(k)
        try:
            if not loc.is_visible():
                continue
            data = loc.evaluate(
                "el => ({href: el.getAttribute('href') || '',"
                " text: (el.innerText || el.textContent || '').replace(/\\s+/g,' ').trim().slice(0,150)})"
            )
            if data["href"] == want_href and data["text"] == want_text:
                return loc
        except Exception:
            continue
    return primary  # 找不到可见同款时返回原节点，让后续等待给出明确报错


# ======================================================================
# 点击下载按钮 + 捕获下载事件（同步主流程）
# ======================================================================
def click_and_capture(page, listener: DownloadListener, chosen: dict, cfg: dict):
    """点击目标元素并等待浏览器产生下载事件，期间监控权限拒绝。

    Args:
        page: 当前页面
        listener: 已挂载的下载监听器
        chosen: scan_download_candidates 输出的候选元素（含 idx/text/href/aria）
        cfg: 配置字典

    Returns:
        download: Playwright Download 对象

    Raises:
        PermissionGateError: 点击后页面出现权限拒绝提示（无下载产生）
        NoDownloadError: 超时无下载、无权限提示（选择器过期的典型症状）
    """
    # 点击前礼貌延时（基础反爬适配）
    human_delay(cfg)

    locator = _visible_locator_for(page, chosen)
    wait_ms = int(cfg.get("timeouts_ms", {}).get("wait", 15000))
    try:
        locator.wait_for(state="visible", timeout=wait_ms)
        locator.scroll_into_view_if_needed(timeout=wait_ms)
    except PlaywrightTimeout:
        raise NoDownloadError("目标按钮不可见/不存在，可能是页面结构变化或选择器过期。")

    # 点击前记录 body 文本基线：只有『点击后新出现的』权限拒绝文案才算数，
    # 避免页面静态说明里恰好含"无权限/需会员"字样造成误判。
    baseline_body = body_text(page) if cfg.get("page", {}).get("deny_texts") else ""

    before = listener.count()
    try:
        locator.click(timeout=wait_ms)
    except PlaywrightTimeout:
        raise NoDownloadError("点击目标按钮超时（元素可能被遮挡或不可点击）。")
    except Exception as e:
        raise RuntimeError(f"点击下载按钮失败：{e}") from e

    # ---- 轮询：等下载事件 / 等权限拒绝提示 ----
    download_ms = int(cfg.get("timeouts_ms", {}).get("download", 120000))
    deadline = time.monotonic() + download_ms / 1000.0
    last_deny_check = 0.0
    while time.monotonic() < deadline:
        if listener.count() > before:
            dl = listener.latest()
            print(f"[下载] 捕获到下载事件: {dl.suggested_filename or dl.url}")
            return dl

        # 每秒检查一次：点击后是否新出现权限拒绝提示（及时止损，而非干等超时）
        now = time.monotonic()
        if now - last_deny_check >= 1.0:
            last_deny_check = now
            deny = new_deny_text(page, cfg, baseline_body)
            if deny:
                raise PermissionGateError(
                    f"服务端返回权限拒绝提示『{deny}』：当前账号无权下载该资源。\n"
                    "  合规处理：立即停止，不做任何越权绕过。"
                    "如你确认账号应有权限，请检查是否登录了正确的会员账号/资源链接是否正确。"
                )
        time.sleep(0.25)

    raise NoDownloadError(
        f"点击后 {download_ms / 1000:.0f} 秒内未产生下载，也未收到权限拒绝提示。\n"
        "可能原因：该按钮并非下载按钮 / 页面结构已变化（选择器过期）/ 下载需二次确认。\n"
        "建议：先运行 python main.py --list-buttons 查看候选，再用 --pick / --index 精确选择。"
    )
