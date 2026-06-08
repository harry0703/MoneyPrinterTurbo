import asyncio
import os
import re
from datetime import datetime, timedelta
from typing import Union
from xml.sax.saxutils import unescape

import edge_tts
import requests
from edge_tts import SubMaker, submaker
from loguru import logger
from moviepy.video.tools import subtitles
from moviepy.audio.io.AudioFileClip import AudioFileClip

# 替代edge_tts.submaker中的mktimestamp函数
def mktimestamp(seconds: float) -> str:
    """将秒数转换为SRT格式的时间戳"""
    td = timedelta(seconds=seconds)
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = td.microseconds // 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

from app.config import config
from app.utils import utils

# 缓存字典，用于存储TTS音色信息
_voice_cache = {
    'coze': {'voices': [], 'timestamp': None, 'api_key': None},
    'siliconflow': {'voices': [], 'timestamp': None},
    'gemini': {'voices': [], 'timestamp': None},
    'qwen': {'voices': [], 'timestamp': None, 'api_key': None}
}

# 缓存有效期（秒）
CACHE_DURATION = 3600  # 1小时


def get_siliconflow_voices() -> list[str]:
    """
    获取硅基流动的声音列表

    Returns:
        声音列表，格式为 ["siliconflow:FunAudioLLM/CosyVoice2-0.5B:alex", ...]
    """
    api_key = config.siliconflow.get("api_key", "")
    if not api_key:
        logger.warning("SiliconFlow API key is NOT set, using HARDCODED voice list")
    else:
        logger.info("SiliconFlow API key is set, using HARDCODED voice list")
    
    logger.info("Loading SiliconFlow voices from HARDCODED list")
    # 硅基流动的声音列表和对应的性别（用于显示）
    voices_with_gender = [
        ("FunAudioLLM/CosyVoice2-0.5B", "alex", "Male"),
        ("FunAudioLLM/CosyVoice2-0.5B", "anna", "Female"),
        ("FunAudioLLM/CosyVoice2-0.5B", "bella", "Female"),
        ("FunAudioLLM/CosyVoice2-0.5B", "benjamin", "Male"),
        ("FunAudioLLM/CosyVoice2-0.5B", "charles", "Male"),
        ("FunAudioLLM/CosyVoice2-0.5B", "claire", "Female"),
        ("FunAudioLLM/CosyVoice2-0.5B", "david", "Male"),
        ("FunAudioLLM/CosyVoice2-0.5B", "diana", "Female"),
    ]

    # 添加siliconflow:前缀，并格式化为显示名称
    result = [
        f"siliconflow:{model}:{voice}-{gender}"
        for model, voice, gender in voices_with_gender
    ]
    logger.info(f"SiliconFlow loaded {len(result)} hardcoded voices: {result}")
    return result


def get_gemini_voices() -> list[str]:
    """
    获取Gemini TTS的声音列表
    
    Returns:
        声音列表，格式为 ["gemini:Zephyr-Female", "gemini:Puck-Male", ...]
    """
    api_key = config.app.get("gemini_api_key", "")
    if not api_key:
        logger.warning("Gemini API key is NOT set, using HARDCODED voice list")
    else:
        logger.info("Gemini API key is set, using HARDCODED voice list")
    
    logger.info("Loading Gemini voices from HARDCODED list")
    # Gemini TTS支持的语音列表
    voices_with_gender = [
        ("Zephyr", "Female"),
        ("Puck", "Male"), 
        ("Charon", "Male"),
        ("Kore", "Female"),
        ("Fenrir", "Male"),
        ("Aoede", "Female"),
        ("Thalia", "Female"),
        ("Sage", "Male"),
        ("Echo", "Female"),
        ("Harmony", "Female"),
        ("Lux", "Female"),
        ("Nova", "Female"),
        ("Vale", "Male"),
        ("Orion", "Male"),
        ("Atlas", "Male"),
    ]
    
    # 添加gemini:前缀，并格式化为显示名称
    result = [
        f"gemini:{voice}-{gender}"
        for voice, gender in voices_with_gender
    ]
    logger.info(f"Gemini loaded {len(result)} hardcoded voices: {result}")
    return result


def get_qwen_voices(force_refresh=False) -> list[str]:
    """
    获取Qwen TTS的声音列表
    
    Args:
        force_refresh: 是否强制刷新缓存
    
    Returns:
        声音列表，格式为: "qwen|voice_id|voice_name-gender|preview_audio|preview_text"
    """
    global _voice_cache
    
    # 检查缓存
    api_key = config.qwen.get("api_key", "")
    cache_entry = _voice_cache['qwen']
    
    # 检查缓存是否有效
    current_time = datetime.now().timestamp()
    if not force_refresh and cache_entry['voices'] and cache_entry['timestamp']:
        cache_age = current_time - cache_entry['timestamp']
        if cache_age < CACHE_DURATION and cache_entry['api_key'] == api_key:
            logger.info(f"Using cached Qwen voices (age: {cache_age:.1f}s)")
            return cache_entry['voices']
    
    logger.info("Loading Qwen voices from hardcoded list")
    
    # 定义默认中文声音列表 (Qwen-TTS 官方语音列表)
    voices_with_id_gender = [
        ("Cherry", "芊悦", "Female"),
        ("Serena", "苏瑶", "Female"),
        ("Ethan", "晨煦", "Male"),
        ("Chelsie", "千雪", "Female"),
        ("Momo", "茉兔", "Female"),
        ("Vivian", "十三", "Female"),
        ("Moon", "月白", "Male"),
        ("Maia", "四月", "Female"),
        ("Kai", "凯", "Male"),
        ("Nofish", "不吃鱼", "Male"),
        ("Bella", "萌宝", "Female"),
        ("Jennifer", "詹妮弗", "Female"),
        ("Ryan", "甜茶", "Male"),
        ("Katerina", "卡捷琳娜", "Female"),
        ("Aiden", "艾登", "Male"),
        ("Eldric Sage", "沧明子", "Male"),
        ("Mia", "乖小妹", "Female"),
        ("Mochi", "沙小弥", "Male"),
        ("Bellona", "燕铮莺", "Female"),
        ("Vincent", "田叔", "Male"),
        ("Bunny", "萌小姬", "Female"),
        ("Neil", "阿闻", "Male"),
        ("Elias", "墨讲师", "Female"),
        ("Arthur", "徐大爷", "Male"),
        ("Nini", "邻家妹妹", "Female"),
        ("Seren", "小婉", "Female"),
    ]

    voices = []

    try:
        api_key = config.qwen.get("api_key", "")
        
        # 使用硬编码的语音列表
        logger.info("Using hardcoded Qwen voices")
        for voice_id, voice_name, gender in voices_with_id_gender:
            voices.append(f"qwen|{voice_id}|{voice_name}-{gender}||")
        logger.info(f"Qwen loaded {len(voices)} hardcoded voices: {voices}")
        
        # 更新缓存
        _voice_cache['qwen'] = {
            'voices': voices,
            'timestamp': current_time,
            'api_key': api_key
        }
        logger.info(f"Qwen voices cached: {len(voices)} voices")
        
        return voices
    except Exception as e:
        # 发生异常，返回默认列表
        logger.error(f"Error getting Qwen voices: {str(e)}")
        for voice_id, voice_name, gender in voices_with_id_gender:
            voices.append(f"qwen|{voice_id}|{voice_name}-{gender}||")
        logger.info(f"Qwen loaded {len(voices)} DEFAULT hardcoded voices (exception occurred): {voices}")
        
        # 即使发生异常，也更新缓存以避免重复失败
        _voice_cache['qwen'] = {
            'voices': voices,
            'timestamp': current_time,
            'api_key': api_key
        }
        return voices


