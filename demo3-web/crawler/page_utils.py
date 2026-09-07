"""页面操作工具集 —— 等待、弹窗关闭、人机验证人工暂停、下载按钮扫描、权限红线检查。

所有功能都服务于『普通用户用本人账号正常浏览/下载』这一合法场景：
- 等待策略处理 JS 动态渲染与懒加载；
- 弹窗/人机验证：能自动处理的（普通浮层/JS 对话框）自动处理；需要人参与的
  验证码一律『暂停并请用户在窗口中人工完成』，绝不编写自动识别/滑动破解代码。
"""
from __future__ import annotations

import random
import re
import time

from playwright.sync_api import TimeoutError as PlaywrightTimeout

# 候选下载元素的统一选择器（扫描与点击共用同一选择器，保证序号一一对应）
NODES_SELECTOR = "a, button, [role='button'], input[type='submit'], input[type='button']"

# 在页面里批量采集候选元素信息的 JS（返回 DOM 顺序的数组）
COLLECT_JS = """(selector) => {
  return Array.from(document.querySelectorAll(selector)).map((el, idx) => {
    const tag = el.tagName.toLowerCase();
    let text = '';
    if (tag === 'input') {
      text = ((el.value || '') + ' ' + (el.getAttribute('placeholder') || '')).trim();
    } else {
      text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
    }
    return {
      idx,
      tag,
      text: text.slice(0, 150),
      href: el.getAttribute('href') || '',
      aria: el.getAttribute('aria-label') || ''
    };
  });
}"""


# ======================================================================
# 基础反爬适配：请求/操作之间的随机延时（礼貌抓取）
# ======================================================================
def human_delay(cfg: dict, min_sec: float = None, max_sec: float = None) -> None:
    """在两次页面操作之间随机停顿，模拟人类节奏，降低对源站的瞬时压力。

    注意：延时只是『基础礼貌性适配』，不会让自动化变得"合法"——
    是否允许自动化取决于目标站点条款；请遵守 robots.txt 与 ToS。
    """
    d = cfg.get("delay", {})
    if not d.get("enabled", True):
        return
    lo = min_sec if min_sec is not None else float(d.get("min_sec", 0.8))
    hi = max_sec if max_sec is not None else float(d.get("max_sec", 2.5))
    time.sleep(random.uniform(max(0.1, lo), max(lo + 0.1, hi)))


# ======================================================================
# 页面等待：处理动态加载
# ======================================================================
def wait_page_ready(page, cfg: dict) -> None:
    """等待页面关键内容就绪。

    1) 若配置了 content_wait 选择器（JS 渲染完成标志），等待其可见；
    2) 否则等待短暂随机时间让懒加载内容出现。
    之后再做一次小幅随机延时，模拟真实阅读节奏。
    """
    sel = (cfg.get("page", {}) or {}).get("content_wait", "")
    wait_ms = int(cfg.get("timeouts_ms", {}).get("wait", 15000))
    if sel:
        try:
            page.locator(sel).first.wait_for(state="visible", timeout=wait_ms)
            print(f"[等待] 动态内容已就绪: {sel}")
        except PlaywrightTimeout:
            print(f"[警告] 等待内容超时（{sel}），继续尝试后续流程……")
    else:
        time.sleep(random.uniform(1.0, 2.0))
    # 给后续懒加载/脚本一个缓冲
    human_delay(cfg)


# ======================================================================
# 弹窗 / 浮层关闭（可自动处理的简单场景）
# ======================================================================
def close_popups(page, cfg: dict) -> None:
    """按配置逐个尝试点击关闭按钮（公告弹窗、Cookie 横幅等）。"""
    selectors = (cfg.get("page", {}) or {}).get("popup_close_selectors", []) or []
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                loc.click(timeout=2000)
                print(f"[弹窗] 已关闭: {sel}")
                time.sleep(random.uniform(0.5, 1.0))
        except Exception:
            pass  # 没有弹窗/已消失时静默跳过


