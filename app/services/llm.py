# ==============================================================================
#  app/services/llm.py (最终修复版 - 含场景延续性规则)
#  操作指南：请复制所有代码，并完全覆盖您项目中的同名文件。
# ==============================================================================

import json
import logging
import re
import requests
from typing import List, Dict

import g4f
from loguru import logger
from openai import AzureOpenAI, OpenAI
from openai.types.chat import ChatCompletion

from app.config import config

_max_retries = 5


def _generate_response(prompt: str) -> str:
    """
    与大语言模型（LLM）提供商进行交互。
    (此函数已从您上传的文件中完整保留)
    """
    try:
        content = ""
        llm_provider = config.app.get("llm_provider", "openai")
        logger.info(f"llm provider: {llm_provider}")
        if llm_provider == "g4f":
            model_name = config.app.get("g4f_model_name", "")
            if not model_name:
                model_name = "gpt-3.5-turbo-16k-0613"
            content = g4f.ChatCompletion.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
            )
        else:
            api_version = ""  # for azure
            if llm_provider == "moonshot":
                api_key = config.app.get("moonshot_api_key")
                model_name = config.app.get("moonshot_model_name")
                base_url = "https://api.moonshot.cn/v1"
            elif llm_provider == "ollama":
                api_key = "ollama"  # any string works but you are required to have one
                model_name = config.app.get("ollama_model_name")
                base_url = config.app.get("ollama_base_url", "")
                if not base_url:
                    base_url = "http://localhost:11434/v1"
            elif llm_provider == "openai":
                api_key = config.app.get("openai_api_key")
                model_name = config.app.get("openai_model_name")
                base_url = config.app.get("openai_base_url", "")
                if not base_url:
                    base_url = "https://api.openai.com/v1"
            elif llm_provider == "oneapi":
                api_key = config.app.get("oneapi_api_key")
                model_name = config.app.get("oneapi_model_name")
                base_url = config.app.get("oneapi_base_url", "")
            elif llm_provider == "azure":
                api_key = config.app.get("azure_api_key")
                model_name = config.app.get("azure_model_name")
                base_url = config.app.get("azure_base_url", "")
                api_version = config.app.get("azure_api_version", "2024-02-15-preview")
            elif llm_provider == "gemini":
                api_key = config.app.get("gemini_api_key")
                model_name = config.app.get("gemini_model_name")
                base_url = "***" # Placeholder from original file
            elif llm_provider == "qwen":
                api_key = config.app.get("qwen_api_key")
                model_name = config.app.get("qwen_model_name")
                base_url = "***" # Placeholder from original file
            elif llm_provider == "cloudflare":
                api_key = config.app.get("cloudflare_api_key")
                model_name = config.app.get("cloudflare_model_name")
                account_id = config.app.get("cloudflare_account_id")
                base_url = "***" # Placeholder from original file
            elif llm_provider == "deepseek":
                api_key = config.app.get("deepseek_api_key")
                model_name = config.app.get("deepseek_model_name")
                base_url = config.app.get("deepseek_base_url")
                if not base_url:
                    base_url = "https://api.deepseek.com"
            elif llm_provider == "ernie":
                api_key = config.app.get("ernie_api_key")
                secret_key = config.app.get("ernie_secret_key")
                base_url = config.app.get("ernie_base_url")
                model_name = "***" # Placeholder from original file
                if not secret_key:
                    raise ValueError(
                        f"{llm_provider}: secret_key is not set, please set it in the config.toml file."
                    )
            elif llm_provider == "pollinations":
                try:
                    base_url = config.app.get("pollinations_base_url", "")
                    if not base_url:
                        base_url = "https://text.pollinations.ai/openai"
                    model_name = config.app.get("pollinations_model_name", "openai-fast")
                    payload = {
                        "model": model_name,
                        "messages": [{"role": "user", "content": prompt}],
                        "seed": 101
                    }
                    if config.app.get("pollinations_private"):
                        payload["private"] = True
                    if config.app.get("pollinations_referrer"):
                        payload["referrer"] = config.app.get("pollinations_referrer")
                    headers = {"Content-Type": "application/json"}
                    response = requests.post(base_url, headers=headers, json=payload)
                    response.raise_for_status()
                    result = response.json()
                    if result and "choices" in result and len(result["choices"]) > 0:
                        content = result["choices"][0]["message"]["content"]
                        return content.replace("\n", "")
                    else:
                        raise Exception(f"[{llm_provider}] returned an invalid response format")
                except requests.exceptions.RequestException as e:
                    raise Exception(f"[{llm_provider}] request failed: {str(e)}")
                except Exception as e:
                    raise Exception(f"[{llm_provider}] error: {str(e)}")

            if llm_provider not in ["pollinations", "ollama"]:
                if not api_key:
                    raise ValueError(f"{llm_provider}: api_key is not set, please set it in the config.toml file.")
                if not model_name:
                    raise ValueError(f"{llm_provider}: model_name is not set, please set it in the config.toml file.")
                if not base_url:
                    raise ValueError(f"{llm_provider}: base_url is not set, please set it in the config.toml file.")

            if llm_provider == "qwen":
                import dashscope
                from dashscope.api_entities.dashscope_response import GenerationResponse
                dashscope.api_key = api_key
                response = dashscope.Generation.call(model=model_name, messages=[{"role": "user", "content": prompt}])
                if response:
                    if isinstance(response, GenerationResponse):
                        if response.status_code != 200:
                            raise Exception(f'[{llm_provider}] returned an error response: "{response}"')
                        content = response["output"]["text"]
                        return content.replace("\n", "")
                    else:
                        raise Exception(f'[{llm_provider}] returned an invalid response: "{response}"')
                else:
                    raise Exception(f"[{llm_provider}] returned an empty response")

            if llm_provider == "gemini":
                import google.generativeai as genai
                genai.configure(api_key=api_key, transport="rest")
                generation_config = {"temperature": 0.5, "top_p": 1, "top_k": 1, "max_output_tokens": 8192}
                safety_settings = [
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_ONLY_HIGH"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_ONLY_HIGH"},
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_ONLY_HIGH"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"},
                ]
                model = genai.GenerativeModel(model_name=model_name, generation_config=generation_config, safety_settings=safety_settings)
                try:
                    response = model.generate_content(prompt)
                    generated_text = response.candidates[0].content.parts[0].text
                    return generated_text
                except (AttributeError, IndexError) as e:
                    logger.error(f"Gemini Error: {e}")
                    return ""

            if llm_provider == "cloudflare":
                response = requests.post(
                    f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model_name}",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"messages": [{"role": "system", "content": "You are a friendly assistant"}, {"role": "user", "content": prompt}]}
                )
                result = response.json()
                logger.info(result)
                return result["result"]["response"]

            if llm_provider == "ernie":
                response = requests.post(
                    "https://aip.baidubce.com/oauth/2.0/token",
                    params={"grant_type": "client_credentials", "client_id": api_key, "client_secret": secret_key}
                )
                access_token = response.json().get("access_token")
                url = f"{base_url}?access_token={access_token}"
                payload = json.dumps({"messages": [{"role": "user", "content": prompt}], "temperature": 0.5, "top_p": 0.8, "penalty_score": 1, "disable_search": False, "enable_citation": False, "response_format": "text"})
                headers = {"Content-Type": "application/json"}
                response = requests.request("POST", url, headers=headers, data=payload).json()
                return response.get("result")

            if llm_provider == "azure":
                client = AzureOpenAI(api_key=api_key, api_version=api_version, azure_endpoint=base_url)
            else:
                client = OpenAI(api_key=api_key, base_url=base_url)

            response: ChatCompletion = client.chat.completions.create(model=model_name, messages=[{"role": "user", "content": prompt}], max_tokens=4096)
            if response:
                if isinstance(response, ChatCompletion):
                    content = response.choices[0].message.content
                else:
                    raise Exception(f'[{llm_provider}] returned an invalid response: "{response}", please check your network connection and try again.')
            else:
                raise Exception(f"[{llm_provider}] returned an empty response, please check your network connection and try again.")

        return content.replace("\n", "")
    except Exception as e:
        logger.error(f"[_generate_response] 发生错误: {e}")
        return f"Error: {str(e)}"


