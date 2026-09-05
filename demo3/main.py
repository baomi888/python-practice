"""DeepSeek 控制台问答工具入口。

用法：python main.py
支持多轮对话，输入 clear 清空上下文，输入 exit 退出。
输入 /web 关键词 可触发联网搜索后再让 DeepSeek 总结。
"""
import sys

from client import DeepSeekClient


def print_welcome(model_name, has_search_key):
    """打印欢迎语与命令说明。"""
    print("=" * 56)
    print(f"   DeepSeek 控制台问答  |  模型：{model_name}")
    print("=" * 56)
    print("  命令：")
    print("    exit         - 退出程序 (´•ω•)ﾉ")
    print("    clear        - 清空对话上下文 (๑•.•๑)")
    if has_search_key:
        print("    /web 关键词  - 联网搜索后由 DeepSeek 总结回答 (๑•.•๑)")
    else:
        print("    /web 关键词  - 联网搜索（需配置 SERPER_API_KEY）")
    print("=" * 56)
    print()


def handle_user_input(client, user_input):
    """处理单次用户输入，分类捕获异常并输出友好提示。"""
    user_input = user_input.strip()

    if not user_input:
        return
    if user_input.lower() == "exit":
        print("👋 再见呀！")
        sys.exit(0)
    if user_input.lower() == "clear":
        client.clear_history()
        print("🧹 对话上下文已清空。")
        return

    # /web 联网搜索命令
    if user_input.startswith("/web"):
        query = user_input[4:].strip()
        if not query:
            print("💡 用法：/web")
            return
        print(f"\n🔍 联网搜索中…「{query}」", end="", flush=True)
        try:
            answer = client.chat_with_web(query)
            print("\r🐟 DeepSeek（联网总结）：")
            print(answer)
        except PermissionError as e:
            print(f"\r❌ {e}")
        except ConnectionError as e:
            print(f"\r❌ 网络问题：{e}")
        except TimeoutError:
            print("\r❌ 请求超时，请稍后重试。")
        except RuntimeError as e:
            print(f"\r❌ {e}")
        print()
        return

    # 正常提问流程
    print("\n🤔 思考中...", end="", flush=True)
    try:
        answer = client.chat(user_input)
        print("\r💬 DeepSeek：")
        print(answer)
    except PermissionError:
        print("\r❌ 认证失败：请检查 .env 中的 DEEPSEEK_API_KEY 是否正确。")
    except ConnectionError:
        print("\r❌ 网络连接失败：请检查网络是否正常。")
    except TimeoutError:
        print("\r❌ 请求超时：请稍后重试。")
    except RuntimeError as e:
        if "JSON" in str(e):
            print(f"\r❌ API 返回格式异常：{e}")
        else:
            print(f"\r❌ 请求失败：{e}")
    print()


def main():
    # 启动时初始化客户端，捕获密钥缺失等初始化异常
    try:
        client = DeepSeekClient()
    except PermissionError as e:
        print(f"❌ 初始化失败：{e}")
        print("   复制 .env.example 为 .env，填入你的 DeepSeek API Key 后重试。")
        sys.exit(1)

    print_welcome(client.model, bool(client.search_api_key))

    # 死循环接收用户输入
    while True:
        try:
            user_input = input("('-ω-') 请输入问题：")
            handle_user_input(client, user_input)
        except KeyboardInterrupt:
            # Ctrl+C 优雅退出
            print("\n\n👋 已中断对话，再见！")
            sys.exit(0)
        except EOFError:
            # Ctrl+D 或输入流结束
            print("\n👋 再见呀！")
            sys.exit(0)


if __name__ == "__main__":
    main()
