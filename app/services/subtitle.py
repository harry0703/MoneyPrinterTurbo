import json
import os.path
import tempfile
import threading
from timeit import default_timer as timer

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None
from loguru import logger

from app.config import config
from app.models import const
from app.utils import utils
from app.utils.subtitle_reader import file_to_subtitles as file_to_subtitles
from app.utils.subtitle_writer import write_subtitle_file

model_size = config.whisper.get("model_size", "large-v3")
device = config.whisper.get("device", "cpu")
compute_type = config.whisper.get("compute_type", "int8")
initial_prompt = config.whisper.get("initial_prompt", "") or None
model = None
_model_init_lock = threading.Lock()


def _ensure_model_loaded() -> bool:
    """Load the large Whisper model once, even when jobs start concurrently."""
    global model
    if model is not None:
        return True

    with _model_init_lock:
        if model is not None:
            return True
        model_path = f"{utils.root_dir()}/models/whisper-{model_size}"
        model_bin_file = f"{model_path}/model.bin"
        if not os.path.isdir(model_path) or not os.path.isfile(model_bin_file):
            model_path = model_size

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
            return False
    return True


def create(
    audio_file,
    subtitle_file: str = "",
    word_level: bool = False,
    log_details: bool = True,
):
    if WhisperModel is None:
        logger.warning("faster_whisper not available, skipping whisper subtitle generation")
        return ""
    if not _ensure_model_loaded():
        return None

    if log_details:
        logger.info(f"start, output file: {subtitle_file}")
    if not subtitle_file:
        subtitle_file = f"{audio_file}.srt"

    segments, info = model.transcribe(
        audio_file,
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
        **({"initial_prompt": initial_prompt} if initial_prompt else {}),
    )

    logger.info(
        f"detected language: '{info.language}', probability: {info.language_probability:.2f}"
    )

    start = timer()
    subtitles = []

    def recognized(seg_text, seg_start, seg_end):
        seg_text = seg_text.strip()
        if not seg_text:
            return

        if log_details:
            msg = "[%.2fs -> %.2fs] %s" % (seg_start, seg_end, seg_text)
            logger.debug(msg)

        subtitles.append(
            {"msg": seg_text, "start_time": seg_start, "end_time": seg_end}
        )

    for segment in segments:
        if not segment.words:
            # Faster Whisper exposes words as Optional[List[Word]]. A segment
            # can still have usable text and timestamps when alignment yields
            # no words; keep that subtitle in both sentence and word modes.
            recognized(segment.text, segment.start, segment.end)
            continue

        if word_level:
            for word in segment.words:
                cleaned_word = word.word.strip()
                if cleaned_word:
                    recognized(cleaned_word, word.start, word.end)
            continue

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
                # Accumulate words; only trailing punctuation ends a sentence.
                seg_text += word.word

                if word.word.rstrip().endswith(tuple(const.PUNCTUATIONS)):
                    # Punctuation inside a word (3.14, 1,000, 12:30) is not a
                    # sentence boundary. Remove only actual trailing delimiters.
                    seg_text = seg_text.rstrip().rstrip("".join(const.PUNCTUATIONS))
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
    if not lines:
        logger.warning("transcription produced no subtitle cues")
        return
    write_subtitle_file(subtitle_file, sub)
    if log_details:
        logger.info(f"subtitle file created: {subtitle_file}")


def transcribe_audio_bytes(audio_bytes: bytes) -> str:
    """Transcribe in-memory WAV audio and remove every temporary artifact."""
    if not isinstance(audio_bytes, bytes) or not audio_bytes:
        return ""

    with tempfile.TemporaryDirectory(prefix="whisper-transcript-") as temp_dir:
        audio_file = os.path.join(temp_dir, "reference.wav")
        subtitle_file = os.path.join(temp_dir, "reference.srt")
        with open(audio_file, "wb") as output:
            output.write(audio_bytes)

        create_result = create(audio_file, subtitle_file, log_details=False)
        if create_result in (None, "") and not os.path.isfile(subtitle_file):
            return ""
        subtitle_items = file_to_subtitles(subtitle_file)
        return " ".join(item[2].strip() for item in subtitle_items if item[2].strip())


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


