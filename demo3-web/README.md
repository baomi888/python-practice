# Baomi Agent — DeepSeek 智能体 Web 应用

> 豆包风格的 **AI Agent + 联网搜索 + 资源下载** 一体化 Web 应用
> Flask 后端 + 原生 HTML/JS 前端 + DeepSeek 大模型

---

## ✨ 功能亮点

### 🧠 AI 对话
- ✅ DeepSeek 大模型（`deepseek-v4-flash`）+ 多轮上下文
- ✅ **联网搜索自动触发**：AI 自己判断是否需要搜，不用手动开 toggle
- ✅ **LLM 驱动资源搜索/下载**：说"帮我下豆包"→ 自动搜 + 自动推荐 + 一键下载
- ✅ 多模态图片理解：上传图片后直接问问题
- ✅ 多会话管理（创建/切换/重命名/删除，文件持久化）
- ✅ 深浅模式（一键切换 + 持久化）
- ✅ Kimi 风格工具栏（复制/重试/分享/点赞/点踩）

### 🔎 联网搜索（中国本地化）
- ✅ **Serper API + Playwright 双阶段**：Google/Bing 搜索 → Playwright 抓正文
- ✅ **中国地区强制** `gl=cn, hl=zh-cn`（不再给你搜出 Chrome 下载页）
- ✅ **浏览器下载页 + Google 主页自动过滤**
- ✅ 可信度评分（官方源+20 GitHub+25 垃圾站-15 假文件直接丢）
- ✅ 三路 fallback 关键词建议（搜不到换词自动再搜）

### 📥 资源搜索 / 下载
- ✅ **对话式触发**（推荐）：直接说"帮我下载豆包 Windows 客户端"
- ✅ **搜索历史下拉**：输入框 focus 自动弹出历史（localStorage 存，去重最多 15 条）
- ✅ 结果按信誉分排序（⭐官方 / ✅可信 / ⚠️一般 / ❌低质）
- ✅ 直链文件一键下载 → 按钮变绿 + 📂打开本地文件
- ✅ 找不到时给**具体替代建议卡**（换关键词 + 换类型 + 用英文搜）
- ✅ 支持 9 种类型：📄PDF / 📚电子书 / 🎵音乐 / 🎬视频 / 📦压缩包 / 🔧软件 / 🐍Python / 📝文本

### 🚀 一键启动
```
双击 start.bat → 自动杀旧进程 → 启 Flask → 自动开浏览器 → 完事
双击 stop.bat → 一键停止
```

---

## 📦 项目结构

```
demo3-web/
├── server.py              # Flask 后端（路由 + API + 会话 + 搜索 + 下载）
├── client.py              # DeepSeekClient（API 调用 + 重试 + 异常分类）
├── index.html             # 前端（HTML + Tailwind v3 + 原生 JS，全部 UI）
├── start.bat              # 🔑 一键启动（杀旧进程 + 启服务 + 开浏览器）
├── stop.bat               # 一键停止
├── app.py                 # Flask 启动入口（被 start.bat 调起）
├── .env.example           # 环境变量模板
├── requirements.txt       # Python 依赖
├── crawler/               # 爬虫子模块
│   ├── paper_download.py  #   arXiv 论文下载（CLI + Python API）
│   ├── download_direct.py #   requests 直链下载（断点续传）
│   ├── download_demo.py   #   Playwright 浏览器下载（点下载按钮）
│   └── config.example.json
├── sessions/              # 会话持久化（运行时自动创建）
├── resources/             # 通用资源下载目录（运行时自动创建）
├── papers/                # arXiv PDF 下载目录（运行时自动创建）
└── README.md              # 本文档
```

---

## 🛠️ 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Flask + flask-cors + requests |
| 大模型 | DeepSeek API（deepseek-v4-flash） |
| 联网搜索 | Serper.dev API（Google + Bing，中国地区） |
| 正文抓取 | Playwright（优先本机 Edge → 退回 Chromium） |
| 文件下载 | requests 流式 + 断点续传 |
| 论文下载 | feedparser + arXiv Atom API |
| PDF 解析 | PyPDF2 |
| 前端 | 原生 HTML5 + Tailwind v3 + 原生 JS（ES6+） |
| 代码高亮 | Prism.js CDN |
| 会话存储 | `sessions/<sid>.json` 文件持久化（零数据库） |

---

## 🚀 快速开始（3 步）

### 1. 安装依赖

