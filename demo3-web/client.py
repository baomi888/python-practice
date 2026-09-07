"""DeepSeek API 客户端封装 —— Baomi Agent 联网检索对话助手

仅依赖 requests + python-dotenv，原生解析 JSON 返回。
异常分类抛出，支持自动重试与多轮上下文。
内置固定 system prompt（Baomi Agent 输出铁则），保障 KV 缓存命中。
"""
import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

# ============== Baomi Agent 固定系统指令 ==============
# 必须保持全文不变，以保障 LLM KV 缓存命中率
BAOMI_SYSTEM_PROMPT = """你是 Baomi Agent —— 联网检索 AI 对话助手，底层使用 Python requests 爬虫获取网页素材，大模型生成回答。

## 输出铁则（必须严格执行，任何情况不能打破）
1. 正文只输出回答文本，绝对禁止输出完整 URL、原始链接字符串。所有链接、网站名称、来源 id 交由后端 sources 结构化 JSON 输出，不由你输出。
2. 引用标记规则：使用上角标¹ ² ³，素材来自几号 source_id，就在对应信息后方加上对应上标。示例：1型糖尿病由免疫损伤导致¹。
3. 禁止自己生成、编造来源列表，禁止输出"来源1：https://xxx"这一类文本。参考来源 UI 完全交给前端根据后端 sources 数组渲染。
4. 没有检索素材时，不要添加任何引用角标。不要虚构引用编号。
5. 输出格式稳定统一，标准 markdown，无多余 emoji、无多余客套话、无多余总结落款。输出结构不要随机变化。
6. 如果信息不足，如实说明信息有限，不要编造事实与引用。

## 上下文结构规则（保障缓存）
静态指令固定在最前面；所有动态内容（爬虫抓取网页片段、用户提问）全部放在 prompt 的最后。
不要在指令区域插入任何动态变量、时间戳、随机字符串，会直接破坏缓存命中。

## 业务边界
- 爬虫素材由后端 Python requests 模块获取，你只负责理解素材内容，打上标引用。
- sources 数组由后端构造，不交由大模型生成，避免幻觉假链接。"""


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

        # 多轮对话历史，首条固定为 Baomi Agent 系统指令
        self.messages = [{"role": "system", "content": BAOMI_SYSTEM_PROMPT}]

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
            user_message: 用户本轮输入（干净内容，将存进 session）
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
        return self.chat_with_override(
            clean_user_message=user_message,
            llm_user_message=user_message,
            sources=None,
            max_retries=max_retries,
            retry_interval=retry_interval,
        )

    def chat_with_override(self, clean_user_message, llm_user_message,
                           sources=None, image_blocks=None, user_files=None,
                           max_retries=2, retry_interval=1):
        """灵活版 chat：session 存干净 user content，LLM 请求可用不同的 user content。

        用于联网搜索场景：clean_user_message 是用户原始问题（存 session），
        llm_user_message 是带搜索素材前缀的完整内容（发给 LLM）。
        图片多模态：image_blocks 为 [{type:"image_url", image_url:{url:"..."}}]，
        此时 content 为数组形式，且 model 自动切换到 vision 版本。

        Args:
            clean_user_message: 存进 session 的干净用户输入
            llm_user_message: 实际发给 LLM 的用户输入（可含搜索素材等动态内容）
            sources: 可选，搜索来源数组，会挂到 assistant message 上持久化
            image_blocks: 可选，图片 content blocks 数组，传了则启用多模态
            user_files: 可选，上传的文件数组（{filename, kind, content, mimetype, size}），
                        会挂到 session 的 user message 上供前端历史回放渲染
            max_retries: 最大重试次数
            retry_interval: 重试间隔秒数
        """
        has_images = bool(image_blocks)

        # session 存干净的 user message，附加 files 供前端历史回放
        user_msg = {"role": "user", "content": clean_user_message}
        if user_files:
            # 瘦身：去掉大 content（文本/PDF 已进 LLM、图片 base64 很大），
            # 只保留元数据 + 图片 base64 的小缩略图（够前端渲染就行）
            slim = []
            for f in user_files:
                entry = {
                    "filename": f.get("filename", ""),
                    "kind": f.get("kind", ""),
                    "size": f.get("size", 0),
                    "mimetype": f.get("mimetype", ""),
                }
                # 图片保留 base64 供历史回放渲染（大图片会存，但不持久化文本内容）
                if f.get("kind") == "image" and f.get("content"):
                    entry["content"] = f["content"]
                slim.append(entry)
            user_msg["files"] = slim
        self.messages.append(user_msg)

        # 构造 LLM 用的 user message
        if has_images:
            # 多模态：content 为数组 [{type:"text", text:"..."}, {type:"image_url", ...}]
            llm_content = [{"type": "text", "text": llm_user_message}] + image_blocks
            llm_messages = list(self.messages)
            llm_messages[-1] = {"role": "user", "content": llm_content}
        else:
            llm_messages = list(self.messages)
            llm_messages[-1] = {"role": "user", "content": llm_user_message}

        # 多模态需要 vision 模型；不支持时给清晰报错
        model = self.model
        if has_images and not model.endswith("-vision-exp"):
            vision_model = os.getenv(
                "DEEPSEEK_VISION_MODEL", "deepseek-v4-flash-vision-exp"
            ).strip()
            model = vision_model

        payload = {
            "model": model,
            "messages": llm_messages,
            "temperature": 0.7,
        }
        last_exception = None

        for attempt in range(max_retries + 1):
            try:
                response = requests.post(
                    self.api_url,
                    headers=self._build_headers(),
                    data=json.dumps(payload),
                    timeout=60 if has_images else 30,  # 图片稍慢
                )

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
                data = json.loads(response.text)
                answer = data["choices"][0]["message"]["content"]

                # URL 兜底清洗
                answer = self._sanitize_reply(answer)

                # assistant message 存 session（带 sources 持久化）
                assistant_msg = {"role": "assistant", "content": answer}
                if sources:
                    assistant_msg["sources"] = sources
                self.messages.append(assistant_msg)
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

    @staticmethod
    def _sanitize_reply(text):
        """兜底清洗：移除 LLM 偶尔输出的完整 URL（即使 system prompt 禁止）。"""
        if not text:
            return text
        import re
        # 移除 http:// 或 https:// 开头的 URL（排除 markdown link 结构如 [text](url) 里的 url）
        text = re.sub(r'https?://\S+', '', text)
        # 清理因移除 URL 产生的多余标点和空格
        text = re.sub(r'\s+([，。、；：,.;:])', r'\1', text)
        text = re.sub(r'[，。、；：,.;:]\s+', ' ', text)
        text = re.sub(r'\s{2,}', ' ', text)
        return text.strip()

    def clear_history(self):
        """清空对话历史，保留首条 system prompt。"""
        self.messages = [{"role": "system", "content": BAOMI_SYSTEM_PROMPT}]

    def ensure_system_prompt(self):
        """确保 messages[0] 是正确的 system prompt（应对旧 session 或 prompt 更新）。"""
        if (not self.messages
                or self.messages[0].get("role") != "system"
                or self.messages[0].get("content") != BAOMI_SYSTEM_PROMPT):
            # 移除旧的 system prompt（如果存在且内容不匹配），再插入最新版本
            self.messages = [m for m in self.messages if m.get("role") != "system"]
            self.messages.insert(0, {"role": "system", "content": BAOMI_SYSTEM_PROMPT})

    def __repr__(self):
        return f"<DeepSeekClient model={self.model!r} history_len={len(self.messages)}>"