def get_coze_voices(force_refresh=False) -> list[str]:
    """
    获取Coze TTS的中文声音列表
    
    Args:
        force_refresh: 是否强制刷新缓存
    
    Returns:
        声音列表，格式为: "coze|voice_id|voice_name-gender|preview_audio|preview_text"
    """
    global _voice_cache
    
    # 检查缓存
    api_key = config.coze.get("api_key", "")
    cache_entry = _voice_cache['coze']
    
    # 检查缓存是否有效
    current_time = datetime.now().timestamp()
    if not force_refresh and cache_entry['voices'] and cache_entry['timestamp']:
        cache_age = current_time - cache_entry['timestamp']
        if cache_age < CACHE_DURATION and cache_entry['api_key'] == api_key:
            logger.info(f"Using cached Coze voices (age: {cache_age:.1f}s)")
            return cache_entry['voices']
    
    logger.info("Fetching Coze voices from API")
    
    # 定义默认中文声音列表
    voices_with_id_gender = [
        ("7426720361732915209", "湾区大叔", "Male"),
        ("7426720361732915210", "财阀千金", "Female"),
        ("7426720361732915211", "青叔", "Male"),
        ("7426720361732915212", "御姐", "Female"),
        ("7426720361732915213", "阳光少年", "Male"),
        ("7426720361732915214", "可爱少女", "Female"),
        ("7426720361732915215", "温和大叔", "Male"),
        ("7426720361732915216", "甜美女生", "Female"),
        ("7426720361732915217", "成熟男声", "Male"),
        ("7426720361732915218", "温柔女声", "Female"),
    ]

    voices = []

    try:
        # 配置Coze API
        api_key = config.coze.get("api_key", "")
        if not api_key:
            # 如果没有API key，返回默认的语音列表
            logger.info("No Coze API key found, using DEFAULT hardcoded voices")
            for voice_id, voice_name, gender in voices_with_id_gender:
                voices.append(f"coze|{voice_id}|{voice_name}-{gender}||")
            logger.info(f"Coze loaded {len(voices)} DEFAULT hardcoded voices (no API key): {voices}")
            # 更新缓存
            _voice_cache['coze'] = {
                'voices': voices,
                'timestamp': current_time,
                'api_key': api_key
            }
            return voices
        
        # Coze TTS声音列表API endpoint
        url = "https://api.coze.cn/v1/audio/voices"
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        page_num = 0
        params = {}

        has_more = True
        while has_more:
            page_num += 1
            params["page_num"] = page_num
            # Send request
            response = requests.get(url, headers=headers, params=params)

            if response.status_code == 200:
                # 解析响应
                data = response.json()
                logger.info(f"Coze voices API response: {data}")

                # Coze API响应格式: {"data": {"voices": [...]}, "code": 0, "msg": "success"}
                response_data = data.get("data", {})
                assert response_data, "Coze API response does not contain data"
                voice_list = response_data.get("voice_list", [])

                if len(voice_list) > 0:
                    for voice in voice_list:
                        # 根据Coze API文档，使用正确的字段名
                        voice_id = voice.get("voice_id", "")
                        voice_name = voice.get("name", "")
                        preview_audio = voice.get("preview_audio", "")
                        preview_text = voice.get("preview_text", "")
                        # 尝试从speaker_id中提取性别信息
                        speaker_id = voice.get("speaker_id", "")
                        gender = voice.get("gender", "")
                        # 获取语言代码
                        language_code = voice.get("language_code", "")
                        # 获取支持的情感
                        support_emotions = voice.get("support_emotions", [])
                        
                        # 只添加中文声音 (language_code 为 "zh")
                        if language_code != "zh":
                            continue
                        
                        # 处理情感列表，格式化为"emotion-display_name"
                        emotion_strings = []
                        for emotion in support_emotions:
                            if isinstance(emotion, dict):
                                # 如果是字典，提取emotion和display_name
                                emotion_value = emotion.get("emotion", "")
                                display_name = emotion.get("display_name", "")
                                if emotion_value:
                                    if display_name:
                                        emotion_strings.append(f"{emotion_value}-{display_name}")
                                    else:
                                        emotion_strings.append(emotion_value)
                            else:
                                # 如果不是字典，直接使用
                                emotion_strings.append(str(emotion))
                        
                        if not gender and speaker_id:
                            # speaker_id格式如: "zh_female_cancan_tob" 或 "zh_male_xxx"
                            if "_female_" in speaker_id.lower():
                                gender = "Female"
                            elif "_male_" in speaker_id.lower():
                                gender = "Male"
                        # 如果speaker_id中没有性别信息，尝试从name中提取
                        if not gender and voice_name:
                            # 检查name中是否包含"男"或"女"
                            if any(gender_term in voice_name.lower() for gender_term in ["女", "姐", "妹","美","靓"]):
                                gender = "Female"
                            elif any(gender_term in voice_name.lower() for gender_term in ["男", "哥", "爷", "伙","婿","叔","兄","弟","俊","帅"]):
                                gender = "Male"
                        if not gender:
                            gender = "Unknown"
                        gender = gender.title()
                        
                        if voice_id and voice_name:
                            # 新格式: coze|voice_id|voice_name-gender|preview_audio|preview_text|emotions
                            # 使用|作为分隔符，避免与URL中的:冲突
                            emotions_str = ",".join(emotion_strings) if emotion_strings else ""
                            voices.append(f"coze|{voice_id}|{voice_name}-{gender}|{preview_audio}|{preview_text}|{emotions_str}")
                            logger.info(f"Found Chinese voice: {voice_id} - {voice_name} ({gender}) with preview audio, text, and emotions: {emotions_str}")

                    has_more = response_data.get("has_more", False)
                    continue
                else:
                    logger.warning(f"Coze API response does not contain voices data. Response: {data}")
                    break

                # 如果API返回的列表为空，使用默认列表
                if not voices:
                    logger.warning("Coze API returned empty voice list, using DEFAULT hardcoded voices")
                    for voice_id, voice_name, gender in voices_with_id_gender:
                        voices.append(f"coze|{voice_id}|{voice_name}-{gender}||")
                    logger.info(f"Coze loaded {len(voices)} DEFAULT hardcoded voices (API empty response): {voices}")
                    break
            else:
                # API调用失败，返回默认列表
                logger.error(f"Failed to get Coze voices from API: {response.status_code} {response.text}")
                for voice_id, voice_name, gender in voices_with_id_gender:
                    voices.append(f"coze|{voice_id}|{voice_name}-{gender}||")
                logger.info(f"Coze loaded {len(voices)} DEFAULT hardcoded voices (API call failed): {voices}")
                break
        
        # 如果没有从API获取到任何声音，使用默认列表
        if len(voices) == 0:
            logger.warning("No voices fetched from API, using DEFAULT hardcoded voices")
            for voice_id, voice_name, gender in voices_with_id_gender:
                voices.append(f"coze|{voice_id}|{voice_name}-{gender}||")
            logger.info(f"Coze loaded {len(voices)} DEFAULT hardcoded voices (no voices from API): {voices}")
        
        # 更新缓存
        _voice_cache['coze'] = {
            'voices': voices,
            'timestamp': current_time,
            'api_key': api_key
        }
        logger.info(f"Coze voices cached: {len(voices)} voices")
        
        return voices
    except Exception as e:
        # 发生异常，返回默认列表
        logger.error(f"Error getting Coze voices from API: {str(e)}")
        for voice_id, voice_name, gender in voices_with_id_gender:
            voices.append(f"coze|{voice_id}|{voice_name}-{gender}||")
        logger.info(f"Coze loaded {len(voices)} DEFAULT hardcoded voices (exception occurred): {voices}")
        
        # 即使发生异常，也更新缓存以避免重复失败
        _voice_cache['coze'] = {
            'voices': voices,
            'timestamp': current_time,
            'api_key': api_key
        }
        return voices


