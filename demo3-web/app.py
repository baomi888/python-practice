"""DeepSeek AI Agent Web App — 现代化智能体界面

基于 Gradio 6.x + 自定义主题 + 玻璃拟态 CSS
支持浅色 / 深色模式一键切换
"""
import sys

import gradio as gr

from client import DeepSeekClient

# ============== 启动初始化 ==============
try:
    client = DeepSeekClient()
except ValueError as e:
    print(f"❌ 启动失败：{e}")
    print("   请编辑 .env 填入有效的 DEEPSEEK_API_KEY 后重新运行。")
    sys.exit(1)

# ============== 自定义主题 ==============
# 以 Soft 为底，覆盖主色调为 AI 感的青紫渐变系
theme = gr.themes.Soft(
    primary_hue="violet",
    secondary_hue="sky",
    neutral_hue="slate",
    font=[gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"],
    font_mono=gr.themes.GoogleFont("JetBrains Mono"),
).set(
    # 浅色模式 token
    body_background_fill="#F5F7FB",
    body_background_fill_dark="#0B0F1A",
    block_background_fill="#FFFFFF",
    block_background_fill_dark="#141A2B",
    block_border_color="#E2E6EF",
    block_border_color_dark="#1F2740",
    input_background_fill="#FFFFFF",
    input_background_fill_dark="#1A2136",
    button_primary_background_fill="#6D5DF6",
    button_primary_background_fill_hover="#8A7BF9",
    button_primary_background_fill_dark="#7B6CF7",
    button_primary_background_fill_hover_dark="#9A8DFB",
    checkbox_label_background_fill_selected="#EEF2FF",
    checkbox_label_background_fill_selected_dark="#242044",
)

# ============== 自定义 CSS ==============
CSS = """
/* ===== 全局容器 ===== */
.gradio-container {
    max-width: 900px !important;
    margin: 0 auto !important;
    padding: 0 !important;
}

/* ===== 顶部 Header 渐变条 ===== */
.app-header {
    background: linear-gradient(135deg, #6D5DF6 0%, #4BC6E8 100%);
    color: white;
    padding: 24px 32px;
    border-radius: 0 0 24px 24px;
    margin-bottom: 0;
    box-shadow: 0 8px 32px -8px rgba(109, 93, 246, 0.35);
    position: relative;
    overflow: hidden;
}
.app-header::before {
    content: '';
    position: absolute;
    top: -50%;
    right: -20%;
    width: 400px;
    height: 400px;
    background: radial-gradient(circle, rgba(255,255,255,0.15) 0%, transparent 70%);
    pointer-events: none;
}
.app-header-dark {
    background: linear-gradient(135deg, #1E1B4B 0%, #0F2A43 100%);
    box-shadow: 0 8px 32px -8px rgba(75, 198, 232, 0.25);
}
.app-title {
    font-size: 22px;
    font-weight: 700;
    letter-spacing: -0.01em;
    margin: 0;
    display: flex;
    align-items: center;
    gap: 10px;
}
.app-subtitle {
    font-size: 13px;
    opacity: 0.85;
    margin-top: 6px;
    font-weight: 400;
}
.app-logo {
    width: 36px;
    height: 36px;
    border-radius: 10px;
    background: rgba(255,255,255,0.2);
    backdrop-filter: blur(10px);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 18px;
}

/* ===== 主题切换按钮 ===== */
.theme-toggle {
    position: absolute;
    top: 20px;
    right: 24px;
    background: rgba(255,255,255,0.18);
    backdrop-filter: blur(12px);
    border: 1px solid rgba(255,255,255,0.25);
    border-radius: 12px;
    padding: 8px 14px;
    color: white;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.25s ease;
    display: flex;
    align-items: center;
    gap: 6px;
    font-family: inherit;
    z-index: 2;
}
.theme-toggle:hover {
    background: rgba(255,255,255,0.3);
    transform: translateY(-1px);
}

/* ===== 主聊天卡片 ===== */
.chat-card {
    background: var(--block-background-fill);
    border: 1px solid var(--block_border_color);
    border-radius: 20px;
    padding: 20px;
    margin-top: -4px;
    box-shadow: 0 4px 24px -12px rgba(0, 0, 0, 0.08);
}

/* ===== Chatbot 组件美化 ===== */
.chat-card .chatbot {
    border: none !important;
    background: transparent !important;
    box-shadow: none !important;
}
.chat-card .chatbot > .wrap {
    border-radius: 16px !important;
    border: 1px solid var(--border-color-primary, #E2E6EF) !important;
    background: var(--body_background_fill, #FAFBFD) !important;
    padding: 8px;
}
[data-theme="dark"] .chat-card .chatbot > .wrap {
    border-color: var(--border-color-primary, #1F2740) !important;
    background: rgba(26, 33, 54, 0.6) !important;
}

/* ===== 输入区 ===== */
.input-card {
    background: var(--block-background-fill);
    border: 1px solid var(--block_border_color);
    border-radius: 20px;
    padding: 20px;
    margin-top: 16px;
    box-shadow: 0 4px 24px -12px rgba(0, 0, 0, 0.08);
}
.input-card textarea {
    border-radius: 14px !important;
    padding: 14px 16px !important;
    font-size: 15px !important;
    resize: none !important;
    min-height: 56px !important;
    max-height: 160px !important;
    line-height: 1.5 !important;
    border: 1.5px solid var(--border-color-primary, #E2E6EF) !important;
    transition: border-color 0.2s ease, box-shadow 0.2s ease !important;
}
.input-card textarea:focus-within {
    border-color: #6D5DF6 !important;
    box-shadow: 0 0 0 4px rgba(109, 93, 246, 0.15) !important;
}

/* ===== 按钮组 ===== */
.btn-group {
    display: flex;
    gap: 10px;
    margin-top: 12px;
}
.btn-primary {
    background: linear-gradient(135deg, #6D5DF6 0%, #4BC6E8 100%) !important;
    border: none !important;
    color: white !important;
    border-radius: 12px !important;
    padding: 12px 28px !important;
    font-weight: 600 !important;
    font-size: 14px !important;
    transition: all 0.25s ease !important;
    box-shadow: 0 4px 14px -4px rgba(109, 93, 246, 0.5) !important;
}
.btn-primary:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 20px -4px rgba(109, 93, 246, 0.6) !important;
}
.btn-secondary {
    background: var(--button-secondary-background-fill) !important;
    border: 1px solid var(--border-color-primary) !important;
    color: var(--body-text-color) !important;
    border-radius: 12px !important;
    padding: 12px 24px !important;
    font-weight: 500 !important;
    font-size: 14px !important;
    transition: all 0.2s ease !important;
}
.btn-secondary:hover {
    background: var(--button-secondary-background-fill-hover) !important;
    transform: translateY(-1px) !important;
}

/* ===== 状态栏 ===== */
.status-bar {
    background: var(--block-background-fill);
    border: 1px solid var(--block_border_color);
    border-radius: 16px;
    padding: 12px 20px;
    margin-top: 16px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: 13px;
    color: var(--body-text-color-subdued);
}
.status-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: rgba(109, 93, 246, 0.1);
    color: #6D5DF6;
    padding: 4px 12px;
    border-radius: 20px;
    font-weight: 500;
    font-size: 12px;
}
[data-theme="dark"] .status-pill {
    background: rgba(123, 108, 247, 0.2);
    color: #9A8DFB;
}

/* ===== 欢迎空状态 ===== */
.welcome-hint {
    text-align: center;
    padding: 32px 16px;
    color: var(--body-text-color-subdued);
    font-size: 14px;
}
.welcome-hint .hint-icon {
    font-size: 36px;
    margin-bottom: 12px;
    display: block;
}

/* ===== 深色模式覆盖 ===== */
[data-theme="dark"] .app-header {
    background: linear-gradient(135deg, #1E1B4B 0%, #0F2A43 100%);
    box-shadow: 0 8px 32px -8px rgba(75, 198, 232, 0.25);
}
[data-theme="dark"] .status-pill {
    background: rgba(123, 108, 247, 0.2);
    color: #9A8DFB;
}

/* ===== 滚动条美化 ===== */
.chat-card ::-webkit-scrollbar {
    width: 6px;
}
.chat-card ::-webkit-scrollbar-track {
    background: transparent;
}
.chat-card ::-webkit-scrollbar-thumb {
    background: rgba(109, 93, 246, 0.3);
    border-radius: 3px;
}
.chat-card ::-webkit-scrollbar-thumb:hover {
    background: rgba(109, 93, 246, 0.5);
}
"""

# ============== 主题切换 JS ==============
# Gradio 6.x 的主题切换实际是切换 <html> 上的 data-theme 属性
JS_TOGGLE = """
() => {
    const html = document.documentElement;
    const isDark = html.getAttribute('data-theme') === 'dark';
    html.setAttribute('data-theme', isDark ? 'light' : 'dark');
    document.body.classList.toggle('dark', !isDark);
    // 同时切换 header 的深色样式
    const header = document.querySelector('.app-header');
    if (header) {
        header.classList.toggle('app-header-dark', !isDark);
    }
    // 持久化选择
    localStorage.setItem('gradio-theme', isDark ? 'light' : 'dark');
    return !isDark ? '🌙 深色模式' : '☀️ 浅色模式';
}
"""

JS_INIT = """
() => {
    const saved = localStorage.getItem('gradio-theme');
    if (saved) {
        document.documentElement.setAttribute('data-theme', saved);
        document.body.classList.toggle('dark', saved === 'dark');
        const header = document.querySelector('.app-header');
        if (header) header.classList.toggle('app-header-dark', saved === 'dark');
    }
}
"""

# ============== 响应函数 ==============
def respond(user_message, history):
    if not user_message or not user_message.strip():
        return history

    reply_map = {
        PermissionError: "❌ 认证失败：请检查 .env 文件中的 API_KEY 是否正确",
        ConnectionError: "❌ 网络连接失败，请检查网络后重试",
        TimeoutError: "❌ 请求超时，请稍后再试",
    }

    try:
        reply = client.chat(user_message.strip())
    except tuple(reply_map.keys()) as e:
        reply = reply_map[type(e)]
    except RuntimeError as e:
        reply = f"❌ 系统错误：{e}"
    except Exception as e:
        reply = f"❌ 系统错误：{e}"

    new_history = list(history) if history else []
    new_history.append({"role": "user", "content": user_message})
    new_history.append({"role": "assistant", "content": reply})
    return new_history


def clear_all():
    client.clear_history()
    return [], "✅ 上下文已清空", f"💬 历史：0"


def get_status():
    model_name = client.model
    history_len = len(client.messages)
    return f"✅ 就绪｜{model_name}｜历史 {history_len}"


# ============== 构建页面 ==============
with gr.Blocks(
    title="DeepSeek AI Agent",
    fill_height=True,
) as demo:

    # ---------- 顶部 Header ----------
    with gr.Row(elem_classes=["app-header"], min_height=120):
        with gr.Column(min_width=0, scale=1):
            gr.HTML(
                """
                <div class="app-logo">🤖</div>
                <div class="app-title">DeepSeek AI Agent</div>
                <div class="app-subtitle">基于大模型的智能对话助手</div>
                """
            )
        theme_btn = gr.Button(
            "🌙 深色模式",
            elem_classes=["theme-toggle"],
            elem_id="theme-toggle-btn",
        )
        theme_btn.click(
            fn=None,
            js=JS_TOGGLE,
            outputs=[theme_btn],
        )

    # ---------- 聊天卡片 ----------
    with gr.Column(elem_classes=["chat-card"]):
        chatbot = gr.Chatbot(
            height=520,
            feedback_options=None,
            elem_classes=["chatbot"],
        )

    # ---------- 输入卡片 ----------
    with gr.Column(elem_classes=["input-card"]):
        textbox = gr.Textbox(
            placeholder="向 AI Agent 发送消息...（Enter 发送 / Shift+Enter 换行）",
            container=False,
            lines=2,
            elem_classes=["input-textarea"],
        )
        with gr.Row(elem_classes=["btn-group"]):
            submit_btn = gr.Button("🚀 发送", variant="primary", elem_classes=["btn-primary"])
            clear_btn = gr.Button("🧹 清空上下文", elem_classes=["btn-secondary"])

    # ---------- 状态栏 ----------
    with gr.Row(elem_classes=["status-bar"]):
        status_text = gr.HTML(
            f'<div><span class="status-pill">● 在线</span> {client.model}</div>'
            f'<div id="history-indicator">💬 历史：0</div>',
        )

    # ---------- 欢迎提示 ----------
    gr.HTML(
        '<div class="welcome-hint"><span class="hint-icon">✨</span> '
        '我是 DeepSeek AI Agent，随时准备帮你解答问题、生成内容或进行头脑风暴。</div>'
    )

    # ============== 事件绑定 ==============
    def on_submit(user_msg, history):
        new_history = respond(user_msg, history)
        status_html = (
            f'<div><span class="status-pill">● 在线</span> {client.model}</div>'
            f'<div id="history-indicator">💬 历史：{len(client.messages)}</div>'
        )
        return new_history, "", status_html

    submit_btn.click(
        fn=on_submit,
        inputs=[textbox, chatbot],
        outputs=[chatbot, textbox, status_text],
    )

    textbox.submit(
        fn=on_submit,
        inputs=[textbox, chatbot],
        outputs=[chatbot, textbox, status_text],
    )

    clear_btn.click(
        fn=clear_all,
        outputs=[chatbot, textbox, status_text],
    )

# ============== 启动 ==============
if __name__ == "__main__":
    print(f"🚀 DeepSeek AI Agent 启动中...（模型：{client.model}）")
    print("📌 http://127.0.0.1:7860")
    demo.launch(
        server_name="127.0.0.1",
        server_port=7860,
        inbrowser=True,
        share=False,
        show_error=True,
        theme=theme,
        css=CSS,
        js=JS_INIT,
    )
