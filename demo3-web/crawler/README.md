# demo3-web / crawler — Playwright 登录会话爬虫

在 **demo3-web（Baomi Agent）** 项目中新增的独立爬虫模块：用 **Playwright 同步 API 模拟真实 Chromium 浏览器**，
处理 **JS 动态渲染**、网页 **动态校验/反爬**、**登录会话 Cookie 保存与复用**、**下载按钮识别与下载事件捕获**。

> ⚠️ **使用前提（务必先读『合规红线』章节）**：本程序只用于**你本人拥有合法账号与访问权限**的网站，
> 只下载你本人有权获取的内容。**绝不包含**任何绕过鉴权、伪造会员权限、破解登录/验证码的代码。

---

## 一、它能做什么（对应需求点）

| 需求 | 实现位置 |
|---|---|
| Playwright **同步 API**，无头/有头切换 | `browser_ctx.py`；CLI `--headless` / `--headed` |
| 页面等待 + 动态加载 + 弹窗 + 简单人机验证 | `page_utils.py`（`wait_page_ready` / `close_popups` / `pause_for_verification`） |
| 登录上下文完整保留，Cookie 复用免重复登录 | `session.py` + `browser_ctx.save_storage_state()` |
| 监听下载事件、自定义保存路径 | `download_mgr.py`（`DownloadListener` + `save_download`） |
| 请求延时、基础反爬适配 | `page_utils.human_delay` + `config.json -> delay` |
| 注释区分合法逻辑 / 标注越权破解红线 | 各模块 docstring + 本文档『合规红线』 |
| 识别页面内下载按钮 | `scan_download_candidates()`（关键词 + 扩展名打分排序） |

---

## 二、目录结构

```
demo3-web/crawler/
├── main.py                  # CLI 入口：登录 → 打开目标页 → 扫描/点击下载按钮 → 保存
├── browser_ctx.py           # Chromium 启动、storage_state 登录态恢复、JS 弹窗兜底
├── session.py               # 登录判定 + 首次【有头】人工登录 + Cookie 落盘
├── page_utils.py            # 等待/弹窗/验证码(人工)/延时/按钮扫描/权限红线检查
├── download_mgr.py          # 下载事件监听与捕获、自定义保存、重名去重
├── config.json              # 默认配置：GitHub 公开仓库演示（无需登录，验证真实下载）
├── config.local.json        # 本地离线演示（登录门禁 + JS 渲染 + 下载/无权限，全流程）
├── config.example.json      # 会员站配置模板（含字段说明）
├── requirements.txt         # playwright
├── .gitignore               # storage/ downloads/ logs/ 不入库
└── local_demo_site/         # 本地演示站点（python -m http.server 启动）
```

---

## 三、环境安装步骤

### 1. 创建虚拟环境（推荐）

```bash
# Windows PowerShell（在 demo3-web/crawler 目录下）
python -m venv .venv
.venv\Scripts\activate

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

### 2. 安装依赖并下载 Chromium

```bash
pip install -r requirements.txt        # 安装 playwright
python -m playwright install chromium  # 下载 Playwright 官方 Chromium
```

- **Linux 服务器**（无头部署）若缺系统库：`python -m playwright install --with-deps chromium`（需 sudo）。
- **国内网络**下载浏览器慢/失败时，可先设置镜像再执行安装：
  ```bash
  # PowerShell
  $env:PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright/"
  python -m playwright install chromium
  ```

验证安装：

```bash
python -c "from playwright.sync_api import sync_playwright; print('playwright OK')"
```

---

## 四、快速开始

### 方案 A：本地离线演示（推荐先跑通，不需要联网）

**第 1 步**：新开一个终端，启动本地演示站点：

```bash
python -m http.server 8000 --directory local_demo_site
```

**第 2 步**：首次【有头】运行，体验"人工登录 → 保存 Cookie"：

```bash
python main.py --config config.local.json --headed
```

程序会打开浏览器访问 `http://127.0.0.1:8000/`，检测到未登录后停在登录页等你点击
页面上的 **"模拟登录（设置演示 Cookie）"** 按钮；登录成功自动保存会话 → 自动打开内容页 →
等待 JS 延迟渲染（1.5s）→ 扫描并自动下载 `data.csv` 到 `downloads/`。

**第 3 步**：第二次【无头】运行，验证 Cookie 复用（不再需要人工）：

```bash
python main.py --config config.local.json --headless
```

**第 4 步（红线演示）**：试试会员专享按钮 —— 程序应在收到"无权限"提示后立刻停止（退出码 3）：

```bash
python main.py --config config.local.json --headless --pick "vip"
```

### 方案 B：真实公开站点（默认配置，GitHub 公共仓库，无需登录）

```bash
python main.py --headed                 # 有头观察：展开 Code 下拉 → 点击 Download ZIP
python main.py --headless               # 无头直接下载
python main.py --list-buttons           # 只扫描列出页面上的下载候选
```

### 方案 C：你自己的会员/需登录站点

1. `copy config.example.json config.mysite.json`（Linux/macOS：`cp`）；
2. 按下节表格修改 `site.home_url / target_url / login` 与页面等待、关键词；
3. 首次运行 **必须带 `--headed`** 用本人账号完成登录（支持扫码/短信/滑块，均可人工完成）；
4. 之后即可 `--headless` 复用会话批量下载**本人有权**的文件。

---

## 五、配置项说明（config.example.json）