def get_all_azure_voices(filter_locals=None) -> list[str]:
    speech_key = config.azure.get("speech_key", "")
    service_region = config.azure.get("speech_region", "")
    if not speech_key or not service_region:
        logger.warning("Azure speech key or region is NOT set, using HARDCODED voice list")
    else:
        logger.info("Azure speech key and region are set, using HARDCODED voice list")
    
    logger.info(f"Loading Azure voices from HARDCODED list (filter_locals={filter_locals})")
    azure_voices_str = """
Name: af-ZA-AdriNeural
Gender: Female

Name: af-ZA-WillemNeural
Gender: Male

Name: am-ET-AmehaNeural
Gender: Male

Name: am-ET-MekdesNeural
Gender: Female

Name: ar-AE-FatimaNeural
Gender: Female

Name: ar-AE-HamdanNeural
Gender: Male

Name: ar-BH-AliNeural
Gender: Male

Name: ar-BH-LailaNeural
Gender: Female

Name: ar-DZ-AminaNeural
Gender: Female

Name: ar-DZ-IsmaelNeural
Gender: Male

Name: ar-EG-SalmaNeural
Gender: Female

Name: ar-EG-ShakirNeural
Gender: Male

Name: ar-IQ-BasselNeural
Gender: Male

Name: ar-IQ-RanaNeural
Gender: Female

Name: ar-JO-SanaNeural
Gender: Female

Name: ar-JO-TaimNeural
Gender: Male

Name: ar-KW-FahedNeural
Gender: Male

Name: ar-KW-NouraNeural
Gender: Female

Name: ar-LB-LaylaNeural
Gender: Female

Name: ar-LB-RamiNeural
Gender: Male

Name: ar-LY-ImanNeural
Gender: Female

Name: ar-LY-OmarNeural
Gender: Male

Name: ar-MA-JamalNeural
Gender: Male

Name: ar-MA-MounaNeural
Gender: Female

Name: ar-OM-AbdullahNeural
Gender: Male

Name: ar-OM-AyshaNeural
Gender: Female

Name: ar-QA-AmalNeural
Gender: Female

Name: ar-QA-MoazNeural
Gender: Male

Name: ar-SA-HamedNeural
Gender: Male

Name: ar-SA-ZariyahNeural
Gender: Female

Name: ar-SY-AmanyNeural
Gender: Female

Name: ar-SY-LaithNeural
Gender: Male

Name: ar-TN-HediNeural
Gender: Male

Name: ar-TN-ReemNeural
Gender: Female

Name: ar-YE-MaryamNeural
Gender: Female

Name: ar-YE-SalehNeural
Gender: Male

Name: az-AZ-BabekNeural
Gender: Male

Name: az-AZ-BanuNeural
Gender: Female

Name: bg-BG-BorislavNeural
Gender: Male

Name: bg-BG-KalinaNeural
Gender: Female

Name: bn-BD-NabanitaNeural
Gender: Female

Name: bn-BD-PradeepNeural
Gender: Male

Name: bn-IN-BashkarNeural
Gender: Male

Name: bn-IN-TanishaaNeural
Gender: Female

Name: bs-BA-GoranNeural
Gender: Male

Name: bs-BA-VesnaNeural
Gender: Female

Name: ca-ES-EnricNeural
Gender: Male

Name: ca-ES-JoanaNeural
Gender: Female

Name: cs-CZ-AntoninNeural
Gender: Male

Name: cs-CZ-VlastaNeural
Gender: Female

Name: cy-GB-AledNeural
Gender: Male

Name: cy-GB-NiaNeural
Gender: Female

Name: da-DK-ChristelNeural
Gender: Female

Name: da-DK-JeppeNeural
Gender: Male

Name: de-AT-IngridNeural
Gender: Female

Name: de-AT-JonasNeural
Gender: Male

Name: de-CH-JanNeural
Gender: Male

Name: de-CH-LeniNeural
Gender: Female

Name: de-DE-AmalaNeural
Gender: Female

Name: de-DE-ConradNeural
Gender: Male

Name: de-DE-FlorianMultilingualNeural
Gender: Male

Name: de-DE-KatjaNeural
Gender: Female

Name: de-DE-KillianNeural
Gender: Male

Name: de-DE-SeraphinaMultilingualNeural
Gender: Female

Name: el-GR-AthinaNeural
Gender: Female

Name: el-GR-NestorasNeural
Gender: Male

Name: en-AU-NatashaNeural
Gender: Female

Name: en-AU-WilliamNeural
Gender: Male

Name: en-CA-ClaraNeural
Gender: Female

Name: en-CA-LiamNeural
Gender: Male

Name: en-GB-LibbyNeural
Gender: Female

Name: en-GB-MaisieNeural
Gender: Female

Name: en-GB-RyanNeural
Gender: Male

Name: en-GB-SoniaNeural
Gender: Female

Name: en-GB-ThomasNeural
Gender: Male

Name: en-HK-SamNeural
Gender: Male

Name: en-HK-YanNeural
Gender: Female

Name: en-IE-ConnorNeural
Gender: Male

Name: en-IE-EmilyNeural
Gender: Female

Name: en-IN-NeerjaExpressiveNeural
Gender: Female

Name: en-IN-NeerjaNeural
Gender: Female

Name: en-IN-PrabhatNeural
Gender: Male

Name: en-KE-AsiliaNeural
Gender: Female

Name: en-KE-ChilembaNeural
Gender: Male

Name: en-NG-AbeoNeural
Gender: Male

Name: en-NG-EzinneNeural
Gender: Female

Name: en-NZ-MitchellNeural
Gender: Male

Name: en-NZ-MollyNeural
Gender: Female

Name: en-PH-JamesNeural
Gender: Male

Name: en-PH-RosaNeural
Gender: Female

Name: en-SG-LunaNeural
Gender: Female

Name: en-SG-WayneNeural
Gender: Male

Name: en-TZ-ElimuNeural
Gender: Male

Name: en-TZ-ImaniNeural
Gender: Female

Name: en-US-AnaNeural
Gender: Female

Name: en-US-AndrewMultilingualNeural
Gender: Male

Name: en-US-AndrewNeural
Gender: Male

Name: en-US-AriaNeural
Gender: Female

Name: en-US-AvaMultilingualNeural
Gender: Female

Name: en-US-AvaNeural
Gender: Female

Name: en-US-BrianMultilingualNeural
Gender: Male

Name: en-US-BrianNeural
Gender: Male

Name: en-US-ChristopherNeural
Gender: Male

Name: en-US-EmmaMultilingualNeural
Gender: Female

Name: en-US-EmmaNeural
Gender: Female

Name: en-US-EricNeural
Gender: Male

Name: en-US-GuyNeural
Gender: Male

Name: en-US-JennyNeural
Gender: Female

Name: en-US-MichelleNeural
Gender: Female

Name: en-US-RogerNeural
Gender: Male

Name: en-US-SteffanNeural
Gender: Male

Name: en-ZA-LeahNeural
Gender: Female

Name: en-ZA-LukeNeural
Gender: Male

Name: es-AR-ElenaNeural
Gender: Female

Name: es-AR-TomasNeural
Gender: Male

Name: es-BO-MarceloNeural
Gender: Male

Name: es-BO-SofiaNeural
Gender: Female

Name: es-CL-CatalinaNeural
Gender: Female

Name: es-CL-LorenzoNeural
Gender: Male

Name: es-CO-GonzaloNeural
Gender: Male

Name: es-CO-SalomeNeural
Gender: Female

Name: es-CR-JuanNeural
Gender: Male

Name: es-CR-MariaNeural
Gender: Female

Name: es-CU-BelkysNeural
Gender: Female

Name: es-CU-ManuelNeural
Gender: Male

Name: es-DO-EmilioNeural
Gender: Male

Name: es-DO-RamonaNeural
Gender: Female

Name: es-EC-AndreaNeural
Gender: Female

Name: es-EC-LuisNeural
Gender: Male

Name: es-ES-AlvaroNeural
Gender: Male

Name: es-ES-ElviraNeural
Gender: Female

Name: es-ES-XimenaNeural
Gender: Female

Name: es-GQ-JavierNeural
Gender: Male

Name: es-GQ-TeresaNeural
Gender: Female

Name: es-GT-AndresNeural
Gender: Male

Name: es-GT-MartaNeural
Gender: Female

Name: es-HN-CarlosNeural
Gender: Male

Name: es-HN-KarlaNeural
Gender: Female

Name: es-MX-DaliaNeural
Gender: Female

Name: es-MX-JorgeNeural
Gender: Male

Name: es-NI-FedericoNeural
Gender: Male

Name: es-NI-YolandaNeural
Gender: Female

Name: es-PA-MargaritaNeural
Gender: Female

Name: es-PA-RobertoNeural
Gender: Male

Name: es-PE-AlexNeural
Gender: Male

Name: es-PE-CamilaNeural
Gender: Female

Name: es-PR-KarinaNeural
Gender: Female

Name: es-PR-VictorNeural
Gender: Male

Name: es-PY-MarioNeural
Gender: Male

Name: es-PY-TaniaNeural
Gender: Female

Name: es-SV-LorenaNeural
Gender: Female

Name: es-SV-RodrigoNeural
Gender: Male

Name: es-US-AlonsoNeural
Gender: Male

Name: es-US-PalomaNeural
Gender: Female

Name: es-UY-MateoNeural
Gender: Male

Name: es-UY-ValentinaNeural
Gender: Female

Name: es-VE-PaolaNeural
Gender: Female

Name: es-VE-SebastianNeural
Gender: Male

Name: et-EE-AnuNeural
Gender: Female

Name: et-EE-KertNeural
Gender: Male

Name: fa-IR-DilaraNeural
Gender: Female

Name: fa-IR-FaridNeural
Gender: Male

Name: fi-FI-HarriNeural
Gender: Male

Name: fi-FI-NooraNeural
Gender: Female

Name: fil-PH-AngeloNeural
Gender: Male

Name: fil-PH-BlessicaNeural
Gender: Female

Name: fr-BE-CharlineNeural
Gender: Female

Name: fr-BE-GerardNeural
Gender: Male

Name: fr-CA-AntoineNeural
Gender: Male

Name: fr-CA-JeanNeural
Gender: Male

Name: fr-CA-SylvieNeural
Gender: Female

Name: fr-CA-ThierryNeural
Gender: Male

Name: fr-CH-ArianeNeural
Gender: Female

Name: fr-CH-FabriceNeural
Gender: Male

Name: fr-FR-DeniseNeural
Gender: Female

Name: fr-FR-EloiseNeural
Gender: Female

Name: fr-FR-HenriNeural
Gender: Male

Name: fr-FR-RemyMultilingualNeural
Gender: Male

Name: fr-FR-VivienneMultilingualNeural
Gender: Female

Name: ga-IE-ColmNeural
Gender: Male

Name: ga-IE-OrlaNeural
Gender: Female

Name: gl-ES-RoiNeural
Gender: Male

Name: gl-ES-SabelaNeural
Gender: Female

Name: gu-IN-DhwaniNeural
Gender: Female

Name: gu-IN-NiranjanNeural
Gender: Male

Name: he-IL-AvriNeural
Gender: Male

Name: he-IL-HilaNeural
Gender: Female

Name: hi-IN-MadhurNeural
Gender: Male

Name: hi-IN-SwaraNeural
Gender: Female

Name: hr-HR-GabrijelaNeural
Gender: Female

Name: hr-HR-SreckoNeural
Gender: Male

Name: hu-HU-NoemiNeural
Gender: Female

Name: hu-HU-TamasNeural
Gender: Male

Name: id-ID-ArdiNeural
Gender: Male

Name: id-ID-GadisNeural
Gender: Female

Name: is-IS-GudrunNeural
Gender: Female

Name: is-IS-GunnarNeural
Gender: Male

Name: it-IT-DiegoNeural
Gender: Male

Name: it-IT-ElsaNeural
Gender: Female

Name: it-IT-GiuseppeMultilingualNeural
Gender: Male

Name: it-IT-IsabellaNeural
Gender: Female

Name: iu-Cans-CA-SiqiniqNeural
Gender: Female

Name: iu-Cans-CA-TaqqiqNeural
Gender: Male

Name: iu-Latn-CA-SiqiniqNeural
Gender: Female

Name: iu-Latn-CA-TaqqiqNeural
Gender: Male

Name: ja-JP-KeitaNeural
Gender: Male

Name: ja-JP-NanamiNeural
Gender: Female

Name: jv-ID-DimasNeural
Gender: Male

Name: jv-ID-SitiNeural
Gender: Female

Name: ka-GE-EkaNeural
Gender: Female

Name: ka-GE-GiorgiNeural
Gender: Male

Name: kk-KZ-AigulNeural
Gender: Female

Name: kk-KZ-DauletNeural
Gender: Male

Name: km-KH-PisethNeural
Gender: Male

Name: km-KH-SreymomNeural
Gender: Female

Name: kn-IN-GaganNeural
Gender: Male

Name: kn-IN-SapnaNeural
Gender: Female

Name: ko-KR-HyunsuMultilingualNeural
Gender: Male

Name: ko-KR-InJoonNeural
Gender: Male

Name: ko-KR-SunHiNeural
Gender: Female

Name: lo-LA-ChanthavongNeural
Gender: Male

Name: lo-LA-KeomanyNeural
Gender: Female

Name: lt-LT-LeonasNeural
Gender: Male

Name: lt-LT-OnaNeural
Gender: Female

Name: lv-LV-EveritaNeural
Gender: Female

Name: lv-LV-NilsNeural
Gender: Male

Name: mk-MK-AleksandarNeural
Gender: Male

Name: mk-MK-MarijaNeural
Gender: Female

Name: ml-IN-MidhunNeural
Gender: Male

Name: ml-IN-SobhanaNeural
Gender: Female

Name: mn-MN-BataaNeural
Gender: Male

Name: mn-MN-YesuiNeural
Gender: Female

Name: mr-IN-AarohiNeural
Gender: Female

Name: mr-IN-ManoharNeural
Gender: Male

Name: ms-MY-OsmanNeural
Gender: Male

Name: ms-MY-YasminNeural
Gender: Female

Name: mt-MT-GraceNeural
Gender: Female

Name: mt-MT-JosephNeural
Gender: Male

Name: my-MM-NilarNeural
Gender: Female

Name: my-MM-ThihaNeural
Gender: Male

Name: nb-NO-FinnNeural
Gender: Male

Name: nb-NO-PernilleNeural
Gender: Female

Name: ne-NP-HemkalaNeural
Gender: Female

Name: ne-NP-SagarNeural
Gender: Male

Name: nl-BE-ArnaudNeural
Gender: Male

Name: nl-BE-DenaNeural
Gender: Female

Name: nl-NL-ColetteNeural
Gender: Female

Name: nl-NL-FennaNeural
Gender: Female

Name: nl-NL-MaartenNeural
Gender: Male

Name: pl-PL-MarekNeural
Gender: Male

Name: pl-PL-ZofiaNeural
Gender: Female

Name: ps-AF-GulNawazNeural
Gender: Male

Name: ps-AF-LatifaNeural
Gender: Female

Name: pt-BR-AntonioNeural
Gender: Male

Name: pt-BR-FranciscaNeural
Gender: Female

Name: pt-BR-ThalitaMultilingualNeural
Gender: Female

Name: pt-PT-DuarteNeural
Gender: Male

Name: pt-PT-RaquelNeural
Gender: Female

Name: ro-RO-AlinaNeural
Gender: Female

Name: ro-RO-EmilNeural
Gender: Male

Name: ru-RU-DmitryNeural
Gender: Male

Name: ru-RU-SvetlanaNeural
Gender: Female

Name: si-LK-SameeraNeural
Gender: Male

Name: si-LK-ThiliniNeural
Gender: Female

Name: sk-SK-LukasNeural
Gender: Male

Name: sk-SK-ViktoriaNeural
Gender: Female

Name: sl-SI-PetraNeural
Gender: Female

Name: sl-SI-RokNeural
Gender: Male

Name: so-SO-MuuseNeural
Gender: Male

Name: so-SO-UbaxNeural
Gender: Female

Name: sq-AL-AnilaNeural
Gender: Female

Name: sq-AL-IlirNeural
Gender: Male

Name: sr-RS-NicholasNeural
Gender: Male

Name: sr-RS-SophieNeural
Gender: Female

Name: su-ID-JajangNeural
Gender: Male

Name: su-ID-TutiNeural
Gender: Female

Name: sv-SE-MattiasNeural
Gender: Male

Name: sv-SE-SofieNeural
Gender: Female

Name: sw-KE-RafikiNeural
Gender: Male

Name: sw-KE-ZuriNeural
Gender: Female

Name: sw-TZ-DaudiNeural
Gender: Male

Name: sw-TZ-RehemaNeural
Gender: Female

Name: ta-IN-PallaviNeural
Gender: Female

Name: ta-IN-ValluvarNeural
Gender: Male

Name: ta-LK-KumarNeural
Gender: Male

Name: ta-LK-SaranyaNeural
Gender: Female

Name: ta-MY-KaniNeural
Gender: Female

Name: ta-MY-SuryaNeural
Gender: Male

Name: ta-SG-AnbuNeural
Gender: Male

Name: ta-SG-VenbaNeural
Gender: Female

Name: te-IN-MohanNeural
Gender: Male

Name: te-IN-ShrutiNeural
Gender: Female

Name: th-TH-NiwatNeural
Gender: Male

Name: th-TH-PremwadeeNeural
Gender: Female

Name: tr-TR-AhmetNeural
Gender: Male

Name: tr-TR-EmelNeural
Gender: Female

Name: uk-UA-OstapNeural
Gender: Male

Name: uk-UA-PolinaNeural
Gender: Female

Name: ur-IN-GulNeural
Gender: Female

Name: ur-IN-SalmanNeural
Gender: Male

Name: ur-PK-AsadNeural
Gender: Male

Name: ur-PK-UzmaNeural
Gender: Female

Name: uz-UZ-MadinaNeural
Gender: Female

Name: uz-UZ-SardorNeural
Gender: Male

Name: vi-VN-HoaiMyNeural
Gender: Female

Name: vi-VN-NamMinhNeural
Gender: Male

Name: zh-CN-XiaoxiaoNeural
Gender: Female

Name: zh-CN-XiaoyiNeural
Gender: Female

Name: zh-CN-YunjianNeural
Gender: Male

Name: zh-CN-YunxiNeural
Gender: Male

Name: zh-CN-YunxiaNeural
Gender: Male

Name: zh-CN-YunyangNeural
Gender: Male

Name: zh-CN-liaoning-XiaobeiNeural
Gender: Female

Name: zh-CN-shaanxi-XiaoniNeural
Gender: Female

Name: zh-HK-HiuGaaiNeural
Gender: Female

Name: zh-HK-HiuMaanNeural
Gender: Female

Name: zh-HK-WanLungNeural
Gender: Male

Name: zh-TW-HsiaoChenNeural
Gender: Female

Name: zh-TW-HsiaoYuNeural
Gender: Female

Name: zh-TW-YunJheNeural
Gender: Male

Name: zu-ZA-ThandoNeural
Gender: Female

Name: zu-ZA-ThembaNeural
Gender: Male


Name: en-US-AvaMultilingualNeural-V2
Gender: Female

Name: en-US-AndrewMultilingualNeural-V2
Gender: Male

Name: en-US-EmmaMultilingualNeural-V2
Gender: Female

Name: en-US-BrianMultilingualNeural-V2
Gender: Male

Name: de-DE-FlorianMultilingualNeural-V2
Gender: Male

Name: de-DE-SeraphinaMultilingualNeural-V2
Gender: Female

Name: fr-FR-RemyMultilingualNeural-V2
Gender: Male

Name: fr-FR-VivienneMultilingualNeural-V2
Gender: Female

Name: zh-CN-XiaoxiaoMultilingualNeural-V2
Gender: Female
    """.strip()
    voices = []
    # 定义正则表达式模式，用于匹配 Name 和 Gender 行
    pattern = re.compile(r"Name:\s*(.+)\s*Gender:\s*(.+)\s*", re.MULTILINE)
    # 使用正则表达式查找所有匹配项
    matches = pattern.findall(azure_voices_str)

    for name, gender in matches:
        # 应用过滤条件
        if filter_locals and any(
            name.lower().startswith(fl.lower()) for fl in filter_locals
        ):
            voices.append(f"{name}-{gender}")
        elif not filter_locals:
            voices.append(f"{name}-{gender}")

    voices.sort()
    logger.info(f"Azure loaded {len(voices)} hardcoded voices (filter_locals={filter_locals})")
    return voices


