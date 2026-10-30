"""Read SRT cue boundaries before adapting them to MoviePy timing tuples."""
import os
import re


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
            # Once a cue has started, timestamps belong to its text until the
            # blank-line separator; they must not overwrite the cue's timing.
            if times and current_times is None:
                current_times = line
            elif line.strip() == "" and current_times:
                index += 1
                times_texts.append((index, current_times.strip(), current_text.strip()))
                current_times, current_text = None, ""
            elif current_times:
                current_text += line

    # Flush the final block. SRT files whose last subtitle is not followed by a
    # trailing blank line never hit the blank-line branch above, so without this
    # the last subtitle would be silently dropped.
    if current_times:
        index += 1
        times_texts.append((index, current_times.strip(), current_text.strip()))
    return times_texts


def moviepy_subtitles(filename):
    """Convert only cue headers; timestamp-bearing text remains caption text."""
    from moviepy.tools import convert_to_seconds

    cues = []
    for _index, timing, text in file_to_subtitles(filename):
        start, end = re.findall("([0-9]*:[0-9]*:[0-9]*,[0-9]*)", timing)
        cues.append(((convert_to_seconds(start), convert_to_seconds(end)), text))
    return cues
