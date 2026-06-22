import json
import logging
import re
import requests
from typing import Dict, List

import g4f
from loguru import logger
from openai import AzureOpenAI, OpenAI
from openai.types.chat import ChatCompletion

from app.config import config

_max_retries = 5

# Load configuration once at module level
stop_on_api_failure = config.app.get("stop_on_api_failure", False)

# Language detection utility
def detect_language(text: str) -> str:
    """
    Detect the language of the given text.
    
    Args:
        text: Text to detect language from
        
    Returns:
        Detected language code
    """
    # Simple language detection based on character sets and common words
    # This is a basic implementation - for production, consider using a proper NLP library
    
    # Check for Chinese characters
    if any('\u4e00' <= char <= '\u9fff' for char in text):
        return "Chinese"
    
    # Check for German umlauts and common German words
    german_indicators = ['ä', 'ö', 'ü', 'ß', 'der', 'die', 'das', 'und', 'in', 'ist']
    if any(indicator in text.lower() for indicator in german_indicators):
        return "German"
    
    # Default to English
    return "English"


def _generate_response(prompt: str) -> str:
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
                # api_key = config.app.get("openai_api_key")
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
                base_url = config.app.get("gemini_base_url", "")
            elif llm_provider == "qwen":
                api_key = config.app.get("qwen_api_key")
                model_name = config.app.get("qwen_model_name")
                base_url = "***"
            elif llm_provider == "cloudflare":
                api_key = config.app.get("cloudflare_api_key")
                model_name = config.app.get("cloudflare_model_name")
                account_id = config.app.get("cloudflare_account_id")
                base_url = "***"
            elif llm_provider == "deepseek":
                api_key = config.app.get("deepseek_api_key")
                model_name = config.app.get("deepseek_model_name")
                base_url = config.app.get("deepseek_base_url")
                if not base_url:
                    base_url = "https://api.deepseek.com"
            elif llm_provider == "modelscope":
                api_key = config.app.get("modelscope_api_key")
                model_name = config.app.get("modelscope_model_name")
                base_url = config.app.get("modelscope_base_url")
                if not base_url:
                    base_url = "https://api-inference.modelscope.cn/v1/"
            elif llm_provider == "ernie":
                api_key = config.app.get("ernie_api_key")
                secret_key = config.app.get("ernie_secret_key")
                base_url = config.app.get("ernie_base_url")
                model_name = "***"
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
                        return content.replace("\n", "")
                    else:
                        raise Exception(f"[{llm_provider}] returned an invalid response format")
                        
                except requests.exceptions.RequestException as e:
                    raise Exception(f"[{llm_provider}] request failed: {str(e)}")
                except Exception as e:
                    raise Exception(f"[{llm_provider}] error: {str(e)}")

            if llm_provider not in ["pollinations", "ollama"]:  # Skip validation for providers that don't require API key
                if not api_key:
                    raise ValueError(
                        f"{llm_provider}: api_key is not set, please set it in the config.toml file."
                    )
                if not model_name:
                    raise ValueError(
                        f"{llm_provider}: model_name is not set, please set it in the config.toml file."
                    )
                if not base_url:
                    raise ValueError(
                        f"{llm_provider}: base_url is not set, please set it in the config.toml file."
                    )

            if llm_provider == "qwen":
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
                                f'[{llm_provider}] returned an error response: "{response}"'
                            )

                        content = response["output"]["text"]
                        return content.replace("\n", "")
                    else:
                        raise Exception(
                            f'[{llm_provider}] returned an invalid response: "{response}"'
                        )
                else:
                    raise Exception(f"[{llm_provider}] returned an empty response")

            if llm_provider == "gemini":
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
                    print("Gemini Error:", e)

                return generated_text

            if llm_provider == "cloudflare":
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
                return result["result"]["response"]

            if llm_provider == "ernie":
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
                return response.get("result")

            if llm_provider == "azure":
                client = AzureOpenAI(
                    api_key=api_key,
                    api_version=api_version,
                    azure_endpoint=base_url,
                )

            if llm_provider == "modelscope":
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
                    
                    return content.replace("\n", "")
                else:
                    raise Exception(f"[{llm_provider}] returned an empty response")

            else:
                client = OpenAI(
                    api_key=api_key,
                    base_url=base_url,
                )

            response = client.chat.completions.create(
                model=model_name, messages=[{"role": "user", "content": prompt}]
            )
            if response:
                if isinstance(response, ChatCompletion):
                    content = response.choices[0].message.content
                else:
                    raise Exception(
                        f'[{llm_provider}] returned an invalid response: "{response}", please check your network '
                        f"connection and try again."
                    )
            else:
                raise Exception(
                    f"[{llm_provider}] returned an empty response, please check your network connection and try again."
                )

        return content.replace("\n", "") if content else ""
    except Exception as e:
        return f"Error: {str(e)}"


def generate_script(
    video_subject: str, language: str = None, paragraph_number: int = 1
) -> str:
    # Default language to Chinese if video_subject is empty
    if not video_subject:
        video_subject = "设计模式"
        default_language = "Chinese"
    else:
        default_language = None
        
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
7. you must not mention the prompt, or anything about the script itself. also, never talk about the amount of paragraphs or lines. just write the script.
8. respond in the same language as the video subject.

# Initialization:
- video subject: {video_subject}
- number of paragraphs: {paragraph_number}
""".strip()
    if language and language != "":
        prompt += f"\n- language: {language}\n- IMPORTANT: Please respond in {language} language."
    else:
        # Auto-detect language from video subject
        detected_language = default_language if default_language else detect_language(video_subject)
        prompt += f"\n- language: {detected_language}\n- IMPORTANT: Please respond in {detected_language} language."

    final_script = ""
    logger.info(f"subject: {video_subject}")

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

        # Select the specified number of paragraphs
        # selected_paragraphs = paragraphs[:paragraph_number]

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
    
    if not final_script or "Error: " in final_script:
        if stop_on_api_failure:
            error_msg = f"LLM API failed to generate script after {_max_retries} attempts"
            logger.error(error_msg)
            return f"Error: {error_msg}"
    
    if "Error: " in final_script:
        logger.error(f"failed to generate video script: {final_script}")
    else:
        logger.success(f"completed: \n{final_script}")
    return final_script.strip()


def generate_terms(video_subject: str, video_script: str, amount: int = 5) -> List[str]:
    prompt = f"""
# Role: Video Search Terms Generator

## Goals:
Generate {amount} search terms for stock videos, depending on the subject of a video.

## Constrains:
1. the search terms are to be returned as a json-array of strings.
2. each search term should consist of 1-3 words, always add the main subject of the video.
3. you must only return the json-array of strings. you must not return anything else. you must not return the script.
4. the search terms must be related to the subject of the video.
5. generate both English and Chinese search terms to get more relevant videos.

## Output Example:
["design patterns", "设计模式", "software design", "软件设计", "coding best practices", "编程最佳实践", "object oriented", "面向对象", "design principles", "设计原则"]

## Context:
### Video Subject
{video_subject}

### Video Script
{video_script}