def parse_voice_name(name: str):
    # zh-CN-XiaoyiNeural-Female
    # zh-CN-YunxiNeural-Male
    # zh-CN-XiaoxiaoMultilingualNeural-V2-Female
    name = name.replace("-Female", "").replace("-Male", "").strip()
    return name


def is_azure_v2_voice(voice_name: str):
    voice_name = parse_voice_name(voice_name)
    if voice_name.endswith("-V2"):
        return voice_name.replace("-V2", "").strip()
    return ""


def is_siliconflow_voice(voice_name: str):
    """检查是否是硅基流动的声音"""
    return voice_name.startswith("siliconflow:")


def is_gemini_voice(voice_name: str):
    """检查是否是Gemini TTS的声音"""
    return voice_name.startswith("gemini:")


def is_coze_voice(voice_name: str):
    """检查是否是Coze TTS的声音"""
    return voice_name.startswith("coze|")


def is_qwen_voice(voice_name: str):
    """检查是否是Qwen TTS的声音"""
    return voice_name.startswith("qwen|")


def tts(
    text: str,
    voice_name: str,
    voice_rate: float,
    voice_file: str,
    voice_volume: float = 1.8,
    emotion: str = "",
    is_preview: bool = False,
) -> Union[SubMaker, None]:
    if is_azure_v2_voice(voice_name):
        result = azure_tts_v2(text, voice_name, voice_file)
    elif is_siliconflow_voice(voice_name):
        # 从voice_name中提取模型和声音
        # 格式: siliconflow:model:voice-Gender
        parts = voice_name.split(":")
        if len(parts) >= 3:
            model = parts[1]
            # 移除性别后缀，例如 "alex-Male" -> "alex"
            voice_with_gender = parts[2]
            voice = voice_with_gender.split("-")[0]
            # 构建完整的voice参数，格式为 "model:voice"
            full_voice = f"{model}:{voice}"
            result = siliconflow_tts(
                text, model, full_voice, voice_rate, voice_file, voice_volume
            )
        else:
            logger.error(f"Invalid siliconflow voice name format: {voice_name}")
            result = None
    elif is_gemini_voice(voice_name):
        # 从voice_name中提取声音名称
        # 格式: gemini:voice-Gender
        parts = voice_name.split(":")
        if len(parts) >= 2:
            # 移除性别后缀，例如 "Zephyr-Female" -> "Zephyr"
            voice_with_gender = parts[1]
            voice = voice_with_gender.split("-")[0]
            result = gemini_tts(text, voice, voice_rate, voice_file, voice_volume)
        else:
            logger.error(f"Invalid gemini voice name format: {voice_name}")
            result = None
    elif is_coze_voice(voice_name):
        # 从voice_name中提取voice_id、preview_audio和preview_text
        # 格式: coze|voice_id|voice_name-gender|preview_audio|preview_text|emotions
        parts = voice_name.split("|")
        if len(parts) >= 2:
            # 提取voice_id，例如 "coze|7426720361732915209|xiaoyi-Female|https://...|preview_text|emotions" -> "7426720361732915209"
            voice_id = parts[1]
            # 提取preview_audio URL (parts[3])
            preview_audio = parts[3] if len(parts) > 3 else ""
            # 提取preview_text (parts[4])
            preview_text = parts[4] if len(parts) > 4 else ""
            # 使用传入的emotion参数
            result = coze_tts(text, voice_id, voice_rate, voice_file, voice_volume, preview_audio, preview_text, emotion, is_preview)
        else:
            logger.error(f"Invalid coze voice name format: {voice_name}")
            result = None
    elif is_qwen_voice(voice_name):
        # 从voice_name中提取voice_id、preview_audio和preview_text
        # 格式: qwen|voice_id|voice_name-gender|preview_audio|preview_text
        parts = voice_name.split("|")
        if len(parts) >= 2:
            # 提取voice_id，例如 "qwen|7426720361732915209|xiaoyi-Female|https://...|preview_text" -> "7426720361732915209"
            voice_id = parts[1]
            # 提取preview_audio URL (parts[3])
            preview_audio = parts[3] if len(parts) > 3 else ""
            # 提取preview_text (parts[4])
            preview_text = parts[4] if len(parts) > 4 else ""
            result = qwen_tts(text, voice_id, voice_rate, voice_file, voice_volume, preview_audio, preview_text, is_preview)
        else:
            logger.error(f"Invalid qwen voice name format: {voice_name}")
            result = None
    else:
        # Default to Azure TTS v1 (Edge TTS)
        logger.info(f"[TTS] Using Azure TTS v1 for voice: {voice_name}")
        result = azure_tts_v1(text, voice_name, voice_rate, voice_file, voice_volume)
    
    # Apply volume adjustment to the generated audio file if needed
    if result is not None and voice_volume != 1.0 and os.path.exists(voice_file):
        try:
            from moviepy import AudioFileClip
            logger.info(f"Applying volume adjustment: {voice_volume}x")
            audio_clip = AudioFileClip(voice_file)
            # Apply volume multiplier
            audio_clip = audio_clip.volumex(voice_volume)
            # Write back to the same file
            temp_file = voice_file + ".temp.mp3"
            audio_clip.write_audiofile(temp_file, codec='mp3')
            audio_clip.close()
            # Replace original file with adjusted one
            os.replace(temp_file, voice_file)
            logger.info(f"Volume adjustment applied successfully")
        except Exception as e:
            logger.warning(f"Failed to apply volume adjustment: {e}")
    
    return result


