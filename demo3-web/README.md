# Baomi Agent — DeepSeek 智能体 Web 应用

基于 DeepSeek 大模型 API 的 **现代 AI Agent 对话 Web 应用**，Flask 后端 + 原生 HTML/Tailwind/JS 前端。复用 `demo3` 核心客户端逻辑，在其基础上扩展了多会话管理、联网搜索、Kimi 风格工具栏、文件上传、参考来源结构化、多模态图片理解等完整的 Web 能力。

> 🔁 本项目是 `demo3`（控制台版）的 Web 升级版本，**核心业务代码（DeepSeekClient）完全复用，不做任何修改**。

## ✨ 功能清单

### 🧠 核心能力（来自 demo3）
- 🔐 `.env` 读取 API 密钥，**零硬编码**
- 💬 多轮对话，自动维护 `messages` 上下文历史
- 🔁 失败自动重试 2 次，间隔 1 秒
- 🛡️ 分类异常处理：认证失败 / 网络断开 / 请求超时 / 服务端错误
- 🌐 **联网搜索**：Serper API 搜最新网页 → 注入 prompt → DeepSeek 总结

### 🖥️ Web 增强（demo3 没有的）

| 模块 | 功能 |
|------|------|
| **多会话管理** | 创建/切换/重命名/删除会话，`sessions/*.json` 持久化，刷新不丢 |
| **深浅模式** | 一键切换 + localStorage 持久化 + 全组件自动适配 |
| **Kimi 风格工具栏** | AI 消息 hover 浮现：**复制 / 重试 / 分享 / 点赞 / 点踩** |
| **Markdown 渲染** | 零依赖自写渲染器：代码块 / 行内代码 / 标题 / 列表 / 加粗 / 引用 / 链接 |
| **代码块增强** | Prism.js 语法高亮 + 头部（语言标签 + 复制按钮）+ XSS escapeHtml 防护 |
| **文件上传** | 📎 支持 图片（base64 多模态理解）/ txt / md / pdf（PyPDF2 提取文本）；豆包风格预览 |
| **图片多模态** | 自动切换 vision 模型；上传图片后直接问"这张图里的人帅吗" |
| **参考来源结构化** | 底部折叠组件（原生 `<details>`）+ 上角标¹²³可点击跳转 + scrollIntoView 高亮 |
| **联网搜索 Toggle** | 滑块开关 + localStorage 会话级记忆；关闭即跳过爬虫 |
| **Loading 文案区分** | 联网时「🔍正在检索网页，生成回答中…」/ 普通「正在生成回答…」 |
| **自定义删除弹窗** | 毛玻璃 modal（非原生 confirm）+ ESC/点遮罩关闭 |
| **输入体验** | 自动增高（最多 5 行）+ Enter 发送 / Shift+Enter 换行 + 聚焦发光 |
| **停止生成** | 生成中发送按钮变红色 + `AbortController` 中断 |
| **响应式** | `<768px` 移动端隐藏侧边栏 |
| **Toast 提示** | 复制/点赞/重试等操作反馈 |

### 🎨 UI 设计规范
- 粉色主题（`#ec4899` → `#f472b6` 渐变）
- **无"我"头像标签**，靠气泡颜色区分（粉色=user，白色卡片=AI）
- 所有气泡 `max-width: 85%`，避免大屏无限拉长
- AI 工具栏默认隐藏，hover 气泡才浮现
- 上传图片独立一行显示（不包在粉色气泡里），点击可全屏预览

## 📦 项目结构

```
demo3-web/
├── server.py          # Flask 后端：路由 + API + 会话管理 + 文件上传解析 + 联网搜索
├── client.py          # DeepSeekClient（复用 demo3 核心 + chat_with_override + vision 支持）
├── index.html         # 原生 HTML + Tailwind v3 + 原生 JS 前端（全部 UI 逻辑）
├── app.py             # Flask 启动入口
├── pig-avatar.png     # AI 绘制的小猪头像（备用）
├── 小猪.jpg           # 用户提供的手绘涂鸦风小猪头像
├── sessions/          # 会话持久化目录（运行时自动创建，已 .gitignore）
│   └── *.json
├── requirements.txt   # 依赖清单（Flask + requests + python-dotenv + PyPDF2）
├── .env.example       # 环境变量模板
├── .gitignore         # Git 忽略规则（.env、sessions/、__pycache__）
└── README.md          # 本文档
```