# ======================================================================
# 简单人机验证场景处理（人工参与，红线内）
# ======================================================================
def pause_for_verification(page, cfg: dict, headless: bool) -> None:
    """检测到人机验证（滑块/点选/图形验证码等）时的处理策略：

    ✅ 合法做法：暂停自动化，打印提示，请用户在窗口内【人工完成】验证；
    ❌ 红线：任何『自动识别/模拟滑动/调用打码平台』的破解代码一律不写。

    Returns:
        验证通过（标记消失）或未配置验证特征时正常返回；
        超时仍无法通过则抛 RuntimeError。
    """
    selectors = (cfg.get("page", {}) or {}).get("verification_selectors", []) or []
    if not selectors:
        return

    def verification_visible() -> bool:
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    return True
            except Exception:
                pass
        return False

    if not verification_visible():
        return

    if headless:
        # 无头模式下无法人工操作 → 明确拒绝继续，而不是尝试绕过
        raise RuntimeError(
            "检测到人机验证，但当前为无头模式无法人工完成。"
            "请改用 --headed 运行，由你在窗口中人工通过验证。"
            "（本程序不提供任何自动破解验证码的能力——合规红线）"
        )

    timeout_ms = int(cfg.get("timeouts_ms", {}).get("verify_wait", 300000))
    deadline = time.monotonic() + timeout_ms / 1000.0
    print("\n" + "=" * 60)
    print("[人机验证] 页面出现了人机验证。请在打开的浏览器窗口中【人工】完成验证。")
    print("           本程序不会自动破解验证码（合规红线）。等待中……")
    print("=" * 60)
    tick = 0
    while verification_visible():
        if time.monotonic() > deadline:
            raise RuntimeError("人机验证等待超时，已停止运行。请人工通过验证后重试。")
        time.sleep(1.0)
        tick += 1
        if tick % 10 == 0:
            print(f"          仍在等待人工验证……（已等待 {tick} 秒）")
    print("[人机验证] 已通过（人工完成），继续执行。")


# ======================================================================
# 展开动态 UI（下拉菜单/折叠区等，展开后下载按钮才会出现在 DOM/视野中）
# ======================================================================
def _click_first_visible(locs, timeout: int) -> None:
    """在多个匹配元素中点击第一个可见的（跳过隐藏副本/离屏副本）。"""
    last_exc = None
    for loc in locs:
        try:
            if loc.is_visible():
                loc.click(timeout=timeout)
                return
        except Exception as e:
            last_exc = e
    if last_exc:
        raise last_exc
    raise RuntimeError("没有可点击的可见匹配元素")


def expand_ui(page, cfg: dict) -> None:
    """按配置的 expand_steps 顺序执行 UI 展开操作。

    支持的 action：
      - click_text : 点击包含指定文本的元素（value）
      - click_role : 点击指定 role 与 name 的元素，如 {"role":"button","name":"Code"}
      - click_css  : 点击 CSS 选择器元素（selector）
      - wait_ms    : 原地等待毫秒（value）
    """
    steps = (cfg.get("page", {}) or {}).get("expand_steps", []) or []
    for step in steps:
        action = step.get("action", "")
        tip = step.get("tip", "")
        try:
            if action == "click_text":
                human_delay(cfg, 0.5, 1.2)
                # 依次尝试匹配项，点击第一个【可见】的（避免点到隐藏副本）
                locs = page.get_by_text(step["value"], exact=False).all()
                _click_first_visible(locs, timeout=8000)
                print(f"[展开] 点击文本 '{step['value']}' 成功{f'（{tip}）' if tip else ''}")
            elif action == "click_role":
                human_delay(cfg, 0.5, 1.2)
                locs = page.get_by_role(step["role"], name=step["name"]).all()
                _click_first_visible(locs, timeout=8000)
                print(f"[展开] 点击 {step['role']} '{step['name']}' 成功{f'（{tip}）' if tip else ''}")
            elif action == "click_css":
                human_delay(cfg, 0.5, 1.2)
                page.locator(step["selector"]).first.click(timeout=8000)
                print(f"[展开] 点击 CSS '{step['selector']}' 成功{f'（{tip}）' if tip else ''}")
            elif action == "wait_ms":
                time.sleep(int(step.get("value", 1000)) / 1000.0)
                print(f"[展开] 等待 {step.get('value')} ms")
            else:
                print(f"[警告] 未知 expand action: {action}")
            time.sleep(random.uniform(0.6, 1.4))  # 展开动画缓冲
        except Exception as e:
            print(f"[展开] 步骤失败（{action} {tip}）：{e}（非致命，继续）")