| 配置 | 含义 |
|---|---|
| `site.home_url` / `target_url` | 首页 / 待抓取下载的目标页 |
| `site.login.enabled` | `true`=需登录；`false`=公开资源直接跳过登录逻辑 |
| `site.login.logged_in_check` | 判定已登录：`marker_present`（选择器可见=已登录，最常用）/ `marker_absent` / `url_contains` |
| `browser.headless` | 默认无头与否（CLI `--headless/--headed` 可覆盖） |
| `browser.channel` | 用本机已装浏览器（如 `"msedge"` / `"chrome"`），留空用 Playwright Chromium |
| `delay.min_sec/max_sec` | 操作间随机延时区间（基础反爬礼貌适配） |
| `timeouts_ms.*` | 页面加载/等待/登录等待/下载等待/人机验证等待（毫秒） |
| `page.content_wait` | JS 动态内容就绪的标志选择器（**动态站必填**，如本地演示的 `#dl-csv`） |
| `page.popup_close_selectors` | 公告/浮层关闭按钮 CSS 列表，自动逐个尝试关闭 |
| `page.verification_selectors` | 人机验证特征选择器；出现时**暂停请人工完成**，不自动破解 |
| `page.deny_texts` | 权限拒绝提示词；命中即按红线停止（如"需要会员"） |
| `page.expand_steps` | 点击展开动态 UI（下拉/折叠），支持 `click_text` / `click_role` / `click_css` / `wait_ms` |
| `download.keywords` | 按钮/链接含这些词视为下载候选（中英文都写） |
| `download.href_ext_hits` | href 以这些扩展名结尾 → 最高分候选 |
| `download.exclude_keywords` | 排除误匹配（登录/注册/翻页等） |
| `paths.storage` | 登录态 Cookie 落盘文件（敏感！已被 .gitignore 忽略） |

---

## 六、常用命令速查

```bash
# 登录态管理
python main.py --config xxx.json --headed --force-login   # 删除旧会话，强制重新人工登录
# 按钮扫描（页面结构变化时先看这里）
python main.py --list-buttons --config xxx.json
# 精确挑选（--index 序号来自 --list-buttons 的输出）
python main.py --pick "data" --config config.local.json
python main.py --index 2 --config config.local.json
# 覆盖 URL（临时抓别的页面）
python main.py --url "https://example.com/other-page" --pick "报告"
```

---

## 七、合规红线（重要，请逐条确认）

本项目只面向**你拥有合法访问权**的资源。**以下内容一律不实现、不绕过**：

1. **不绕过鉴权**：不注入/重放他人 Cookie，不偷取他人会话；
2. **不伪造会员权限**：不改 Cookie/localStorage 里的会员标记、不伪造支付/会员接口返回；
3. **不破解登录**：不自动填他人账号、不爆破密码、不做验证码自动识别/打码/滑块模拟；
   人机验证出现时**由你在窗口中人工完成**（`pause_for_verification` 就是这么设计的）；
4. **无权限即停**：服务端返回"无权限/需要会员"时程序立刻中止并报错（退出码 3），
   提示你确认账号身份或走站内正规渠道开通，而不是找绕过路径；
5. **尊重网站条款**：延时只是礼貌性节流，不等于获得授权——自动化访问前请确认目标站
   robots.txt 与用户协议是否允许，商业化/批量抓取建议先取得书面许可；
6. **保管好会话文件**：`crawler/storage/*.json` 等于你的登录凭证，**不要提交到 Git、
   不要发给任何人**（`.gitignore` 已默认忽略）；
7. 敏感内容（付费资料、会员专享、个人隐私数据）是否可自动化获取，以站方规则与当地法律为准。

---

## 八、常见问题

| 现象 | 处理 |
|---|---|
| 首次运行报"需要登录但无头模式" | 带上 `--headed` 先完成一次人工登录（会自动保存 Cookie） |
| 点击后提示无下载、无权限、超时 | 页面结构变了：先 `--list-buttons` 看候选，再用 `--pick/--index`；或更新 `expand_steps/content_wait` |
| 提示"服务端返回权限拒绝" | 当前账号确实无权 → 合规停止；确认账号/链接无误后重试 |
| GitHub 页面改版后点不动 Code/Download ZIP | 更新 `config.json` 的 `expand_steps` 与 `download.keywords`（版本变更常见） |
| 下载按钮在 iframe/内嵌框架里 | 当前扫描基于主框架 DOM；请改用 `expand_steps` 的 `click_css` 先点进/切到对应框架页面，或把该 iframe 的 src 作为 `target_url` 直接访问 |
| 无头 Linux 缺依赖 | `python -m playwright install --with-deps chromium` |
| 想用本机 Edge/Chrome | `browser.channel` 填 `msedge`/`chrome`，可不下载 Playwright Chromium |

---

## 九、与 demo3 / demo3-web 的关系

| 模块 | 说明 |
|---|---|
| `demo3` | 控制台版 DeepSeek 问答（requests 直连 API） |
| `demo3-web` | Flask Web 版（联网搜索仅用 Serper 搜索元数据，不抓正文） |
| `demo3-web/crawler`（本模块） | **新增**：真正的网页正文/文件抓取引擎（Playwright），
  可作为 demo3-web 联网搜索的"正文抓取"增强（把返回的网页文本喂给 Baomi Agent），
  也可独立命令行使用。接入 Flask 时请把 Playwright 放在独立进程/队列中，避免阻塞请求线程。 |