## 🛠️ 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| **后端** | Flask + flask-cors | Python Web 框架 |
| **API 客户端** | `requests` + `python-dotenv` | **原生 HTTP，不依赖任何 AI SDK** |
| **PDF 解析** | `PyPDF2` | 服务器端提取 PDF 文本 |
| **前端** | 原生 HTML5 + Tailwind CSS v3 + 原生 JS（ES6+） | CDN 引入 Tailwind |
| **代码高亮** | Prism.js CDN | 核心 + python/js/ts/java/go/css/json/markup 语言包 |
| **图标** | 全部内联 SVG，零第三方图标库 | — |
| **联网搜索** | Serper.dev API（Google 搜索结果） | 可选，免费额度每月 2500 次 |
| **多模态** | DeepSeek Vision 模型 | 图片请求自动切换 `deepseek-v4-flash-vision-exp` |
| **会话存储** | `sessions/<sid>.json` | 文件持久化，零数据库 |

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

> 依赖清单：Flask、flask-cors、requests、python-dotenv、PyPDF2

### 2. 配置密钥

```bash
# Windows PowerShell
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

编辑 `.env`：

```env
# 必填：DeepSeek API
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_API_URL=https://api.deepseek.com/v1/chat/completions

# 可选：多模态图片理解
# DEEPSEEK_VISION_MODEL=deepseek-v4-flash-vision-exp

# 可选：联网搜索（https://serper.dev 注册）
SERPER_API_KEY=your_serper_api_key_here
```

### 3. 启动服务

```bash
python server.py
```

启动成功后：

```
Baomi Agent 服务启动中...
http://127.0.0.1:7860
```

浏览器自动打开，开始聊天 🎉

## 🖥️ 界面操作

### 侧边栏
| 操作 | 说明 |
|---|---|
| 点击「+ 新对话」 | 创建新会话 |
| 点击历史项 | 切换会话，加载完整消息历史 |
| hover 历史项 → 点 X | 删除会话（自定义确认弹窗） |
| 点击底部「深色/浅色模式」 | 切换主题 |

### 顶部栏
| 控件 | 说明 |
|---|---|
| **🔎 联网搜索 Toggle** | 滑块开关；开=粉色高亮「已联网」；状态 localStorage 持久化；发请求带 `web_search: true/false` |
| 会话标题 | AI 根据首条消息自动生成（可在侧栏重命名） |

### 输入区
| 操作 | 说明 |
|---|---|
| **📎 附件按钮** | 弹出文件选择器；支持图片（JPG/PNG/GIF/WebP）、txt、md、pdf；可多选 |
| 直接输入 → Enter / 点发送 | 发送消息 |
| Shift + Enter | 输入框内换行 |
| 发送中 → 点红色停止按钮 | 中断生成（AbortController） |

### 附件预览（豆包风格）
| 类型 | 预览样式 |
|---|---|
| 图片 | 68×68 缩略图卡片（独立一行，不包粉色气泡）；点击可全屏放大 |
| 文本 | 豆包风卡片：📄蓝图标 + 文件名 + 大小 |
| Markdown | 豆包风卡片：📝紫图标 + 文件名 + 大小 |
| PDF | 豆包风卡片：📕红图标 + 文件名 + 大小 |

### 消息渲染
| 操作 | 说明 |
|---|---|
| **hover AI 气泡** → 底部工具栏 | 复制 / 重试 / 分享 / 点赞 / 点踩（默认隐藏） |
| **点击上角标¹²³** | 平滑滚动到对应参考来源条目 → flash 动画高亮 |
| **参考来源折叠组件** | 默认展开；chevron 旋转动画；点角标自动展开 |

### 工具栏详情（hover AI 消息浮现）

| 图标 | 功能 | 说明 |
|---|---|---|
| 📋 复制 | 复制 AI 回复纯文本 | 自动剥离 Markdown 语法 + Toast 提示 |
| 🔄 重试 | 用原问题重新生成 | 删除旧 AI 气泡，重新发送 |
| 🔗 分享 | 复制当前页面链接 | 带时间戳参数 |
| 👍 点赞 | 标记好回复 | 按钮变粉色高亮 |
| 👎 点踩 | 标记差回复 | 按钮变粉色高亮 |

## 🔌 API 文档

### 基础路径
```
http://127.0.0.1:7860
```

### 接口列表

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/` | 返回前端 `index.html` |
| `GET` | `/api/health` | 健康检查：模型名、是否配置搜索、会话数 |
| **`POST`** | **`/api/chat`** | **核心接口**：发送消息 → 返回 AI 回复 + sources |
| **`POST`** | **`/api/upload`** | **文件上传**：multipart/form-data；后端解析后返回结构化内容 |
| `GET` | `/api/sessions` | 列出所有会话（按修改时间降序） |
| `POST` | `/api/sessions` | 创建新会话 |
| `GET` | `/api/sessions/<sid>` | 加载某个会话完整消息历史 |
| `DELETE` | `/api/sessions/<sid>` | 删除会话 |
| `POST` | `/api/sessions/<sid>/rename` | 重命名会话 |
| `POST` | `/api/sessions/<sid>/clear` | 清空会话消息（保留会话本身） |