# ======================================================================
# 下载按钮扫描与识别
# ======================================================================
def _text_of(c: dict) -> str:
    return " ".join(filter(None, [c.get("text", ""), c.get("href", ""), c.get("aria", "")]))


def _candidate_blocked(cfg: dict, c: dict) -> bool:
    """候选元素是否应被排除：
    1. 无可识别文本/href/aria 的纯图标（无法判断意图，跳过）；
    2. href 为空链接(# / javascript:)；
    3. 命中 exclude_keywords（登录/注册/导航等，防止误点）。
    """
    raw = _text_of(c)
    if not raw.strip():
        return True
    href = (c.get("href") or "").strip().lower()
    if href.startswith("#") or href.startswith("javascript:"):
        return True
    low = raw.lower()
    for kw in cfg.get("download", {}).get("exclude_keywords", []):
        if kw.strip().lower() in low:
            return True
    return False


def _rank(cfg: dict, c: dict) -> int:
    """给候选元素打分：命中关键词 +2/词，href 以文件扩展名结尾 +5（最像下载目标）。"""
    low = _text_of(c).lower()
    score = 0
    for kw in cfg.get("download", {}).get("keywords", ["下载", "download"]):
        if kw.strip().lower() in low:
            score += 2
    href = (c.get("href") or "").strip().lower()
    for ext in cfg.get("download", {}).get("href_ext_hits", []):
        if href.endswith(ext.lower()):
            score += 5
    return score


def scan_download_candidates(page, cfg: dict) -> list:
    """扫描页面内所有 a/button 等元素，返回【按下载意图排序】的候选列表。

    Returns:
        list[dict]: 每项含 idx(对应统一选择器的 nth 序号)、tag、text、href、aria、score。
        该 idx 可直接用于 page.locator(NODES_SELECTOR).nth(idx) 点击。
    """
    try:
        nodes = page.evaluate(COLLECT_JS, NODES_SELECTOR)
    except Exception as e:
        print(f"[扫描] 采集页面元素失败：{e}")
        return []
    nodes = [n for n in nodes if not _candidate_blocked(cfg, n)]
    for n in nodes:
        n["score"] = _rank(cfg, n)
    nodes.sort(key=lambda x: (-x["score"], x["idx"]))  # 高分优先，同分按 DOM 顺序
    return nodes


# ======================================================================
# 权限红线检查（绝不越权）
# ======================================================================
def candidate_is_vetoed(cfg: dict, text: str, href: str = "", aria: str = "") -> str:
    """点击前的红线检查：候选元素自身若带『需付费/需会员/无权限』字样，
    说明该按钮本来就不是给当前账号用的 → 直接拒绝点击（返回拒绝原因）。

    普通用户/本人会员账号的合法权限由账号本身决定：有权限则正常下载，
    无权限则停下并提示，绝不通过改包/伪造凭证去拿本不属于自己的文件。
    """
    low = (text + " " + href + " " + aria).lower()
    for deny in cfg.get("page", {}).get("deny_texts", []):
        if deny.lower() in low:
            return f"目标带权限门槛字样『{deny}』（当前账号不应触发该操作）"
    return ""


def body_text(page) -> str:
    """读取当前页面 body 可见文本（供权限拒绝检测比对）。失败返回空串。"""
    try:
        return page.locator("body").inner_text(timeout=3000)
    except Exception:
        return ""


def new_deny_text(page, cfg: dict, baseline: str = "") -> str:
    """检测『相对 baseline 新出现的』权限拒绝文案。

    设计原因：页面静态区域（页脚说明等）可能本身就包含"无权限/需会员"等字样，
    只有点击后**新增**的拒绝提示才代表服务端对本操作的拒绝 → 据此判定可避免误伤。
    """
    denies = cfg.get("page", {}).get("deny_texts", []) or []
    if not denies:
        return ""
    current = body_text(page)
    if not baseline:  # 基线读取失败时保守处理：不因静态文案误报
        return ""
    for deny in denies:
        if deny in current and deny not in baseline:
            return deny
    return ""
