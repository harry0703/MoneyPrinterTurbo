import dataclasses
import json
import logging
import re
import requests
from typing import List

from loguru import logger
from openai import AzureOpenAI, OpenAI
from openai.types.chat import ChatCompletion

from app.config import config

_max_retries = 5
_DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
_DEPRECATED_GEMINI_MODELS = {"gemini-pro", "gemini-1.0-pro"}
MIN_SCRIPT_PARAGRAPH_NUMBER = 1
MAX_SCRIPT_PARAGRAPH_NUMBER = 10
MAX_SCRIPT_PROMPT_LENGTH = 2000
MAX_SCRIPT_SYSTEM_PROMPT_LENGTH = 8000
_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think>", re.IGNORECASE | re.DOTALL)
_UNCLOSED_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*$", re.IGNORECASE | re.DOTALL)
_URL_USERINFO_RE = re.compile(r"((?:https?|wss?)://)([^/\s?#@]*:[^/\s?#@]*@)", re.IGNORECASE)
_SENSITIVE_QUERY_RE = re.compile(
    r"([?&](?:api[_-]?key|access[_-]?token|token|key|secret|password)=)([^&#\s]+)",
    re.IGNORECASE,
)

# =============================================================================
# Provider registry
#
# 历史上 _generate_response 用一条近 460 行的 if/elif 链分发 22 个 LLM provider，
# 每个分支都重复“读配置 → 校验 → 调用”三段逻辑，并且把默认 base_url/model
# 硬编码进分支体里。这里把可声明部分抽成 ProviderConfig 表，让 _generate_response
# 只负责查表、校验和按 client_kind 分发，新增 OpenAI-compatible provider 时
# 只需要加一行注册，而不用再复制整段分支。
# =============================================================================

# 结构化错误码常量。当前 _generate_response 仍然以文案形式返回错误，
# 但暴露这些常量可以让上层逐步迁移到结构化判定（Fix #13 预留）。
ERROR_CODES = frozenset(
    {
        "MISSING_API_KEY",
        "MISSING_MODEL",
        "MISSING_BASE_URL",
        "PROVIDER_DISABLED",
        "EMPTY_RESPONSE",
        "PROVIDER_ERROR",
        "UNKNOWN_PROVIDER",
    }
)


@dataclasses.dataclass(frozen=True)
class LLMResult:
    """
    结构化 LLM 调用结果，供 Agent / API 调用方做路由、重试和降级决策。

    传统的 `_generate_response` 在失败时把所有异常压成一个 `"Error: ..."` 字符串，
    调用方只能做字符串匹配，分不清是「key 无效（需重新认证）」、「限流（需等待）」、
    「网络（需重试）」还是「模型格式错（需换 prompt）」。`LLMResult` 把这些信息
    显式拆开，error_code 取 ERROR_CODES 中的一个常量，便于程序化判断。

    ok=True 时 text 为归一化后的正文，error_code/error_message 为空；
    ok=False 时 text 为空，error_code/error_message 描述失败原因。
    """

    ok: bool
    text: str = ""
    error_code: str = ""
    error_message: str = ""

    def as_text(self) -> str:
        """兼容旧调用方的字符串表示：成功返回正文，失败返回 'Error: <message>'。"""
        if self.ok:
            return self.text
        return f"Error: {self.error_message}"


def _classify_error_message(message: str) -> str:
    """
    把 _generate_response 返回的错误字符串映射成结构化 error_code。

    错误文案由 _validate_provider_config / 各 _call_* 函数产生，这里按关键词归类，
    让 Agent 能据此决定重试 / 降级 / 提示用户补配置。无法归类时回退到 PROVIDER_ERROR。
    """
    lowered = (message or "").lower()
    if "unknown llm_provider" in lowered:
        return "UNKNOWN_PROVIDER"
    if "api_key is not set" in lowered:
        return "MISSING_API_KEY"
    if "model_name is not set" in lowered:
        return "MISSING_MODEL"
    if "base_url is not set" in lowered:
        return "MISSING_BASE_URL"
    if "secret_key is not set" in lowered:
        return "MISSING_API_KEY"
    if "provider is disabled" in lowered or "enable_g4f" in lowered:
        return "PROVIDER_DISABLED"
    if "empty" in lowered or "invalid response" in lowered:
        return "EMPTY_RESPONSE"
    return "PROVIDER_ERROR"


@dataclasses.dataclass(frozen=True)
class ProviderConfig:
    """单个 LLM provider 的静态声明。

    Attributes:
        name: provider 名称，对应 config.app["llm_provider"] 的取值。
        requires_api_key: True 时校验逻辑会要求 {name}_api_key 非空。
        requires_base_url: True 时校验逻辑会要求解析后的 base_url 非空。
        default_base_url: 用户未显式配置 base_url 时的兜底值。
        default_model: 用户未显式配置 model_name 时的兜底值。
        client_kind: 决定调用哪个 _call_<kind> 函数。openai 走通用
            OpenAI Chat Completions 兼容路径，其余值对应专用分支。
    """

    name: str
    requires_api_key: bool = True
    requires_base_url: bool = True
    default_base_url: str = ""
    default_model: str = ""
    client_kind: str = "openai"  # openai|azure|qwen|gemini|cloudflare|ernie|litellm|pollinations|g4f|modelscope


