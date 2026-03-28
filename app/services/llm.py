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
    video_subject: str, language: str = "", paragraph_number: int = 1
) -> str:
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
    if language:
        prompt += f"\n- language: {language}"

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
5. reply with english search terms only.

## Output Example:
["search term 1", "search term 2", "search term 3","search term 4","search term 5"]

## Context:
### Video Subject
{video_subject}

### Video Script
{video_script}

Please note that you must use English for generating video search terms; Chinese is not accepted.
""".strip()

    logger.info(f"subject: {video_subject}")

    search_terms = []
    response = ""
    for i in range(_max_retries):
        try:
            response = _generate_response(prompt)
            if "Error: " in response:
                logger.error(f"failed to generate video script: {response}")
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
    video_subject: str,
    language: str = "",
    max_scenes: int = 5
) -> str:
    """
    Generate multi-scene script for video.
    
    Args:
        video_subject: The subject of the video
        language: Language for the script
        max_scenes: Maximum number of scenes to generate
    
    Returns:
        Multi-scene script text in the following format:
        (镜头: 镜头描述)
        【开始时间-结束时间 场景标题】
        主播文案内容
    """
    prompt = f"""
# Role: Multi-Scene Video Script Generator

## Goals:
Generate a multi-scene video script based on the subject. The script should be divided into multiple scenes, each with its own visual requirements and narration.

## Constraints:
1. Divide the video into 3-5 scenes based on the content flow
2. Each scene must include:
   - Camera/visual description in parentheses: (镜头: 描述)
   - Time range in brackets: 【开始秒数-结束秒数 场景标题】
   - Narration script for that scene
3. Total video length should be around 30-60 seconds
4. Scene transitions should be natural and logical
5. Do not include any markdown formatting
6. Do not include scene numbers or other metadata
7. Respond in the same language as the video subject
8. Do not require the host to be on camera throughout the entire video
9. Include scenes that show relevant materials, products, or visuals related to the topic
10. Balance between host on-camera scenes and material展示 scenes

## Output Format:
(镜头: 主播坐在电脑前，屏幕上是代码编辑器)
【0-5秒 开场引入】
各位朋友们，今天我要和大家分享一个非常重要的话题...

(镜头: 特写屏幕，展示代码运行效果)
【5-15秒 核心内容一】
首先，让我们来看一下这个问题的本质...

(镜头: 切换到产品展示画面)
【15-25秒 核心内容二】
接下来，我要给大家介绍具体的解决方案...

(镜头: 回到主播画面，展示总结)
【25-30秒 总结收尾】
总结一下，今天我们讨论了...