### `/api/upload` 请求/响应

```http
POST /api/upload
Content-Type: multipart/form-data

file: (binary) test.pdf
```

```json
{
  "files": [
    {
      "filename": "test.pdf",
      "kind": "text",
      "mimetype": "application/pdf",
      "content": "PDF 提取的完整文本内容...",
      "size": 10240
    }
  ]
}
```

| kind | 处理方式 |
|---|---|
| `image` | 图片 bytes → base64 → 前端渲染缩略图；后端组装 `image_url` blocks 传给 vision 模型 |
| `text` | txt/md → UTF-8 读取；pdf → PyPDF2 逐页提取 |
| `unsupported` | 不支持的类型（如 docx）→ `error` 字段提示 |

### `/api/chat` 请求示例

```json
POST /api/chat
{
  "session_id": "abc123def456",
  "message": "2024 年诺贝尔物理学奖得主是谁？",
  "web_search": true,
  "files": [
    {
      "filename": "photo.jpg",
      "kind": "image",
      "mimetype": "image/jpeg",
      "content": "/9j/4AAQSkZJRgABAQ...",
      "size": 204800
    }
  ]
}
```

### `/api/chat` 响应示例

```json
{
  "reply": "2024 年诺贝尔物理学奖由约翰·霍普菲尔德和尤里·利奥波德共同获得¹。他们...",
  "model": "deepseek-v4-flash",
  "history_len": 8,
  "searched": true,
  "sources": [
    {"source_id": 1, "title": "2024 Nobel Prize in Physics - Wikipedia", "snippet": "...", "link": "https://..."},
    {"source_id": 2, "title": "...", "snippet": "...", "link": "..."}
  ]
}
```

## 🧩 联网搜索 + 参考来源渲染流程

```
用户发送 + web_search=true
    ↓
Flask 调 Serper API（google.serper.dev/search）
    ↓
format_sources_for_llm() — 只传 source_id + title + snippet
❌ 绝对不把原始 URL 注入 prompt（防止 LLM 幻觉输出假链接）
    ↓
DeepSeekClient.chat_with_override(sources=...)
    ↓
LLM 返回带上角标¹²³的回答（system prompt 强制约束输出铁则）
    ↓
后端返回结构化 sources JSON 给前端（独立于 reply 文本）
    ↓
前端 convertSuperscripts()：
  TreeWalker 遍历文本节点 → Unicode¹²³ → <sup class="ref-sup" data-source-id="1">1</sup>
  跳过 <code> 防误伤代码块内数字
    ↓
前端 renderSources()：
  <details open><summary>▶ 参考来源 3</summary>
  → 列表项 <a class="ref-item" data-source-id="1" href="原始URL" target="_blank">
  → 只显示 title，不显示长 URL
    ↓
bindSupScroll() — 点击上角标：
  找到同气泡里 .ref-item[data-source-id=N]
  → 展开 details → scrollIntoView → flash 动画高亮
```

## 🗂️ 会话文件格式

```json
{
  "id": "abc123def456",
  "title": "2024 诺贝尔物理学奖",
  "created_at": 1725500000,
  "messages": [
    {"role": "system", "content": "...Baomi Agent 固定指令..."},
    {"role": "user", "content": "图片里的人帅吗", "files": [{"filename": "photo.jpg", "kind": "image", "content": "base64..."}]},
    {"role": "assistant", "content": "...", "sources": [{"source_id":1,"title":"...","link":"..."}]}
  ]
}
```

> user message 的 `files` 字段存**瘦身版**：图片保留 base64（供历史回放渲染），文本/PDF 只存元数据（`filename, kind, size, mimetype`），不存提取的文本内容（已经在当前对话消费过了）。

## 🛡️ 异常分类处理

