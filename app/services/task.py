import math
import os.path
import re
from os import path

from loguru import logger

from app.config import config
from app.models import const
from app.models.schema import VideoConcatMode, VideoParams
from app.services import llm, material, subtitle, twelvelabs, video, voice, upload_post
from app.services import state as sm
from app.utils import file_security, utils


def generate_script(task_id, params):
    logger.info("\n\n## generating video script")
    video_script = params.video_script.strip()
    if not video_script:
        video_script = llm.generate_script(
            video_subject=params.video_subject,
            language=params.video_language,
            paragraph_number=params.paragraph_number,
            video_script_prompt=params.video_script_prompt,
            custom_system_prompt=params.custom_system_prompt,
        )
    else:
        logger.debug(f"video script: \n{video_script}")

    if not video_script:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error("failed to generate video script.")
        return None

    return video_script


def generate_terms(task_id, params, video_script):
    logger.info("\n\n## generating video terms")
    video_terms = params.video_terms
    if not video_terms:
        # 开启素材按文案顺序匹配后，关键词本身也必须按脚本叙事顺序生成；
        # 否则后续即使顺序下载和顺序拼接，也只能复用一组全局主题词，
        # 无法改善“后面内容的画面提前出现”的问题。
        video_terms = llm.generate_terms(
            video_subject=params.video_subject,
            video_script=video_script,
            amount=8 if params.match_materials_to_script else 5,
            match_script_order=params.match_materials_to_script,
        )
    else:
        if isinstance(video_terms, str):
            video_terms = [term.strip() for term in re.split(r"[,，]", video_terms)]
        elif isinstance(video_terms, list):
            video_terms = [term.strip() for term in video_terms]
        else:
            raise ValueError("video_terms must be a string or a list of strings.")

        logger.debug(f"video terms: {utils.to_json(video_terms)}")

    if not video_terms:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error("failed to generate video terms.")
        return None

    # 可选的 TwelveLabs Marengo 语义重排：未启用时返回原顺序，无任何副作用。
    # 顺序匹配模式下关键词顺序本身就是脚本叙事顺序，必须保持原样，故跳过。
    if not params.match_materials_to_script:
        video_terms = twelvelabs.rerank_terms_by_subject(
            video_subject=params.video_subject,
            search_terms=video_terms,
        )

    return video_terms


def save_script_data(task_id, video_script, video_terms, params):
    script_file = path.join(utils.task_dir(task_id), "script.json")
    script_data = {
        "script": video_script,
        "search_terms": video_terms,
        "params": params,
    }

    with open(script_file, "w", encoding="utf-8") as f:
        f.write(utils.to_json(script_data))


# =============================================================================
# pipeline 阶段产物持久化（manifest.json）
#
# 每个 stop_at 边界（script/terms/audio/subtitle/materials/video）成功后，
# 把该阶段的产物路径与关键字段写入 storage/tasks/<task_id>/manifest.json。
# 这样：
#   1. 失败后可以从最近的 stop_at 边界续跑，不用重算脚本/关键词/音频。
#   2. stop_at 之后的阶段（例如已生成 audio，想继续生成 subtitle/video）
#      可以复用已有产物，节省 LLM 和 TTS 成本。
#   3. 调用方（Agent / API）可以从 manifest 读回任意阶段的产物。
#
# 注意：TTS 返回的 sub_maker 是内存对象，无法序列化。因此 resume 不能跨
# TTS 边界续跑字幕生成——只有 custom_audio_file 路径或 stop_at 在 audio
# 之后的续跑才有效。本版 resume 只支持 stop_at 之后的阶段续跑。
# =============================================================================

_MANIFEST_STAGE_ORDER = [
    "script",
    "terms",
    "audio",
    "subtitle",
    "materials",
    "video",
]


def _manifest_path(task_id) -> str:
    return path.join(utils.task_dir(task_id), "manifest.json")


def _load_manifest(task_id) -> dict:
    """读取任务 manifest，不存在或损坏时返回空 dict。"""
    manifest_file = _manifest_path(task_id)
    if not path.isfile(manifest_file):
        return {}
    try:
        with open(manifest_file, "r", encoding="utf-8") as f:
            import json as _json

            data = _json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        logger.warning(f"failed to load manifest, treating as empty: {manifest_file}")
        return {}


