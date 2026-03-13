import json
import os.path
import re
from timeit import default_timer as timer

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None
from loguru import logger

try:
    import torch
except ImportError:
    torch = None

from app.config import config
from app.utils import utils

model_size = config.whisper.get("model_size", "large-v3")
device = config.whisper.get("device", "cpu")
compute_type = config.whisper.get("compute_type", "int8")
model = None


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


def create(audio_file, subtitle_file: str = ""):
    global model
    if WhisperModel is None:
        logger.warning("faster_whisper not available, skipping whisper subtitle generation")
        return ""
    if not model:
        model_path = f"{utils.root_dir()}/models/whisper-{model_size}"
        model_bin_file = f"{model_path}/model.bin"
        if not os.path.isdir(model_path) or not os.path.isfile(model_bin_file):
            model_path = model_size

        # 每次都从配置中读取最新的device设置
        device = config.whisper.get("device", "cpu")
        # 转换device值，WhisperModel使用"cuda"而不是"GPU"
        if device.upper() == "GPU":
            device = "cuda"
        compute_type = config.whisper.get("compute_type", "int8")
        
        logger.info(
            f"loading model: {model_path}, device: {device}, compute_type: {compute_type}"
        )
        try:
            model = WhisperModel(
                model_size_or_path=model_path, device=device, compute_type=compute_type
            )
        except Exception as e:
            logger.error(
                f"failed to load model: {e} \n\n"
                f"********************************************\n"
                f"this may be caused by network issue. \n"
                f"please download the model manually and put it in the 'models' folder. \n"
                f"see [README.md FAQ](https://github.com/harry0703/MoneyPrinterTurbo) for more details.\n"
                f"********************************************\n\n"
            )
            return None

    # 每次都从配置中读取最新的device设置
    device = config.whisper.get("device", "cpu")
    compute_type = config.whisper.get("compute_type", "int8")
    
    logger.info(f"start, output file: {subtitle_file}")
    logger.info(f"using device: {device}, compute_type: {compute_type}")
    if not subtitle_file:
        subtitle_file = f"{audio_file}.srt"

    # Clear GPU cache before transcription to avoid out of memory
    if device.upper() == "GPU":
        device_str = "cuda"
    else:
        device_str = device.lower()
    
    if device_str == "cuda" and torch is not None:
        logger.info("Clearing GPU cache before transcription")
        torch.cuda.empty_cache()

    segments, info = model.transcribe(
        audio_file,
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
    )

    # Clear GPU cache after transcription
    if device_str == "cuda" and torch is not None:
        logger.info("Clearing GPU cache after transcription")
        torch.cuda.empty_cache()

    logger.info(
        f"detected language: '{info.language}', probability: {info.language_probability:.2f}"
    )

    start = timer()
    subtitles = []

    def recognized(seg_text, seg_start, seg_end):
        seg_text = seg_text.strip()
        if not seg_text:
            return

        msg = "[%.2fs -> %.2fs] %s" % (seg_start, seg_end, seg_text)
        logger.debug(msg)

        subtitles.append(
            {"msg": seg_text, "start_time": seg_start, "end_time": seg_end}
        )

    for segment in segments:
        words_idx = 0
        words_len = len(segment.words)

        seg_start = 0
        seg_end = 0
        seg_text = ""

        if segment.words:
            is_segmented = False
            for word in segment.words:
                if not is_segmented:
                    seg_start = word.start
                    is_segmented = True

                seg_end = word.end
                # If it contains punctuation, then break the sentence.
                seg_text += word.word

                if utils.str_contains_punctuation(word.word):
                    # remove last char
                    seg_text = seg_text[:-1]
                    if not seg_text:
                        continue

                    recognized(seg_text, seg_start, seg_end)

                    is_segmented = False
                    seg_text = ""

                if words_idx == 0 and segment.start < word.start:
                    seg_start = word.start
                if words_idx == (words_len - 1) and segment.end > word.end:
                    seg_end = word.end
                words_idx += 1

        if not seg_text:
            continue

        recognized(seg_text, seg_start, seg_end)

    end = timer()

    diff = end - start
    logger.info(f"complete, elapsed: {diff:.2f} s")

    idx = 1
    lines = []
    for subtitle in subtitles:
        text = subtitle.get("msg")
        if text:
            lines.append(
                utils.text_to_srt(
                    idx, text, subtitle.get("start_time"), subtitle.get("end_time")
                )
            )
            idx += 1

    sub = "\n".join(lines) + "\n"
    with open(subtitle_file, "w", encoding="utf-8") as f:
        f.write(sub)
    logger.info(f"subtitle file created: {subtitle_file}")


