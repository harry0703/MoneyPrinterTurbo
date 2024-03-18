import os.path
from os import path

from loguru import logger

from app.config import config
from app.models.schema import VideoParams, VoiceNames
from app.services import llm, material, voice, video, subtitle
from app.utils import utils


def _parse_voice(name: str):
    # "female-zh-CN-XiaoxiaoNeural",
    # remove first part split by "-"
    if name not in VoiceNames:
        name = VoiceNames[0]

    parts = name.split("-")
    _lang = f"{parts[1]}-{parts[2]}"
    _voice = f"{_lang}-{parts[3]}"

    return _voice, _lang


def start(task_id, params: VideoParams):
    """
    {
        "video_subject": "",
        "video_aspect": "横屏 16:9（西瓜视频）",
        "voice_name": "女生-晓晓",
        "enable_bgm": false,
        "font_name": "STHeitiMedium 黑体-中",
        "text_color": "#FFFFFF",
        "font_size": 60,
        "stroke_color": "#000000",
        "stroke_width": 1.5
    }
    """
    logger.info(f"start task: {task_id}")
    video_subject = params.video_subject
    voice_name, language = _parse_voice(params.voice_name)
    paragraph_number = params.paragraph_number
    n_threads = params.n_threads

    logger.info("\n\n## generating video script")
    script = llm.generate_script(video_subject=video_subject, language=language, paragraph_number=paragraph_number)

    logger.info("\n\n## generating video terms")
    search_terms = llm.generate_terms(video_subject=video_subject, video_script=script, amount=5)

    script_file = path.join(utils.task_dir(task_id), f"script.json")
    script_data = {
        "script": script,
        "search_terms": search_terms
    }

    with open(script_file, "w") as f:
        f.write(utils.to_json(script_data))

    audio_file = path.join(utils.task_dir(task_id), f"audio.mp3")
    subtitle_path = path.join(utils.task_dir(task_id), f"subtitle.srt")

    logger.info("\n\n## generating audio")
    sub_maker = voice.tts(text=script, voice_name=voice_name, voice_file=audio_file)

    subtitle_provider = config.app.get("subtitle_provider", "").strip().lower()
    logger.info(f"\n\n## generating subtitle, provider: {subtitle_provider}")
    subtitle_fallback = False
    if subtitle_provider == "edge":
        voice.create_subtitle(text=script, sub_maker=sub_maker, subtitle_file=subtitle_path)
        if not os.path.exists(subtitle_path):
            subtitle_fallback = True
            logger.warning("subtitle file not found, fallback to whisper")

    if subtitle_provider == "whisper" or subtitle_fallback:
        subtitle.create(audio_file=audio_file, subtitle_file=subtitle_path)
        logger.info("\n\n## correcting subtitle")
        subtitle.correct(subtitle_file=subtitle_path, video_script=script)

    logger.info("\n\n## downloading videos")
    video_paths = material.download_videos(task_id=task_id, search_terms=search_terms, video_aspect=params.video_aspect,
                                           wanted_count=20,
                                           minimum_duration=5)

    logger.info("\n\n## combining videos")
    combined_video_path = path.join(utils.task_dir(task_id), f"combined.mp4")
    video.combine_videos(combined_video_path=combined_video_path,
                         video_paths=video_paths,
                         audio_file=audio_file,
                         video_aspect=params.video_aspect,
                         max_clip_duration=5,
                         threads=n_threads)

    final_video_path = path.join(utils.task_dir(task_id), f"final.mp4")

    bgm_file = video.get_bgm_file(bgm_name=params.bgm_name)
    logger.info("\n\n## generating video")
    # Put everything together
    video.generate_video(video_path=combined_video_path,
                         audio_path=audio_file,
                         subtitle_path=subtitle_path,
                         output_file=final_video_path,

                         video_aspect=params.video_aspect,

                         threads=n_threads,

                         font_name=params.font_name,
                         fontsize=params.font_size,
                         text_fore_color=params.text_fore_color,
                         stroke_color=params.stroke_color,
                         stroke_width=params.stroke_width,

                         bgm_file=bgm_file
                         )
    logger.start(f"task {task_id} finished")
    return {
        "video_file": final_video_path,
    }