def _update_manifest(task_id, **artifacts):
    """合并写入 manifest。已有字段会被同名参数覆盖。"""
    if not artifacts:
        return
    manifest = _load_manifest(task_id)
    manifest.update(artifacts)
    manifest_file = _manifest_path(task_id)
    try:
        with open(manifest_file, "w", encoding="utf-8") as f:
            import json as _json

            f.write(_json.dumps(manifest, ensure_ascii=False, indent=2))
    except OSError as exc:
        logger.warning(f"failed to persist manifest: {exc}")


def _manifest_stage_completed(task_id, stage: str) -> bool:
    """
    判断 manifest 里某个阶段是否已完成且产物仍可用。

    对于文件类产物（audio_file/subtitle_path/materials），同时检查文件存在性，
    避免 manifest 指向已被删除的文件时误判为已完成。
    """
    manifest = _load_manifest(task_id)
    if stage == "script":
        return bool(manifest.get("script"))
    if stage == "terms":
        return bool(manifest.get("terms"))
    if stage == "audio":
        audio_file = manifest.get("audio_file")
        return bool(audio_file) and path.isfile(audio_file)
    if stage == "subtitle":
        # 字幕可被禁用（subtitle_enabled=False 返回空串），所以用 manifest 里的
        # 标志而非文件存在性判断。
        return manifest.get("subtitle_resolved") is True
    if stage == "materials":
        materials = manifest.get("materials")
        if not materials:
            return False
        return all(path.isfile(m) for m in materials)
    return False





def resolve_custom_audio_file(task_id: str, custom_audio_file: str | None) -> str:
    requested_file = (custom_audio_file or "").strip()
    if not requested_file:
        return ""

    task_dir = utils.task_dir(task_id)
    try:
        return file_security.resolve_path_within_directory(
            task_dir,
            requested_file,
        )
    except ValueError as exc:
        task_dir_error = exc

    server_audio_file = path.realpath(
        requested_file
        if path.isabs(requested_file)
        else path.join(utils.root_dir(), requested_file)
    )
    if not path.isabs(requested_file):
        project_root = path.realpath(utils.root_dir())
        try:
            if path.commonpath([project_root, server_audio_file]) != project_root:
                raise ValueError(
                    "relative custom audio paths must stay within the project directory"
                )
        except ValueError as exc:
            raise ValueError(
                "custom audio file must be task-local or an existing server-side file"
            ) from exc

    if not path.isfile(server_audio_file):
        raise ValueError(
            "custom audio file does not exist or is not a file"
        ) from task_dir_error

    return server_audio_file


def generate_audio(task_id, params, video_script):
    '''
    Generate audio for the video script.
    If a custom audio file is provided, it will be used directly.
    There will be no subtitle maker object returned in this case.
    Otherwise, TTS will be used to generate the audio.
    Returns:
        - audio_file: path to the generated or provided audio file
        - audio_duration: duration of the audio in seconds
        - sub_maker: subtitle maker object if TTS is used, None otherwise
    '''
    logger.info("\n\n## generating audio")
    # /audio 和 /subtitle 请求模型不包含 custom_audio_file，
    # 这里统一做兼容读取，避免直调接口时抛属性错误。
    requested_custom_audio_file = getattr(params, "custom_audio_file", None)
    try:
        custom_audio_file = resolve_custom_audio_file(
            task_id, requested_custom_audio_file
        )
    except ValueError as exc:
        logger.error(
            "custom audio file is invalid, "
            f"task_id: {task_id}, path: {requested_custom_audio_file}, error: {str(exc)}"
        )
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return None, None, None

    if not custom_audio_file:
        logger.info("no custom audio file provided, using TTS to generate audio.")
        audio_file = path.join(utils.task_dir(task_id), "audio.mp3")
        sub_maker = voice.tts(
            text=video_script,
            voice_name=voice.parse_voice_name(params.voice_name),
            voice_rate=params.voice_rate,
            voice_file=audio_file,
        )
        if sub_maker is None:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error(
                """failed to generate audio:
1. check if the language of the voice matches the language of the video script.
2. check if the network is available. If you are in China, it is recommended to use a VPN and enable the global traffic mode.
            """.strip()
            )
            return None, None, None
        audio_duration = math.ceil(voice.get_audio_duration(sub_maker))
        if audio_duration == 0:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error("failed to get audio duration.")
            return None, None, None
        return audio_file, audio_duration, sub_maker
    else:
        logger.info(f"using custom audio file: {custom_audio_file}")
        audio_duration = voice.get_audio_duration(custom_audio_file)
        if audio_duration == 0:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error("failed to get audio duration from custom audio file.")
            return None, None, None
        return custom_audio_file, audio_duration, None