# 注意：qwen/cloudflare/ernie 之前在分支体里把 base_url/model_name 写成 "***"
# 作为“运行时才确定”的占位符，但占位符会污染错误信息和日志，且对校验逻辑
# 没有实际意义。这里把真实默认值填回：qwen 用 dashscope 兼容地址（虽然 dashscope
# SDK 自己不读 base_url，但保留可读默认值便于排错），ernie 写入官方 ernie-4.0
# 模型名，cloudflare 的 URL 在 _call_cloudflare 内按 account_id+model_name 拼装。
_PROVIDER_REGISTRY: dict[str, ProviderConfig] = {
    "openai": ProviderConfig(
        name="openai",
        default_base_url="https://api.openai.com/v1",
    ),
    "ollama": ProviderConfig(
        name="ollama",
        requires_api_key=False,
        default_base_url="",  # 运行时通过 config.get_default_ollama_base_url() 解析
    ),
    "azure": ProviderConfig(
        name="azure",
        client_kind="azure",
    ),
    "qwen": ProviderConfig(
        name="qwen",
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        client_kind="qwen",
    ),
    "gemini": ProviderConfig(
        name="gemini",
        requires_base_url=False,
        client_kind="gemini",
    ),
    "cloudflare": ProviderConfig(
        name="cloudflare",
        client_kind="cloudflare",
    ),
    "ernie": ProviderConfig(
        name="ernie",
        default_base_url="https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/ernie-4.0-8k-latest",
        default_model="ernie-4.0-8k-latest",
        client_kind="ernie",
    ),
    "grok": ProviderConfig(
        name="grok",
        default_base_url="https://api.x.ai/v1",
    ),
    "groq": ProviderConfig(
        name="groq",
        default_base_url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
    ),
    "deepseek": ProviderConfig(
        name="deepseek",
        default_base_url="https://api.deepseek.com",
    ),
    "modelscope": ProviderConfig(
        name="modelscope",
        default_base_url="https://api-inference.modelscope.cn/v1/",
        client_kind="modelscope",
    ),
    "moonshot": ProviderConfig(
        name="moonshot",
        default_base_url="https://api.moonshot.cn/v1",
    ),
    "aihubmix": ProviderConfig(
        name="aihubmix",
        default_base_url="https://aihubmix.com/v1",
        default_model="gpt-5.4-mini",
    ),
    "aimlapi": ProviderConfig(
        name="aimlapi",
        default_base_url="https://api.aimlapi.com/v1",
        default_model="openai/gpt-4o-mini",
    ),
    "oneapi": ProviderConfig(
        name="oneapi",
        # 无默认值：用户必须自行配置 oneapi_base_url 和 oneapi_model_name。
    ),
    "minimax": ProviderConfig(
        name="minimax",
        default_base_url="https://api.minimax.io/v1",
    ),
    "evolink": ProviderConfig(
        name="evolink",
        default_base_url="https://direct.evolink.ai/v1",
        default_model="gpt-5.5",
    ),
    "mimo": ProviderConfig(
        name="mimo",
        default_base_url="https://api.xiaomimimo.com/v1",
        default_model="mimo-v2.5-pro",
    ),
    "volcengine": ProviderConfig(
        name="volcengine",
        default_base_url="https://ark.cn-beijing.volces.com/api/v3",
        default_model="doubao-seed-2-1-turbo-260628",
    ),
    "litellm": ProviderConfig(
        name="litellm",
        requires_api_key=False,
        requires_base_url=False,
        client_kind="litellm",
    ),
    "pollinations": ProviderConfig(
        name="pollinations",
        requires_api_key=False,
        default_base_url="https://text.pollinations.ai/openai",
        default_model="openai-fast",
        client_kind="pollinations",
    ),
    "g4f": ProviderConfig(
        name="g4f",
        requires_api_key=False,
        requires_base_url=False,
        client_kind="g4f",
    ),
}


DEFAULT_SCRIPT_SYSTEM_PROMPT = """
# Role: Video Script Generator

## Goals:
Generate a script for a video, depending on the subject of the video.

## Constrains:
1. the script is to be returned as a string with the specified number of paragraphs.
2. do not under any circumstance reference this prompt in your response.
3. get straight to the point, don't start with unnecessary things like, "welcome to this video".
4. you must not include any type of markdown or formatting in the script, never use a title.
5. only return the raw content of the script.
6. do not include "voiceover", "narrator" or similar indicators of what should be spoken at the beginning of each paragraph or line.
7. you must not mention the prompt, or anything about the script itself. also, never talk about the amount of paragraphs or lines. just write the script.
8. respond in the same language as the video subject.
""".strip()


def _normalize_text_response(content, llm_provider: str) -> str:
    # 不同 LLM SDK 在异常或被拦截场景下，可能返回 None、空字符串，
    # 甚至返回非字符串对象。这里统一做兜底校验，避免后续直接调用
    # `.replace()` 时抛出 `NoneType` 之类的属性错误。
    if content is None:
        raise ValueError(f"[{llm_provider}] returned empty text content")

    if not isinstance(content, str):
        raise TypeError(
            f"[{llm_provider}] returned non-text content: {type(content).__name__}"
        )

    # MiniMax M3、DeepSeek R1 这类 reasoning 模型可能会把内部推理包在
    # `<think>...</think>` 中返回。视频脚本和关键词只需要最终可朗读文本，
    # 如果不在服务层统一清理，WebUI、字幕和配音都会把思考过程当正文处理。
    content = _THINK_BLOCK_RE.sub("", content)
    content = _UNCLOSED_THINK_BLOCK_RE.sub("", content).strip()
    if not content:
        raise ValueError(f"[{llm_provider}] returned empty text content")

    return content.replace("\n", "")


def _sanitize_error_message(error: object) -> str:
    """
    清理返回给 WebUI/API 的错误信息，避免自定义 base_url 中的凭据泄露。

    一些 OpenAI-compatible SDK 会把请求 URL 原样拼进异常信息。如果用户为了
    代理网关配置了 `https://user:pass@example.com/v1`，直接返回 `str(e)`
    就会把密码暴露给页面、API 调用方或后续日志。这里仅处理错误文案，不改变
    实际请求地址，避免影响正常调用链路。
    """
    message = str(error)
    message = _URL_USERINFO_RE.sub(r"\1***:***@", message)
    message = _SENSITIVE_QUERY_RE.sub(r"\1***", message)
    return message