def _prefix_distances(a, b):
    """Return the edit distances between a and the prefixes of b: item j is b[:j]."""
    # Lowercase one character at a time, so that j stays an index into b:
    # "İ".lower() has two characters.
    a = [c.lower() for c in a]
    b = [c.lower() for c in b]
    previous_row = list(range(len(b) + 1))
    for i, c1 in enumerate(a):
        current_row = [i + 1]
        for j, c2 in enumerate(b):
            current_row.append(
                min(
                    previous_row[j + 1] + 1,
                    current_row[j] + 1,
                    previous_row[j] + (c1 != c2),
                )
            )
        previous_row = current_row
    return previous_row


def _prefix_similarity(a, b):
    """Return how much the shorter of a and b is like the start of the longer one."""
    shorter, longer = sorted((a, b), key=len)
    return 1 - min(_prefix_distances(shorter, longer)) / len(shorter)


def _end_of_script_line_in_cue(
    script_line, cue_text, next_script_line, next_cue_text, line_after_next
):
    """
    Return where script_line ends in cue_text when the cue starts with
    script_line and goes on like next_script_line, else None.

    next_cue_text is the text of the cue after it, and line_after_next the
    script line after next_script_line, each "" when there is none.
    """
    if len(cue_text) <= len(script_line):
        return None
    distances = _prefix_distances(script_line, cue_text)
    end = distances.index(min(distances))
    if not end or similarity(script_line, cue_text[:end]) <= 0.8:
        return None
    rest = cue_text[end:].strip()
    if not rest or _prefix_similarity(rest, next_script_line) <= 0.8:
        return None
    if (
        next_cue_text
        and len(rest) < len(next_script_line)
        and _prefix_similarity(next_script_line, next_cue_text)
        >= _prefix_similarity(next_script_line, rest + " " + next_cue_text)
    ):
        # The next cue starts the next line by itself. The rest of this cue is
        # then the start of that line written twice, as in "We went home and
        # then we" before "and then we slept", or a letter that Whisper added,
        # as in "Hello worlds" for "Hello world" before "So we went".
        return None
    if (
        next_cue_text
        and len(rest) >= len(next_script_line)
        and similarity(rest, next_script_line) > 0.8
        and _prefix_similarity(next_script_line, next_cue_text) > 0.8
        and (
            not line_after_next
            or _prefix_similarity(next_script_line, next_cue_text)
            > _prefix_similarity(line_after_next, next_cue_text)
        )
    ):
        # The rest of this cue is the whole next line, and the next cue is that
        # line again, as in "We went home and then we slept" before "and then
        # we slept". When the next cue starts the line after it as well, as in
        # "Come here, come here, come here.", the cue is still cut.
        return None
    return end


def _srt_time_to_seconds(value):
    hours, minutes, seconds = value.strip().replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _cut_cues(subtitle_items, first, last, cut_at):
    """
    Cut subtitle_items[first:last], joined with spaces, at character cut_at.

    Return the time of the cut and the index of the first cue after it. When the
    cut is inside a cue, the rest of that cue replaces it, from the time of the
    cut, which is in proportion to the characters before it.
    """
    offset = 0
    index = first
    while index < last - 1:
        text = subtitle_items[index][2].strip()
        if cut_at <= offset + len(text):
            break
        offset += len(text) + 1
        index += 1

    number, times, text = subtitle_items[index]
    text = text.strip()
    start, end = times.split(" --> ")
    position = min(max(cut_at - offset, 0), len(text))
    rest = text[position:].strip()
    if not rest:
        return end, index + 1

    start_seconds = _srt_time_to_seconds(start)
    cut_seconds = start_seconds + (
        _srt_time_to_seconds(end) - start_seconds
    ) * position / len(text)
    cut = utils.time_convert_seconds_to_hmsm(cut_seconds)
    subtitle_items[index] = (number, f"{cut} --> {end}", rest)
    return cut, index


def similarity(a, b):
    distance = levenshtein_distance(a.lower(), b.lower())
    max_length = max(len(a), len(b))
    return 1 - (distance / max_length)


