# DeepSeek 智能对话助手（Gradio Web 版）

基于 Gradio 的 DeepSeek 大模型 Web 聊天应用，复用 `demo3` 的核心客户端逻辑。

## ✨ 功能特性

- 🌐 **Web 可视化聊天**：浏览器打开即用，无需命令行
- 💬 **多轮上下文对话**：自动维护 `messages` 历史，支持连续追问
- 🔁 **自动重试机制**：失败自动重试 2 次，间隔 1 秒
- 🛡️ **友好错误提示**：网络异常、密钥错误、请求超时等均返回可读提示
- 🔐 **环境变量管理**：`.env` 存密钥，代码零硬编码
- 🧹 **前后端同步清空**：一键清空同时清除界面显示和后端对话历史

## 📦 项目结构

```
demo3-web/
├── client.py          # DeepSeekClient 类（复用 demo3 核心）
├── app.py             # Gradio Web 界面主程序
├── requirements.txt   # 依赖清单
├── .env.example       # 环境变量模板
├── .gitignore         # Git 忽略规则
└── README.md          # 本文档
```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置密钥

```bash
# 复制模板
copy .env.example .env    # Windows
# cp .env.example .env   # macOS / Linux

# 编辑 .env，把占位符换成你的真实 Key
```

`.env` 文件内容：

```
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_API_URL=https://api.deepseek.com/v1/chat/completions
```

### 3. 启动 Web 服务

```bash
python app.py
```

启动成功后控制台会输出：

```
🚀 DeepSeek Web 服务启动中...（模型：deepseek-v4-flash）
📌 浏览器将自动打开 http://127.0.0.1:7860
```

浏览器自动打开，开始聊天 🎉

## 🖥️ 界面操作说明

| 操作 | 说明 |
|---|---|
| 在输入框输入内容 → 回车 / 点击「发送」 | 发送消息给 DeepSeek |
| 点击「🔄 重新生成」 | 重新生成上一条回复 |
| 点击「↩️ 撤销」 | 撤销上一轮对话（前端） |
| 点击「🧹 清空对话」 | 清空前端界面显示 |
| 点击「🧹 清空后端上下文」 | 同时清空前端 + 后端对话历史（推荐用这个！） |

## 🔒 安全说明

- `.env` 文件已在 `.gitignore` 中，**永远不会提交到 GitHub**
- 所有 API 密钥从环境变量读取，代码中零硬编码
- 如果 `.env` 泄露，请立即到 https://platform.deepseek.com 作废并重建密钥

## 🧪 核心能力验证

| 能力 | 状态 |
|---|---|
| `requests` + `python-dotenv`（禁止 SDK） | ✅ |
| 启动时校验密钥，缺失直接退出 | ✅ |
| `timeout=30` | ✅ |
| 异常分类捕获并返回友好提示 | ✅ |
| 前后端对话历史同步清空 | ✅ |
| 任何错误不导致 Web 服务崩溃 | ✅ |