def convert_rate_to_percent(rate: float) -> str:
    if rate == 1.0:
        return "+0%"
    percent = round((rate - 1.0) * 100)
    if percent > 0:
        return f"+{percent}%"
    else:
        return f"{percent}%"


def azure_tts_v1(
    text: str, voice_name: str, voice_rate: float, voice_file: str, voice_volume: float = 1.0
) -> Union[SubMaker, None]:
    voice_name = parse_voice_name(voice_name)
    text = text.strip()
    rate_str = convert_rate_to_percent(voice_rate)
    for i in range(3):
        try:
            logger.info(f"start, voice name: {voice_name}, try: {i + 1}")

            async def _do() -> SubMaker:
                communicate = edge_tts.Communicate(text, voice_name, rate=rate_str)
                sub_maker = edge_tts.SubMaker()
                with open(voice_file, "wb") as file:
                    async for chunk in communicate.stream():
                        if chunk["type"] == "audio":
                            file.write(chunk["data"])
                        elif chunk["type"] == "WordBoundary":
                            sub_maker.create_sub(
                                (chunk["offset"], chunk["duration"]), chunk["text"]
                            )
                return sub_maker

            sub_maker = asyncio.run(_do())
            if not sub_maker or not sub_maker.subs:
                logger.warning("failed, sub_maker is None or sub_maker.subs is None")
                continue

            logger.info(f"completed, output file: {voice_file}")
            return sub_maker
        except Exception as e:
            logger.error(f"failed, error: {str(e)}")
    return None


def siliconflow_tts(
    text: str,
    model: str,
    voice: str,
    voice_rate: float,
    voice_file: str,
    voice_volume: float = 1.0,
) -> Union[SubMaker, None]:
    """
    使用硅基流动的API生成语音

    Args:
        text: 要转换为语音的文本
        model: 模型名称，如 "FunAudioLLM/CosyVoice2-0.5B"
        voice: 声音名称，如 "FunAudioLLM/CosyVoice2-0.5B:alex"
        voice_rate: 语音速度，范围[0.25, 4.0]
        voice_file: 输出的音频文件路径
        voice_volume: 语音音量，范围[0.6, 5.0]，需要转换为硅基流动的增益范围[-10, 10]

    Returns:
        SubMaker对象或None
    """
    text = text.strip()
    api_key = config.siliconflow.get("api_key", "")

    if not api_key:
        logger.error("SiliconFlow API key is not set")
        return None

    # 将voice_volume转换为硅基流动的增益范围
    # 默认voice_volume为1.0，对应gain为0
    gain = voice_volume - 1.0
    # 确保gain在[-10, 10]范围内
    gain = max(-10, min(10, gain))

    url = "https://api.siliconflow.cn/v1/audio/speech"

    payload = {
        "model": model,
        "input": text,
        "voice": voice,
        "response_format": "mp3",
        "sample_rate": 32000,
        "stream": False,
        "speed": voice_rate,
        "gain": gain,
    }

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    for i in range(3):  # 尝试3次
        try:
            logger.info(
                f"start siliconflow tts, model: {model}, voice: {voice}, try: {i + 1}"
            )

            response = requests.post(url, json=payload, headers=headers)

            if response.status_code == 200:
                # 保存音频文件
                with open(voice_file, "wb") as f:
                    f.write(response.content)

                # 创建一个空的SubMaker对象
                sub_maker = SubMaker()

                # 获取音频文件的实际长度
                try:
                    # 尝试使用moviepy获取音频长度
                    from moviepy import AudioFileClip

                    audio_clip = AudioFileClip(voice_file)
                    audio_duration = audio_clip.duration
                    audio_clip.close()

                    # 将音频长度转换为100纳秒单位（与edge_tts兼容）
                    audio_duration_100ns = int(audio_duration * 10000000)

                    # 使用文本分割来创建更准确的字幕
                    # 将文本按标点符号分割成句子
                    sentences = utils.split_string_by_punctuations(text)

                    if sentences:
                        # 计算每个句子的大致时长（按字符数比例分配）
                        total_chars = sum(len(s) for s in sentences)
                        char_duration = (
                            audio_duration_100ns / total_chars if total_chars > 0 else 0
                        )

                        current_offset = 0
                        for sentence in sentences:
                            if not sentence.strip():
                                continue

                            # 计算当前句子的时长
                            sentence_chars = len(sentence)
                            sentence_duration = int(sentence_chars * char_duration)

                            # 添加到SubMaker
                            sub_maker.subs.append(sentence)
                            sub_maker.offset.append(
                                (current_offset, current_offset + sentence_duration)
                            )

                            # 更新偏移量
                            current_offset += sentence_duration
                    else:
                        # 如果无法分割，则使用整个文本作为一个字幕
                        sub_maker.subs = [text]
                        sub_maker.offset = [(0, audio_duration_100ns)]

                except Exception as e:
                    logger.warning(f"Failed to create accurate subtitles: {str(e)}")
                    # 回退到简单的字幕
                    sub_maker.subs = [text]
                    # 使用音频文件的实际长度，如果无法获取，则假设为10秒
                    sub_maker.offset = [
                        (
                            0,
                            audio_duration_100ns
                            if "audio_duration_100ns" in locals()
                            else 10000000,
                        )
                    ]

                logger.success(f"siliconflow tts succeeded: {voice_file}")
                print("s", sub_maker.subs, sub_maker.offset)
                return sub_maker
            else:
                logger.error(
                    f"siliconflow tts failed with status code {response.status_code}: {response.text}"
                )
        except Exception as e:
            logger.error(f"siliconflow tts failed: {str(e)}")

    return None


