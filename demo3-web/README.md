# Baomi Agent — DeepSeek 智能体 Web 应用

基于 DeepSeek 大模型 API 的 **现代 AI Agent 对话 Web 应用**，Flask 后端 + 原生 HTML/Tailwind/JS 前端。复用 `demo3` 核心客户端逻辑，在其基础上扩展了多会话管理、联网搜索、Kimi 风格工具栏等完整的 Web 能力。

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
| **自定义删除弹窗** | 毛玻璃 modal（非原生 confirm）+ ESC/点遮罩关闭 |
| **输入体验** | 自动增高（最多 5 行）+ Enter 发送 / Shift+Enter 换行 + 聚焦发光 |
| **停止生成** | 生成中发送按钮变红色 + `AbortController` 中断 |
| **响应式** | `<768px` 移动端隐藏侧边栏 |
| **Toast 提示** | 复制/点赞/重试等操作反馈 |

## 📦 项目结构

```
demo3-web/
├── server.py          # Flask 后端：路由 + API + 会话管理
├── client.py          # DeepSeekClient（复用 demo3 核心，零修改）
├── index.html         # 原生 HTML + Tailwind v3 + 原生 JS 前端
├── pig-avatar.png     # AI 绘制的小猪头像（备用）
├── 小猪.jpg           # 用户提供的手绘涂鸦风小猪头像
├── sessions/          # 会话持久化目录（运行时自动创建）
│   ├── abc123.json
│   └── ...
├── requirements.txt   # 依赖清单
├── .env.example       # 环境变量模板
├── .gitignore         # Git 忽略规则（.env、sessions/、__pycache__）
└── README.md          # 本文档
```

## 🛠️ 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| **后端** | Flask + flask-cors | Python Web 框架 |
| **API 客户端** | `requests` + `python-dotenv` | **原生 HTTP，不依赖任何 AI SDK** |
| **前端** | 原生 HTML5 + Tailwind CSS v3 + 原生 JS（ES6+） | CDN 引入 Tailwind |
| **图标** | 全部内联 SVG，零第三方图标库 | — |
| **联网搜索** | Serper.dev API（Google 搜索结果） | 可选，免费额度每月 2500 次 |
| **会话存储** | `sessions/<sid>.json` | 文件持久化，零数据库 |

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

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

# 可选：联网搜索（https://serper.dev 注册）
SERPER_API_KEY=your_serper_api_key_here
```

> 不配 Serper 也能用，只是联网搜索按钮点了也不会调搜索。

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

### 聊天区
| 操作 | 说明 |
|---|---|
| 直接输入 → Enter / 点发送 | 发送消息 |
| Shift + Enter | 输入框内换行 |
| 发送中 → 点红色停止按钮 | 中断生成（AbortController） |
| **hover AI 气泡** → 底部工具栏 | 复制 / 重试 / 分享 / 点赞 / 点踩 |
| 点顶部「🔎 联网搜索」按钮 | 开启/关闭联网搜索 |
| 点建议卡片（💻💡🔎📝） | 快捷发送预设问题 |

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
| `POST` | `/api/chat` | **核心接口**：发送消息 → 返回 AI 回复 |
| `GET` | `/api/sessions` | 列出所有会话（按修改时间降序） |
| `POST` | `/api/sessions` | 创建新会话 |
| `GET` | `/api/sessions/<sid>` | 加载某个会话完整消息历史 |
| `DELETE` | `/api/sessions/<sid>` | 删除会话 |
| `POST` | `/api/sessions/<sid>/rename` | 重命名会话 |
| `POST` | `/api/sessions/<sid>/clear` | 清空会话消息（保留会话本身） |

### `/api/chat` 请求示例

```json
POST /api/chat
{
  "session_id": "abc123def456",
  "message": "写一段 Python 快速排序代码",
  "web_search": false
}
```

### `/api/chat` 响应示例

```json
{
  "reply": "好的，快速排序代码如下...",
  "model": "deepseek-v4-flash",
  "history_len": 6,
  "searched": false,
  "title": "写一段 Python 快速排序代码"
}
```

## 🧩 联网搜索流程

```
用户发送 + web_search=true
    ↓
Flask 调 Serper API（google.serper.dev/search）
    ↓
把搜索结果注入 prompt：
"以下是我通过联网搜索找到的最新信息，请结合这些信息回答..."
    ↓
DeepSeekClient.chat(增强后的消息)
    ↓
返回引用来源的总结回复
```

## 🗂️ 会话文件格式

```json
{
  "id": "abc123def456",
  "title": "写一段 Python 快速排序代码",
  "created_at": 1725500000,
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ]
}
```

## 🛡️ 异常分类处理

| 异常类型 | HTTP 状态码 | 友好提示 | 触发场景 |
|---|---|---|---|
| `PermissionError` | 401 | 认证失败 | API_KEY 错误 |
| `ConnectionError` | 502 | 网络连接失败 | 无网络 / API 域名不可达 |
| `TimeoutError` | 504 | 请求超时 | API 响应过慢 |
| `RuntimeError` | 500 | 其他错误 | 服务端 5xx / JSON 解析失败 |

## 🔒 安全

- `.env` 已在 `.gitignore` 中，**永远不会提交到 GitHub**
- `sessions/*.json` 也被忽略（包含对话历史）
- 所有密钥从环境变量读取，代码零硬编码
- Flask 加了 `no-cache` 响应头防止浏览器缓存旧 HTML

## 📝 本周知识点（对照 demo3）

### Python 后端
- 类封装（`DeepSeekClient.__init__`、实例属性、方法）
- `requests.post()` + `timeout=30` + 重试逻辑
- `json.loads()` 原生解析
- `python-dotenv` 加载 `.env`
- 异常分类捕获（`PermissionError` / `ConnectionError` / `TimeoutError`）
- Flask 路由 + JSON 请求/响应
- `pathlib.Path` 文件操作 + `json.dumps` 持久化

### 前端
- 原生 JavaScript ES6+（fetch / async-await / AbortController）
- Tailwind CSS v3 CDN + 自定义 CSS 变量
- BEM 命名规范
- HTML5 `<canvas>` / `<img>` 头像处理
- `localStorage` 持久化主题偏好
- `clipboard.writeText` API 复制文本

## 📁 与 demo3 的关系

```
demo3/                demo3-web/
├── client.py  ←──── 完全复用，零修改 ←────  client.py
├── main.py                                server.py（Flask 重新实现交互层）
├── .env.example                           .env.example（同一格式）
└── README.md                              index.html（原生 HTML 前端）
                                           sessions/*.json（新增持久化）
```

**核心业务逻辑（API 调用 + 重试 + 异常分类）在 `demo3/client.py` 已经写好，demo3-web 只是换了个交互界面（Flask + 浏览器），没有重写任何业务代码。**