def generate_script(video_subject: str, language: str = "", paragraph_number: int = 1) -> str:
    """
    根据视频主题生成脚本。
    (此函数已从您上传的文件中完整保留)
    """
    prompt = f"""
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
7. you must not mention the prompt, or anything about the script itself. also, never talk about the number of paragraphs or lines. just write the script.
8. respond in the same language as the video subject.
# Initialization:
- video subject: {video_subject}
- number of paragraphs: {paragraph_number}
""".strip()
    if language:
        prompt += f"\n- language: {language}"

    final_script = ""
    logger.info(f"subject: {video_subject}")

    def format_response(response):
        response = response.replace("*", "").replace("#", "")
        response = re.sub(r"\[.*\]", "", response)
        response = re.sub(r"\(.*\)", "", response)
        paragraphs = response.split("\n\n")
        return "\n\n".join(paragraphs)

    for i in range(_max_retries):
        try:
            response = _generate_response(prompt=prompt)
            if response:
                final_script = format_response(response)
            else:
                logging.error("gpt returned an empty response")
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


def generate_storyboard(video_subject: str, video_script: str) -> List[Dict]:
    """
    根据视频主题和脚本，生成一个包含多个场景对象的故事板列表。
    每个对象包含 'script' 和 'search_terms'。
    (此函数已更新为新版逻辑并重命名)
    """
    prompt_template = """
# 角色 (Role)
你是一位顶级的“视觉内容策略师”（Expert Visual Content Strategist）。你的核心专长是将书面脚本转化为具体、引人入胜且在主流视频素材库（如 Pexels, Pixabay）中高度可搜索的视觉关键词序列。你的输出必须兼具艺术相关性和技术实用性。

# 核心任务 (Core Task)
你的任务是接收一段视频脚本，严格按照下述的“核心思维链与执行规则”，输出一个格式化、无额外解释的 JSON 数组。数组中的每个对象代表脚本中的一个句子，并包含该句子对应的、经过策略优化的视觉搜索关键词字符串。

# 关键输出格式 (Critical Output Format)
你必须且只能输出一个严格的、不包含任何前后说明文字的 JSON 数组。每个JSON对象必须只包含两个键：
1.  `"script"`: 原始脚本的句子。
2.  `"search_terms"`: 一个由逗号分隔的、全英文小写的关键词字符串。

# 核心思维链与执行规则 (Core Chain of Thought & Execution Rules)
你必须严格按照以下顺序思考和执行每一步，不得跳过或颠倒。

### 步骤 1: 分段 (Segmentation)
将接收到的 `{video_script}` 分解成独立的句子。每个句子构成一个独立的处理单元，对应JSON数组中的一个对象。

### 步骤 2: 初步提取 (Initial Extraction)
对于每个句子，首先识别并提取所有字面上（Verbatim）的名词和可以被视觉化的核心概念。

### 步骤 3: 视觉化与过滤 (Visualization & Filtering) - [不可妥协的规则]
审视步骤 2 中提取的每个词。必须无条件过滤掉所有抽象、无形、无法直接用镜头表达的概念。
- **绝对禁止的词汇范畴**: 概念（`concept`）、情感（`happiness`）、性质（`quality`）、关系（`relationship`）、不可见的动作或状态（`protection`, `damage`, `stress`, `health`, `age`）。
- **此步骤的目标**: 清理掉所有在视频素材库中没有意义的“噪音”词汇。

### 步骤 3b: 场景延续性规则 (Continuity Rule for Abstract Sentences) - [新增规则]
如果在步骤3之后，一个句子的关键词列表变为空（例如，句子是 "And for good reason."），**你绝不能返回空字符串**。你必须：
1.  **参考前一个场景**的视觉主题和关键词。
2.  生成一个与前一场景**相关但不同**的关键词，以实现视觉上的平滑过渡或情感深化。
3.  **示例**: 如果前一场景的关键词是 `person's eyes, eye close-up`，那么对于 "And for good reason." 这个句子，一个好的延续性关键词可以是 `thoughtful expression` (深思的表情) 或 `person looking at camera` (人物看镜头)。

### 步骤 4: 可搜索性增强 (Searchability Enhancement) - [智能扩展规则]
审视步骤 3 和 3b 后剩下的关键词。这是发挥你“策略师”价值的关键。
- **识别技术/专业词汇**: 如果关键词过于学术化、专业化或罕见（例如：`anthocyanins`, `macula`），以至于在标准素材库中不可能找到匹配，你必须为其补充一个或多个更通用、更形象的搜索词。
- **补充原则**: 补充的词汇必须与原词在视觉上高度相关。
  - 示例 1: 对于 `retina` (视网膜)，补充 `eye close-up`。最终结果包含 `"retina, eye close-up"`。
  - 示例 2: 对于 `anthocyanins` (花青素)，补充 `colorful fruits` 或 `antioxidant food`。最终结果包含 `"anthocyanins, colorful fruits"`。
- **此步骤的目标**: 确保最终的关键词列表不仅在内容上正确，在实践中也真正可用。

### 步骤 5: 多样性原则 (Diversity Principle)
在构建最终的关键词字符串时，确保**连续两个有内容的视觉片段**不会使用完全相同的主要搜索词。例如，如果前一个片段的主要关键词是 `blueberries`，下一个片段应优先使用其它关键词（如 `food`, `eyes`）来开始，以增强视觉多样性。

### 步骤 6: 最终构建 (Final Construction)
将经过以上所有步骤处理和优化后的关键词，整理成一个全英文小写、用英文逗号分隔的字符串，作为 `search_terms` 的最终值。

# 待处理脚本 (Script to Process):
```
{video_script}
```

**Your JSON Output (must be a valid JSON array):**
"""
    prompt = prompt_template.format(video_script=video_script, video_subject=video_subject)

    logger.info(f"正在为主题 '{video_subject}' 生成故事板 (Storyboard)...")
    response_str = _generate_response(prompt=prompt)
    logger.debug(f"从LLM收到的原始回复: {response_str}")

    try:
        json_match = re.search(r'\[.*\]', response_str, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
            storyboard = json.loads(json_str)
            logger.success(f"成功从LLM回复中解析出 {len(storyboard)} 个场景。")
            return storyboard
        else:
            logger.error(f"在回复中未找到有效的JSON数组。原始回复: {response_str}")
            return []
    except json.JSONDecodeError as e:
        logger.error(f"解析JSON失败: {e}。原始回复: {response_str}")
        return []


def generate_video_category(video_subject: str) -> str:
    """
    根据视频主题选择最合适的视频分类。
    (此函数已从您上传的文件中完整保留)
    """
    prompt = f"""
# Role: Video Category Selector
## Goal:
Based on the provided 'Video Subject', select the ONE most suitable category from the `Category List` that best represents the subject. Your response must be only the single category name.
## Category List:
backgrounds, fashion, nature, science, education, feelings, health, people, religion, places, animals, industry, computer, food, sports, transportation, travel, buildings, business, music
## Instructions:
- Analyze the 'Video Subject'.
- Choose the single best-fitting category from the list.
- Respond with ONLY the category name and nothing else.
## Example:
Video Subject: "The benefits of a ketogenic diet"
Response: health
Video Subject: "A tour of the Grand Canyon"
Response: travel
## CONTEXT:
### Video Subject:
{video_subject}
"""
    category = _generate_response(prompt).strip().lower()
    valid_categories = ["backgrounds", "fashion", "nature", "science", "education", "feelings", "health", "people", "religion", "places", "animals", "industry", "computer", "food", "sports", "transportation", "travel", "buildings", "business", "music"]
    if category not in valid_categories:
        logger.warning(f"Generated category '{category}' is not valid. Falling back to 'nature'.")
        return "nature"
    
    logger.success(f"Successfully selected video category: {category}")
    return category


if __name__ == "__main__":
    # 这个部分用于直接运行此文件进行测试
    video_subject = "生命的意义是什么"
    script = generate_script(
        video_subject=video_subject, language="zh-CN", paragraph_number=1
    )
    print("######################")
    print(script)
    # 注意：这里调用的是重命名后的函数 generate_storyboard
    storyboard = generate_storyboard(
        video_subject=video_subject, video_script=script
    )
    print("######################")
    import pprint
    pprint.pprint(storyboard)
    print("-----输出包含的场景数量-----")
    if storyboard:
        print(len(storyboard))
    else:
        print(0)

