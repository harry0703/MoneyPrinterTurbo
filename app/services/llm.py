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
                base_url = "***"
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

                genai.configure(api_key=api_key, transport="rest")

                generation_config = {
                    "temperature": 0.5,
                    "top_p": 1,
                    "top_k": 1,
                    "max_output_tokens": 8192,
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
            else:
                client = OpenAI(
                    api_key=api_key,
                    base_url=base_url,
                )

            response: ChatCompletion = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096
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
    if "Error: " in final_script:
        logger.error(f"failed to generate video script: {final_script}")
    else:
        logger.success(f"completed: \n{final_script}")
    return final_script.strip()


# def generate_terms(video_subject: str, video_script: str) -> List[str]:
#     prompt = f"""
# # Role: AI Video Director and Editor

# ## Core Goal:
# Analyze the provided complete video script and intelligently segment it into a sequence of logical scenes suitable for a short-form video. For each segmented scene, you must generate a highly descriptive English search query ideal for finding the most relevant stock footage on platforms like Pexels.

# ## Output Format and Constraints:
# 1.  **You MUST return a pure, single JSON Array.** Do not include any explanatory text, markdown markers (` ```json ... ``` `), or any other content outside of the JSON array. Your entire response body must be a valid JSON array that can be parsed directly.
# 2.  each search term should consist of 1-3 words, always add the main subject of the video.
# 3.  Constraints for the `pexels_search_query` field value:
#     - It must be a concise, highly descriptive **English phrase**.
#     - It is intended to be used directly as the `query` parameter for the Pexels API.
#     - It should describe a concrete **visual scene**, not an abstract concept or emotion.
#     - **Excellent Examples**: "Man walking alone on foggy road", "Futuristic city skyline at night", "Close up of old book pages turning".
#     - **Poor Examples**: "sadness", "a trip", "the meaning of life".
# 4.  Scene segmentation should be based on logical shifts in the narrative, changes in time, or natural transition points for visuals.
# 5. reply with english search terms only.
# 6.**The number of search terms should directly correspond to the number of distinct scenes you identify in the script. A longer script should naturally result in more search terms.**

# ## Output Example:
# ["search term 1", "search term 2", "search term 3","search term 4","search term 5", "..."]

# ## Context:
# ### Video Subject
# {video_subject}
def generate_terms(video_subject: str, video_script: str) -> List[str]:
    """
    Generate video terms from video subject and script.
    """
    prompt_template = """
# Role: Video Search Terms Generator

## Task:
Generate a concise, comma-separated list of 1-5 English search terms based on the provided `Video Subject` and `Video Script`. These terms will be used to find relevant video clips.

## Instructions:
1.  **Analyze Context:** Read the `Video Subject` and `Video Script` to understand the main topics and visual elements.
2.  **Brainstorm Keywords:** Think of concrete, visually-driven keywords. Avoid abstract concepts.
3.  **Select & Refine:** Choose the most powerful and representative terms.
4.  **Format Output:** Provide a single line of comma-separated English keywords. Do not include any other text, explanations, or formatting.

## Example:
**Video Subject:** "The Impact of Sugar on Your Brain"
**Video Script:** "Sugar, a sweet temptation, can have a profound effect on our brain chemistry..."
**Output:**
`sugar cubes, brain scan, dopamine release, person eating candy, neural pathways`

## Your Turn:
### Video Subject:
{video_subject}

### Video Script:
{video_script}

### Output:
"""
    prompt = prompt_template.format(
        video_subject=video_subject, video_script=video_script
    )

    logger.info(f"subject: {video_subject}")

    try:
        response = _generate_response(prompt)
        # remove blank lines
        generated_text = "\n".join(
            [line for line in response.split("\n") if line.strip()]
        )
        if not generated_text:
            logger.warning("LLM returned empty terms list.")
            return []

        terms = [term.strip().strip("`'\"") for term in generated_text.split(",")]
        logger.info(f"Generated terms: {terms}")
        return terms
    except Exception as e:
        logger.error(f"Failed to generate video terms: {e}")
        return []


# def generate_storyboard(video_subject: str, video_script: str) -> List[Dict]:
#     """
#     Analyzes the entire script, breaks it down into scenes, and generates matching search terms for each scene.
#     Returns a list of scenes, where each scene is a dictionary containing 'scene_script' and 'search_terms'.
#     """
#     prompt = f"""
# # Role: Video Script Analyst

# ## GOAL:
# Your task is to transform a video script into a storyboard. You will read the provided script, segment it into scenes, and for each scene, generate a set of descriptive, visual search terms that will be used to find stock video footage. The final output must be a valid JSON array of objects.

# ## STEP-BY-STEP INSTRUCTIONS:
# 1.  **Segment the Script:** Read the `Video Script` and break it down into short, logical, spoken segments. A segment should typically be one or two sentences long.

# ## EXAMPLE (Note the Realism and Concreteness):
# [
#   {{
#     "scene_script": "Blueberries. They're often called nature's perfect food for your eyes.",
#     "search_terms": ["woman eating fresh blueberries from a bowl", "close up of fresh blueberries", "bowl of blueberries on a table"]
#   }},
#   {{
#     "scene_script": "And for good reason. Packed with anthocyanins, vitamin C, and ludian...",
#     "search_terms": ["nutritionist explaining health benefits", "close up of vitamin C tablets", "diagram of anthocyanin molecule"]
#   }},
#   {{
#     "scene_script": "...these tiny berries act like microscopic shields, protecting your retina and macula from oxidative stress and age related damage.",
#     "search_terms": ["medical animation of the human eye", "diagram of the retina and macula", "older person with healthy eyes smiling"]
#   }}
# ]

# ## CONTEXT:
# ### Video Subject:
# {video_subject}

# ### Video Script:
# {video_script}
def generate_storyboard(video_subject: str, video_script: str) -> List[Dict]:
    """
    Analyzes the script, breaks it into scenes, and extracts the main subject nouns as search terms for each scene.
    Returns a list of scenes, where each scene is a dictionary containing 'scene_script' and 'search_terms'.
    """
    # [核心修改] 通过更明确、更强力的指令，强制要求 LLM 将视频脚本的每一句话都处理成一个独立的场景，并为每个场景生成对应的英文关键词。
    prompt = f"""
You are a video production assistant. Your task is to process a script for a video, breaking it down sentence by sentence to generate visual search terms.

**CRITICAL INSTRUCTIONS - FOLLOW THESE RULES EXACTLY:**

1.  **ONE SENTENCE = ONE VISUAL SEGMENT:** Each sentence from the script is a distinct visual segment. Do not merge sentences.
2.  **CONCRETE & VISUAL KEYWORDS ONLY:** The `search_terms` MUST be concrete, visual, and tangible things. They must be nouns or descriptive actions that can be found in a video library. 
    - **GOOD:** `blueberries`, `person walking`, `city skyline`, `laughing friends`, `human eye`.
    - **BAD / FORBIDDEN:** `reason`, `concept`, `idea`, `method`, `health`, `protection`, `damage`. Never use abstract, non-visual words.
3.  **MANDATORY KEYWORD DIVERSITY:** You are FORBIDDEN from using the same primary keyword for two consecutive segments. If segment 1 uses `blueberries`, segment 2 MUST use a different but relevant keyword (e.g., `antioxidants` could be visualized as `colorful fruits`, `retina` as `close-up of eye`). DIVERSIFY a lot.

**REQUIRED OUTPUT FORMAT:**
- You must output a valid JSON array of objects.
- Each object represents one sentence and must ONLY contain two keys: `script` and `search_terms`.

**EXAMPLE:**

Video Script:
"Blueberries are packed with anthocyanins, which are great for your eyes. These antioxidants protect the retina from damage."

Your JSON Output:
```json
[
    {{
        "script": "Blueberries are packed with anthocyanins, which are great for your eyes.",
        "search_terms": "blueberries, fresh fruit, antioxidant food"
    }},
    {{
        "script": "These antioxidants protect the retina from damage.",
        "search_terms": "close-up of eye, retina scan, vision test"
    }}
]
```

**Video Script to Process:**
```
{video_script}
```

**Your JSON Output (must be a valid JSON array):**
"""
    # return []

    logger.info(f"Generating storyboard for subject: {video_subject}")
    response_str = _generate_response(prompt)

    try:
        # The model should return a valid JSON array string.
        # Find the start and end of the JSON array.
        json_start = response_str.find('[')
        json_end = response_str.rfind(']')
        if json_start != -1 and json_end != -1 and json_start < json_end:
            json_str = response_str[json_start:json_end+1]
            storyboard = json.loads(json_str)
            logger.success("Successfully parsed storyboard from LLM response.")
            return storyboard
        else:
            logger.error(f"Could not find a valid JSON array in the response. Raw response: {response_str}")
            return []
    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON. Raw response: {response_str}")
        # Fallback logic can be added here if needed, e.g., using regex to extract JSON.
        return []


# ... (您的其他函数和代码保持不变)


if __name__ == "__main__":
    video_subject = "生命的意义是什么"
    script = generate_script(
        video_subject=video_subject, language="zh-CN", paragraph_number=1
    )
    print("######################")
    print(script)
    search_terms = generate_terms(
        video_subject=video_subject, video_script=script
    )
    print("######################")
    print(search_terms)
    print("-----输出包含的场景数量-----")
    print(len(search_terms))

def generate_video_category(video_subject: str) -> str:
    """
    Selects the most appropriate video category from a predefined list based on the video subject.
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
    # Fallback to a default category if the response is invalid
    valid_categories = ["backgrounds", "fashion", "nature", "science", "education", "feelings", "health", "people", "religion", "places", "animals", "industry", "computer", "food", "sports", "transportation", "travel", "buildings", "business", "music"]
    if category not in valid_categories:
        logger.warning(f"Generated category '{category}' is not valid. Falling back to 'nature'.")
        return "nature"
    
    logger.success(f"Successfully selected video category: {category}")
    return category