def _extract_chat_completion_text(response, llm_provider: str) -> str:
    # OpenAI 兼容接口在异常场景下，可能返回没有 choices、
    # 或者 choices/message/content 为空的响应对象。
    # 这里统一做结构校验，避免出现 `NoneType is not subscriptable`
    # 这类底层属性访问错误。
    choices = getattr(response, "choices", None)
    if not choices:
        raise ValueError(f"[{llm_provider}] returned empty choices")

    first_choice = choices[0]
    message = getattr(first_choice, "message", None)
    if message is None:
        raise ValueError(f"[{llm_provider}] returned empty message")

    content = getattr(message, "content", None)
    return _normalize_text_response(content, llm_provider)


def _get_response_field(value, key: str):
    """兼容 dict 和 SDK 响应对象的字段读取。"""
    if isinstance(value, dict):
        return value.get(key)

    try:
        return value[key]
    except (KeyError, TypeError, AttributeError):
        return getattr(value, key, None)


def _extract_qwen_generation_text(response) -> str:
    """
    从 DashScope Generation 响应中提取文本。

    Qwen 使用 `messages` 调用时返回的是 chat 结构：
    `output.choices[0].message.content`；旧 completion 形态才会返回
    `output.text`。这里两个路径都兼容，避免 `output.text` 为 None 时
    继续 `.replace()` 触发不可诊断的 AttributeError。
    """
    output = _get_response_field(response, "output")
    choices = _get_response_field(output, "choices") if output else None
    if choices is not None:
        if not choices:
            logger.warning("Qwen returned an empty choices list")
            raise ValueError("[qwen] returned empty choices")

        first_choice = choices[0]
        message = _get_response_field(first_choice, "message")
        content = _get_response_field(message, "content") if message else None
        if content is not None:
            return _normalize_text_response(content, "qwen")

    text = _get_response_field(output, "text") if output else None
    return _normalize_text_response(text, "qwen")


def _resolve_provider_config(provider: ProviderConfig) -> dict:
    """读取 provider 对应的 config.app 配置，并补齐默认值。

    返回字典包含所有 _call_<kind> 函数可能用到的字段。不同 client_kind
    只会读取自己需要的子集，因此这里一次性解析全部，避免分发逻辑里再
    重复 config.app.get。base_url/model_name 在用户未配置时回退到
    ProviderConfig 里声明的默认值；ollama 的 base_url 默认值需要运行时
    通过容器检测确定，单独处理。
    """
    name = provider.name
    api_key = config.app.get(f"{name}_api_key")
    model_name = config.app.get(f"{name}_model_name")
    base_url = config.app.get(f"{name}_base_url", "")

    # ollama 不需要真实 API key，但 OpenAI SDK 要求 api_key 参数非空才能构造
    # 客户端。历史上固定填 "ollama" 作为占位字符串，保持该行为以兼容现有配置。
    if name == "ollama":
        api_key = "ollama"

    if not base_url and provider.default_base_url:
        base_url = provider.default_base_url
    if not model_name and provider.default_model:
        model_name = provider.default_model

    # ollama 没有 registry 默认 base_url；走容器检测兜底，保持原有行为。
    if name == "ollama" and not base_url:
        base_url = config.get_default_ollama_base_url()

    # Gemini 旧模型名已经陆续下线，这里自动兼容历史配置，避免用户沿用旧值时
    # 直接收到 404。gemini 在 registry 里没有 default_model，因此单独兜底。
    if name == "gemini":
        if not model_name:
            model_name = _DEFAULT_GEMINI_MODEL
        elif model_name in _DEPRECATED_GEMINI_MODELS:
            logger.warning(
                f"gemini model '{model_name}' is deprecated, fallback to '{_DEFAULT_GEMINI_MODEL}'"
            )
            model_name = _DEFAULT_GEMINI_MODEL

    resolved: dict = {
        "api_key": api_key,
        "model_name": model_name,
        "base_url": base_url,
    }

    if name == "azure":
        resolved["api_version"] = config.app.get(
            "azure_api_version", "2024-02-15-preview"
        )
    if name == "ernie":
        resolved["secret_key"] = config.app.get("ernie_secret_key")
    if name == "cloudflare":
        resolved["account_id"] = config.app.get("cloudflare_account_id")

    return resolved


def _validate_provider_config(provider: ProviderConfig, resolved: dict) -> None:
    """校验 provider 必填配置。

    替代原 _generate_response 中 line 360 的硬编码白名单校验。
    错误文案保持与历史实现完全一致，因为 test_llm.py 直接断言子串，
    例如 "api_key is not set, please set it in the config.toml file."。
    """
    name = provider.name
    api_key = resolved.get("api_key")
    model_name = resolved.get("model_name")
    base_url = resolved.get("base_url")

    if provider.requires_api_key and not api_key:
        raise ValueError(
            f"{name}: api_key is not set, please set it in the config.toml file."
        )

    # g4f 自己在 _call_g4f 内读 g4f_model_name 并带默认值；litellm 在
    # _call_litellm 内校验 model_name。两者不在此处统一校验，避免覆盖
    # 各自的特殊默认值逻辑。
    if name not in {"g4f", "litellm"} and not model_name:
        raise ValueError(
            f"{name}: model_name is not set, please set it in the config.toml file."
        )

    if (
        provider.requires_base_url
        and not base_url
        and provider.client_kind != "gemini"
    ):
        raise ValueError(
            f"{name}: base_url is not set, please set it in the config.toml file."
        )

    if name == "ernie":
        secret_key = resolved.get("secret_key")
        if not secret_key:
            raise ValueError(
                f"{name}: secret_key is not set, please set it in the config.toml file."
            )


def _call_g4f(prompt: str, model_name: str) -> str:
    """g4f 分支：opt-in 校验、懒加载、模型默认值都在这里完成。"""
    if not config.app.get("enable_g4f", False):
        raise ValueError(
            "g4f provider is disabled by default because it relies on "
            "reverse-engineered third-party endpoints. Set enable_g4f=true "
            "in config.toml only if you understand and accept the security, "
            "reliability, and legal risks."
        )

    logger.warning(
        "g4f provider is enabled. This provider may be unstable and carries "
        "supply-chain and terms-of-service risks. Prefer official providers, "
        "OpenAI-compatible APIs, LiteLLM, Ollama, or local inference for production."
    )
    try:
        import g4f
    except ImportError as e:
        raise ValueError(
            "g4f package is not installed by default. Install the optional "
            "dependency with `uv sync --extra g4f` only if you understand "
            "and accept the provider risks."
        ) from e

    if not model_name:
        model_name = "gpt-3.5-turbo-16k-0613"
    content = g4f.ChatCompletion.create(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
    )
    return _normalize_text_response(content, "g4f")