def generate_subtitle(task_id, params, video_script, sub_maker, audio_file):
    '''
    Generate subtitle for the video script.
    If subtitle generation is disabled or no subtitle maker is provided, it will return an empty string.
    Otherwise, it will generate the subtitle using the specified provider.
    Returns:
        - subtitle_path: path to the generated subtitle file
    '''
    logger.info("\n\n## generating subtitle")
    if not params.subtitle_enabled:
        return ""

    subtitle_path = path.join(utils.task_dir(task_id), "subtitle.srt")
    subtitle_provider = config.app.get("subtitle_provider", "edge").strip().lower()
    logger.info(f"\n\n## generating subtitle, provider: {subtitle_provider}")

    if sub_maker is None and subtitle_provider != "whisper":
        # 自定义音频不会经过 TTS，因此没有 Edge/Azure 等 TTS 返回的
        # sub_maker 时间轴。只有 Whisper 可以直接从音频文件转写字幕；
        # 其他字幕提供方继续保持原有行为，避免生成错误的空时间轴。
        logger.warning(
            "subtitle maker is missing, skip subtitle generation for provider: "
            f"{subtitle_provider}"
        )
        return ""

    subtitle_fallback = False
    if subtitle_provider == "edge":
        voice.create_subtitle(
            text=video_script, sub_maker=sub_maker, subtitle_file=subtitle_path
        )
        if not os.path.exists(subtitle_path):
            subtitle_fallback = True
            logger.warning("subtitle file not found, fallback to whisper")

    if subtitle_provider == "whisper" or subtitle_fallback:
        subtitle.create(audio_file=audio_file, subtitle_file=subtitle_path)
        logger.info("\n\n## correcting subtitle")
        subtitle.correct(subtitle_file=subtitle_path, video_script=video_script)

    subtitle_lines = subtitle.file_to_subtitles(subtitle_path)
    if not subtitle_lines:
        logger.warning(f"subtitle file is invalid: {subtitle_path}")
        return ""

    return subtitle_path


def get_video_materials(task_id, params, video_terms, audio_duration):
    if params.video_source == "local":
        logger.info("\n\n## preprocess local materials")
        materials = video.preprocess_video(
            materials=params.video_materials, clip_duration=params.video_clip_duration
        )
        if not materials:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error(
                "no valid materials found, please check the materials and try again."
            )
            return None
        return [material_info.url for material_info in materials]
    else:
        logger.info(f"\n\n## downloading videos from {params.video_source}")
        # 顺序匹配模式只在用户显式开启时生效。这里强制素材下载按关键词顺序
        # 轮询，避免某个早期关键词下载太多素材，把后续脚本主题挤出最终时间线。
        downloaded_videos = material.download_videos(
            task_id=task_id,
            search_terms=video_terms,
            source=params.video_source,
            video_aspect=params.video_aspect,
            video_concat_mode=(
                VideoConcatMode.sequential
                if params.match_materials_to_script
                else params.video_concat_mode
            ),
            audio_duration=audio_duration * params.video_count,
            max_clip_duration=params.video_clip_duration,
            match_script_order=params.match_materials_to_script,
        )
        if not downloaded_videos:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error(
                "failed to download videos, maybe the network is not available. if you are in China, please use a VPN."
            )
            return None
        return downloaded_videos


