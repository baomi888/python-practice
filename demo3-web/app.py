"""DeepSeek 智能对话 Web 应用（Gradio 版）

复用 demo3 的 DeepSeekClient 核心逻辑，提供浏览器聊天界面。
适配 Gradio 6.x API。
"""
import sys

import gradio as gr

from client import DeepSeekClient

# ============== 启动阶段：初始化客户端 ==============
try:
    client = DeepSeekClient()
except ValueError as e:
    print(f"❌ 启动失败：{e}")
    print("   请编辑 .env 填入有效的 DEEPSEEK_API_KEY 后重新运行。")
    sys.exit(1)


# ============== 响应函数 ==============
def respond(user_message, history):
    """ChatInterface 响应函数。

    Args:
        user_message: 当前轮用户输入
        history: Gradio 自动维护的前端聊天历史

    Returns:
        str: 模型回复或友好错误提示
    """
    if not user_message or not user_message.strip():
        return ""

    try:
        return client.chat(user_message.strip())
    except PermissionError:
        return "❌ 认证失败：请检查 .env 文件中的 API_KEY 是否正确"
    except ConnectionError:
        return "❌ 网络连接失败，请检查网络后重试"
    except TimeoutError:
        return "❌ 请求超时，请稍后再试"
    except RuntimeError as e:
        return f"❌ 系统错误：{e}"
    except Exception as e:
        return f"❌ 系统错误：{e}"


def clear_all():
    """清空后端历史 + 返回空列表给 Chatbot 清前端。"""
    client.clear_history()
    return [], f"✅ 后端上下文已清空｜模型：{client.model}｜历史长度：0"


# ============== 构建页面 ==============
with gr.Blocks(title="DeepSeek 智能对话助手") as demo:
    gr.Markdown(
        """
        # 🤖 DeepSeek 智能对话助手

        基于 Gradio 的大模型对话 Web 应用，支持多轮上下文对话。

        - 💡 **发送消息**：在输入框输入内容后回车或点击「发送」
        - 🔄 **重新生成**：点击「停止」再发送一次相同问题可触发新回复
        - 🧹 **清空后端上下文**：一键清空当前对话历史（前端 + 后端同步）
        """
    )

    # 聊天组件
    chatbot = gr.Chatbot(
        height=500,
        show_copy_button=True,
        feedback_options=None,
    )

    # 输入区域
    with gr.Row():
        textbox = gr.Textbox(
            placeholder="在此输入你的问题，回车发送...",
            container=False,
            scale=7,
        )

    # 按钮区域
    with gr.Row():
        submit_btn = gr.Button("🚀 发送", variant="primary")
        clear_btn = gr.Button("🧹 清空后端上下文", variant="secondary")
        status_output = gr.Textbox(
            label="状态",
            value=f"✅ 客户端已就绪｜模型：{client.model}｜历史长度：0",
            interactive=False,
            container=True,
        )

    # 绑定事件
    submit_btn.click(
        fn=respond,
        inputs=[textbox, chatbot],
        outputs=[chatbot],
    ).then(
        fn=lambda: "",  # 清空输入框
        outputs=[textbox],
    ).then(
        fn=lambda: f"💬 历史长度：{len(client.messages)}",
        outputs=[status_output],
    )

    textbox.submit(
        fn=respond,
        inputs=[textbox, chatbot],
        outputs=[chatbot],
    ).then(
        fn=lambda: "",
        outputs=[textbox],
    ).then(
        fn=lambda: f"💬 历史长度：{len(client.messages)}",
        outputs=[status_output],
    )

    clear_btn.click(
        fn=clear_all,
        outputs=[chatbot, status_output],
    )

# ============== 启动 Web 服务 ==============
if __name__ == "__main__":
    print(f"🚀 DeepSeek Web 服务启动中...（模型：{client.model}）")
    print("📌 浏览器将自动打开 http://127.0.0.1:7860")
    demo.launch(
        server_name="127.0.0.1",
        server_port=7860,
        inbrowser=True,
        share=False,
        show_error=True,
    )