Please generate both English and Chinese search terms to ensure better search results.
""".strip()

    logger.info(f"subject: {video_subject}")

    search_terms = []
    response = ""
    for i in range(_max_retries):
        try:
            response = _generate_response(prompt)
            if "Error: " in response:
                logger.error(f"failed to generate video terms: {response}")
                if stop_on_api_failure:
                    return response
                return []
            search_terms = json.loads(response)
            if not isinstance(search_terms, list) or not all(
                isinstance(term, str) for term in search_terms
            ):
                logger.error("response is not a list of strings.")
                continue

        except Exception as e:
            logger.warning(f"failed to generate video terms: {str(e)}")
            if stop_on_api_failure:
                error_msg = f"LLM API failed to generate video terms after {_max_retries} attempts: {str(e)}"
                logger.error(error_msg)
                return f"Error: {error_msg}"
            if response:
                match = re.search(r"\[.*]", response)
                if match:
                    try:
                        search_terms = json.loads(match.group())
                    except Exception as e:
                        logger.warning(f"failed to generate video terms: {str(e)}")
                        pass

        if search_terms and len(search_terms) > 0:
            break
        if i < _max_retries:
            logger.warning(f"failed to generate video terms, trying again... {i + 1}")

    if not search_terms and stop_on_api_failure:
        error_msg = f"LLM API failed to generate video terms after {_max_retries} attempts"
        logger.error(error_msg)
        return f"Error: {error_msg}"

    logger.success(f"completed: \n{search_terms}")
    return search_terms


def generate_tags(scene_script: str, visual_requirement: str = "", max_tags: int = 3) -> List[str]:
    """
    Generate 1-3 tags for a scene based on its script content and visual requirements.
    
    Args:
        scene_script: Scene script text
        visual_requirement: Scene visual requirements
        max_tags: Maximum number of tags to generate
        
    Returns:
        List of generated tags
    """
    # Build context with both script and visual requirements
    context = f"### Scene Script\n{scene_script}"
    if visual_requirement and visual_requirement.strip():
        context += f"\n\n### Visual Requirements\n{visual_requirement}"
    
    prompt = f"""
    # Role: Scene Tag Generator
    
    ## Goals:
    Generate {max_tags} relevant tags for a video scene based on its script content and visual requirements.
    
    ## Constrains:
    1. The tags are to be returned as a json-array of strings.
    2. Each tag should be a single word or short phrase (1-3 words).
    3. The tags must be directly related to the content of the scene and its visual requirements.
    4. You must only return the json-array of strings. You must not return anything else.
    5. Respond in the same language as the scene script.
    
    ## Output Example:
    ["tag1", "tag2", "tag3"]
    
    ## Context:
    {context}
    """
    
    # Strip whitespace and ensure proper formatting
    prompt = prompt.strip()
    
    logger.info(f"Generating tags for scene script: {scene_script[:50]}...")
    
    tags = []
    response = ""
    for i in range(_max_retries):
        try:
            response = _generate_response(prompt)
            
            if not response or response.strip() == "":
                logger.warning(f"LLM API returned empty response, attempt {i + 1}/{_max_retries}")
                continue
                
            if "Error: " in response:
                logger.error(f"Failed to generate tags: {response}")
                if stop_on_api_failure:
                    return []
                continue
            tags = json.loads(response)
            if not isinstance(tags, list) or not all(
                isinstance(tag, str) for tag in tags
            ):
                logger.error("Response is not a list of strings.")
                continue
            
            # Limit to max_tags
            tags = tags[:max_tags]
            
        except Exception as e:
            logger.warning(f"Failed to generate tags: {str(e)}")
            if stop_on_api_failure:
                error_msg = f"LLM API failed to generate tags after {_max_retries} attempts: {str(e)}"
                logger.error(error_msg)
                return []
            if response:
                match = re.search(r"\[.*]", response)
                if match:
                    try:
                        tags = json.loads(match.group())
                        # Limit to max_tags
                        tags = tags[:max_tags]
                    except Exception as e:
                        logger.warning(f"Failed to parse tags: {str(e)}")
                        pass
        
        if tags and len(tags) > 0:
            break
        if i < _max_retries:
            logger.warning(f"Failed to generate tags, trying again... {i + 1}")
    
    if not tags and stop_on_api_failure:
        error_msg = f"LLM API failed to generate tags after {_max_retries} attempts"
        logger.error(error_msg)
        return []
    
    logger.success(f"Generated tags: {tags}")
    return tags


def _get_content_type_opening_guidance(content_type: str, language: str = "English") -> str:
    """
    Get content-type-specific opening scene guidance for the LLM.
    
    Args:
        content_type: One of "narrative", "informative", "discussive"
        language: Language for the guidance (determines examples and tone)
        
    Returns:
        Guidance text for generating optimized opening scenes
    """
    
    # Detect language for guidance
    is_chinese = language.lower() in ["chinese", "zh"]
    is_german = language.lower() == "german"
    
    if content_type == "narrative":
        # News, stories, event reports - start with dramatic event or surprising fact
        if is_chinese:
            return """CONTENT TYPE: 新闻叙事类
- 开场策略: 以戏剧性事件或惊人事实开场，立即抓住观众注意力
- 开场钩子类型: 
  * 突发事件: "就在今天下午三点，发生了史无前例的事情..."
  * 惊人数据: "最新调查显示，80% 的人都不知道这个秘密..."
  * 悬念开头: "当所有人都以为事情已经结束时，真相才刚刚浮出水面..."
- 视觉技巧: 动态分屏、快速缩放、统计数据文字动画
- 音频技巧: 紧迫、戏剧性的语气，使用时间敏感的措辞
- 评估标准: 开场3秒内必须出现钩子元素"""
        elif is_german:
            return """CONTENT TYPE: Narrative (News/Stories)
- Opening Strategy: Start with dramatic event or surprising fact to immediately grab attention
- Opening Hook Types:
  * Breaking news: "Gestern um 15 Uhr passierte etwas Beispielloses..."
  * Surprising data: "Neueste Umfragen zeigen, dass 80% der Menschen dieses Geheimnis nicht kennen..."
  * Suspense: "Als alle dachten, es wäre vorbei, beginnt die Wahrheit gerade erst..."
- Visual Techniques: Dynamic split-screen, fast zoom, statistic text animations
- Audio Techniques: Urgent, dramatic tone with time-sensitive language
- Evaluation: Hook element must appear within first 3 seconds"""
        else:
            return """CONTENT TYPE: Narrative (News/Stories)
- Opening Strategy: Start with dramatic event or surprising fact to immediately grab attention
- Opening Hook Types:
  * Breaking news: "Yesterday at 3 PM, something unprecedented happened..."
  * Surprising data: "Latest surveys show that 80% of people don't know this secret..."
  * Suspense: "When everyone thought it was over, the truth was just beginning..."
- Visual Techniques: Dynamic split-screen, fast zoom, statistic text animations
- Audio Techniques: Urgent, dramatic tone with time-sensitive language
- Evaluation: Hook element must appear within first 3 seconds"""
    
    elif content_type == "informative":
        # Articles, tutorials, explainers - pose curiosity-inducing question
        if is_chinese:
            return """CONTENT TYPE: 知识科普类
- 开场策略: 提出引发好奇的问题，激发观众求知欲
- 开场钩子类型:
  * 好奇问题: "你有没有想过，为什么 AI 能够比大多数开发者更好地编写代码？"
  * 惊人事实: "你可能不知道，你每天都在使用的这个功能，背后隐藏着一个惊人的秘密..."
  * 反直觉开场: "与传统观念相反，最有效的学习方法往往看起来最'笨'..."
- 视觉技巧: 神秘的特写镜头、聚光灯效果、动态问号动画
- 音频技巧: 好奇、引人入胜的语气，提出发人深省的问题
- 评估标准: 开场问题必须在5秒内清晰表达"""
        elif is_german:
            return """CONTENT TYPE: Informative (Articles/Tutorials)
- Opening Strategy: Pose curiosity-inducing question to spark audience curiosity
- Opening Hook Types:
  * Curious question: "Hast du dich jemals gefragt, warum KI Code besser schreiben kann als die meisten Entwickler?"
  * Surprising fact: "Was du vielleicht nicht weißt: Hinter dieser Funktion verbirgt sich ein erstaunliches Geheimnis..."
  * Counterintuitive: "Entgegen der landläufigen Meinung ist die effektivste Lernmethode oft die 'dümmste'..."
- Visual Techniques: Mysterious close-ups, spotlight effects, animated question marks
- Audio Techniques: Curious, engaging tone with thought-provoking questions
- Evaluation: Opening question must be clearly expressed within 5 seconds"""
        else:
            return """CONTENT TYPE: Informative (Articles/Tutorials)
- Opening Strategy: Pose curiosity-inducing question to spark audience curiosity
- Opening Hook Types:
  * Curious question: "Have you ever wondered why AI can write code better than most developers?"
  * Surprising fact: "What you might not know: behind this feature lies an amazing secret..."
  * Counterintuitive: "Contrary to popular belief, the most effective learning method often looks the 'dumbest'..."
- Visual Techniques: Mysterious close-ups, spotlight effects, animated question marks
- Audio Techniques: Curious, engaging tone with thought-provoking questions
- Evaluation: Opening question must be clearly expressed within 5 seconds"""
    
    elif content_type == "discussive":
        # Debates, opinions, commentaries - present provocative statement
        if is_chinese:
            return """CONTENT TYPE: 观点讨论类
- 开场策略: 提出引发争议的论点，激发观众思考和参与
- 开场钩子类型:
  * 争议观点: "70% 的专家在这个问题上持反对意见，而这可能会彻底改变你的认知..."
  * 对比冲突: "有人说这是最好的方案，有人却认为这是灾难的开始..."
  * 立场鲜明: "我必须直言不讳：这个被所有人追捧的方法，实际上是个陷阱！"
