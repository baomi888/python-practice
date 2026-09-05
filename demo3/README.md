# Demo3 — DeepSeek 控制台问答工具

一个基于 DeepSeek 大模型 API 的终端交互问答工具，支持多轮上下文连续对话、自动重试与分类异常处理。

## ✨ 功能列表

- 🔐 `.env` 读取 API 密钥，**零硬编码**
- 💬 多轮对话，自动维护 `messages` 上下文历史
- 🔁 失败自动重试 2 次，间隔 1 秒
- 🧹 `clear` 命令一键清空上下文
- 🚪 `exit` 命令优雅退出
- 🛡️ 分类异常提示：认证失败 / 网络断开 / 请求超时 / 返回格式异常
- 🌐 **联网搜索**：`/web 关键词` 自动搜网页后由 DeepSeek 总结（可选，需 Serper API Key）

## 🛠️ 技术栈

- `requests` — 原生 HTTP 请求（**不依赖任何 AI SDK**）
- `python-dotenv` — 加载 `.env` 环境变量
- 标准库 `json` — 原生解析 API 返回

## 📦 项目结构

```
demo3/
├── client.py      # DeepSeekClient 客户端类封装
├── main.py        # 控制台交互主循环入口
├── .env.example   # 环境变量模板（含占位符）
├── .gitignore     # Git 忽略（.env、__pycache__、IDE 文件）
└── README.md      # 项目说明
```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install python-dotenv requests
```

### 2. 配置密钥

```bash
# Windows PowerShell
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

编辑 `.env`，将 `DEEPSEEK_API_KEY` 替换为你自己的密钥：

```
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_API_URL=https://api.deepseek.com/v1/chat/completions
```

### 2.5 （可选）配置联网搜索

联网搜索使用 [Serper.dev](https://serper.dev) 的免费 API（每月 2500 次）：

1. 打开 https://serper.dev 用邮箱注册
2. 进入 Dashboard → API Keys → 复制 Key
3. 粘贴到 `.env` 的 `SERPER_API_KEY`：
   ```
   SERPER_API_KEY=your_serper_api_key_here
   ```

不配 Serper 也没关系，普通对话功能完全不受影响，只是 `/web` 命令不可用。

### 3. 运行程序

```bash
cd demo3
python main.py
```

### 4. 控制台命令

| 命令 | 说明 |
|---|---|
| 直接输入文字 | 发送提问给 DeepSeek |
| `exit` | 退出程序 |
| `clear` | 清空对话上下文，开启新会话 |
| `/web 关键词` | 联网搜索后由 DeepSeek 总结回答 |

## 🔑 核心实现要点

### 类封装（client.py）

```python
from client import DeepSeekClient

client = DeepSeekClient()          # 启动即校验 .env
answer = client.chat("你好")       # 自动维护 messages 历史
client.clear_history()             # 清空上下文
```

### 请求格式

```json
{
  "model": "deepseek-v4-flash",
  "messages": [{"role": "user", "content": "..."}],
  "temperature": 0.7
}
```

### 异常分类

| 异常类型 | 触发场景 | 友好提示 |
|---|---|---|
| `PermissionError` | 密钥无效（401/403） | 检查 .env 中的 API_KEY |
| `ConnectionError` | 网络断开 | 检查网络连接 |
| `TimeoutError` | 请求超时 | 稍后重试 |
| `RuntimeError` | JSON 解析失败 | API 返回格式异常 |

### 安全

- `.env` 文件**绝对不提交到 Git**（已在 `.gitignore` 中忽略）
- 代码中零硬编码密钥
- 仅 `.env.example` 中保留占位符 `sk_your_api_key_here`

## 📝 本周知识点

- Python 类封装（`__init__`、实例属性、方法）
- `requests.post()` 发送 HTTP 请求 + `timeout` 参数
- `json.loads()` 原生解析 JSON
- `python-dotenv` 加载 `.env` 环境变量
- 异常分类捕获（`except` 不同异常类型）
- `try/except/finally` + 重试逻辑
- 命令行交互（`input()` + `KeyboardInterrupt`）