def _call_qwen(prompt: str, api_key: str, model_name: str) -> str:
    """dashscope Generation 调用。base_url 由 dashscope SDK 自行管理，不使用。"""
    import dashscope
    from dashscope.api_entities.dashscope_response import GenerationResponse

    dashscope.api_key = api_key
    response = dashscope.Generation.call(
        model=model_name, messages=[{"role": "user", "content": prompt}]
    )
    if response:
        if isinstance(response, GenerationResponse):
            status_code = response.status_code
            if status_code != 200:
                raise Exception(
                    f'[qwen] returned an error response: "{response}"'
                )

            return _extract_qwen_generation_text(response)
        else:
            raise Exception(
                f'[qwen] returned an invalid response: "{response}"'
            )
    else:
        raise Exception(f"[qwen] returned an empty response")


def _call_gemini(prompt: str, api_key: str, model_name: str, base_url: str) -> str:
    import google.generativeai as genai

    if not base_url:
        genai.configure(api_key=api_key, transport="rest")
    else:
        genai.configure(api_key=api_key, transport="rest", client_options={'api_endpoint': base_url})

    generation_config = {
        "temperature": 0.5,
        "top_p": 1,
        "top_k": 1,
        "max_output_tokens": 2048,
    }

    safety_settings = [
        {
            "category": "HARM_CATEGORY_HARASSMENT",
            "threshold": "BLOCK_ONLY_HIGH",
        },
        {
            "category": "HARM_CATEGORY_HATE_SPEECH",
            "threshold": "BLOCK_ONLY_HIGH",
        },
        {
            "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
            "threshold": "BLOCK_ONLY_HIGH",
        },
        {
            "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
            "threshold": "BLOCK_ONLY_HIGH",
        },
    ]

    model = genai.GenerativeModel(
        model_name=model_name,
        generation_config=generation_config,
        safety_settings=safety_settings,
    )

    try:
        response = model.generate_content(prompt)
        candidates = response.candidates
        generated_text = candidates[0].content.parts[0].text
    except (AttributeError, IndexError) as e:
        logger.warning(
            f"gemini returned invalid response content: {str(e)}"
        )
        raise ValueError(
            f"[gemini] returned invalid response content"
        )

    return _normalize_text_response(generated_text, "gemini")


def _call_cloudflare(
    prompt: str, api_key: str, model_name: str, account_id: str
) -> str:
    # URL 在调用时由 account_id + model_name 拼装，因此注册表里不存默认 base_url，
    # 也避免了历史上 base_url = "***" 占位符污染错误信息。
    response = requests.post(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model_name}",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "messages": [
                {
                    "role": "system",
                    "content": "You are a friendly assistant",
                },
                {"role": "user", "content": prompt},
            ]
        },
    )
    result = response.json()
    logger.info(result)
    return _normalize_text_response(result["result"]["response"], "cloudflare")


def _call_ernie(
    prompt: str, api_key: str, secret_key: str, base_url: str
) -> str:
    response = requests.post(
        "https://aip.baidubce.com/oauth/2.0/token",
        params={
            "grant_type": "client_credentials",
            "client_id": api_key,
            "client_secret": secret_key,
        }
    )
    access_token = response.json().get("access_token")
    url = f"{base_url}?access_token={access_token}"

    payload = json.dumps(
        {
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.5,
            "top_p": 0.8,
            "penalty_score": 1,
            "disable_search": False,
            "enable_citation": False,
            "response_format": "text",
        }
    )
    headers = {"Content-Type": "application/json"}

    response = requests.request(
        "POST", url, headers=headers, data=payload
    ).json()
    return _normalize_text_response(response.get("result"), "ernie")


def _call_litellm(prompt: str, model_name: str) -> str:
    import litellm

    if not model_name:
        raise ValueError(
            f"litellm: model_name is not set, please set it in the config.toml file."
        )

    response = litellm.completion(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
        drop_params=True,
    )

    if not response:
        raise ValueError(f"[litellm] returned empty response")
    if not getattr(response, "choices", None):
        raise ValueError(f"[litellm] returned empty response")

    return _extract_chat_completion_text(response, "litellm")


def _call_azure(
    prompt: str, api_key: str, model_name: str, base_url: str, api_version: str
) -> str:
    # Azure OpenAI SDK 使用 `azure_endpoint` 和 `api_version` 生成专用请求地址，
    # 不能复用普通 OpenAI-compatible 的 `base_url` 初始化逻辑。这里直接创建
    # AzureOpenAI 客户端并返回，避免落入通用 OpenAI fallback。
    logger.info(f"requesting azure chat completion, model: {model_name}")
    client = AzureOpenAI(
        api_key=api_key,
        api_version=api_version,
        azure_endpoint=base_url,
    )
    response = client.chat.completions.create(
        model=model_name, messages=[{"role": "user", "content": prompt}]
    )
    if response:
        if isinstance(response, ChatCompletion):
            return _extract_chat_completion_text(response, "azure")
        else:
            raise Exception(
                f'[azure] returned an invalid response: "{response}", please check your network '
                f"connection and try again."
            )
    else:
        raise Exception(
            f"[azure] returned an empty response, please check your network connection and try again."
        )


def _call_modelscope(
    prompt: str, api_key: str, model_name: str, base_url: str
) -> str:
    # ModelScope 通过 extra_body 关闭 thinking 并以流式聚合结果，
    # 因此不与其他 OpenAI-compatible provider 共用 _call_openai_compatible。
    content = ''
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
    )
    response = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
        extra_body={"enable_thinking": False},
        stream=True
    )
    if response:
        for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                content += delta.content

        if not content.strip():
            raise ValueError("Empty content in stream response")

        return _normalize_text_response(content, "modelscope")
    else:
        raise Exception(f"[modelscope] returned an empty response")