- 视觉技巧: 分屏展示对立观点、对比色方案、有冲击力的文字动画
- 音频技巧: 有争议性、充满活力的语气，突出争议性
- 评估标准: 开场必须明确表达立场或争议点"""
        elif is_german:
            return """CONTENT TYPE: Discussive (Debates/Comments)
- Opening Strategy: Present provocative statement to spark audience thinking and engagement
- Opening Hook Types:
  * Controversial opinion: "70% der Experten widersprechen bei diesem Thema, und das könnte Ihre Wahrnehmung völlig verändern..."
  * Contrasting conflict: "Manche sagen, dies sei die beste Lösung, während andere glauben, es sei der Beginn einer Katastrophe..."
  * Clear stance: "Ich muss Klartext reden: Diese von allen begehrte Methode ist tatsächlich eine Falle!"
- Visual Techniques: Split-screen opposing views, contrasting color schemes, impactful text animations
- Audio Techniques: Provocative, energetic tone highlighting controversy
- Evaluation: Opening must clearly express stance or controversy"""
        else:
            return """CONTENT TYPE: Discussive (Debates/Comments)
- Opening Strategy: Present provocative statement to spark audience thinking and engagement
- Opening Hook Types:
  * Controversial opinion: "70% of experts disagree on this issue, and it might completely change your perception..."
  * Contrasting conflict: "Some say this is the best solution, while others believe it's the start of a disaster..."
  * Clear stance: "I have to be blunt: this method everyone is raving about is actually a trap!"
- Visual Techniques: Split-screen opposing views, contrasting color schemes, impactful text animations
- Audio Techniques: Provocative, energetic tone highlighting controversy
- Evaluation: Opening must clearly express stance or controversy"""
    
    else:
        # Unknown content type - generic engaging opening
        if is_chinese:
            return """CONTENT TYPE: 通用类
- 开场策略: 用有冲击力的钩子直接切入主题，禁止使用"大家好""欢迎来到"等套话
- 开场钩子类型（任选其一）:
  * 发人深省的提问: "你有没有想过，为什么...？"
  * 惊人事实/数据: "99%的人都不知道..."
  * 反直觉断言: "与你想象的完全相反..."
  * 场景代入: "想象一下，如果有一天..."
- 视觉技巧: 有冲击力的画面或数据可视化，快速吸引注意力
- 音频技巧: 充满张力的语气，制造紧迫感或好奇心
- 评估标准: 开场3秒内必须出现钩子，绝不以问候语开头"""
        elif is_german:
            return """CONTENT TYPE: General
- Opening Strategy: Hook the audience immediately with an impactful opening — NO generic greetings like "Hallo zusammen"
- Opening Hook Types (choose one):
  * Thought-provoking question: "Hast du dich jemals gefragt, warum...?"
  * Surprising fact/data: "99% der Menschen wissen nicht, dass..."
  * Counterintuitive claim: "Ganz anders als du denkst..."
  * Scene-setting: "Stell dir vor, was passieren würde, wenn..."
- Visual Techniques: Impactful visuals or data visualization to grab attention fast
- Audio Techniques: Tense, curious tone creating urgency or curiosity
- Evaluation: Hook must appear within first 3 seconds, never start with a greeting"""
        else:
            return """CONTENT TYPE: General
- Opening Strategy: Hook the audience immediately with an impactful opening — NO generic greetings like "Hello everyone"
- Opening Hook Types (choose one):
  * Thought-provoking question: "Have you ever wondered why...?"
  * Surprising fact/data: "99% of people don't know that..."
  * Counterintuitive claim: "Contrary to what you might think..."
  * Scene-setting: "Imagine what would happen if..."
- Visual Techniques: Impactful visuals or data visualization to grab attention fast
- Audio Techniques: Tense, curious tone creating urgency or curiosity
- Evaluation: Hook must appear within first 3 seconds, never start with a greeting"""


# Lazy script patterns - placeholder content that LLMs sometimes generate instead of real dialogue
_LAZY_SCRIPT_PATTERNS = [
    # Chinese lazy patterns - meta-descriptions instead of actual content
    r"这是一个.{2,10}(的)?(详细|具体|深入)?(讲解|介绍|说明|内容|分析|解读)",
    r"下面(我们)?来(详细|具体|深入)?(讲解|介绍|说明|分析|解读|看看)",
    r"接下来(让我们?)?(看看|了解|探讨|讲解|介绍|分析)",
    r"让我们(一起)?来(看看|了解|探讨|学习|分析|解读)",
    r"这里(主要)?(介绍|讲解|说明|包含|涵盖|涉及)",
    r"这(部分|个场景|一段|里).{0,5}(主要)?(是|包含|涵盖|讲解|介绍)",
    r"(本节|本场景|本段).{0,5}(主要)?(介绍|讲解|说明|涵盖)",
    # English lazy patterns
    r"this (section|part|scene|segment) (covers|contains|includes|explains|discusses)",
    r"(now |next,? )?let'?s (look at|explore|examine|dive into|see)",
    r"(here we|we will|we are going to) (cover|explore|discuss|examine|explain)",
    r"this is (a |an )?(detailed |comprehensive )?(explanation|overview|breakdown)",
]


def _is_lazy_script(script: str, language: str = None) -> bool:
    """
    Detect if a scene script is lazy/placeholder content instead of actual spoken dialogue.
    
    Args:
        script: The script content to check
        language: Language hint (optional)
        
    Returns:
        True if the script appears to be lazy placeholder content
    """
    if not script or not script.strip():
        return True
    
    script_clean = script.strip()
    script_lower = script_clean.lower()
    
    # Check minimum length - too short to be real content
    # Chinese: ~4 chars/sec, minimum 3 seconds = 12 chars (but allow very short hooks)
    # Use a conservative threshold to avoid false positives on intentionally short scenes
    if len(script_clean) < 15:
        return True
    
    # Check against known lazy patterns
    import re
    for pattern in _LAZY_SCRIPT_PATTERNS:
        if re.search(pattern, script_lower):
            # If the script is short AND matches a lazy pattern, it's lazy
            if len(script_clean) < 60:
                return True
    
    return False


def generate_multi_scene_script(
    video_content: str,
    language: str = "",
    max_scenes: int = 16,
    content_type: str = "",
    host_visible: bool = True
) -> str:
    """
    Generate multi-scene script for video.

    Args:
        video_content: The content of the video (can be a subject or full script)
        language: Language for the script
        max_scenes: Maximum number of scenes to generate
        content_type: Content type for optimized opening scene generation (optional)
                     Options: "narrative", "informative", "discussive"
        host_visible: Whether the video host appears on camera. If False, visuals
                     should focus on objects, graphics, and scenes without showing
                     the host/presenter.

    Returns:
        Multi-scene script in JSON format
    """
    logger.info(f"[LLM] generate_multi_scene_script called with host_visible={host_visible}")
    # JSON Schema definition for strict output format
    json_schema = """{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["scenes"],
  "properties": {
    "scenes": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["title", "keywords", "visual", "script", "emotion"],
        "properties": {
          "title": {"type": "string"},
          "keywords": {"type": "string"},
          "visual": {"type": "string"},
          "script": {"type": "string"},
          "emotion": {"type": "string"}
        }
      }
    }
  }
}"""

    # Few-shot examples in different languages - conditional based on host_visible
    if host_visible:
        few_shot_examples = """# Few-Shot Examples

## Example 1 (Chinese):
Input: 人工智能正在改变我们的生活方式
Output:
{"scenes":[{"title":"震撼开场","keywords":"人工智能,变革,未来","visual":"科技感十足的工作室，主持人表情严肃，背景大屏幕闪烁着数据流。运镜：快速推进到主持人面部特写。","script":"你有没有想过，未来十年，你的工作可能被一个程序完全取代？","emotion":"严肃,引人深思"},{"title":"AI应用场景","keywords":"智能家居,语音助手,自动化","visual":"特写智能音箱设备，灯光柔和闪烁，周围是现代化家居环境。运镜：缓慢平移展示智能家居全貌。","script":"从智能家居到语音助手，从自动驾驶到智能医疗，AI正在渗透到我们生活的方方面面。","emotion":"专业,讲解"},{"title":"未来展望","keywords":"发展趋势,创新,前景","visual":"主持人站在科技感背景前，屏幕显示未来城市景象。运镜：拉远镜头展示完整场景。","script":"展望未来，AI将带来更多可能性，让我们一起期待吧！","emotion":"自信,鼓舞"}]}