## Context:
- Video Subject: {video_subject}
- Maximum Scenes: {max_scenes}
""".strip()
    
    if language:
        prompt += f"\n- Language: {language}"

    logger.info(f"generating multi-scene script for subject: {video_subject}")
    
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
            logger.error(f"failed to generate multi-scene script: {e}")
        
        if i < _max_retries - 1:
            logger.warning(f"failed to generate multi-scene script, trying again... {i + 1}")
    
    if not final_script or "Error: " in final_script:
        # Check if we should stop on API failure
        if stop_on_api_failure:
            error_msg = f"LLM API failed to generate multi-scene script after {_max_retries} attempts"
            logger.error(error_msg)
            return f"Error: {error_msg}"
        
        # Fallback: generate a simple multi-scene structure
        logger.warning("using fallback multi-scene script generation")
        fallback_script = f"(镜头: 开场画面)\n【0-10秒 开场引入】\n各位朋友们，今天我要和大家分享一个关于{video_subject}的话题。\n\n(镜头: 核心内容展示)\n【10-20秒 核心内容】\n{video_subject}是一个非常重要的话题，它涉及到我们生活的方方面面。\n\n(镜头: 总结画面)\n【20-30秒 总结收尾】\n希望今天的分享对大家有所帮助，谢谢大家！"
        return fallback_script
    else:
        logger.success(f"completed multi-scene script generation: \n{final_script}")
    
    return final_script.strip()


def parse_multi_scene_script(script_text: str) -> List[Dict]:
    """
    Parse multi-scene script text into structured data.
    
    Input format:
        (镜头: 镜头描述)
        【0-5秒 场景标题】
        主播文案内容...
    
    Args:
        script_text: Multi-scene script text
    
    Returns:
        List of scene dictionaries with structure:
        [
            {
                "id": "scene_1",
                "camera": "镜头描述",
                "start_time": 0,
                "end_time": 5,
                "title": "场景标题",
                "script": "主播文案"
            },
            ...
        ]
    """
    import re
    
    scenes = []
    scene_id = 1
    
    # Split by scene markers (镜头:)
    # Pattern to match scene blocks
    scene_pattern = r'\(镜头[:：]\s*([^)]+)\)\s*【(\d+)-(\d+)秒?\s+([^】]+)】\s*([^\(]+)'
    
    matches = re.findall(scene_pattern, script_text, re.DOTALL)
    
    for match in matches:
        camera, start_time, end_time, title, script = match
        scene = {
            "id": f"scene_{scene_id}",
            "camera": camera.strip(),
            "start_time": float(start_time),
            "end_time": float(end_time),
            "title": title.strip(),
            "script": script.strip()
        }
        scenes.append(scene)
        scene_id += 1
    
    # If no matches with strict pattern, try alternative parsing
    if not scenes:
        # Try to split by camera marker
        parts = re.split(r'\(镜头[:：]', script_text)
        for i, part in enumerate(parts[1:], 1):  # Skip first empty part
            lines = part.strip().split('\n')
            if len(lines) >= 2:
                camera = lines[0].replace(')', '').strip()
                
                # Try to extract time and title from second line
                time_match = re.search(r'【(\d+)-(\d+)秒?\s+([^】]+)】', lines[1])
                if time_match:
                    start_time = float(time_match.group(1))
                    end_time = float(time_match.group(2))
                    title = time_match.group(3).strip()
                    # Rest is script
                    script = '\n'.join(lines[2:]).strip()
                    
                    scene = {
                        "id": f"scene_{i}",
                        "camera": camera,
                        "start_time": start_time,
                        "end_time": end_time,
                        "title": title,
                        "script": script
                    }
                    scenes.append(scene)
    
    logger.info(f"parsed {len(scenes)} scenes from multi-scene script")
    return scenes


def convert_to_multi_scene(
    video_script: str,
    video_subject: str = ""
) -> str:
    """
    Convert single-scene script to multi-scene format.
    
    Args:
        video_script: Single-scene script text
        video_subject: Video subject for context
    
    Returns:
        Multi-scene script text
    """
    prompt = f"""
# Role: Script Converter

## Goals:
Convert the provided single-scene script into a multi-scene format with visual descriptions and time markers.

## Constraints:
1. Divide the script into 3-5 logical scenes based on content flow
2. Each scene must include:
   - Camera/visual description in parentheses: (镜头: 描述)
   - Time range in brackets: 【开始秒数-结束秒数 场景标题】
   - Narration script for that scene (adapted from original script)
3. Total length should match the original script's pacing
4. Scene transitions should be natural
5. Do not add new content, only reorganize existing content
6. Do not include any markdown formatting
7. Do not require the host to be on camera throughout the entire video
8. Include scenes that show relevant materials, products, or visuals related to the topic
9. Balance between host on-camera scenes and material展示 scenes

## Output Format:
(镜头: 主播坐在电脑前)
【0-5秒 开场】
[Adapted opening narration]

(镜头: 特写屏幕)
【5-15秒 主要内容】
[Adapted main content]

(镜头: 产品展示)
【15-25秒 解决方案】
[Adapted solution content]

## Context:
- Video Subject: {video_subject}
- Original Script:
{video_script}
""".strip()

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
            fallback_script = f"(镜头: 开场画面)\n【0-10秒 开场】\n{video_script}\n\n(镜头: 核心内容)\n【10-20秒 核心内容】\n{video_script}\n\n(镜头: 结尾)\n【20-30秒 结尾】\n{video_script}"
        else:
            # Split into 3 roughly equal parts
            part1_end = total_lines // 3
            part2_end = 2 * (total_lines // 3)
            
            part1 = '\n'.join(script_lines[:part1_end])
            part2 = '\n'.join(script_lines[part1_end:part2_end])
            part3 = '\n'.join(script_lines[part2_end:])
            
            fallback_script = f"(镜头: 开场画面)\n【0-10秒 开场】\n{part1}\n\n(镜头: 核心内容展示)\n【10-20秒 核心内容】\n{part2}\n\n(镜头: 总结画面)\n【20-30秒 总结】\n{part3}"
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
4. The search terms must be in English for better stock video search results
5. Focus on visual elements mentioned in the camera description
6. Always include keywords related to the overall video subject to maintain consistency across scenes

## Output Example:
["computer screen", "coding", "programmer", "software development", "technology"]

## Context:
### Video Subject
{video_subject}

### Scene Camera/Visual Description
{scene_camera}

### Scene Script
{scene_script}
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
    