```bash
cd demo3-web
pip install -r requirements.txt
```

> 可选依赖（未装也能跑，自动降级）：
> - `playwright` + `playwright install chromium` — 联网搜索正文抓取
> - `feedparser` — arXiv 论文下载

### 2. 配置密钥

```bash
copy .env.example .env       # Windows PowerShell
# cp .env.example .env      # macOS / Linux
```

编辑 `.env`：

```env
# 必填：DeepSeek
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_API_URL=https://api.deepseek.com/v1/chat/completions

# 可选：多模态
# DEEPSEEK_VISION_MODEL=deepseek-v4-flash-vision-exp

# 可选：联网搜索（https://serper.dev 注册，免费每月 2500 次）
SERPER_API_KEY=your_key_here
```

### 3. 启动

```
方式 A（推荐）：双击 start.bat
方式 B：命令行 python server.py
```

启动成功后自动打开 **http://localhost:7860** 🎉

---

## 💬 对话里怎么触发搜索/下载？

### AI 自动意图识别——你说这些话就自动搜

| 你说 | AI 做什么 |
|------|----------|
| 「帮我下载豆包客户端」 | 🔎 搜资源 → LLM 推荐 doubao.com 官网第 1 → 卡片出来 → 点下载 |
| 「给我 RAG 相关的 PDF 论文」 | 🔎 搜 arXiv → LLM 筛选 → PDF 直链排前面 |
| 「想找个 blender 免费教程」 | 🔎 多引擎搜 blender → 官方源 + GitHub + 国内站 |
| 「豆包最新版本号是多少」 | 🔎 自动搜联网信息（普通 info 意图） |
| （闲聊"你好"） | AI 自己说"不需要联网"，直接用已有知识回答 |

### 信誉分系统

每张资源卡有信誉徽章（AI 已经帮你筛过了）：

| 徽章 | 含义 |
|------|------|
| ⭐ 官方 | doubao.com / github.com/releases / python.org 等 |
| ✅ 可信 | sourceforge / ninite / 官方 CDN |
| ⚠️ 一般 | apkpure / uptodown（可能有广告） |
| ❌ 低质 | 垃圾广告站 / 超小假文件（已尽量过滤） |

### 找不到资源时

AI 会自动给**替代建议卡**：
- 换关键词试试（列出它自动生成的替代词）
- 换类型试试（加 site:github.com / filetype:pdf）
- 用英文搜（中文关键词结果天生少）
- 直接说在对话框（说完整需求效果好）

---

## 🖥️ 界面操作

### 侧边栏
- 「+ 新对话」→ 创建
- 点击历史项 → 切换
- hover 历史项 → X 删除
- 底部 → 深浅模式切换

### 输入区
| 操作 | 说明 |
|------|------|
| **focus 输入框** | 自动弹出**🔍 搜索历史**（最近 15 条，点一行直接填入） |
| **输入时** | 历史实时按子串过滤 |
| **Enter** | 发送 |
| **Shift + Enter** | 换行 |
| **📎 附件** | 图片 / txt / md / pdf 多选 |
| **发送中红色按钮** | 停止生成 |

### AI 回复气泡底部
```
📦 AI 为你找到 4 个可下载资源 · 点「⬇ 下载」直接下到本地

⭐ 官方 | 🔗 网页 | www.doubao.com | 58 KB | ⬇ 下载  🔗
✅ 可信 | 📄 PDF | arxiv.org | 752 KB | ⬇ 下载  🔗
⚠️ 一般 | 🔗 网页 | uptodown.com | - | ⬇ 下载  🔗
```

点「⬇ 下载」→ 按钮变绿 ✅ 已下 → 追加 📂 打开按钮
点「🔗」→ 浏览器打开原页面

---

## 🔌 API 文档

### 核心接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 返回前端 index.html |
| GET | `/api/health` | 健康检查 |
| POST | `/api/chat` | **核心对话接口**（支持自动联网搜索 + 资源查找） |
| POST | `/api/upload` | 文件上传（图片 → base64 / txt,md,pdf → 文本提取） |
| GET | `/api/sessions` | 列出所有会话 |
| POST | `/api/sessions` | 创建新会话 |
| GET | `/api/sessions/<sid>` | 加载会话历史 |
| DELETE | `/api/sessions/<sid>` | 删除会话 |