def file_to_subtitles(filename):
    if not filename or not os.path.isfile(filename):
        return []

    times_texts = []
    current_times = None
    current_text = ""
    index = 0
    with open(filename, "r", encoding="utf-8") as f:
        for line in f:
            times = re.findall("([0-9]*:[0-9]*:[0-9]*,[0-9]*)", line)
            if times:
                current_times = line
            elif line.strip() == "" and current_times:
                index += 1
                times_texts.append((index, current_times.strip(), current_text.strip()))
                current_times, current_text = None, ""
            elif current_times:
                current_text += line
    return times_texts


def levenshtein_distance(s1, s2):
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def similarity(a, b):
    distance = levenshtein_distance(a.lower(), b.lower())
    max_length = max(len(a), len(b))
    return 1 - (distance / max_length)


def correct(subtitle_file, video_script):
    """
    纠正字幕文件，使其与视频脚本匹配
    当Whisper生成的字幕与原始脚本不匹配时，使用原始脚本替换字幕文本
    并根据文本长度重新分配时间戳
    """
    if not os.path.exists(subtitle_file):
        logger.error(f"subtitle file not found: {subtitle_file}")
        return

    # 读取原始字幕文件
    subtitle_items = file_to_subtitles(subtitle_file)
    if not subtitle_items:
        logger.error(f"subtitle file is empty: {subtitle_file}")
        return

    # 处理视频脚本
    video_script = _format_text(video_script)
    script_lines = utils.split_string_by_punctuations(video_script)
    script_lines = [line.strip() for line in script_lines if line.strip()]

    if not script_lines:
        logger.error("video script is empty")
        return

    # 计算总音频时长（从字幕文件中获取）
    total_duration = 0
    if subtitle_items:
        last_item = subtitle_items[-1]
        end_time_str = last_item[1].split(" --> ")[1]
        total_duration = _srt_time_to_seconds(end_time_str)

    # 计算总脚本长度（字符数）
    total_script_chars = sum(len(line) for line in script_lines)

    # 重新分配时间戳
    new_subtitle_items = []
    current_time = 0

    for i, script_line in enumerate(script_lines):
        # 计算当前行的时间比例
        line_chars = len(script_line)
        line_duration = (line_chars / total_script_chars) * total_duration if total_script_chars > 0 else 0
        
        # 转换为SRT时间格式
        start_time_str = _seconds_to_srt_time(current_time)
        end_time_str = _seconds_to_srt_time(current_time + line_duration)
        
        # 添加到新字幕列表
        new_subtitle_items.append(
            (
                i + 1,
                f"{start_time_str} --> {end_time_str}",
                script_line,
            )
        )
        
        # 更新当前时间
        current_time += line_duration

    # 保存纠正后的字幕文件
    with open(subtitle_file, "w", encoding="utf-8") as fd:
        for i, item in enumerate(new_subtitle_items):
            fd.write(f"{i + 1}\n{item[1]}\n{item[2]}\n\n")
    logger.info("Subtitle corrected with reallocated timestamps")


def _srt_time_to_seconds(time_str):
    """
    Convert SRT time format to seconds
    Format: 00:00:00,000
    """
    try:
        if not time_str:
            return 0
        parts = time_str.split(",")
        if len(parts) < 2:
            return 0
        time_part = parts[0]
        ms_part = parts[1]
        time_components = time_part.split(":")
        if len(time_components) < 3:
            return 0
        h, m, s = map(int, time_components)
        ms = int(ms_part)
        return h * 3600 + m * 60 + s + ms / 1000
    except Exception as e:
        logger.error(f"Error converting SRT time to seconds: {e}")
        return 0


def _seconds_to_srt_time(seconds):
    """
    将秒转换为SRT时间格式
    格式: 00:00:00,000
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


if __name__ == "__main__":
    task_id = "c12fd1e6-4b0a-4d65-a075-c87abe35a072"
    task_dir = utils.task_dir(task_id)
    subtitle_file = f"{task_dir}/subtitle.srt"
    audio_file = f"{task_dir}/audio.mp3"

    subtitles = file_to_subtitles(subtitle_file)
    print(subtitles)

    script_file = f"{task_dir}/script.json"
    with open(script_file, "r") as f:
        script_content = f.read()
    s = json.loads(script_content)
    script = s.get("script")

    correct(subtitle_file, script)

    subtitle_file = f"{task_dir}/subtitle-test.srt"
    create(audio_file, subtitle_file)