def _call_pollinations(prompt: str, base_url: str, model_name: str) -> str:
    try:
        # Prepare the payload
        payload = {
            "model": model_name,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "seed": 101  # Optional but helps with reproducibility
        }

        # Optional parameters if configured
        if config.app.get("pollinations_private"):
            payload["private"] = True
        if config.app.get("pollinations_referrer"):
            payload["referrer"] = config.app.get("pollinations_referrer")

        headers = {
            "Content-Type": "application/json"
        }

        # Make the API request
        response = requests.post(base_url, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()

        if result and "choices" in result and len(result["choices"]) > 0:
            content = result["choices"][0]["message"]["content"]
            return _normalize_text_response(content, "pollinations")
        else:
            raise Exception(f"[pollinations] returned an invalid response format")

    except requests.exceptions.RequestException as e:
        raise Exception(f"[pollinations] request failed: {str(e)}")
    except Exception as e:
        raise Exception(f"[pollinations] error: {str(e)}")


def _call_openai_compatible(
    prompt: str, api_key: str, model_name: str, base_url: str
) -> str:
    """通用 OpenAI Chat Completions 兼容路径。

    覆盖 openai/ollama/moonshot/aihubmix/aimlapi/oneapi/grok/groq/minimax/
    evolink/mimo/volcengine/deepseek 等 provider。它们只有配置默认值不同，
    调用方式完全一致，因此复用同一段 OpenAI 客户端创建 + chat completion 逻辑。
    """
    llm_provider = config.app.get("llm_provider", "openai")
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
    )

    response = client.chat.completions.create(
        model=model_name, messages=[{"role": "user", "content": prompt}]
    )
    if response:
        if isinstance(response, ChatCompletion):
            return _extract_chat_completion_text(response, llm_provider)
        else:
            raise Exception(
                f'[{llm_provider}] returned an invalid response: "{response}", please check your network '
                f"connection and try again."
            )
    else:
        raise Exception(
            f"[{llm_provider}] returned an empty response, please check your network connection and try again."
        )


def _generate_response(prompt: str) -> str:
    try:
        llm_provider = config.app.get("llm_provider", "openai")
        logger.info(f"llm provider: {llm_provider}")

        provider = _PROVIDER_REGISTRY.get(llm_provider)
        if provider is None:
            raise ValueError(f"unknown llm_provider: {llm_provider}")

        resolved = _resolve_provider_config(provider)
        _validate_provider_config(provider, resolved)

        api_key = resolved.get("api_key")
        model_name = resolved.get("model_name")
        base_url = resolved.get("base_url")

        kind = provider.client_kind

        if kind == "g4f":
            # g4f 不走通用解析路径里的 model_name 校验，它自己读 g4f_model_name。
            return _call_g4f(prompt, config.app.get("g4f_model_name", ""))
        if kind == "qwen":
            return _call_qwen(prompt, api_key, model_name)
        if kind == "gemini":
            return _call_gemini(prompt, api_key, model_name, base_url)
        if kind == "cloudflare":
            return _call_cloudflare(
                prompt, api_key, model_name, resolved.get("account_id")
            )
        if kind == "ernie":
            return _call_ernie(
                prompt, api_key, resolved.get("secret_key"), base_url
            )
        if kind == "litellm":
            return _call_litellm(prompt, model_name)
        if kind == "azure":
            return _call_azure(
                prompt, api_key, model_name, base_url, resolved.get("api_version")
            )
        if kind == "modelscope":
            return _call_modelscope(prompt, api_key, model_name, base_url)
        if kind == "pollinations":
            return _call_pollinations(prompt, base_url, model_name)

        # client_kind == "openai" 的通用兼容路径。
        return _call_openai_compatible(prompt, api_key, model_name, base_url)
    except Exception as e:
        return f"Error: {_sanitize_error_message(e)}"


def generate_response_structured(prompt: str) -> LLMResult:
    """
    结构化版本的 LLM 调用入口，返回带 error_code 的 LLMResult。

    供未来 Agent 路由 / API 调用方使用：调用方可以按 error_code 决定
    重试（PROVIDER_ERROR / EMPTY_RESPONSE）、降级到另一个 provider、
    还是提示用户补配置（MISSING_API_KEY / MISSING_MODEL / MISSING_BASE_URL）。

    内部复用 _generate_response，保持行为完全一致；只是把成功/失败
    拆成结构化字段，不再压成单一字符串。
    """
    response = _generate_response(prompt)
    if isinstance(response, str) and response.startswith("Error:"):
        # 去掉 "Error: " 前缀后做分类，保留原始文案供排错。
        message = response[len("Error:"):].strip()
        return LLMResult(
            ok=False,
            text="",
            error_code=_classify_error_message(message),
            error_message=message,
        )
    return LLMResult(ok=True, text=response or "")


def _limit_script_text(text: str | None, max_length: int, field_name: str) -> str:
    value = (text or "").strip()
    if len(value) <= max_length:
        return value

    # API 层已经用 Pydantic 做长度校验；这里继续兜底，是为了保护
    # WebUI 或内部服务直接调用 generate_script 时不会把超长提示词发送给模型，
    # 避免 token 成本异常和请求失败。
    logger.warning(
        f"{field_name} is too long and will be truncated to {max_length} characters."
    )
    return value[:max_length]


def _normalize_script_paragraph_number(paragraph_number: int | None) -> int:
    try:
        value = int(paragraph_number or MIN_SCRIPT_PARAGRAPH_NUMBER)
    except (TypeError, ValueError):
        value = MIN_SCRIPT_PARAGRAPH_NUMBER

    if value < MIN_SCRIPT_PARAGRAPH_NUMBER or value > MAX_SCRIPT_PARAGRAPH_NUMBER:
        # WebUI 和 API 都会限制范围；这里兜底处理内部调用，避免异常参数直接扩大
        # LLM 生成成本或生成空结果。
        logger.warning(
            "script paragraph_number is out of range and will be clamped: "
            f"{value}"
        )
        return max(MIN_SCRIPT_PARAGRAPH_NUMBER, min(value, MAX_SCRIPT_PARAGRAPH_NUMBER))

    return value


