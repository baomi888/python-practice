"""DeepSeek API 客户端封装

仅依赖 requests + python-dotenv，原生解析 JSON 返回。
异常分类抛出，支持自动重试与多轮上下文。
"""
import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv


class DeepSeekClient:
    """DeepSeek 大模型 API 客户端。"""

    def __init__(self, dotenv_path=None):
        """初始化客户端，加载 .env 并校验 API_KEY。

        Args:
            dotenv_path: .env 文件路径，默认从当前脚本所在目录查找
        """
        if dotenv_path is None:
            dotenv_path = Path(__file__).parent / ".env"
        load_dotenv(dotenv_path=dotenv_path)

        self.api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip()
        self.api_url = os.getenv(
            "DEEPSEEK_API_URL",
            "https://api.deepseek.com/v1/chat/completions",
        ).strip()

        # 启动即校验密钥，避免运行中才发现问题
        if not self.api_key or self.api_key == "sk_your_api_key_here":
            raise ValueError(
                "API_KEY 未配置。请复制 .env.example 为 .env 并填入你的 DEEPSEEK_API_KEY。"
            )

        # 多轮对话历史
        self.messages = []

    def _build_headers(self):
        """构造请求头。"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(self, user_message):
        """构造请求体，附带完整对话历史。"""
        self.messages.append({"role": "user", "content": user_message})
        return {
            "model": self.model,
            "messages": self.messages,
            "temperature": 0.7,
        }

    def chat(self, user_message, max_retries=2, retry_interval=1):
        """发送请求并返回回答文本，支持自动重试。

        Args:
            user_message: 用户本轮输入
            max_retries: 失败后的最大重试次数（不含首次请求）
            retry_interval: 重试间隔秒数

        Returns:
            str: 模型回答文本

        Raises:
            PermissionError: 密钥无效（401/403）
            ConnectionError: 网络连接失败
            TimeoutError: 请求超时
            RuntimeError: 其他请求异常或 JSON 解析失败
        """
        payload = self._build_payload(user_message)
        last_exception = None

        for attempt in range(max_retries + 1):
            try:
                response = requests.post(
                    self.api_url,
                    headers=self._build_headers(),
                    data=json.dumps(payload),
                    timeout=30,
                )

                # HTTP 状态码分类处理
                if response.status_code in (401, 403):
                    raise PermissionError(
                        f"认证失败（HTTP {response.status_code}）：请检查 API_KEY 是否正确。"
                    )
                if response.status_code == 429:
                    if attempt < max_retries:
                        time.sleep(retry_interval)
                        continue
                    raise RuntimeError("请求过于频繁，已达最大重试次数。")
                if response.status_code >= 500:
                    if attempt < max_retries:
                        time.sleep(retry_interval)
                        continue
                    raise RuntimeError(
                        f"服务端错误（HTTP {response.status_code}）：{response.text[:200]}"
                    )

                response.raise_for_status()

                # 原生 JSON 解析
                data = json.loads(response.text)
                answer = data["choices"][0]["message"]["content"]

                # 追加助手回复到历史，支持多轮上下文
                self.messages.append({"role": "assistant", "content": answer})
                return answer

            except PermissionError:
                raise
            except requests.exceptions.Timeout as e:
                last_exception = TimeoutError(f"请求超时：{e}")
            except requests.exceptions.ConnectionError as e:
                last_exception = ConnectionError(f"网络连接失败：{e}")
            except json.JSONDecodeError as e:
                raise RuntimeError(f"API 返回格式异常，无法解析 JSON：{e}") from e
            except requests.exceptions.RequestException as e:
                last_exception = RuntimeError(f"请求异常：{e}")

            if attempt < max_retries:
                time.sleep(retry_interval)

        raise last_exception

    def clear_history(self):
        """清空对话历史，开启全新上下文。"""
        self.messages.clear()

    def __repr__(self):
        return f"<DeepSeekClient model={self.model!r} history_len={len(self.messages)}>"
