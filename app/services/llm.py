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

        return content.replace("\n", "")
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


def generate_tags(scene_script: str, max_tags: int = 3) -> List[str]:
    """
    Generate 1-3 tags for a scene based on its script content.
    
    Args:
        scene_script: Scene script text
        max_tags: Maximum number of tags to generate
        
    Returns:
        List of generated tags
    """
    prompt = f"""
    # Role: Scene Tag Generator
    
    ## Goals:
    Generate {max_tags} relevant tags for a video scene based on its script content.
    
    ## Constrains:
    1. The tags are to be returned as a json-array of strings.
    2. Each tag should be a single word or short phrase (1-3 words).
    3. The tags must be directly related to the content of the scene.
    4. You must only return the json-array of strings. You must not return anything else.
    5. Respond in the same language as the scene script.
    
    ## Output Example:
    ["tag1", "tag2", "tag3"]
    
    ## Context:
    ### Scene Script
    {scene_script}
    """.strip()
    
    logger.info(f"Generating tags for scene script: {scene_script[:50]}...")
    
    tags = []
    response = ""
    for i in range(_max_retries):
        try:
            response = _generate_response(prompt)
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


def generate_multi_scene_script(
    video_content: str,
    language: str = "",
    max_scenes: int = 12
) -> str:
    """
    Generate multi-scene script for video.
    
    Args:
        video_content: The content of the video (can be a subject or full script)
        language: Language for the script
        max_scenes: Maximum number of scenes to generate
    
    Returns:
        Multi-scene script in JSON format
    """
    # 构建提示词，避免f-string解析错误
    prompt = """
# Role
You are a senior video director and storyboard designer with 10 years of experience. You excel at transforming various types of text content (whether it's informative articles, stories, or marketing copy) into visually impactful and logically coherent storyboard scripts.

# Goal
Please read the user-provided [Original Text] and adapt it into a structured multi-scene script in JSON format.

# Constraints & Workflow
1. **Audio-First Principle**: Audio (dialogue) is the core, and video and subtitles serve the dialogue. All visual elements and scene designs should enhance the expression of the dialogue.
2. **Semantic Scene Division**: Analyze the semantic structure of the article, identify logical turning points, and divide the content into 5-15 scenes (including opening, main body, and conclusion)
   - **Opening Scene**: Should include natural greetings and background introduction, avoid directly entering the topic to make the video start more smoothly
   - Each scene should have complete content and a clear theme, with logical coherence
   - Scene content should be independent and able to clearly express a complete concept or viewpoint
3. **Visual Transformation**:
    - Reject boring visuals (such as "a person speaking").
    - Must use **visual metaphors** (expressing abstract concepts with concrete objects), **dynamic graphics**, or **scene reenactment**.
    - Visual descriptions should be **pure text, concise and standard**, including: subject, environment, action, camera movement (such as close-up, push-in, pull-out).
    - Visual elements must be closely related to the dialogue content and able to enhance the expression of the dialogue.
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

# Output Format
Please return a JSON object with the following structure:
{
  "scenes": [
    {
      "title": "Scene title",
      "keywords": "keyword1, keyword2, keyword3",
      "visual": "Detailed visual requirements including subject, environment, action, and camera movement",
      "script": "Dialogue script",
      "emotion": "Emotion annotation"
    }
  ]
}

# Requirements
1. Return only the JSON, no other text
2. Ensure the JSON is valid and properly formatted
3. Include 5-15 scenes
4. Each scene must have all required fields
5. Visual descriptions must be detailed and specific

# Input Text
[Original Text]:
"""
    prompt += video_content
    prompt += """
"""
    prompt = prompt.strip()
    
    if language:
        prompt += f"\n- Language: {language}\n- IMPORTANT: Please respond in {language} language. All content, including scene titles, visual descriptions, dialogue scripts, and emotion markers, must be in {language}."
    else:
        # Auto-detect language from video content
        detected_language = detect_language(video_content)
        prompt += f"\n- Language: {detected_language}\n- IMPORTANT: Please respond in {detected_language} language. All content, including scene titles, visual descriptions, dialogue scripts, and emotion markers, must be in {detected_language}."

    logger.info(f"generating multi-scene script for content: {video_content}")
    
    final_script = ""
    for i in range(_max_retries):
        try:
            response = _generate_response(prompt=prompt)
            if response:
                final_script = response
                break
        except Exception as e:
            logger.error(f"failed to generate multi-scene script: {e}")
        
        if i < _max_retries - 1:
            logger.warning(f"failed to generate multi-scene script, trying again... {i + 1}")
    
    if not final_script or "Error: " in final_script:
        # Fallback: generate a simple multi-scene structure in JSON
        logger.warning("using fallback multi-scene script generation")
        fallback_json = f"{{\n  \"scenes\": [\n    {{\n      \"title\": \"开场引入\",\n      \"keywords\": \"introduction, greeting, overview\",\n      \"visual\": \"主播站在明亮的工作室中，背景是现代化的办公环境，前方有一个大屏幕显示主题。运镜：从远到近的推镜头，聚焦到主播面部表情。\",\n      \"script\": \"各位朋友们，今天我要和大家分享一个关于设计模式的重要话题。\",\n      \"emotion\": \"热情、亲切\"\n    }},\n    {{\n      \"title\": \"核心内容\",\n      \"keywords\": \"core content, explanation, details\",\n      \"visual\": \"特写屏幕上的相关内容，配合动态图形展示关键信息。运镜：平移镜头，展示不同的视觉元素。\",\n      \"script\": \"设计模式是软件开发中的重要概念，它提供了一套解决常见问题的最佳实践。\",\n      \"emotion\": \"专业、清晰\"\n    }},\n    {{\n      \"title\": \"总结收尾\",\n      \"keywords\": \"conclusion, summary, closing\",\n      \"visual\": \"回到主播画面，主播面带微笑，背景屏幕显示总结要点。运镜：拉远镜头，展示完整的工作室环境。\",\n      \"script\": \"希望今天的分享对大家有所帮助，谢谢大家的观看！\",\n      \"emotion\": \"自信、鼓舞\"\n    }}\n  ]\n}}"
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
        # 处理Markdown代码块标记
        cleaned_script = script_text.strip()
        # 移除可能的Markdown代码块标记
        if cleaned_script.startswith('```json') and cleaned_script.endswith('```'):
            # 处理```json和{之间没有空格的情况
            cleaned_script = cleaned_script[7:-3].strip()
        elif cleaned_script.startswith('```') and cleaned_script.endswith('```'):
            # 处理```和{之间没有空格的情况
            cleaned_script = cleaned_script[3:-3].strip()
        # 进一步清理，确保JSON格式正确
        # 移除可能的前导和尾随字符
        cleaned_script = cleaned_script.strip()
        # 确保JSON以{开头，以}结尾
        if cleaned_script and (not cleaned_script.startswith('{') or not cleaned_script.endswith('}')):
            # 尝试找到JSON的开始和结束位置
            start_idx = cleaned_script.find('{')
            end_idx = cleaned_script.rfind('}')
            if start_idx != -1 and end_idx != -1:
                cleaned_script = cleaned_script[start_idx:end_idx+1]
        
        data = json.loads(cleaned_script)
        if "scenes" in data and isinstance(data["scenes"], list):
            for i, scene_data in enumerate(data["scenes"]):
                scene = {
                    "id": f"scene_{scene_id}",
                    "title": scene_data.get("title", f"Scene {scene_id}"),
                    "visual": scene_data.get("visual", ""),
                    "audio": scene_data.get("script", ""),
                    "emotion": scene_data.get("emotion", ""),
                    "script": scene_data.get("script", ""),  # 保持与原有结构兼容
                    "camera": scene_data.get("visual", ""),  # 保持与原有结构兼容
                    "keywords": scene_data.get("keywords", ""),  # 新增关键词字段
                    "start_time": scene_id * 10,  # 保持与原有结构兼容
                    "end_time": (scene_id + 1) * 10,  # 保持与原有结构兼容
                    "full_script": f"###  Scene {scene_id}: {scene_data.get('title', f'Scene {scene_id}')}\n- **Core Keywords**：{scene_data.get('keywords', '')}\n- **Visual (Visual Elements)**：\n{scene_data.get('visual', '')}\n- **Audio (Dialogue Script)**：\n[{scene_data.get('emotion', '')}] {scene_data.get('script', '')}"
                }
                scenes.append(scene)
                scene_id += 1
            logger.info(f"Successfully parsed {len(scenes)} scenes from JSON format")
            
            # 限制场景数量在合理范围内 (5-15)
            max_scenes = 15
            min_scenes = 5
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
    
    # 限制场景数量在合理范围内 (5-15)
    max_scenes = 15
    min_scenes = 5
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
    language: str = None
) -> str:
    """
    Convert single-scene script to multi-scene format.
    
    Args:
        video_script: Single-scene script text
        video_subject: Video subject for context
        language: Language for the generated script
    
    Returns:
        Multi-scene script text with visual descriptions, camera movements, and emotion annotations
    """
    prompt = f"""
# Role
You are a senior video director and storyboard designer with 10 years of experience. You excel at transforming various types of text content (whether it's informative articles, stories, or marketing copy) into visually impactful and logically coherent storyboard scripts.

# Goal
Please read the user-provided [Original Text] and adapt it into a standardized **scene-based storyboard script**.

# Constraints & Workflow
1. **Audio-First Principle**: Audio (dialogue) is the core, and video and subtitles serve the dialogue. All visual elements and scene designs should enhance the expression of the dialogue.
2. **Semantic Scene Division**: Analyze the semantic structure of the article, identify logical turning points, and divide the content into 5-15 scenes (including opening, main body, and conclusion)
   - **Opening Scene**: Should include natural greetings and background introduction, avoid directly entering the topic to make the video start more smoothly
   - Each scene should have complete content and a clear theme, with logical coherence
   - Scene content should be independent and able to clearly express a complete concept or viewpoint
3. **Visual Transformation**:
    - Reject boring visuals (such as "a person speaking").
    - Must use **visual metaphors** (expressing abstract concepts with concrete objects), **dynamic graphics**, or **scene reenactment**.
    - Visual descriptions should be **pure text, concise and standard**, including: subject, environment, action, camera movement (such as close-up, push-in, pull-out).
    - Visual elements must be closely related to the dialogue content and able to enhance the expression of the dialogue.
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
6. **Format Enforcement**: **Must** strictly follow the [Output Template] format below, without arbitrarily adding or removing fields.

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
        # Split the script into 3 parts
        script_lines = video_script.split('\n')
        total_lines = len(script_lines)
        
        if total_lines <= 1:
            # Very short script, create minimal structure
            fallback_script = f"###  场景 1：开场引入\n- **Visual (画面视觉)**：\n    - 主播站在明亮的工作室中，背景是现代化的办公环境，前方有一个大屏幕显示主题。\n    - 运镜：从远到近的推镜头，聚焦到主播面部表情。\n- **Audio (口播文案)**：\n    - ([热情、亲切]) {video_script}\n\n###  场景 2：核心内容\n- **Visual (画面视觉)**：\n    - 特写屏幕上的相关内容，配合动态图形展示关键信息。\n    - 运镜：平移镜头，展示不同的视觉元素。\n- **Audio (口播文案)**：\n    - ([专业、清晰]) {video_script}\n\n###  场景 3：总结收尾\n- **Visual (画面视觉)**：\n    - 回到主播画面，主播面带微笑，背景屏幕显示总结要点。\n    - 运镜：拉远镜头，展示完整的工作室环境。\n- **Audio (口播文案)**：\n    - ([自信、鼓舞]) {video_script}"
        else:
            # Split into 3 roughly equal parts
            part1_end = total_lines // 3
            part2_end = 2 * (total_lines // 3)
            
            part1 = '\n'.join(script_lines[:part1_end])
            part2 = '\n'.join(script_lines[part1_end:part2_end])
            part3 = '\n'.join(script_lines[part2_end:])
            
            fallback_script = f"###  场景 1：开场引入\n- **Visual (画面视觉)**：\n    - 主播站在明亮的工作室中，背景是现代化的办公环境，前方有一个大屏幕显示主题。\n    - 运镜：从远到近的推镜头，聚焦到主播面部表情。\n- **Audio (口播文案)**：\n    - ([热情、亲切]) {part1}\n\n###  场景 2：核心内容\n- **Visual (画面视觉)**：\n    - 特写屏幕上的相关内容，配合动态图形展示关键信息。\n    - 运镜：平移镜头，展示不同的视觉元素。\n- **Audio (口播文案)**：\n    - ([专业、清晰]) {part2}\n\n###  场景 3：总结收尾\n- **Visual (画面视觉)**：\n    - 回到主播画面，主播面带微笑，背景屏幕显示总结要点。\n    - 运镜：拉远镜头，展示完整的工作室环境。\n- **Audio (口播文案)**：\n    - ([自信、鼓舞]) {part3}"
        return fallback_script
    else:
        logger.success(f"completed script conversion: \n{final_script}")
    
    return final_script.strip()


def generate_scene_terms(
    video_subject: str,
    scene_script: str,
    scene_camera: str,
    amount: int = 5
) -> List[str]:
    """
    Generate search terms for a specific scene.
    
    Args:
        video_subject: Overall video subject
        scene_script: Script for this specific scene
        scene_camera: Camera/visual description for this scene
        amount: Number of terms to generate
    
    Returns:
        List of search terms
    """
    prompt = f"""
# Role: Scene-Specific Video Search Terms Generator

## Goals:
Generate {amount} search terms for stock videos for a specific scene.

## Constraints:
1. The search terms should be relevant to both the scene's visual description and narration
2. Each search term should consist of 1-3 words
3. You must only return the JSON array of strings
4. Generate both English and Chinese search terms to get more relevant videos
5. Focus on visual elements mentioned in the camera description
6. Always include keywords related to the overall video subject to maintain consistency across scenes

## Output Example:
["design patterns", "设计模式", "software design", "软件设计", "coding best practices", "编程最佳实践", "object oriented", "面向对象", "design principles", "设计原则"]

## Context:
### Video Subject
{video_subject}

### Scene Camera/Visual Description
{scene_camera}

### Scene Script
{scene_script}

Please generate both English and Chinese search terms to ensure better search results.
""".strip()

    logger.info(f"generating terms for scene")
    
    search_terms = []
    response = ""
    for i in range(_max_retries):
        try:
            response = _generate_response(prompt)
            if "Error: " in response:
                logger.error(f"failed to generate scene terms: {response}")
                if stop_on_api_failure:
                    return f"Error: {response}"
                return []
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
    