## Example 2 (English):
Input: The importance of healthy eating habits
Output:
{"scenes":[{"title":"Shocking Start","keywords":"health,diet,crisis","visual":"Close-up of a heart monitor beeping erratically, then cut to host in a bright kitchen. Camera: Quick zoom out from monitor to reveal host.","script":"Did you know that poor eating habits kill more people every year than smoking, accidents, and violence combined?","emotion":"serious,urgent"},{"title":"Balanced Diet","keywords":"proteins,vegetables,fruits","visual":"Close-up of colorful vegetables and fruits arranged on a kitchen counter. Camera: Slow pan across the ingredients.","script":"A balanced diet includes plenty of vegetables, fruits, lean proteins, and whole grains. These provide essential nutrients for our body.","emotion":"informative,clear"},{"title":"Healthy Lifestyle","keywords":"exercise,habit,wellness","visual":"Host in a gym setting with modern equipment. Camera: Medium shot with background blur.","script":"Remember, healthy eating combined with regular exercise creates the foundation for a wellness lifestyle.","emotion":"motivational,inspiring"}]}"""
    else:
        few_shot_examples = """# Few-Shot Examples

## Example 1 (Chinese):
Input: 人工智能正在改变我们的生活方式
Output:
{"scenes":[{"title":"震撼开场","keywords":"人工智能,变革,未来","visual":"数据流在黑色背景中快速流动，聚光灯照亮中央的AI芯片。运镜：从芯片特写快速拉远展示数据网络。","script":"就在你听这段话的这一秒钟，AI已经做出了十亿个决策——而你浑然不知。","emotion":"紧迫,震撼"},{"title":"AI应用场景","keywords":"智能家居,语音助手,自动化","visual":"特写智能音箱设备，灯光柔和闪烁，周围是现代化家居环境。运镜：缓慢平移展示智能家居全貌。","script":"从智能家居到语音助手，从自动驾驶到智能医疗，AI正在渗透到我们生活的方方面面。","emotion":"专业,讲解"},{"title":"未来展望","keywords":"发展趋势,创新,前景","visual":"科技感背景屏幕显示未来城市景象的动画。运镜：拉远镜头展示完整场景。","script":"展望未来，AI将带来更多可能性，让我们一起期待吧！","emotion":"自信,鼓舞"}]}

## Example 2 (English):
Input: The importance of healthy eating habits
Output:
{"scenes":[{"title":"Shocking Start","keywords":"health,diet,crisis","visual":"Animated infographic showing a ticking clock with food icons spinning around it. Camera: Fast zoom into the clock face.","script":"Every single meal you eat is either adding years to your life — or taking them away. Which one are you choosing?","emotion":"serious,thought-provoking"},{"title":"Balanced Diet","keywords":"proteins,vegetables,fruits","visual":"Close-up of colorful vegetables and fruits arranged on a kitchen counter. Camera: Slow pan across the ingredients.","script":"A balanced diet includes plenty of vegetables, fruits, lean proteins, and whole grains. These provide essential nutrients for our body.","emotion":"informative,clear"},{"title":"Healthy Lifestyle","keywords":"exercise,habit,wellness","visual":"Modern gym equipment with motivational graphics displayed on screens. Camera: Medium shot with background blur.","script":"Remember, healthy eating combined with regular exercise creates the foundation for a wellness lifestyle.","emotion":"motivational,inspiring"}]}"""

    # Adaptive prompts for different retry attempts
    retry_adaptive_prompts = {
        0: "",  # First attempt - no additional instruction
        1: "\n\n[REMINDER] Ensure your response is valid JSON starting with `{` and ending with `}`. Check for proper bracket matching.",
        2: "\n\n[REMINDER] JSON PARSING ERROR PREVENTION: Make sure all strings use straight quotes, no trailing commas, and all brackets are properly closed.",
        3: "\n\n[CRITICAL] Your previous responses had JSON formatting issues. Output ONLY valid JSON like this example: {\"scenes\":[{\"title\":\"...\",\"keywords\":\"...\",\"visual\":\"...\",\"script\":\"...\",\"emotion\":\"...\"}]}",
    }

    # Build base prompt
    prompt = """