def build_script_prompt(
    video_subject: str,
    language: str = "",
    paragraph_number: int = 1,
    video_script_prompt: str = "",
    custom_system_prompt: str = "",
) -> str:
    paragraph_number = _normalize_script_paragraph_number(paragraph_number)
    video_script_prompt = _limit_script_text(
        video_script_prompt, MAX_SCRIPT_PROMPT_LENGTH, "video_script_prompt"
    )
    custom_system_prompt = _limit_script_text(
        custom_system_prompt, MAX_SCRIPT_SYSTEM_PROMPT_LENGTH, "custom_system_prompt"
    )

    # 将“脚本生成规则”和“运行时上下文”分开拼接。这样高级用户即使覆盖默认
    # system prompt，也不会漏掉视频主题、语言、段落数这些每次生成都必须带上的参数。
    prompt = custom_system_prompt or DEFAULT_SCRIPT_SYSTEM_PROMPT
    prompt += f"""

# Initialization:
- video subject: {video_subject}
- number of paragraphs: {paragraph_number}
""".rstrip()
    if language:
        prompt += f"\n- language: {language}"
    if video_script_prompt:
        prompt += f"""

# Additional User Requirements:
{video_script_prompt}
""".rstrip()

    return prompt


def generate_script(
    video_subject: str,
    language: str = "",
    paragraph_number: int = 1,
    video_script_prompt: str = "",
    custom_system_prompt: str = "",
) -> str:
    paragraph_number = _normalize_script_paragraph_number(paragraph_number)
    video_script_prompt = _limit_script_text(
        video_script_prompt, MAX_SCRIPT_PROMPT_LENGTH, "video_script_prompt"
    )
    custom_system_prompt = _limit_script_text(
        custom_system_prompt, MAX_SCRIPT_SYSTEM_PROMPT_LENGTH, "custom_system_prompt"
    )
    prompt = build_script_prompt(
        video_subject=video_subject,
        language=language,
        paragraph_number=paragraph_number,
        video_script_prompt=video_script_prompt,
        custom_system_prompt=custom_system_prompt,
    )
    final_script = ""
    logger.info(
        "generating video script: "
        f"subject={video_subject}, paragraph_number={paragraph_number}, "
        f"has_custom_prompt={bool(video_script_prompt.strip())}, "
        f"has_custom_system_prompt={bool(custom_system_prompt.strip())}"
    )

    def format_response(response):
        # Clean the script
        # Remove asterisks, hashes
        response = response.replace("*", "")
        response = response.replace("#", "")

        # Remove markdown syntax
        response = re.sub(r"\[.*\]", "", response)
        response = re.sub(r"\(.*\)", "", response)

        # Split the script into paragraphs
        paragraphs = response.split("\n\n")

        # 这里不在服务层裁剪到 paragraph_number 段：prompt 已经显式约束了段落数，
        # 裁剪会让 LLM 多返回的合理内容被丢弃，反而缩短下游 TTS/字幕/素材时长预算。
        # 信任模型对 prompt 的遵守，保留全部段落。
        # （历史上曾有 selected_paragraphs = paragraphs[:paragraph_number] 的裁剪，
        # 但会改变输出长度行为，故移除。）

        # Join the selected paragraphs into a single string
        return "\n\n".join(paragraphs)

    for i in range(_max_retries):
        try:
            response = _generate_response(prompt=prompt)
            if response:
                final_script = format_response(response)
            else:
                logging.error("gpt returned an empty response")

            # g4f may return an error message
            if final_script and "当日额度已消耗完" in final_script:
                raise ValueError(final_script)

            if final_script:
                break
        except Exception as e:
            logger.error(f"failed to generate script: {e}")

        if i < _max_retries:
            logger.warning(f"failed to generate video script, trying again... {i + 1}")
    if "Error: " in final_script:
        logger.error(f"failed to generate video script: {final_script}")
    else:
        logger.success(f"completed: \n{final_script}")
    return final_script.strip()