def generate_final_videos(
    task_id, params, downloaded_videos, audio_file, subtitle_path
):
    final_video_paths = []
    combined_video_paths = []
    # 多视频生成默认会打散素材以增加差异；但“按文案顺序匹配素材”追求的是
    # 时间线稳定性和可解释性，所以开启后所有输出都使用顺序拼接。
    if params.match_materials_to_script:
        video_concat_mode = VideoConcatMode.sequential
    elif params.video_count == 1:
        video_concat_mode = params.video_concat_mode
    else:
        video_concat_mode = VideoConcatMode.random
    video_transition_mode = params.video_transition_mode

    _progress = 50
    for i in range(params.video_count):
        index = i + 1
        combined_video_path = path.join(
            utils.task_dir(task_id), f"combined-{index}.mp4"
        )
        logger.info(f"\n\n## combining video: {index} => {combined_video_path}")
        video.combine_videos(
            combined_video_path=combined_video_path,
            video_paths=downloaded_videos,
            audio_file=audio_file,
            video_aspect=params.video_aspect,
            video_concat_mode=video_concat_mode,
            video_transition_mode=video_transition_mode,
            max_clip_duration=params.video_clip_duration,
            threads=params.n_threads,
        )

        _progress += 50 / params.video_count / 2
        sm.state.update_task(task_id, progress=_progress)

        final_video_path = path.join(utils.task_dir(task_id), f"final-{index}.mp4")

        logger.info(f"\n\n## generating video: {index} => {final_video_path}")
        video.generate_video(
            video_path=combined_video_path,
            audio_path=audio_file,
            subtitle_path=subtitle_path,
            output_file=final_video_path,
            params=params,
        )

        _progress += 50 / params.video_count / 2
        sm.state.update_task(task_id, progress=_progress)

        final_video_paths.append(final_video_path)
        combined_video_paths.append(combined_video_path)

    return final_video_paths, combined_video_paths