def correct(subtitle_file, video_script):
    subtitle_items = file_to_subtitles(subtitle_file)
    normalized_script = utils.normalize_script_for_subtitle_matching(video_script)
    # create() splits Whisper segments at punctuation but not at the space that ends
    # a Thai or Lao sentence, so a segment can hold several of those sentences.
    script_lines = utils.split_string_by_punctuations(
        normalized_script, split_thai_and_lao_sentences=False
    )

    corrected = False
    new_subtitle_items = []
    script_index = 0
    subtitle_index = 0

    while script_index < len(script_lines) and subtitle_index < len(subtitle_items):
        script_line = script_lines[script_index].strip()
        subtitle_line = subtitle_items[subtitle_index][2].strip()

        if script_line == subtitle_line:
            new_subtitle_items.append(subtitle_items[subtitle_index])
            script_index += 1
            subtitle_index += 1
        else:
            combined_subtitle = subtitle_line
            start_time = subtitle_items[subtitle_index][1].split(" --> ")[0]
            end_time = subtitle_items[subtitle_index][1].split(" --> ")[1]
            next_subtitle_index = subtitle_index + 1

            while next_subtitle_index < len(subtitle_items):
                next_subtitle = subtitle_items[next_subtitle_index][2].strip()
                if similarity(
                    script_line, combined_subtitle + " " + next_subtitle
                ) > similarity(script_line, combined_subtitle):
                    combined_subtitle += " " + next_subtitle
                    end_time = subtitle_items[next_subtitle_index][1].split(" --> ")[1]
                    next_subtitle_index += 1
                else:
                    break

            if script_index + 1 < len(script_lines):
                # Whisper can leave out a comma that the script has, as in "before
                # they run and reads pass". Then one cue holds this line and the
                # start of the next one, and the next line gets the rest of it.
                next_cue_text = ""
                if next_subtitle_index < len(subtitle_items):
                    next_cue_text = subtitle_items[next_subtitle_index][2].strip()
                line_after_next = ""
                if script_index + 2 < len(script_lines):
                    line_after_next = script_lines[script_index + 2].strip()
                line_end = _end_of_script_line_in_cue(
                    script_line,
                    combined_subtitle,
                    script_lines[script_index + 1].strip(),
                    next_cue_text,
                    line_after_next,
                )
                if line_end is not None:
                    end_time, next_subtitle_index = _cut_cues(
                        subtitle_items, subtitle_index, next_subtitle_index, line_end
                    )
                    combined_subtitle = combined_subtitle[:line_end].strip()

            if similarity(script_line, combined_subtitle) > 0.8:
                logger.warning(
                    f"Merged/Corrected - Script: {script_line}, Subtitle: {combined_subtitle}"
                )
                new_subtitle_items.append(
                    (
                        len(new_subtitle_items) + 1,
                        f"{start_time} --> {end_time}",
                        script_line,
                    )
                )
                corrected = True
            else:
                logger.warning(
                    f"Mismatch - Script: {script_line}, Subtitle: {combined_subtitle}"
                )
                new_subtitle_items.append(
                    (
                        len(new_subtitle_items) + 1,
                        f"{start_time} --> {end_time}",
                        script_line,
                    )
                )
                corrected = True

            script_index += 1
            subtitle_index = next_subtitle_index

    # Process the remaining lines of the script.
    while script_index < len(script_lines):
        logger.warning(f"Extra script line: {script_lines[script_index]}")
        if subtitle_index < len(subtitle_items):
            new_subtitle_items.append(
                (
                    len(new_subtitle_items) + 1,
                    subtitle_items[subtitle_index][1],
                    script_lines[script_index],
                )
            )
            subtitle_index += 1
        else:
            new_subtitle_items.append(
                (
                    len(new_subtitle_items) + 1,
                    "00:00:00,000 --> 00:00:00,000",
                    script_lines[script_index],
                )
            )
        script_index += 1
        corrected = True

    if subtitle_index < len(subtitle_items):
        logger.warning(
            f"Dropping {len(subtitle_items) - subtitle_index} transcription cue(s) "
            "after the script ends"
        )
        corrected = True

    if corrected:
        content = "".join(
            f"{i + 1}\n{item[1]}\n{item[2]}\n\n"
            for i, item in enumerate(new_subtitle_items)
        )
        write_subtitle_file(subtitle_file, content)
        logger.info("Subtitle corrected")
    else:
        logger.success("Subtitle is correct")


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