def azure_tts_v2(text: str, voice_name: str, voice_file: str) -> Union[SubMaker, None]:
    voice_name = is_azure_v2_voice(voice_name)
    if not voice_name:
        logger.error(f"invalid voice name: {voice_name}")
        raise ValueError(f"invalid voice name: {voice_name}")
    text = text.strip()

    def _format_duration_to_offset(duration) -> int:
        if isinstance(duration, str):
            time_obj = datetime.strptime(duration, "%H:%M:%S.%f")
            milliseconds = (
                (time_obj.hour * 3600000)
                + (time_obj.minute * 60000)
                + (time_obj.second * 1000)
                + (time_obj.microsecond // 1000)
            )
            return milliseconds * 10000

        if isinstance(duration, int):
            return duration

        return 0

    for i in range(3):
        try:
            logger.info(f"start, voice name: {voice_name}, try: {i + 1}")

            import azure.cognitiveservices.speech as speechsdk

            sub_maker = SubMaker()

            def speech_synthesizer_word_boundary_cb(evt: speechsdk.SessionEventArgs):
                # print('WordBoundary event:')
                # print('\tBoundaryType: {}'.format(evt.boundary_type))
                # print('\tAudioOffset: {}ms'.format((evt.audio_offset + 5000)))
                # print('\tDuration: {}'.format(evt.duration))
                # print('\tText: {}'.format(evt.text))
                # print('\tTextOffset: {}'.format(evt.text_offset))
                # print('\tWordLength: {}'.format(evt.word_length))

                duration = _format_duration_to_offset(str(evt.duration))
                offset = _format_duration_to_offset(evt.audio_offset)
                sub_maker.subs.append(evt.text)
                sub_maker.offset.append((offset, offset + duration))

            # Creates an instance of a speech config with specified subscription key and service region.
            speech_key = config.azure.get("speech_key", "")
            service_region = config.azure.get("speech_region", "")
            if not speech_key or not service_region:
                logger.error("Azure speech key or region is not set")
                return None

            audio_config = speechsdk.audio.AudioOutputConfig(
                filename=voice_file, use_default_speaker=True
            )
            speech_config = speechsdk.SpeechConfig(
                subscription=speech_key, region=service_region
            )
            speech_config.speech_synthesis_voice_name = voice_name
            # speech_config.set_property(property_id=speechsdk.PropertyId.SpeechServiceResponse_RequestSentenceBoundary,
            #                            value='true')
            speech_config.set_property(
                property_id=speechsdk.PropertyId.SpeechServiceResponse_RequestWordBoundary,
                value="true",
            )

            speech_config.set_speech_synthesis_output_format(
                speechsdk.SpeechSynthesisOutputFormat.Audio48Khz192KBitRateMonoMp3
            )
            speech_synthesizer = speechsdk.SpeechSynthesizer(
                audio_config=audio_config, speech_config=speech_config
            )
            speech_synthesizer.synthesis_word_boundary.connect(
                speech_synthesizer_word_boundary_cb
            )

            result = speech_synthesizer.speak_text_async(text).get()
            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                logger.success(f"azure v2 speech synthesis succeeded: {voice_file}")
                return sub_maker
            elif result.reason == speechsdk.ResultReason.Canceled:
                cancellation_details = result.cancellation_details
                logger.error(
                    f"azure v2 speech synthesis canceled: {cancellation_details.reason}"
                )
                if cancellation_details.reason == speechsdk.CancellationReason.Error:
                    logger.error(
                        f"azure v2 speech synthesis error: {cancellation_details.error_details}"
                    )
            logger.info(f"completed, output file: {voice_file}")
        except Exception as e:
            logger.error(f"failed, error: {str(e)}")
    return None


def gemini_tts(
    text: str,
    voice_name: str,
    voice_rate: float,
    voice_file: str,
    voice_volume: float = 1.0,
) -> Union[SubMaker, None]:
    """
    使用Google Gemini TTS生成语音
    
    Args:
        text: 要转换的文本
        voice_name: 语音名称，如 "Zephyr", "Puck" 等
        voice_rate: 语音速率（当前未使用）
        voice_file: 输出音频文件路径
        voice_volume: 音频音量（当前未使用）
        
    Returns:
        SubMaker对象或None
    """
    import base64
    import json
    import io
    from pydub import AudioSegment
    import google.generativeai as genai
    
    try:
        # 配置Gemini API
        api_key = config.app.get("gemini_api_key", "")
        if not api_key:
            logger.error("Gemini API key is not set")
            return None
            
        genai.configure(api_key=api_key)
        
        logger.info(f"start, voice name: {voice_name}, try: 1")
        
        # 使用Gemini TTS API
        model = genai.GenerativeModel("gemini-2.5-flash-preview-tts")
        
        generation_config = {
            "response_modalities": ["AUDIO"],
            "speech_config": {
                "voice_config": {
                    "prebuilt_voice_config": {
                        "voice_name": voice_name
                    }
                }
            }
        }
        
        response = model.generate_content(
            contents=text,
            generation_config=generation_config
        )
        
        # 检查响应
        if not response.candidates or not response.candidates[0].content:
            logger.error("No audio content received from Gemini TTS")
            return None
            
        # 获取音频数据
        audio_data = None
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'inline_data') and part.inline_data:
                audio_data = part.inline_data.data
                break
                
        if not audio_data:
            logger.error("No audio data found in response")
            return None
            
        # 音频数据已经是原始字节，不需要base64解码
        if isinstance(audio_data, str):
            # 如果是字符串，则需要base64解码
            audio_bytes = base64.b64decode(audio_data)
        else:
            # 如果已经是字节，直接使用
            audio_bytes = audio_data
        
        # 尝试不同的音频格式 - Gemini可能返回不同的格式
        audio_segment = None
        
        # Gemini返回Linear PCM格式，按照文档参数解析
        try:
            audio_segment = AudioSegment.from_file(
                io.BytesIO(audio_bytes), 
                format="raw",
                frame_rate=24000,  # Gemini TTS默认采样率
                channels=1,        # 单声道
                sample_width=2     # 16-bit
            )
        except Exception as e:
            logger.error(f"Failed to load PCM audio: {e}")
            return None
        
        # 导出为MP3格式
        audio_segment.export(voice_file, format="mp3")
        
        logger.info(f"completed, output file: {voice_file}")
        
        # 创建SubMaker对象用于字幕
        sub_maker = SubMaker()
        audio_duration = len(audio_segment) / 1000.0  # 转换为秒
        
        # 将音频长度转换为100纳秒单位（与edge_tts兼容）
        audio_duration_100ns = int(audio_duration * 10000000)
        
        # 使用create_sub方法正确创建字幕项
        sub_maker.create_sub(
            (0, audio_duration_100ns), 
            text
        )
        
        return sub_maker
        
    except ImportError as e:
        logger.error(f"Missing required package for Gemini TTS: {str(e)}. Please install: pip install pydub")
        return None
    except Exception as e:
        logger.error(f"Gemini TTS failed, error: {str(e)}")
        return None