def start(task_id, params: VideoParams, stop_at: str = "video", resume: bool = False):
    """
    启动视频生成任务。

    stop_at 控制执行到哪个阶段就停下并返回：script/terms/audio/subtitle/materials/video。

    resume=True 时，会优先复用 manifest.json 里已记录且产物文件仍然存在的阶段结果，
    跳过对应的生成步骤。注意 TTS 返回的 sub_maker 是内存对象无法持久化，所以：
      - audio 阶段只有在 custom_audio_file 路径下才能真正跳过（复用已有音频文件）；
      - 普通 TTS 路径下，即使 manifest 里有 audio_file，sub_maker 也拿不回来，
        会重新生成音频。script/terms/materials 这些纯数据/文件产物可以安全复用。
    默认 resume=False，行为与历史完全一致。
    """
    logger.info(f"start task: {task_id}, stop_at: {stop_at}, resume: {resume}")
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=5)

    # 1. Generate script
    if resume and _manifest_stage_completed(task_id, "script"):
        video_script = _load_manifest(task_id).get("script", "")
        logger.info(f"resume: reuse script from manifest")
    else:
        video_script = generate_script(task_id, params)
    if not video_script or "Error: " in video_script:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    _update_manifest(task_id, script=video_script)
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=10)

    if stop_at == "script":
        sm.state.update_task(
            task_id, state=const.TASK_STATE_COMPLETE, progress=100, script=video_script
        )
        return {"script": video_script}

    # 2. Generate terms
    if resume and _manifest_stage_completed(task_id, "terms") and params.video_source != "local":
        video_terms = _load_manifest(task_id).get("terms", [])
        # terms 顺序在 match_materials_to_script 下是有意义的，复用时不重排。
        logger.info(f"resume: reuse terms from manifest")
    elif params.video_source != "local":
        video_terms = generate_terms(task_id, params, video_script)
    else:
        video_terms = ""
    if params.video_source != "local" and not video_terms:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    save_script_data(task_id, video_script, video_terms, params)
    if video_terms:
        _update_manifest(task_id, terms=video_terms)

    if stop_at == "terms":
        sm.state.update_task(
            task_id, state=const.TASK_STATE_COMPLETE, progress=100, terms=video_terms
        )
        return {"script": video_script, "terms": video_terms}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=20)

    # 3. Generate audio
    # sub_maker 无法持久化，所以 resume 只能复用音频文件本身，sub_maker 永远要重置。
    sub_maker = None
    audio_resumed = False
    if resume and _manifest_stage_completed(task_id, "audio"):
        manifest = _load_manifest(task_id)
        resumed_audio_file = manifest.get("audio_file", "")
        resumed_duration = manifest.get("audio_duration", 0)
        # 只有 custom_audio_file 路径下 sub_maker 本就是 None，复用才是无损的。
        # TTS 路径复用音频文件会导致后续字幕生成拿不到时间轴，故仍需重新生成。
        requested_custom_audio = getattr(params, "custom_audio_file", None) or ""
        if requested_custom_audio.strip():
            audio_file = resumed_audio_file
            audio_duration = resumed_duration
            sub_maker = None
            audio_resumed = True
            logger.info(
                f"resume: reuse custom audio from manifest: {audio_file}"
            )
    if not audio_resumed:
        audio_file, audio_duration, sub_maker = generate_audio(
            task_id, params, video_script
        )
    if not audio_file:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    _update_manifest(
        task_id, audio_file=audio_file, audio_duration=audio_duration
    )
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=30)

    if stop_at == "audio":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            audio_file=audio_file,
        )
        return {"audio_file": audio_file, "audio_duration": audio_duration}

    # 4. Generate subtitle
    if resume and _manifest_stage_completed(task_id, "subtitle"):
        subtitle_path = _load_manifest(task_id).get("subtitle_path", "")
        logger.info(f"resume: reuse subtitle from manifest: {subtitle_path}")
    else:
        subtitle_path = generate_subtitle(
            task_id, params, video_script, sub_maker, audio_file
        )
    _update_manifest(
        task_id, subtitle_path=subtitle_path, subtitle_resolved=True
    )

    if stop_at == "subtitle":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            subtitle_path=subtitle_path,
        )
        return {"subtitle_path": subtitle_path}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=40)

    # 5. Get video materials
    if resume and _manifest_stage_completed(task_id, "materials"):
        downloaded_videos = _load_manifest(task_id).get("materials", [])
        logger.info(f"resume: reuse {len(downloaded_videos)} materials from manifest")
    else:
        downloaded_videos = get_video_materials(
            task_id, params, video_terms, audio_duration
        )
    if not downloaded_videos:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    _update_manifest(task_id, materials=downloaded_videos)

    if stop_at == "materials":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            materials=downloaded_videos,
        )
        return {"materials": downloaded_videos}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=50)

    # 仅完整视频生成流程才需要处理视频拼接模式；
    # 这样可以避免 /subtitle 和 /audio 这类请求访问不存在的字段。
    if type(params.video_concat_mode) is str:
        params.video_concat_mode = VideoConcatMode(params.video_concat_mode)

    # 6. Generate final videos
    final_video_paths, combined_video_paths = generate_final_videos(
        task_id, params, downloaded_videos, audio_file, subtitle_path
    )

    if not final_video_paths:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    logger.success(
        f"task {task_id} finished, generated {len(final_video_paths)} videos."
    )

    # 7. Cross-post to social platforms (if enabled)
    cross_post_results = []
    if upload_post.upload_post_service.is_configured() and upload_post.upload_post_service.auto_upload:
        platforms = upload_post.upload_post_service.platforms
        logger.info(f"\n\n## cross-posting videos to {', '.join(platforms)}")

        youtube_extra = None
        if any(p.startswith("youtube") for p in platforms):
            metadata = llm.generate_social_metadata(
                video_subject=params.video_subject,
                video_script=video_script,
                language=params.video_language or "",
                platform="youtube_shorts",
            )
            youtube_extra = {
                "youtube_title": metadata.get("title", params.video_subject),
                "youtube_description": metadata.get("caption", ""),
                "tags": metadata.get("hashtags", []),
                "privacyStatus": upload_post.upload_post_service.youtube_privacy_status,
                "containsSyntheticMedia": True,
            }

        for video_path in final_video_paths:
            result = upload_post.cross_post_video(
                video_path=video_path,
                title=params.video_subject or "Check out this video! #shorts #viral",
                youtube_extra=youtube_extra,
            )
            cross_post_results.append(result)
            if result.get('success'):
                logger.info(f"✅ Cross-posted: {video_path}")
            else:
                logger.warning(f"⚠️ Failed to cross-post: {video_path} - {result.get('error', 'Unknown error')}")

    kwargs = {
        "videos": final_video_paths,
        "combined_videos": combined_video_paths,
        "script": video_script,
        "terms": video_terms,
        "audio_file": audio_file,
        "audio_duration": audio_duration,
        "subtitle_path": subtitle_path,
        "materials": downloaded_videos,
        "cross_post_results": cross_post_results if cross_post_results else None,
    }
    _update_manifest(
        task_id,
        videos=final_video_paths,
        combined_videos=combined_video_paths,
    )
    sm.state.update_task(
        task_id, state=const.TASK_STATE_COMPLETE, progress=100, **kwargs
    )
    return kwargs


if __name__ == "__main__":
    task_id = "task_id"
    params = VideoParams(
        video_subject="金钱的作用",
        voice_name="zh-CN-XiaoyiNeural-Female",
        voice_rate=1.0,
    )
    start(task_id, params, stop_at="video")