# Role
You are a senior video director and storyboard designer with 10 years of experience. You excel at transforming various types of text content (whether it's informative articles, stories, or marketing copy) into visually impactful and logically coherent storyboard scripts.

# Goal
Please read the user-provided [Original Text] and adapt it into a structured multi-scene script in JSON format.

# JSON Schema (STRICT OUTPUT FORMAT)
Your output MUST conform to this JSON Schema:
{json_schema}

# Constraints & Workflow
1. **Audio-First Principle**: Audio (dialogue) is the core, and video and subtitles serve the dialogue. All visual elements and scene designs should enhance the expression of the dialogue.
2. **Semantic Scene Division**: Analyze the semantic structure of the article, identify logical turning points, and divide the content into 5-15 scenes (including opening, main body, and conclusion)
   - **Opening Scene**: MUST start with a powerful hook — NOT a generic greeting like "大家好" or "Hello everyone". Use one of: a thought-provoking question ("你有没有想过..."), a surprising fact/statistic, a bold controversial statement, or an impactful scene-setting line. Get straight to the point while grabbing attention in the first 3 seconds.
   - Each scene should have complete content and a clear theme, with logical coherence
   - Scene content should be independent and able to clearly express a complete concept or viewpoint
3. **Visual Transformation**:
   - Reject boring visuals (such as "a person speaking").
   - Must use **visual metaphors** (expressing abstract concepts with concrete objects), **dynamic graphics**, or **scene reenactment**.
   - Visual descriptions should be **pure text, concise and standard**, including: subject, environment, action, camera movement (such as close-up, push-in, pull-out).
   - Visual elements must be closely related to the dialogue content and able to enhance the expression of the dialogue.
   - **Host Visibility**: {host_visibility_instruction}
4. **Dialogue Optimization**: Rewrite the original text into natural spoken language and mark tone/emotion.
   - Dialogue content should be clear, fluent, and suitable for spoken expression
   - Emotion markers should accurately reflect the emotional tone of the dialogue
   - **Technical Content Handling**: When dealing with technical content (code, terms, symbols):
     - Replace technical terms with plain language explanations
     - Avoid directly reading code or symbols (e.g., instead of reading "#", say "hashtag")
     - Use analogies and examples to explain complex concepts
     - Keep sentences short and conversational
     - Ensure the content flows naturally when spoken aloud
5. **Keyword Extraction**: Extract 3-5 core keywords for each scene.
6. **ANTI-LAZY RULE (CRITICAL)**: Every scene's "script" field MUST contain **substantial, specific, and detailed** spoken content directly derived from the original text. Each scene script should be at least 40 characters long (for Chinese) or 80 characters long (for English).
   - **FORBIDDEN**: Placeholder sentences that describe what the scene is about instead of actual spoken content. Examples of FORBIDDEN lazy scripts:
     - "这是一个核心内容部分的详细讲解。"
     - "下面我们来详细讲解一下这个部分。"
     - "接下来让我们看看具体的内容。"
     - "This section covers the core content in detail."
     - "Now let's look at the specific content."
   - Each scene's script MUST contain real, concrete spoken words that the host would actually say — including specific facts, examples, data points, or arguments extracted from the original text.
   - If the original text has 5 key points, distribute them across scenes and write out the actual explanation for each point.

{few_shot_examples}

# CRITICAL Output Requirements
1. Return ONLY the raw JSON object, NO markdown code blocks, NO backticks, NO explanatory text
2. The response must start with `{` and end with `}` - nothing before or after
3. All string values MUST use straight double quotes (not single quotes)
4. NO trailing commas in arrays or objects
5. NO escape characters within string values (use proper JSON escaping if needed)
6. Each scene object must have ALL 5 fields: title, keywords, visual, script, emotion
7. DO NOT wrap the JSON in ```json or ``` markers - output pure JSON only
8. The scenes array must be valid and properly formatted

# Input Text
[Original Text]:
"""
    prompt += video_content
    prompt += """
"""
    prompt = prompt.strip()
    
    # Add host visibility instruction
    if host_visible:
        host_visibility_instruction = "Host is visible on camera. Include host/presenter in visual descriptions, showing facial expressions and gestures."
    else:
        host_visibility_instruction = "Host is NOT visible on camera. Do NOT include any person, host, or presenter in visual descriptions. Focus on objects, scenes, graphics, and text-based visuals only."
    
    # Replace placeholders
    prompt = prompt.replace("{json_schema}", json_schema).replace("{few_shot_examples}", few_shot_examples).replace("{host_visibility_instruction}", host_visibility_instruction)

    # Add language instruction
    if language:
        prompt += f"\n- Language: {language}\n- IMPORTANT: Please respond in {language} language. All content, including scene titles, visual descriptions, dialogue scripts, and emotion markers, must be in {language}."
    else:
        # Auto-detect language from video content
        detected_language = detect_language(video_content)
        prompt += f"\n- Language: {detected_language}\n- IMPORTANT: Please respond in {detected_language} language. All content, including scene titles, visual descriptions, dialogue scripts, and emotion markers, must be in {detected_language}."

    # Add content-type-specific opening scene guidance
    if content_type:
        content_type_guidance = _get_content_type_opening_guidance(content_type, language or detect_language(video_content))
        prompt += f"\n\n# Content-Type Specific Opening Scene Guidance\n{content_type_guidance}"

    final_script = ""
    for i in range(_max_retries):
        # Add adaptive reminder for retries
        adaptive_prompt = prompt + retry_adaptive_prompts.get(i, "")

        try:
            response = _generate_response(prompt=adaptive_prompt)

            if not response or response.strip() == "":
                logger.warning(f"LLM API returned empty response, attempt {i + 1}/{_max_retries}")
                continue

            final_script = response
            break
        except Exception as e:
            logger.error(f"failed to generate multi-scene script: {e}")

        if i < _max_retries - 1:
            logger.warning(f"failed to generate multi-scene script, trying again... {i + 1}")

    if not final_script or "Error: " in final_script:
        # Fallback: generate a simple multi-scene structure using actual content from the original text
        logger.warning("using fallback multi-scene script generation with actual content from original text")
        
        # Extract actual content from video_content for the fallback (avoid lazy placeholders)
        import re as _re
        content_clean = video_content.strip()
        # Split into sentences or paragraphs to extract real content
        sentences = [s.strip() for s in _re.split(r'[。！？.!?\n]+', content_clean) if len(s.strip()) >= 10]
        
        # Build actual script content from original text
        if len(sentences) >= 2:
            middle_script = "。".join(sentences[1:len(sentences)-1]) if len(sentences) > 2 else sentences[1]
            middle_script = middle_script[:200] + "。" if len(middle_script) > 200 else middle_script + "。"
        elif sentences:
            middle_script = sentences[0][:200] + "。"
        else:
            # No extractable sentences, use raw content
            middle_script = content_clean[:200] + "。" if len(content_clean) > 200 else content_clean + "。"
        
        # Escape quotes for JSON
        middle_script = middle_script.replace('"', '\\"').replace('\n', ' ')
        
        if host_visible:
            fallback_json = f'{{"scenes":[{{"title":"震撼开场","keywords":"hook,impact,surprise","visual":"主播表情认真，背景屏幕显示醒目的数据或画面。运镜：快速推进到主播面部特写。","script":"你知道吗？接下来我要告诉你的这件事，可能会彻底改变你的看法。","emotion":"严肃,引人入胜"}},{{"title":"核心内容","keywords":"core content,explanation,details","visual":"特写屏幕上的相关内容，配合动态图形展示关键信息。运镜：平移镜头，展示不同的视觉元素。","script":"{middle_script}","emotion":"专业,清晰"}},{{"title":"总结收尾","keywords":"conclusion,summary,closing","visual":"回到主播画面，主播面带微笑，背景屏幕显示总结要点。运镜：拉远镜头，展示完整的工作室环境。","script":"希望今天的分享对大家有所帮助，谢谢大家的观看！","emotion":"自信,鼓舞"}}]}}'
        else:
            fallback_json = f'{{"scenes":[{{"title":"震撼开场","keywords":"hook,impact,surprise","visual":"大屏幕显示醒目的数据或画面，聚光灯聚焦到主题文字。运镜：快速推进到屏幕特写。","script":"就在你看到这段话的这一刻，世界上正在发生一件你可能完全不知道的事。","emotion":"紧迫,震撼"}},{{"title":"核心内容","keywords":"core content,explanation,details","visual":"特写屏幕上的相关内容，配合动态图形展示关键信息。运镜：平移镜头，展示不同的视觉元素。","script":"{middle_script}","emotion":"专业,清晰"}},{{"title":"总结收尾","keywords":"conclusion,summary,closing","visual":"屏幕显示总结要点，背景是现代化的办公环境。运镜：拉远镜头，展示完整场景。","script":"希望今天的分享对大家有所帮助，谢谢大家的观看！","emotion":"自信,鼓舞"}}]}}'
        return fallback_json
    else:
        logger.success(f"completed multi-scene script generation: \n{final_script}")

    return final_script.strip()


def parse_multi_scene_script(script_text: str) -> List[Dict]:
    """
    Parse multi-scene script text into structured data.
    
    Input format can be either:
    1. JSON format with scenes array
    2. Text format with scene sections
    
    Args:
        script_text: Multi-scene script text (JSON or text format)
    
    Returns:
        List of scene dictionaries with structure:
        [
            {
                "id": "scene_1",
                "title": "场景核心主题",
                "visual": "视觉描述",
                "audio": "口播文案",
                "emotion": "情绪标注",
                "script": "完整脚本",
                "keywords": "关键词"
            },
            ...
        ]
    """
    import re
    import json
    
    scenes = []
    scene_id = 1
    
    # 首先尝试解析JSON格式
    try:
        logger.info("Attempting to parse JSON format")
        cleaned_script = script_text.strip()
        
        if not cleaned_script:
            logger.warning("Empty script text provided, falling back to text parsing")
            raise ValueError("Empty script text")
        
        if cleaned_script.startswith('```json') and cleaned_script.endswith('```'):
            cleaned_script = cleaned_script[7:-3].strip()
        elif cleaned_script.startswith('```') and cleaned_script.endswith('```'):
            cleaned_script = cleaned_script[3:-3].strip()
        
        cleaned_script = cleaned_script.strip()
        
        if cleaned_script and (not cleaned_script.startswith('{') or not cleaned_script.endswith('}')):
            start_idx = cleaned_script.find('{')
            end_idx = cleaned_script.rfind('}')
            if start_idx != -1 and end_idx != -1:
                cleaned_script = cleaned_script[start_idx:end_idx+1]
        
        data = json.loads(cleaned_script)
        if "scenes" in data and isinstance(data["scenes"], list):
            for i, scene_data in enumerate(data["scenes"]):
                visual_content = scene_data.get("visual", "")
                if not visual_content or visual_content.strip() == "":
                    logger.warning(f"Scene {scene_id} parsed with empty visual requirements from LLM response")
                
                scene = {
                    "id": f"scene_{scene_id}",
                    "title": scene_data.get("title", f"Scene {scene_id}"),
                    "visual": visual_content,
                    "audio": scene_data.get("script", ""),
                    "emotion": scene_data.get("emotion", ""),
                    "script": scene_data.get("script", ""),  # 保持与原有结构兼容
                    "camera": visual_content,  # 保持与原有结构兼容
                    "keywords": scene_data.get("keywords", ""),  # 新增关键词字段
                    "start_time": scene_id * 10,  # 保持与原有结构兼容
                    "end_time": (scene_id + 1) * 10,  # 保持与原有结构兼容
                    "full_script": f"###  Scene {scene_id}: {scene_data.get('title', f'Scene {scene_id}')}\n- **Core Keywords**：{scene_data.get('keywords', '')}\n- **Visual (Visual Elements)**：\n{visual_content}\n- **Audio (Dialogue Script)**：\n[{scene_data.get('emotion', '')}] {scene_data.get('script', '')}"
                }
                scenes.append(scene)
                scene_id += 1
            logger.info(f"Successfully parsed {len(scenes)} scenes from JSON format")
            
            # 限制场景数量在合理范围内 (3-16)
            max_scenes = 16
            min_scenes = 3
            if len(scenes) > max_scenes:
                logger.warning(f"Found {len(scenes)} scenes, limiting to {max_scenes} scenes")
                scenes = scenes[:max_scenes]
            elif len(scenes) < min_scenes:
                logger.warning(f"Found {len(scenes)} scenes, which is less than the recommended minimum of {min_scenes} scenes")
            
            return scenes
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parsing failed: {e}, falling back to text parsing")
    except Exception as e:
        logger.warning(f"Error parsing JSON: {e}, falling back to text parsing")
    
    # JSON解析失败，尝试使用原来的文本解析
    logger.info("Falling back to text format parsing")
    
    # 首先尝试匹配新格式
    scene_pattern = r'###\s*Scene\s*(\d+):\s*([^\n]+)\s*-\s*\*\*Core Keywords\*\*：\s*([^\n]+)\s*-\s*\*\*Visual \(Visual Elements\)\*\*：\s*([\s\S]*?)\s*-\s*\*\*Audio \(Dialogue Script\)\*\*：\s*([\s\S]*?)(?=###\s*Scene|$)'
    matches = re.findall(scene_pattern, script_text, re.DOTALL)
    
    if matches:
        for match in matches:
            scene_num, title, keywords, visual, audio = match
            
            # 提取情绪标注
            emotion_match = re.search(r'\[(.*?)\]', audio)
            emotion = emotion_match.group(1) if emotion_match else ""
            
            # 清理音频文本
            clean_audio = re.sub(r'\[.*?\]\s*', '', audio).strip()
            
            # 清理视觉文本
            clean_visual = visual.strip()
            
            # 清理关键词
            clean_keywords = keywords.strip()
            
            scene = {
                "id": f"scene_{scene_id}",
                "title": title.strip(),
                "visual": clean_visual,
                "audio": clean_audio,
                "emotion": emotion,
                "script": clean_audio,  # 保持与原有结构兼容
                "camera": clean_visual,  # 保持与原有结构兼容
                "keywords": clean_keywords,  # 新增关键词字段
                "start_time": scene_id * 10,  # 保持与原有结构兼容
                "end_time": (scene_id + 1) * 10,  # 保持与原有结构兼容
                "full_script": f"###  Scene {scene_num}: {title}\n- **Core Keywords**：{keywords}\n- **Visual (Visual Elements)**：\n{visual}\n- **Audio (Dialogue Script)**：\n{audio}"
            }
            scenes.append(scene)
            scene_id += 1
    else:
        # 尝试匹配旧格式
        old_scene_pattern = r'###\s*Scene\s*(\d+):\s*([^\n]+)\s*-\s*\*\*Visual \(Visual Elements\)\*\*：\s*([\s\S]*?)\s*-\s*\*\*Audio \(Dialogue Script\)\*\*：\s*([\s\S]*?)(?=###\s*Scene|$)'
        old_matches = re.findall(old_scene_pattern, script_text, re.DOTALL)
        
        if old_matches:
            for match in old_matches:
                scene_num, title, visual, audio = match
                
                # 提取情绪标注
                emotion_match = re.search(r'\[(.*?)\]', audio)
                emotion = emotion_match.group(1) if emotion_match else ""
                
                # 清理音频文本
                clean_audio = re.sub(r'\[.*?\]\s*', '', audio).strip()
                
                # 清理视觉文本
                clean_visual = visual.strip()
                
                scene = {
                    "id": f"scene_{scene_id}",
                    "title": title.strip(),
                    "visual": clean_visual,
                    "audio": clean_audio,
                    "emotion": emotion,
                    "script": clean_audio,  # 保持与原有结构兼容
                    "camera": clean_visual,  # 保持与原有结构兼容
                    "keywords": "",  # 旧格式没有关键词
                    "start_time": scene_id * 10,  # 保持与原有结构兼容
                    "end_time": (scene_id + 1) * 10,  # 保持与原有结构兼容
                    "full_script": f"###  Scene {scene_num}: {title}\n- **Visual (Visual Elements)**：\n{visual}\n- **Audio (Dialogue Script)**：\n{audio}"
                }
                scenes.append(scene)
                scene_id += 1
        else:
            # 处理混合格式的情况 - 直接基于场景标记分割
            # 首先清理脚本，移除多余的Markdown标记
            cleaned_script = script_text.replace('*', '').replace('#', '')
            
            # 按场景标记分割
            scene_markers = re.split(r'###\s*(?:Scene|场景)\s*(\d+)', cleaned_script)
            
            for i in range(1, len(scene_markers), 2):
                scene_num = scene_markers[i]
                scene_content = scene_markers[i+1]
                
                # 提取标题
                title_match = re.search(r'[:：]\s*([^\n]+)', scene_content)
                title = title_match.group(1).strip() if title_match else f"Scene {scene_num}"
                
                # 提取视觉需求 - 查找包含视觉元素的部分
                visual_match = re.search(r'(?:Visual|视觉).*?:\s*([\s\S]*?)(?:Audio|Audio|口播|$)', scene_content, re.IGNORECASE)
                visual = visual_match.group(1).strip() if visual_match else ""
                
                # 提取音频/口播内容
                audio_match = re.search(r'(?:Audio|口播).*?:\s*([\s\S]*?)(?=###|$)', scene_content, re.IGNORECASE)
                audio = audio_match.group(1).strip() if audio_match else ""
                
                # 提取情绪标注
                emotion_match = re.search(r'\[(.*?)\]', audio)
                emotion = emotion_match.group(1) if emotion_match else ""
                
                # 清理音频文本
                clean_audio = re.sub(r'\[.*?\]\s*', '', audio).strip()
                
                # 清理视觉文本
                clean_visual = visual.strip()
                
                # 提取关键词
                keywords_match = re.search(r'(?:Core Keywords|核心关键词).*?:\s*([^\n]+)', scene_content, re.IGNORECASE)
                keywords = keywords_match.group(1).strip() if keywords_match else ""
                
                scene = {
                    "id": f"scene_{scene_id}",
                    "title": title,
                    "visual": clean_visual,
                    "audio": clean_audio,
                    "emotion": emotion,
                    "script": clean_audio,  # 保持与原有结构兼容
                    "camera": clean_visual,  # 保持与原有结构兼容
                    "keywords": keywords,  # 关键词字段
                    "start_time": scene_id * 10,  # 保持与原有结构兼容
                    "end_time": (scene_id + 1) * 10,  # 保持与原有结构兼容
                    "full_script": f"###  Scene {scene_num}: {title}\n- **Visual (Visual Elements)**：\n{visual}\n- **Audio (Dialogue Script)**：\n{audio}"
                }
                scenes.append(scene)
                scene_id += 1
    
    # 如果仍然没有匹配到场景，创建一个默认场景
    if not scenes:
        # 清理脚本内容
        cleaned_content = script_text.replace('*', '').replace('#', '').strip()
        
        # 创建默认场景
        scene = {
            "id": "scene_1",
            "title": "Default Scene",
            "visual": "Default visual requirements",
            "audio": cleaned_content,
            "emotion": "",
            "script": cleaned_content,
            "camera": "Default visual requirements",
            "keywords": "",
            "start_time": 0,
            "end_time": 10,
            "full_script": cleaned_content
        }
        scenes.append(scene)
    
    # 限制场景数量在合理范围内 (3-16)
    max_scenes = 16
    min_scenes = 3
    if len(scenes) > max_scenes:
        logger.warning(f"Found {len(scenes)} scenes, limiting to {max_scenes} scenes")
        scenes = scenes[:max_scenes]
    elif len(scenes) < min_scenes:
        logger.warning(f"Found {len(scenes)} scenes, which is less than the recommended minimum of {min_scenes} scenes")
    
    logger.info(f"parsed {len(scenes)} scenes from multi-scene script")
    return scenes


def convert_to_multi_scene(
    video_script: str,
    video_subject: str = "",
    language: str = None,
    content_type: str = "",
    host_visible: bool = True
) -> str:
    """
    Convert single-scene script to multi-scene format.
    
    Args:
        video_script: Single-scene script text
        video_subject: Video subject for context
        language: Language for the generated script
        content_type: Content type for optimized opening scene generation (optional)
                     Options: "narrative", "informative", "discussive"
        host_visible: Whether the video host appears on camera. If False, visuals
                     should focus on objects, graphics, and scenes without showing
                     the host/presenter.
    
    Returns:
        Multi-scene script text with visual descriptions, camera movements, and emotion annotations
    """
    logger.info(f"[LLM] convert_to_multi_scene called with host_visible={host_visible}")
    
    # Host visibility instruction
    host_visibility_instruction = "Host is visible on camera. Include host/presenter in visual descriptions, showing facial expressions and gestures." if host_visible else "Host is NOT visible on camera. Do NOT include any person, host, or presenter in visual descriptions. Focus on objects, scenes, graphics, and text-based visuals only."
    
    prompt = f"""
# Role
You are a senior video director and storyboard designer with 10 years of experience. You excel at transforming various types of text content (whether it's informative articles, stories, or marketing copy) into visually impactful and logically coherent storyboard scripts.

# Goal
Please read the user-provided [Original Text] and adapt it into a standardized **scene-based storyboard script**.

# Constraints & Workflow
1. **Audio-First Principle**: Audio (dialogue) is the core, and video and subtitles serve the dialogue. All visual elements and scene designs should enhance the expression of the dialogue.
2. **Semantic Scene Division**: Analyze the semantic structure of the article, identify logical turning points, and divide the content into 5-15 scenes (including opening, main body, and conclusion)
   - **Opening Scene**: MUST start with a powerful hook — NOT a generic greeting like "大家好" or "Hello everyone". Use one of: a thought-provoking question ("你有没有想过..."), a surprising fact/statistic, a bold controversial statement, or an impactful scene-setting line. Get straight to the point while grabbing attention in the first 3 seconds.
   - Each scene should have complete content and a clear theme, with logical coherence
   - Scene content should be independent and able to clearly express a complete concept or viewpoint
3. **Visual Transformation**:
    - Reject boring visuals (such as "a person speaking").
    - Must use **visual metaphors** (expressing abstract concepts with concrete objects), **dynamic graphics**, or **scene reenactment**.
    - Visual descriptions should be **pure text, concise and standard**, including: subject, environment, action, camera movement (such as close-up, push-in, pull-out).
    - Visual elements must be closely related to the dialogue content and able to enhance the expression of the dialogue.
    - **Host Visibility**: {host_visibility_instruction}
    - **Format Requirements**: Use clear, straightforward language without special formatting or markers.
4. **Dialogue Optimization**: Rewrite the original text into natural spoken language and mark tone/emotion.
   - Dialogue content should be clear, fluent, and suitable for spoken expression
   - Emotion markers should accurately reflect the emotional tone of the dialogue
   - **Technical Content Handling**: When dealing with technical content (code, terms, symbols):
     - Replace technical terms with plain language explanations
     - Avoid directly reading code or symbols (e.g., instead of reading "#", say "hashtag")
     - Use analogies and examples to explain complex concepts
     - Keep sentences short and conversational
     - Ensure the content flows naturally when spoken aloud
5. **Keyword Extraction**: Extract 3-5 core keywords for each scene.
6. **ANTI-LAZY RULE (CRITICAL)**: Every scene's dialogue (Audio) field MUST contain **substantial, specific, and detailed** spoken content directly derived from the original text. Each scene dialogue should be at least 40 characters long (for Chinese) or 80 characters long (for English).
   - **FORBIDDEN**: Placeholder sentences that describe what the scene is about instead of actual spoken content. Examples of FORBIDDEN lazy scripts:
     - "这是一个核心内容部分的详细讲解。"
     - "下面我们来详细讲解一下这个部分。"
     - "接下来让我们看看具体的内容。"
     - "This section covers the core content in detail."
     - "Now let's look at the specific content."
   - Each scene's dialogue MUST contain real, concrete spoken words that the host would actually say — including specific facts, examples, data points, or arguments extracted from the original text.
   - If the original text has 5 key points, distribute them across scenes and write out the actual explanation for each point.
7. **Format Enforcement**: **Must** strictly follow the [Output Template] format below, without arbitrarily adding or removing fields.

# Output Template (Please strictly follow this format)

###  Scene [Number]: [Scene Core Theme]
- **Core Keywords**: Keyword 1, Keyword 2, Keyword 3
- **Visual (Visual Elements)**:
    - **Visual Element 1**: Detailed description
    - **Visual Element 2**: Detailed description
- **Audio (Dialogue Script)**:
    - ([Emotion Marker]) Dialogue content

# Few-Shot Example (Reference Example)
*If the input is "Procrastination is because the brain is avoiding pain", the output should include:*
###  Scene 1: The Instinct to Avoid Pain
- **Core Keywords**: Monkey, Steering Wheel, Chaos
- **Visual (Visual Elements)**:
    - **Visual Contrast**: On the left side of the screen, a happy little monkey doll is grabbing the steering wheel, while on the right side, a rational helmsman (human) is tied to a pole. The background is a chaotic amusement park.
    - **Camera Movement**: Quick push-pull to express a sense of chaos.
- **Audio (Dialogue Script)**:
    - ([Vivid, Metaphorical]) Procrastination is not actually a time management issue, but an emotional management issue. It's like having a monkey in your brain that grabs the steering wheel...

# Input Text
[Original Text]:
{video_script}
""".strip()

    if language:
        prompt += f"\n- Language: {language}\n- IMPORTANT: Please respond in {language} language. All content, including scene titles, visual descriptions, dialogue scripts, and emotion markers, must be in {language}."

    # Add content-type-specific opening scene guidance
    if content_type:
        content_type_guidance = _get_content_type_opening_guidance(content_type, language or "English")
        prompt += f"\n\n# Content-Type Specific Opening Scene Guidance\n{content_type_guidance}"

    logger.info("converting single-scene script to multi-scene format")
    
    final_script = ""
    for i in range(_max_retries):
        try:
            response = _generate_response(prompt=prompt)
            if response:
                final_script = response
                # Clean up the script
                final_script = final_script.replace("*", "")
                final_script = final_script.replace("#", "")
                break
        except Exception as e:
            logger.error(f"failed to convert script: {e}")
        
        if i < _max_retries - 1:
            logger.warning(f"failed to convert script, trying again... {i + 1}")
    
    if not final_script or "Error: " in final_script:
        # Check if we should stop on API failure
        if stop_on_api_failure:
            error_msg = f"LLM API failed to convert script after {_max_retries} attempts"
            logger.error(error_msg)
            return f"Error: {error_msg}"
        
        # Fallback: create a simple multi-scene structure from original script
        logger.warning("using fallback script conversion")
        
        # Host visibility for fallback
        host_visual_1 = "主播站在明亮的工作室中，背景是现代化的办公环境，前方有一个大屏幕显示主题。\n    - 运镜：从远到近的推镜头，聚焦到主播面部表情。" if host_visible else "现代化工作室的全景，大屏幕显示主题内容。\n    - 运镜：从远到近的推镜头，聚焦到屏幕上的主题文字。"
        host_visual_3 = "回到主播画面，主播面带微笑，背景屏幕显示总结要点。\n    - 运镜：拉远镜头，展示完整的工作室环境。" if host_visible else "屏幕显示总结要点，背景是现代化的办公环境。\n    - 运镜：拉远镜头，展示完整场景。"
        
        # Split the script into 3 parts
        script_lines = video_script.split('\n')
        total_lines = len(script_lines)
        
        if total_lines <= 1:
            # Very short script, create minimal structure
            fallback_script = f"###  场景 1：震撼开场\n- **Visual (画面视觉)**：\n    - {host_visual_1}\n- **Audio (口播文案)**：\n    - ([严肃、引人入胜]) {video_script}\n\n###  场景 2：核心内容\n- **Visual (画面视觉)**：\n    - 特写屏幕上的相关内容，配合动态图形展示关键信息。\n    - 运镜：平移镜头，展示不同的视觉元素。\n- **Audio (口播文案)**：\n    - ([专业、清晰]) {video_script}\n\n###  场景 3：总结收尾\n- **Visual (画面视觉)**：\n    - {host_visual_3}\n- **Audio (口播文案)**：\n    - ([自信、鼓舞]) {video_script}"
        else:
            # Split into 3 roughly equal parts
            part1_end = total_lines // 3
            part2_end = 2 * (total_lines // 3)
            
            part1 = '\n'.join(script_lines[:part1_end])
            part2 = '\n'.join(script_lines[part1_end:part2_end])
            part3 = '\n'.join(script_lines[part2_end:])
            
            fallback_script = f"###  场景 1：震撼开场\n- **Visual (画面视觉)**：\n    - {host_visual_1}\n- **Audio (口播文案)**：\n    - ([严肃、引人入胜]) {part1}\n\n###  场景 2：核心内容\n- **Visual (画面视觉)**：\n    - 特写屏幕上的相关内容，配合动态图形展示关键信息。\n    - 运镜：平移镜头，展示不同的视觉元素。\n- **Audio (口播文案)**：\n    - ([专业、清晰]) {part2}\n\n###  场景 3：总结收尾\n- **Visual (画面视觉)**：\n    - {host_visual_3}\n- **Audio (口播文案)**：\n    - ([自信、鼓舞]) {part3}"
        return fallback_script
    else:
        logger.success(f"completed script conversion: \n{final_script}")
    
    return final_script.strip()


def update_scenes_visuals(
    scenes: List[dict],
    host_visible: bool = True,
    language: str = "zh"
) -> List[dict]:
    """
    Update existing scenes' visual descriptions based on host_visible setting.
    If host_visible is False, ensure visuals don't include host/person.
    If host_visible is True, add appropriate host visuals.

    Args:
        scenes: List of existing scene dictionaries
        host_visible: Whether the video host appears on camera
        language: Language for the visual descriptions

    Returns:
        List of updated scene dictionaries with revised visuals
    """
    logger.info(f"Updating scenes based on host_visible: {host_visible}")

    # Host visibility instruction for prompt
    host_visibility_instruction = (
        "Host is visible on camera. Include host/presenter in visual descriptions, showing facial expressions and gestures."
        if host_visible
        else "Host is NOT visible on camera. Do NOT include any person, host, or presenter in visual descriptions. Focus on objects, scenes, graphics, and text-based visuals only."
    )

    # Convert scenes to JSON for LLM processing
    scenes_json = json.dumps(scenes, ensure_ascii=False)

    prompt = f"""
# Role: Scene Visual Updater
You are a senior video director and storyboard designer.

# Goal
Update the visual descriptions (camera/visual field) of provided scenes based on the host visibility requirement.

# Host Visibility Requirement
{host_visibility_instruction}

# Constraints
1. Keep all scene titles, scripts, keywords, and emotions unchanged
2. Only update the visual/camera descriptions
3. Maintain the same number of scenes
4. Visual descriptions should be:
   - Clear and concise
   - Include subject, environment, action, and camera movement
   - Closely related to the scene's content
5. Return ONLY the updated scenes in valid JSON format, nothing else

# Original Scenes (JSON):
{scenes_json}

Please update the visual/camera descriptions according to the host visibility requirement and return the scenes JSON in the same structure.
""".strip()

    updated_scenes = None
    for i in range(_max_retries):
        try:
            response = _generate_response(prompt=prompt)
            if response:
                # Try to parse the response
                updated_scenes = parse_multi_scene_script(response)
                if updated_scenes and len(updated_scenes) > 0:
                    logger.success(f"Successfully updated {len(updated_scenes)} scenes visuals")
                    break
        except Exception as e:
            logger.error(f"Failed to update scenes visuals: {e}")

        if i < _max_retries - 1:
            logger.warning(f"Failed to update scenes visuals, trying again... {i + 1}")

    # If we couldn't update via LLM, try simple keyword replacement
    if not updated_scenes or len(updated_scenes) != len(scenes):
        logger.warning("Falling back to simple keyword replacement for scene visuals")
        updated_scenes = []
        for scene in scenes:
            updated_scene = scene.copy()
            visual = scene.get('visual', scene.get('camera', ''))

            if not host_visible:
                # Remove host/person keywords from visual
                keywords_to_remove = ['主持人', '主播', 'host', 'presenter', 'person', '人物', '他', '她', 'them']
                for keyword in keywords_to_remove:
                    visual = visual.replace(keyword, '')

                # Replace host-specific visuals with object/scene-focused alternatives
                replacements = {
                    '主持人站在': '展示',
                    '主播': '屏幕',
                    'host standing': 'displaying',
                    'presenter': 'graphics',
                }
                for old, new in replacements.items():
                    if old in visual:
                        visual = visual.replace(old, new)

            updated_scene['visual'] = visual.strip()
            if 'camera' in updated_scene:
                updated_scene['camera'] = visual.strip()
            updated_scenes.append(updated_scene)

    return updated_scenes


def generate_scene_terms(
    video_subject: str,
    scene_script: str,
    scene_camera: str,
    amount: int = 5
) -> List[str]:
    """
    Generate search terms for a specific scene.
    Generate terms in the same language as the scene script.
    English translations will be added during video search.

    Args:
        video_subject: Overall video subject
        scene_script: Script for this specific scene
        scene_camera: Camera/visual description for this scene
        amount: Number of terms to generate

    Returns:
        List of search terms in the original language
    """
    prompt = f"""
# Role: Scene-Specific Video Search Terms Generator

## Goals:
Generate {amount} search terms for stock videos for a specific scene.

## Constraints:
1. The search terms should be relevant to both the scene's visual description and narration
2. Each search term should consist of 1-3 words
3. You must only return the JSON array of strings
4. Generate search terms in the same language as the scene script
5. Focus on visual elements mentioned in the camera description
6. Always include keywords related to the overall video subject to maintain consistency across scenes

## Output Example:
["城市夜景", "摩天大楼", "都市生活", "繁华街道", "现代建筑"]

## Context:
### Video Subject
{video_subject}

### Scene Camera/Visual Description
{scene_camera}

### Scene Script
{scene_script}

Please generate search terms in the same language as the scene script.
""".strip()

    logger.info(f"generating terms for scene")

    search_terms = []
    response = ""
    for i in range(_max_retries):
        try:
            response = _generate_response(prompt)
            
            if not response or response.strip() == "":
                logger.warning(f"LLM API returned empty response, attempt {i + 1}/{_max_retries}")
                continue
                
            if "Error: " in response:
                logger.error(f"failed to generate scene terms: {response}")
                if stop_on_api_failure:
                    return f"Error: {response}"
                continue
            search_terms = json.loads(response)
            if not isinstance(search_terms, list) or not all(
                isinstance(term, str) for term in search_terms
            ):
                logger.error("response is not a list of strings.")
                continue
        except Exception as e:
            logger.warning(f"failed to generate scene terms: {str(e)}")
            if stop_on_api_failure:
                error_msg = f"LLM API failed to generate scene terms after {_max_retries} attempts: {str(e)}"
                logger.error(error_msg)
                return f"Error: {error_msg}"
            if response:
                match = re.search(r'\[.*]', response)
                if match:
                    try:
                        search_terms = json.loads(match.group())
                    except Exception as e:
                        logger.warning(f"failed to parse scene terms: {str(e)}")
                        pass

        if search_terms and len(search_terms) > 0:
            break
        if i < _max_retries - 1:
            logger.warning(f"failed to generate scene terms, trying again... {i + 1}")

    if not search_terms and stop_on_api_failure:
        error_msg = f"LLM API failed to generate scene terms after {_max_retries} attempts"
        logger.error(error_msg)
        return f"Error: {error_msg}"

    logger.success(f"completed scene terms: {search_terms}")
    return search_terms


def add_english_translations(terms: List[str]) -> List[str]:
    """
    For non-English terms, add English translations to maximize video search coverage.

    Args:
        terms: List of search terms (may contain any language)

    Returns:
        List of terms with English translations added for non-English terms
    """
    if not terms:
        return terms

    # Check if terms are already in English
    def is_english_term(term: str) -> bool:
        """Check if a term is primarily English (ASCII characters)."""
        if not term:
            return True
        # Count non-ASCII characters
        non_ascii_count = sum(1 for char in term if ord(char) > 127)
        # If more than 30% non-ASCII, consider it non-English
        return non_ascii_count / len(term) < 0.3

    # Separate English and non-English terms
    english_terms = [t for t in terms if is_english_term(t)]
    non_english_terms = [t for t in terms if not is_english_term(t)]

    if not non_english_terms:
        # All terms are already in English
        return terms

    # Generate English translations for non-English terms
    translations = []
    try:
        terms_str = ", ".join([f'"{t}"' for t in non_english_terms])
        prompt = f"""
Translate the following search terms to English for video search purposes.
Return ONLY a JSON array with the English translations in the same order.

Terms to translate:
[{terms_str}]

Requirements:
1. Each translation should be 1-3 words
2. Use common video search keywords
3. Return ONLY the JSON array, no other text

Example output:
["city night view", "skyscraper", "urban life"]
""".strip()

        response = _generate_response(prompt)
        if "Error: " not in response:
            try:
                translations = json.loads(response)
                if not isinstance(translations, list):
                    translations = []
            except:
                # Try to extract array from response
                match = re.search(r'\[.*]', response)
                if match:
                    try:
                        translations = json.loads(match.group())
                    except:
                        translations = []
    except Exception as e:
        logger.warning(f"Failed to generate translations: {str(e)}")
        translations = []

    # Combine original terms with English translations
    final_terms = list(terms)  # Keep original terms
    if translations and len(translations) == len(non_english_terms):
        final_terms.extend(translations)
        logger.info(f"Added English translations: {translations}")
    else:
        logger.warning(f"Translation mismatch: expected {len(non_english_terms)}, got {len(translations)}")

    return final_terms


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
    