### 资源搜索/下载（给前端独立调用 + LLM 内部复用）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/resource/search` | 搜资源（Serper 多路并发 + HEAD 探测 + 信誉分排序） |
| POST | `/api/resource/download` | 下载直链文件到 `resources/` 目录 |
| GET | `/api/resource/list` | 列出已下载文件 |
| GET | `/api/resource/file/<filename>` | 浏览器打开已下载文件 |

### `/api/chat` 请求

```json
{
  "session_id": "abc123",
  "message": "帮我下载豆包 Windows 客户端",
  "web_search": false,
  "files": []
}
```

### `/api/chat` 响应

```json
{
  "reply": "推荐从 doubao.com 官网下载（⭐ 官方，最可信）...",
  "model": "deepseek-v4-flash",
  "searched": true,
  "sources": [
    {"source_id": 1, "title": "下载豆包客户端", "snippet": "...", "link": "..."}
  ],
  "resource_results": [
    {
      "title": "下载豆包客户端",
      "filetype_label": "🔗 网页",
      "domain": "www.doubao.com",
      "score": 78.0,
      "link": "https://www.doubao.com/download/",
      "is_suggestion": false
    }
  ]
}
```

---

## 🧩 联网搜索完整流程

```
用户在对话框说 "帮我下豆包"
         ↓
   /api/chat
         ↓
_auto_should_search() ──→ 自动识别 intent_tag="resource"
         ↓
do_web_search() ──→ Serper (gl=cn, hl=zh-cn) + Playwright 抓正文
         ↓
_run_resource_search() ──→ Google + Bing 并发
   ├─ 多路 query（原始 + 剥掉指令词 + 加 github/official/filetype:pdf）
   ├─ HEAD 探测 Content-Type + Content-Length
   ├─ _score_resource() 信誉分（官方+20 GitHub+25 广告-15 假文件<3KB直接丢）
   ├─ 过滤浏览器下载页黑名单
   ├─ 结果 < 3 条？→ 自动换关键词再搜一轮
   └─ 还是少？→ 生成 💡 建议卡
         ↓
_format_resource_results_for_llm() ──→ 喂给 DeepSeek
         ↓
DeepSeek 回复自然语言推荐 + resource_results 结构化卡
         ↓
前端 renderResourceCards() ──→ 在对话气泡底部渲染卡片
```

---

## 🗂️ 会话文件格式

`sessions/<sid>.json`：

```json
{
  "id": "abc123",
  "title": "新对话",
  "created_at": 1725500000,
  "messages": [
    {"role": "system", "content": "...Baomi Agent 指令..."},
    {"role": "user", "content": "帮我下载豆包"},
    {"role": "assistant", "content": "推荐 doubao.com 官网..."}
  ]
}
```

---

## 🛡️ 合规红线

- ❌ 不破解付费墙 / 不伪造 Cookie 提权
- ❌ 不碰 Sci-Hub / LibGen / BT 站 / 盗版 MP3 站（PIRACY_BLOCKLIST）
- ✅ 只推荐合法公开资源（GitHub Releases / 官方下载页 / arXiv / public domain）
- ✅ Cookie 只存自己的登录态（crawler/sessions/）
- ✅ `.env` 和 `sessions/` 已在 `.gitignore`

---

## 📝 更新日志

### Day 9（2026-09-09）
- ✅ **LLM 驱动资源搜索**：意图识别 → Serper 多路 → Playwright 正文 → LLM 筛选推荐 → 对话气泡卡
- ✅ **搜索历史下拉**：输入框 focus 自动弹出，localStorage 存，去重 15 条
- ✅ **一键启动脚本**：`start.bat` / `stop.bat`
- ✅ **中国本地化**：Serper `gl=cn, hl=zh-cn`，浏览器下载页黑名单
- ✅ **信誉分 + 浏览器下载页过滤**

### Day 8
- ✅ Playwright 正文抓取集成联网搜索
- ✅ arXiv 文献搜索 + 下载后端（`/api/paper/*`）

### Day 5-7
- ✅ 文件上传（图片 / txt / md / pdf）
- ✅ Kimi 风格工具栏 + 代码块增强 + 上角标跳转
- ✅ 多会话持久化 + 深浅模式

---

## 🔒 安全

- `.env` / `sessions/` / `resources/` 全部在 `.gitignore`
- 所有密钥从环境变量读取，零硬编码
- 前端 `escapeHtml()` 全程 XSS 防护
- 文件上传后端 MIME + 扩展名双重校验

> 🎀 粉色主题 · 豆包风格预览 · 小猪涂鸦头像 🐷