def _strip_code_fence(text: str) -> str:
    """Strip a surrounding markdown code fence from an LLM response.

    Non-OpenAI providers (Claude, Gemini, …) frequently wrap JSON output in a
    ```json … ``` fence even when asked to return raw JSON. Removing it lets the
    first json.loads() succeed instead of falling through to the regex recovery
    path (and spuriously logging a warning). Mirrors the DOTALL handling already
    used in _parse_social_metadata().
    """
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def generate_terms(
    video_subject: str,
    video_script: str,
    amount: int = 5,
    match_script_order: bool = False,
) -> List[str]:
    if match_script_order:
        goal = (
            f"Generate {amount} chronological stock-video search terms that follow "
            "the order of topics in the video script."
        )
        ordering_rule = (
            "6. keep the terms in the same order as the script narration; "
            "earlier terms must describe earlier visual moments."
        )
        # 有序关键词模式下，示例数量要和 amount 保持一致，避免模型被固定
        # 的 4 个示例误导，导致长文案只返回少量关键词，影响素材覆盖度。
        example_terms = [
            "opening visual topic",
            *[
                f"script visual topic {index}"
                for index in range(2, max(amount, 1))
            ],
            "final visual topic",
        ]
        output_example = json.dumps(example_terms[:amount], ensure_ascii=False)
    else:
        goal = (
            f"Generate {amount} search terms for stock videos, depending on the "
            "subject of a video."
        )
        ordering_rule = ""
        output_example = (
            '["search term 1", "search term 2", "search term 3",'
            '"search term 4", "search term 5"]'
        )

    prompt = f"""
# Role: Video Search Terms Generator

## Goals:
{goal}

## Constrains:
1. the search terms are to be returned as a json-array of strings.
2. each search term should consist of 1-3 words, always add the main subject of the video.
3. you must only return the json-array of strings. you must not return anything else. you must not return the script.
4. the search terms must be related to the subject of the video.
5. reply with english search terms only.
{ordering_rule}

## Output Example:
{output_example}

## Context:
### Video Subject
{video_subject}

### Video Script
{video_script}

Please note that you must use English for generating video search terms; Chinese is not accepted.
""".strip()

    logger.info(
        f"subject: {video_subject}, match_script_order: {match_script_order}"
    )

    search_terms = []
    response = ""
    for i in range(_max_retries):
        try:
            response = _generate_response(prompt)
            if "Error: " in response:
                # 不能把错误字符串 return 出去：下游 task.py 只用 `if not video_terms`
                # 判空，会把 "Error: ..." 当成合法关键词列表一路传到素材搜索。
                # 这里记日志后返回空列表，让上层走正常失败分支。
                logger.error(f"failed to generate video terms: {response}")
                return []
            search_terms = json.loads(_strip_code_fence(response))
            if not isinstance(search_terms, list) or not all(
                isinstance(term, str) for term in search_terms
            ):
                logger.error("response is not a list of strings.")
                continue

        except Exception as e:
            logger.warning(f"failed to generate video terms: {str(e)}")
            if response:
                match = re.search(r"\[.*]", response, re.DOTALL)
                if match:
                    try:
                        search_terms = json.loads(match.group())
                    except Exception as e:
                        # 这里保留重试流程，但必须记录 LLM 返回的非标准 JSON，
                        # 否则后续排查搜索词为空时无法定位
                        # 是模型格式问题还是解析逻辑问题。
                        logger.warning(f"failed to generate video terms: {str(e)}")

        if search_terms and len(search_terms) > 0:
            break
        if i < _max_retries:
            logger.warning(f"failed to generate video terms, trying again... {i + 1}")

    logger.success(f"completed: \n{search_terms}")
    return search_terms


# =============================================================================
# Social publishing metadata
#
# 根据视频主题和脚本生成发布到短视频平台时常用的 title、caption 和 hashtags。
# 这块能力只复用现有 LLM provider，不接入任何外部发布服务，也不影响视频生成主链路。
# =============================================================================

# 不同平台的文案长度和 hashtag 数量偏好不同。这里使用保守上限，避免模型返回
# 过长内容后调用方还需要二次裁剪。
SOCIAL_PLATFORMS = {
    "tiktok": {"title_max": 100, "caption_max": 2200, "hashtag_count": 5},
    "youtube_shorts": {"title_max": 100, "caption_max": 5000, "hashtag_count": 3},
    "instagram_reels": {"title_max": 125, "caption_max": 2200, "hashtag_count": 8},
    "facebook_reels": {"title_max": 125, "caption_max": 2200, "hashtag_count": 5},
}
DEFAULT_SOCIAL_PLATFORM = "tiktok"
DEFAULT_SOCIAL_LANGUAGE = "auto"
MAX_SOCIAL_SUBJECT_LENGTH = 500
MAX_SOCIAL_SCRIPT_LENGTH = 8000
MAX_SOCIAL_LANGUAGE_LENGTH = 64

SOCIAL_PLATFORM_LABELS = {
    "tiktok": "TikTok",
    "youtube_shorts": "YouTube Shorts",
    "instagram_reels": "Instagram Reels",
    "facebook_reels": "Facebook Reels",
}

# LLM 不可用时的通用兜底标签。这里故意不绑定某个国家或语种，保证 API
# 对中文、英文、越南语等不同场景都能返回可用结构。
DEFAULT_SOCIAL_HASHTAGS = [
    "#shorts",
    "#viral",
    "#trending",
    "#fyp",
    "#video",
    "#reels",
    "#creator",
    "#content",
]


def _resolve_social_platform(platform: str | None) -> str:
    value = (platform or "").strip().lower()
    return value if value in SOCIAL_PLATFORMS else DEFAULT_SOCIAL_PLATFORM


def _normalize_social_language(language: str | None) -> str:
    value = (language or DEFAULT_SOCIAL_LANGUAGE).strip()
    if len(value) > MAX_SOCIAL_LANGUAGE_LENGTH:
        logger.warning(
            "social metadata language is too long and will be truncated to "
            f"{MAX_SOCIAL_LANGUAGE_LENGTH} characters."
        )
        value = value[:MAX_SOCIAL_LANGUAGE_LENGTH]
    return value or DEFAULT_SOCIAL_LANGUAGE


def _limit_social_text(text: str | None, max_length: int, field_name: str) -> str:
    value = (text or "").strip()
    if len(value) <= max_length:
        return value

    # API 层会限制长度；这里继续兜底，是为了保护内部调用或未来 WebUI
    # 直接调用时不会把超长内容发送给模型，避免 token 成本异常。
    logger.warning(
        f"{field_name} is too long and will be truncated to {max_length} characters."
    )
    return value[:max_length]


def _social_language_instruction(language: str | None) -> str:
    language = _normalize_social_language(language)
    if language.lower() == DEFAULT_SOCIAL_LANGUAGE:
        return (
            "Use the same language as the video subject and script. If the subject "
            "and script use different languages, prefer the script language."
        )

    return f'Write "title" and "caption" in this language: {language}.'


def _clamp_text(text, max_length: int) -> str:
    value = ("" if text is None else str(text)).strip()
    if max_length and len(value) > max_length:
        return value[:max_length].rstrip()
    return value