def coze_tts(
    text: str,
    voice_id: str,
    voice_rate: float,
    voice_file: str,
    voice_volume: float = 1.0,
    preview_audio: str = "",
    preview_text: str = "",
    emotion: str = "",
    is_preview: bool = False,
) -> Union[SubMaker, None]:
    """
    使用Coze TTS生成语音
    
    Args:
        text: 要转换的文本
        voice_id: 语音ID，如 "7426720361732915209", "7426720361732915210" 等
        voice_rate: 语音速率
        voice_file: 输出音频文件路径
        voice_volume: 音频音量
        preview_audio: 预览音频URL（用于试听）
        preview_text: 预览文本（用于匹配试听）
        emotion: 语音情感（如果支持）
        
    Returns:
        SubMaker对象或None
    """
    import io
    
    try:
        from pydub import AudioSegment
    except ImportError as e:
        logger.error(f"Failed to import pydub: {str(e)}")
        logger.error("Please install pydub and its dependencies: pip install pydub")
        return None
    
    try:
        # 只有在试听时才使用预览音频
        # 试听时传入的文本就是预览文本本身，且长度较短
        # 正式生成时，即使文本较短，也应该使用TTS API生成
        is_preview_mode = is_preview and preview_text and text.strip() == preview_text.strip()
        
        if preview_audio and is_preview_mode:
            logger.info(f"Preview mode: downloading preview audio from: {preview_audio}")
            try:
                response = requests.get(preview_audio, timeout=30)
                if response.status_code == 200:
                    with open(voice_file, "wb") as f:
                        f.write(response.content)
                    logger.info(f"Preview audio saved to: {voice_file}")
                    # 预览音频时不需要创建字幕，直接返回None
                    return None
                else:
                    logger.error(f"Failed to download preview audio: {response.status_code}")
            except Exception as e:
                logger.error(f"Error downloading preview audio: {str(e)}")
            # If download fails, continue trying TTS API
        
        # 配置Coze API
        api_key = config.coze.get("api_key", "")
        if not api_key:
            logger.error("Coze API key is not set")
            return None
        
        # Coze TTS API endpoint
        url = "https://api.coze.cn/v1/audio/speech"
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        # Text segmentation processing - Coze API has length limit
        # Split text by punctuation, each segment not exceeding 1024 characters
        max_segment_length = 1024
        segments = []
        
        if len(text) <= max_segment_length:
            # Text length within limit, process directly
            segments = [text]
        else:
            # Text length exceeds limit, need segmentation
            logger.info(f"Text length {len(text)} exceeds Coze API limit, splitting into segments")
            
            # Use utils.split_string_by_punctuations to split text
            sentences = utils.split_string_by_punctuations(text)
            
            current_segment = ""
            for sentence in sentences:
                if len(current_segment) + len(sentence) + 1 <= max_segment_length:
                    # Current segment plus new sentence won't exceed limit, add to current segment
                    if current_segment:
                        current_segment += " " + sentence
                    else:
                        current_segment = sentence
                else:
                    # Current segment plus new sentence will exceed limit, save current segment and start new segment
                    if current_segment:
                        segments.append(current_segment)
                    current_segment = sentence
            
            # Save the last segment
            if current_segment:
                segments.append(current_segment)
            
            logger.info(f"Split text into {len(segments)} segments")
        
        # Process each text segment
        audio_segments = []
        for i, segment in enumerate(segments):
            logger.info(f"Processing segment {i+1}/{len(segments)}, length: {len(segment)}")
            
            # Build request parameters - use correct parameter names and types
            payload = {
                "voice_id": voice_id,
                "speed": float(voice_rate),  # Coze API expects float
                "sample_rate": 8000,  # Default sample rate
                "input": segment,  # Use input parameter instead of text
                "language_code": "zh"  # Apply Chinese language code for all Coze voices
            }
            
            # If emotion parameter is provided, add to request
            if emotion:
                payload["emotion"] = emotion
            
            # Send request
            response = requests.post(url, json=payload, headers=headers)
            
            # Record complete API response information (for debugging)
            logger.info(f"Coze TTS API response status for segment {i+1}: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"Coze TTS API response body for segment {i+1}: {response.text}")
                return None
            
            # Get audio data
            audio_bytes = response.content
            
            # Try different audio formats - Coze may return different formats
            try:
                # Try to load audio directly
                audio_segment = AudioSegment.from_file(
                    io.BytesIO(audio_bytes),
                    format="mp3"  # Assume Coze returns MP3 format
                )
                audio_segments.append(audio_segment)
            except Exception as e:
                logger.error(f"Failed to load audio for segment {i+1}: {e}")
                logger.error(f"Audio data length: {len(audio_bytes)} bytes")
                return None
        
        # Merge audio segments and apply volume adjustment
        if len(audio_segments) == 1:
            # Only one segment, apply volume and export
            audio_segment = audio_segments[0]
            if voice_volume != 1.0:
                logger.info(f"Applying volume adjustment in Coze TTS: {voice_volume}x")
                # pydub uses dB, convert volume multiplier to dB
                # volume_multiplier = 10^(dB/20) => dB = 20*log10(volume_multiplier)
                import math
                volume_change_db = 20 * math.log10(voice_volume)
                audio_segment = audio_segment + volume_change_db
            audio_segment.export(voice_file, format="mp3")
        else:
            # Multiple segments, merge, apply volume, and export
            logger.info(f"Merging {len(audio_segments)} audio segments")
            combined = audio_segments[0]
            for i in range(1, len(audio_segments)):
                combined += audio_segments[i]
            
            if voice_volume != 1.0:
                logger.info(f"Applying volume adjustment in Coze TTS: {voice_volume}x")
                import math
                volume_change_db = 20 * math.log10(voice_volume)
                combined = combined + volume_change_db
            
            combined.export(voice_file, format="mp3")
        
        logger.info(f"completed, output file: {voice_file}")
        
        # Coze TTS只负责音频生成，字幕由Whisper生成
        # 返回None，让generate_subtitle函数使用Whisper生成字幕
        return None
        
    except ImportError as e:
        logger.error(f"Missing required package for Coze TTS: {str(e)}. Please install: pip install pydub")
        return None
    except Exception as e:
        logger.error(f"Coze TTS failed, error: {str(e)}")
        return None


def qwen_tts(
    text: str,
    voice_id: str,
    voice_rate: float,
    voice_file: str,
    voice_volume: float = 1.0,
    preview_audio: str = "",
    preview_text: str = "",
    is_preview: bool = False,
) -> Union[SubMaker, None]:
    """
    使用Qwen TTS生成语音
    
    Args:
        text: 要转换的文本
        voice_id: 语音ID，如 "7426720361732915209", "7426720361732915210" 等
        voice_rate: 语音速率
        voice_file: 输出音频文件路径
        voice_volume: 音频音量
        preview_audio: 预览音频URL（用于试听）
        preview_text: 预览文本（用于匹配试听）
        
    Returns:
        SubMaker对象或None
    """
    import io
    
    try:
        from pydub import AudioSegment
    except ImportError as e:
        logger.error(f"Failed to import pydub: {str(e)}")
        logger.error("Please install pydub and its dependencies: pip install pydub")
        return None
    
    try:
        # 只有在试听时才使用预览音频
        is_preview_mode = is_preview and preview_text and text.strip() == preview_text.strip()
        
        if preview_audio and is_preview_mode:
            logger.info(f"Preview mode: downloading preview audio from: {preview_audio}")
            try:
                response = requests.get(preview_audio, timeout=30)
                if response.status_code == 200:
                    with open(voice_file, "wb") as f:
                        f.write(response.content)
                    logger.info(f"Preview audio saved to: {voice_file}")
                    return None
                else:
                    logger.error(f"Failed to download preview audio: {response.status_code}")
            except Exception as e:
                logger.error(f"Error downloading preview audio: {str(e)}")
        
        # 配置Qwen API (使用HTTP API)
        api_key = config.qwen.get("api_key", "")
        base_url = "https://dashscope.aliyuncs.com/api/v1"  # 硬编码Qwen API端点
        
        if not api_key:
            logger.warning("Qwen API key is not set, using text-to-speech fallback")
            return None
        
        logger.info(f"Using Qwen TTS with base_url: {base_url}")
        
        # Text segmentation processing - Qwen API limit is typically 5000 characters
        max_segment_length = 5000
        segments = []
        
        if len(text) <= max_segment_length:
            segments = [text]
        else:
            logger.info(f"Text length {len(text)} exceeds Qwen API limit, splitting into segments")
            sentences = utils.split_string_by_punctuations(text)
            
            current_segment = ""
            for sentence in sentences:
                if len(current_segment) + len(sentence) + 1 <= max_segment_length:
                    if current_segment:
                        current_segment += " " + sentence
                    else:
                        current_segment = sentence
                else:
                    if current_segment:
                        segments.append(current_segment)
                    current_segment = sentence
            
            if current_segment:
                segments.append(current_segment)
            
            logger.info(f"Split text into {len(segments)} segments")
        
        # Process each text segment
        audio_segments = []
        for i, segment in enumerate(segments):
            logger.info(f"Processing segment {i+1}/{len(segments)}, length: {len(segment)}")
            
            try:
                # 使用HTTP API调用Qwen TTS (Qwen-TTS)
                url = f"{base_url}/services/aigc/multimodal-generation/generation"
                
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
                
                payload = {
                    "model": "qwen3-tts-flash",
                    "input": {
                        "text": segment,
                        "voice": voice_id
                    },
                    "parameters": {
                        "format": "mp3",
                        "sample_rate": 24000
                    }
                }
                
                logger.info(f"Qwen TTS API request URL: {url}")
                
                response = requests.post(url, json=payload, headers=headers, timeout=30)
                
                logger.info(f"Qwen TTS API response status: {response.status_code}")
                
                if response.status_code == 200:
                    try:
                        response_data = response.json()
                        logger.debug(f"Qwen TTS response: {response_data}")
                        
                        if response_data.get("output") and response_data["output"].get("audio"):
                            audio_output = response_data["output"]["audio"]
                            logger.debug(f"Audio output: {audio_output}")
                            
                            audio_url = audio_output.get("url") if isinstance(audio_output, dict) else getattr(audio_output, 'url', None)
                            audio_data = audio_output.get("data") if isinstance(audio_output, dict) else getattr(audio_output, 'data', None)
                            
                            if audio_url:
                                # 下载音频文件
                                logger.info(f"Downloading audio from URL: {audio_url}")
                                audio_response = requests.get(audio_url, timeout=30)
                                if audio_response.status_code == 200:
                                    audio_bytes = audio_response.content
                                    logger.info(f"Downloaded audio, size: {len(audio_bytes)} bytes")
                                    try:
                                        audio_segment = AudioSegment.from_file(
                                            io.BytesIO(audio_bytes)
                                        )
                                        audio_segments.append(audio_segment)
                                        logger.info(f"Successfully decoded audio for segment {i+1}")
                                    except Exception as e:
                                        logger.error(f"Failed to decode audio: {e}")
                                        # 尝试保存到文件调试
                                        temp_file = "qwen_debug_audio.mp3"
                                        with open(temp_file, 'wb') as f:
                                            f.write(audio_bytes)
                                        logger.info(f"Saved audio to {temp_file} for debugging")
                                        return None
                                else:
                                    logger.error(f"Failed to download audio: {audio_response.status_code}")
                                    return None
                            elif audio_data:
                                # 解码base64音频数据
                                logger.info(f"Decoding base64 audio, data size: {len(audio_data)} chars")
                                import base64
                                audio_bytes = base64.b64decode(audio_data)
                                audio_segment = AudioSegment.from_file(
                                    io.BytesIO(audio_bytes)
                                )
                                audio_segments.append(audio_segment)
                                logger.info(f"Decoded base64 audio for segment {i+1}")
                            else:
                                logger.error(f"No audio URL or data in response for segment {i+1}")
                                return None
                        else:
                            logger.error(f"Invalid response format for segment {i+1}")
                            return None
                    except (ValueError, KeyError) as e:
                        logger.error(f"Failed to parse Qwen TTS response: {e}")
                        return None
                else:
                    error_msg = f"Qwen TTS API failed: {response.status_code}"
                    if response.text:
                        error_msg += f" - {response.text[:500]}"
                    logger.error(error_msg)
                    return None
                    
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Qwen TTS API exception for segment {i+1}: {error_msg}")
                return None
        
        # Merge audio segments and apply volume adjustment
        if len(audio_segments) == 1:
            audio_segment = audio_segments[0]
            if voice_volume != 1.0:
                logger.info(f"Applying volume adjustment in Qwen TTS: {voice_volume}x")
                import math
                volume_change_db = 20 * math.log10(voice_volume)
                audio_segment = audio_segment + volume_change_db
            audio_segment.export(voice_file, format="mp3")
        else:
            logger.info(f"Merging {len(audio_segments)} audio segments")
            combined = audio_segments[0]
            for i in range(1, len(audio_segments)):
                combined += audio_segments[i]
            
            if voice_volume != 1.0:
                logger.info(f"Applying volume adjustment in Qwen TTS: {voice_volume}x")
                import math
                volume_change_db = 20 * math.log10(voice_volume)
                combined = combined + volume_change_db
            
            combined.export(voice_file, format="mp3")
        
        logger.info(f"completed, output file: {voice_file}")
        
        # Qwen TTS只负责音频生成，字幕由Whisper生成
        return None
        
    except ImportError as e:
        logger.error(f"Missing required package for Qwen TTS: {str(e)}. Please install: pip install pydub")
        return None
    except Exception as e:
        logger.error(f"Qwen TTS failed, error: {str(e)}")
        return None


def _format_text(text: str) -> str:
    # text = text.replace("\n", " ")
    text = text.replace("[", " ")
    text = text.replace("]", " ")
    text = text.replace("(", " ")
    text = text.replace(")", " ")
    text = text.replace("{", " ")
    text = text.replace("}", " ")
    text = text.strip()
    return text


def create_subtitle(sub_maker: submaker.SubMaker, text: str, subtitle_file: str):
    """
    优化字幕文件
    1. 将字幕文件按照标点符号分割成多行
    2. 逐行匹配字幕文件中的文本
    3. 生成新的字幕文件
    """

    text = _format_text(text)

    def formatter(idx: int, start_time: float, end_time: float, sub_text: str) -> str:
        """
        1
        00:00:00,000 --> 00:00:02,360
        跑步是一项简单易行的运动
        """
        start_t = mktimestamp(start_time).replace(".", ",")
        end_t = mktimestamp(end_time).replace(".", ",")
        return f"{idx}\n{start_t} --> {end_t}\n{sub_text}\n"

    start_time = -1.0
    sub_items = []
    sub_index = 0

    script_lines = utils.split_string_by_punctuations(text)

    def match_line(_sub_line: str, _sub_index: int):
        if len(script_lines) <= _sub_index:
            return ""

        _line = script_lines[_sub_index]
        if _sub_line == _line:
            return script_lines[_sub_index].strip()

        _sub_line_ = re.sub(r"[^\w\s]", "", _sub_line)
        _line_ = re.sub(r"[^\w\s]", "", _line)
        if _sub_line_ == _line_:
            return _line_.strip()

        _sub_line_ = re.sub(r"\W+", "", _sub_line)
        _line_ = re.sub(r"\W+", "", _line)
        if _sub_line_ == _line_:
            return _line.strip()

        return ""

    sub_line = ""

    try:
        for _, (offset, sub) in enumerate(zip(sub_maker.offset, sub_maker.subs)):
            _start_time, end_time = offset
            if start_time < 0:
                start_time = _start_time

            sub = unescape(sub)
            sub_line += sub
            sub_text = match_line(sub_line, sub_index)
            if sub_text:
                sub_index += 1
                line = formatter(
                    idx=sub_index,
                    start_time=start_time,
                    end_time=end_time,
                    sub_text=sub_text,
                )
                sub_items.append(line)
                start_time = -1.0
                sub_line = ""

        if len(sub_items) == len(script_lines):
            with open(subtitle_file, "w", encoding="utf-8") as file:
                file.write("\n".join(sub_items) + "\n")
            try:
                sbs = subtitles.file_to_subtitles(subtitle_file, encoding="utf-8")
                duration = max([tb for ((ta, tb), txt) in sbs])
                logger.info(
                    f"completed, subtitle file created: {subtitle_file}, duration: {duration}"
                )
            except Exception as e:
                logger.error(f"failed, error: {str(e)}")
                os.remove(subtitle_file)
        else:
            logger.warning(
                f"failed, sub_items len: {len(sub_items)}, script_lines len: {len(script_lines)}"
            )

    except Exception as e:
        logger.error(f"failed, error: {str(e)}")


def _get_audio_duration_from_submaker(sub_maker: submaker.SubMaker):
    """
    获取音频时长
    """
    if not sub_maker.offset:
        return 0.0
    return sub_maker.offset[-1][1] / 10000000

def _get_audio_duration_from_mp3(mp3_file: str) -> float:
    """
    获取MP3音频时长
    """
    if not os.path.exists(mp3_file):
        logger.error(f"MP3 file does not exist: {mp3_file}")
        return 0.0

    try:
        # Use moviepy to get the duration of the MP3 file
        with AudioFileClip(mp3_file) as audio:
            return audio.duration  # Duration in seconds
    except Exception as e:
        logger.error(f"Failed to get audio duration from MP3: {str(e)}")
        return 0.0

def get_audio_duration( target: Union[str, submaker.SubMaker]) -> float:
    """
    获取音频时长
    如果是SubMaker对象，则从SubMaker中获取时长
    如果是MP3文件，则从MP3文件中获取时长
    """
    if isinstance(target, submaker.SubMaker):
        return _get_audio_duration_from_submaker(target)
    elif isinstance(target, str) and target.endswith(".mp3"):
        return _get_audio_duration_from_mp3(target)
    else:
        logger.error(f"Invalid target type: {type(target)}")
        return 0.0

if __name__ == "__main__":
    voice_name = "zh-CN-XiaoxiaoMultilingualNeural-V2-Female"
    voice_name = parse_voice_name(voice_name)
    voice_name = is_azure_v2_voice(voice_name)
    print(voice_name)

    voices = get_all_azure_voices()
    print(len(voices))

    async def _do():
        temp_dir = utils.storage_dir("temp")

        voice_names = [
            "zh-CN-XiaoxiaoMultilingualNeural",
            # 女性
            "zh-CN-XiaoxiaoNeural",
            "zh-CN-XiaoyiNeural",
            # 男性
            "zh-CN-YunyangNeural",
            "zh-CN-YunxiNeural",
        ]
        text = """
        静夜思是唐代诗人李白创作的一首五言古诗。这首诗描绘了诗人在寂静的夜晚，看到窗前的明月，不禁想起远方的家乡和亲人，表达了他对家乡和亲人的深深思念之情。全诗内容是：“床前明月光，疑是地上霜。举头望明月，低头思故乡。”在这短短的四句诗中，诗人通过“明月”和“思故乡”的意象，巧妙地表达了离乡背井人的孤独与哀愁。首句“床前明月光”设景立意，通过明亮的月光引出诗人的遐想；“疑是地上霜”增添了夜晚的寒冷感，加深了诗人的孤寂之情；“举头望明月”和“低头思故乡”则是情感的升华，展现了诗人内心深处的乡愁和对家的渴望。这首诗简洁明快，情感真挚，是中国古典诗歌中非常著名的一首，也深受后人喜爱和推崇。
            """

        text = """
        What is the meaning of life? This question has puzzled philosophers, scientists, and thinkers of all kinds for centuries. Throughout history, various cultures and individuals have come up with their interpretations and beliefs around the purpose of life. Some say it's to seek happiness and self-fulfillment, while others believe it's about contributing to the welfare of others and making a positive impact in the world. Despite the myriad of perspectives, one thing remains clear: the meaning of life is a deeply personal concept that varies from one person to another. It's an existential inquiry that encourages us to reflect on our values, desires, and the essence of our existence.
        """

        text = """
               预计未来3天深圳冷空气活动频繁，未来两天持续阴天有小雨，出门带好雨具；
               10-11日持续阴天有小雨，日温差小，气温在13-17℃之间，体感阴凉；
               12日天气短暂好转，早晚清凉；
                   """

        text = "[Opening scene: A sunny day in a suburban neighborhood. A young boy named Alex, around 8 years old, is playing in his front yard with his loyal dog, Buddy.]\n\n[Camera zooms in on Alex as he throws a ball for Buddy to fetch. Buddy excitedly runs after it and brings it back to Alex.]\n\nAlex: Good boy, Buddy! You're the best dog ever!\n\n[Buddy barks happily and wags his tail.]\n\n[As Alex and Buddy continue playing, a series of potential dangers loom nearby, such as a stray dog approaching, a ball rolling towards the street, and a suspicious-looking stranger walking by.]\n\nAlex: Uh oh, Buddy, look out!\n\n[Buddy senses the danger and immediately springs into action. He barks loudly at the stray dog, scaring it away. Then, he rushes to retrieve the ball before it reaches the street and gently nudges it back towards Alex. Finally, he stands protectively between Alex and the stranger, growling softly to warn them away.]\n\nAlex: Wow, Buddy, you're like my superhero!\n\n[Just as Alex and Buddy are about to head inside, they hear a loud crash from a nearby construction site. They rush over to investigate and find a pile of rubble blocking the path of a kitten trapped underneath.]\n\nAlex: Oh no, Buddy, we have to help!\n\n[Buddy barks in agreement and together they work to carefully move the rubble aside, allowing the kitten to escape unharmed. The kitten gratefully nuzzles against Buddy, who responds with a friendly lick.]\n\nAlex: We did it, Buddy! We saved the day again!\n\n[As Alex and Buddy walk home together, the sun begins to set, casting a warm glow over the neighborhood.]\n\nAlex: Thanks for always being there to watch over me, Buddy. You're not just my dog, you're my best friend.\n\n[Buddy barks happily and nuzzles against Alex as they disappear into the sunset, ready to face whatever adventures tomorrow may bring.]\n\n[End scene.]"

        text = "大家好，我是乔哥，一个想帮你把信用卡全部还清的家伙！\n今天我们要聊的是信用卡的取现功能。\n你是不是也曾经因为一时的资金紧张，而拿着信用卡到ATM机取现？如果是，那你得好好看看这个视频了。\n现在都2024年了，我以为现在不会再有人用信用卡取现功能了。前几天一个粉丝发来一张图片，取现1万。\n信用卡取现有三个弊端。\n一，信用卡取现功能代价可不小。会先收取一个取现手续费，比如这个粉丝，取现1万，按2.5%收取手续费，收取了250元。\n二，信用卡正常消费有最长56天的免息期，但取现不享受免息期。从取现那一天开始，每天按照万5收取利息，这个粉丝用了11天，收取了55元利息。\n三，频繁的取现行为，银行会认为你资金紧张，会被标记为高风险用户，影响你的综合评分和额度。\n那么，如果你资金紧张了，该怎么办呢？\n乔哥给你支一招，用破思机摩擦信用卡，只需要少量的手续费，而且还可以享受最长56天的免息期。\n最后，如果你对玩卡感兴趣，可以找乔哥领取一本《卡神秘籍》，用卡过程中遇到任何疑惑，也欢迎找乔哥交流。\n别忘了，关注乔哥，回复用卡技巧，免费领取《2024用卡技巧》，让我们一起成为用卡高手！"

        text = """
        2023全年业绩速览
公司全年累计实现营业收入1476.94亿元，同比增长19.01%，归母净利润747.34亿元，同比增长19.16%。EPS达到59.49元。第四季度单季，营业收入444.25亿元，同比增长20.26%，环比增长31.86%；归母净利润218.58亿元，同比增长19.33%，环比增长29.37%。这一阶段
的业绩表现不仅突显了公司的增长动力和盈利能力，也反映出公司在竞争激烈的市场环境中保持了良好的发展势头。
2023年Q4业绩速览
第四季度，营业收入贡献主要增长点；销售费用高增致盈利能力承压；税金同比上升27%，扰动净利率表现。
业绩解读
利润方面，2023全年贵州茅台，>归母净利润增速为19%，其中营业收入正贡献18%，营业成本正贡献百分之一，管理费用正贡献百分之一点四。(注：归母净利润增速值=营业收入增速+各科目贡献，展示贡献/拖累的前四名科目，且要求贡献值/净利润增速>15%)
"""
        text = "静夜思是唐代诗人李白创作的一首五言古诗。这首诗描绘了诗人在寂静的夜晚，看到窗前的明月，不禁想起远方的家乡和亲人"

        text = _format_text(text)
        lines = utils.split_string_by_punctuations(text)
        print(lines)

        for voice_name in voice_names:
            voice_file = f"{temp_dir}/tts-{voice_name}.mp3"
            subtitle_file = f"{temp_dir}/tts.mp3.srt"
            sub_maker = azure_tts_v2(
                text=text, voice_name=voice_name, voice_file=voice_file
            )
            create_subtitle(sub_maker=sub_maker, text=text, subtitle_file=subtitle_file)
            audio_duration = get_audio_duration(sub_maker)
            print(f"voice: {voice_name}, audio duration: {audio_duration}s")

    loop = asyncio.get_event_loop_policy().get_event_loop()
    try:
        loop.run_until_complete(_do())
    finally:
        loop.close()