| 异常类型 | HTTP 状态码 | 友好提示 | 触发场景 |
|---|---|---|---|
| `PermissionError` | 401 | 认证失败 | API_KEY 错误 |
| `ConnectionError` | 502 | 网络连接失败 | 无网络 / API 域名不可达 |
| `TimeoutError` | 504 | 请求超时 | API 响应过慢 |
| `RuntimeError` | 500 | 其他错误 | 服务端 5xx / JSON 解析失败 / 未配置 SERPER_API_KEY |

## 🔒 安全

- `.env` 已在 `.gitignore` 中，**永远不会提交到 GitHub**
- `sessions/*.json` 也被忽略（包含对话历史 + 用户上传的图片 base64）
- 所有密钥从环境变量读取，代码零硬编码
- Flask 加了 `no-cache` 响应头防止浏览器缓存旧 HTML
- 前端 `escapeHtml()` 全程 XSS 防护（Markdown 渲染、代码块、附件名）
- 上角标转换用 TreeWalker 在 DOM 文本节点操作，不破坏 HTML 结构
- 文件上传后端做 MIME + 扩展名双重校验；PyPDF2 延迟导入减少内存

## 🧠 Baomi Agent 系统指令（保护 KV 缓存）

前端不修改，但后端 `client.py` 内置固定 system prompt，约束 LLM 输出格式：

| 约束 | 说明 |
|---|---|
| **禁止输出完整 URL** | 链接、来源名称全走后端 sources JSON 返回 |
| **上角标¹²³引用** | 对应后端传入的 source_id |
| **禁止编造来源列表** | 后端 Python 爬虫产出 sources 数组，LLM 不能自己生成 |
| **无素材不加角标** | 没有检索素材不虚构引用编号 |
| **标准 markdown** | 无多余表情/客套话/总结落款 |
| **静态指令固定** | 动态爬虫素材 + 用户提问拼在 prompt 末尾，保障 KV 缓存命中率 ≥ 95% |

## 📝 知识点（对照 demo3 学习计划）

### Python 后端
- 类封装（`DeepSeekClient.__init__`、实例属性、方法）
- `requests.post()` + `timeout=30` + 重试逻辑
- `json.loads()` 原生解析
- `python-dotenv` 加载 `.env`
- 异常分类捕获（`PermissionError` / `ConnectionError` / `TimeoutError`）
- Flask 路由 + JSON 请求/响应 + `request.files` multipart 处理
- `pathlib.Path` 文件操作 + `json.dumps` 持久化
- PyPDF2 延迟导入 + 异常容错
- base64 编解码 + BytesIO 内存流

### 前端
- 原生 JavaScript ES6+（fetch / async-await / AbortController）
- Tailwind CSS v3 CDN + 自定义 CSS 变量
- BEM 命名规范
- Prism.js 动态加载 + `highlightElement` 代码高亮
- `document.createTreeWalker` 遍历 DOM 文本节点做精细替换
- `DocumentFragment` 减少 DOM reflow
- `<details>/<summary>` 原生折叠组件
- `localStorage` 持久化主题 + Toggle 状态
- `clipboard.writeText` API 复制文本
- `navigator.clipboard` + Toast 反馈
- `scrollIntoView({behavior:'smooth'})` 平滑滚动
- HTML5 `DataTransfer` 模拟文件选择
- MutationObserver 可选（代码块增强绑定）

## 📁 与 demo3 的关系

```
demo3/                demo3-web/
├── client.py  ←──── 复用架构，扩展 vision + chat_with_override ──── client.py
├── main.py                                server.py（Flask 重新实现交互层）
├── .env.example                           .env.example（同一格式，新增 vision 配置）
└── README.md                              index.html（全新前端）
                                           app.py（启动入口）
                                           sessions/*.json（新增持久化）
                                           requirements.txt（新增 PyPDF2）
```

**核心业务逻辑（API 调用 + 重试 + 异常分类）在 `demo3/client.py` 已经写好，demo3-web 只是换了个交互界面（Flask + 浏览器），没有重写任何业务代码。新增功能（多模态、sources 持久化、chat_with_override 灵活接口）都是扩展，不破坏原有调用链。**

## 📈 commit 历史

```
commit 26524d4  demo3-web 初版：Flask + 多会话 + 联网搜索 + Kimi 工具栏
commit xxxxxxx  P1-3 文件上传：/api/upload + PyPDF2 + base64 + 豆包风格预览
commit xxxxxxx  P1-4 代码块增强：Prism.js + 复制按钮 + escapeHtml
commit xxxxxxx  P0 UI 改造：sources 折叠 + 上角标跳转 + Toggle + Loading 区分
```