def _normalize_hashtags(raw, count: int) -> List[str]:
    """
    将 LLM 返回的 hashtag 统一整理成 `#tag` 格式。

    LLM 可能返回字符串、数组、带空格的词组、重复标签或包含标点的内容。
    这里集中清洗，可以让接口响应结构稳定，也避免平台发布时出现空标签、
    重复标签或不符合常见格式的 hashtag。
    """
    if isinstance(raw, str):
        candidates = re.split(r"[\s,]+", raw)
    elif isinstance(raw, (list, tuple)):
        # 数组里的每一项视为一个完整标签，因此 "du lich" 会变成
        # "#dulich"，而不是拆成两个标签。
        candidates = [str(entry) for entry in raw]
    else:
        candidates = []

    seen = set()
    result: List[str] = []
    for item in candidates:
        tag = re.sub(r"[^\w]", "", item, flags=re.UNICODE)
        if not tag:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(f"#{tag}")
        if count and len(result) >= count:
            break
    return result


def build_social_metadata_prompt(
    video_subject: str,
    video_script: str = "",
    language: str = DEFAULT_SOCIAL_LANGUAGE,
    platform: str = DEFAULT_SOCIAL_PLATFORM,
) -> str:
    video_subject = _limit_social_text(
        video_subject, MAX_SOCIAL_SUBJECT_LENGTH, "video_subject"
    )
    video_script = _limit_social_text(
        video_script, MAX_SOCIAL_SCRIPT_LENGTH, "video_script"
    )
    platform = _resolve_social_platform(platform)
    spec = SOCIAL_PLATFORMS[platform]
    label = SOCIAL_PLATFORM_LABELS.get(platform, platform)
    language_instruction = _social_language_instruction(language)

    prompt = f"""
# Role: Short-Video Social Media Copywriter

## Goal
Write engaging publishing metadata for a short video that will be posted on {label}.

## Constraints
1. Respond ONLY with a single valid minified JSON object. No markdown, no code fences, no commentary.
2. The JSON must contain exactly these keys: "title", "caption", "hashtags".
3. "title": a catchy hook, at most {spec['title_max']} characters.
4. "caption": an engaging description that ends with a call to action, at most {spec['caption_max']} characters. Do not put hashtags inside the caption.
5. "hashtags": a JSON array of exactly {spec['hashtag_count']} strings. Each must start with "#", contain no spaces, and be relevant to the topic and to {label}.
6. {language_instruction}

## Output Example
{{"title":"...","caption":"...","hashtags":["#example","#video"]}}

## Context
### Video Subject
{video_subject}

### Video Script
{video_script}
""".strip()
    return prompt


def _parse_social_metadata(response: str, platform: str) -> dict:
    spec = SOCIAL_PLATFORMS[_resolve_social_platform(platform)]

    data = None
    try:
        data = json.loads(_strip_code_fence(response))
    except Exception:
        # 部分模型会在 JSON 外层包一段说明文字或 markdown fence。
        # API 调用方只需要稳定结构，所以这里尝试提取第一个 JSON object。
        match = re.search(r"\{.*\}", response or "", re.DOTALL)
        if match:
            data = json.loads(match.group())

    if not isinstance(data, dict):
        raise ValueError("social metadata response is not a JSON object")

    title = _clamp_text(data.get("title", ""), spec["title_max"])
    caption = _clamp_text(data.get("caption", ""), spec["caption_max"])
    hashtags = _normalize_hashtags(data.get("hashtags", []), spec["hashtag_count"])

    if not title and not caption:
        raise ValueError("social metadata response is missing both title and caption")

    return {"title": title, "caption": caption, "hashtags": hashtags}


def _fallback_social_metadata(
    video_subject: str, video_script: str, platform: str
) -> dict:
    spec = SOCIAL_PLATFORMS[_resolve_social_platform(platform)]
    subject = (video_subject or "").strip()
    script = (video_script or "").strip()

    title = subject
    if not title and script:
        # 没有主题时，用脚本第一句兜底生成 title，避免接口返回空标题。
        title = re.split(r"(?<=[.!?。！？])\s+", script)[0]

    return {
        "title": _clamp_text(title, spec["title_max"]),
        "caption": _clamp_text(script or subject, spec["caption_max"]),
        "hashtags": _normalize_hashtags(
            DEFAULT_SOCIAL_HASHTAGS, spec["hashtag_count"]
        ),
    }


def generate_social_metadata(
    video_subject: str,
    video_script: str = "",
    language: str = DEFAULT_SOCIAL_LANGUAGE,
    platform: str = DEFAULT_SOCIAL_PLATFORM,
) -> dict:
    """
    生成短视频发布文案元数据。

    返回结构固定为 `{"title": str, "caption": str, "hashtags": List[str]}`。
    如果 LLM 不可用或返回格式异常，会降级为通用启发式结果，保证 API
    调用方始终拿到可展示、可发布前编辑的数据结构。
    """
    platform = _resolve_social_platform(platform)
    language = _normalize_social_language(language)
    video_subject = _limit_social_text(
        video_subject, MAX_SOCIAL_SUBJECT_LENGTH, "video_subject"
    )
    video_script = _limit_social_text(
        video_script, MAX_SOCIAL_SCRIPT_LENGTH, "video_script"
    )
    prompt = build_social_metadata_prompt(
        video_subject=video_subject,
        video_script=video_script,
        language=language,
        platform=platform,
    )
    logger.info(
        f"generating social metadata: platform={platform}, language={language}"
    )

    response = ""
    for i in range(_max_retries):
        try:
            response = _generate_response(prompt)
            if isinstance(response, str) and "Error: " in response:
                logger.error(f"failed to generate social metadata: {response}")
                break
            metadata = _parse_social_metadata(response, platform)
            logger.success(f"completed: \n{metadata}")
            return metadata
        except Exception as e:
            logger.warning(f"failed to parse social metadata: {str(e)}")

        if i < _max_retries - 1:
            logger.warning(
                f"failed to generate social metadata, trying again... {i + 1}"
            )

    logger.warning("falling back to heuristic social metadata")
    return _fallback_social_metadata(video_subject, video_script, platform)


if __name__ == "__main__":
    video_subject = "生命的意义是什么"
    script = generate_script(
        video_subject=video_subject, language="zh-CN", paragraph_number=1
    )
    print("######################")
    print(script)
    search_terms = generate_terms(
        video_subject=video_subject, video_script=script, amount=5
    )
    print("######################")
    print(search_terms)
    
