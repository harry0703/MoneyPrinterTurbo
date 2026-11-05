from datetime import timedelta
from unittest.mock import patch

import pytest
from edge_tts import SubMaker
from edge_tts.srt_composer import Subtitle

from app.services import subtitle, voice
from app.utils import utils

# A script pasted from a social media post can carry emoji.
SCRIPT = "Ready to grow 📈? Let's go 👉 now ✅."


@pytest.mark.parametrize(
    "emoji",
    [
        "📈",
        "👉",
        "✅",
        "🚀🔥",
        "😍",
        "⏰",
        "❤\ufe0f",  # red heart
        "⬆\ufe0f",  # up arrow
        "👍\U0001f3fd",  # thumbs up: medium skin tone
        "✌\U0001f3fb",  # victory hand: light skin tone
        "👩\u200d💻",  # woman technologist
        "🇺🇸",  # flag: United States
        "🏴\U000e0067\U000e0062\U000e0073\U000e0063\U000e0074\U000e007f",  # flag: Scotland
    ],
)
def test_remove_emoji_drops_emoji_and_the_space_before_it(emoji):
    assert utils.remove_emoji(f"Go {emoji} now") == "Go now"


def test_remove_emoji_keeps_keycap_digits_and_text_symbols():
    assert utils.remove_emoji("1\ufe0f\u20e3 Step one") == "1 Step one"
    text = "★ ♪ → 25℃ 90° © ™ € C# #1 5*3"
    assert utils.remove_emoji(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "快来试试吧。",
        "カタカナとひらがな",
        "مرحبا بالعالم",
        "क्\u200dष क्\u200cष",  # Devanagari conjuncts with ZWJ and ZWNJ
    ],
)
def test_remove_emoji_keeps_other_scripts(text):
    assert utils.remove_emoji(text) == text


def test_remove_emoji_keeps_line_breaks_and_leaves_no_space_before_punctuation():
    assert utils.remove_emoji(SCRIPT) == "Ready to grow? Let's go now."
    assert utils.remove_emoji("快来试试吧😍。") == "快来试试吧。"
    assert (
        utils.remove_emoji("Hi 👋\n\n🔥 Hot take\nDone.✅ Next")
        == "Hi\n\nHot take\nDone. Next"
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("✅Free shipping ✅Easy returns", "Free shipping Easy returns"),
        ("Big news 🚀Launching today", "Big news Launching today"),
        ("Follow us 👉@moneyprinter", "Follow us @moneyprinter"),
        ("I love🍕pizza", "I love pizza"),
        ("Good morning☀\ufe0feveryone", "Good morning everyone"),
        ("Done.✅Next", "Done. Next"),
        ("Привет👋мир", "Привет мир"),
        ("좋아요😊감사합니다", "좋아요 감사합니다"),  # Korean puts spaces between words
    ],
)
def test_remove_emoji_keeps_words_apart(text, expected):
    # Edge TTS takes "shippingEasy" for one word.
    assert utils.remove_emoji(text) == expected


def test_remove_emoji_removes_a_row_of_emoji_like_one_emoji():
    assert utils.remove_emoji("Go 🚀❤\ufe0f now") == "Go now"
    assert utils.remove_emoji("Big news 🚀❤\ufe0f.") == "Big news."
    assert utils.remove_emoji("I love🍕❤\ufe0fpizza") == "I love pizza"


def test_remove_emoji_leaves_no_space_inside_brackets_or_quotes():
    assert utils.remove_emoji("(🚀 Launching today)") == "(Launching today)"
    assert utils.remove_emoji('"So good😍"') == '"So good"'
    assert utils.remove_emoji('"😍So good"') == '"So good"'
    assert utils.remove_emoji('"So good"😍 says Anna') == '"So good" says Anna'


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            'Customers say 😍"Best purchase ever!" Order today.',
            'Customers say "Best purchase ever!" Order today.',
        ),
        ('Tap 👉"Link in bio" to shop.', 'Tap "Link in bio" to shop.'),
        ('Rated ⭐⭐⭐⭐⭐"Amazing"', 'Rated "Amazing"'),
        ("She said 🔥'hi'", "She said 'hi'"),
        ('"😍 Best purchase ever" says Anna.', '"Best purchase ever" says Anna.'),
        ("'🔥 hi'", "'hi'"),
        ('"wow"🔥amazing', '"wow" amazing'),
        ('She said "wow"🔥 and he said 😍"cool"', 'She said "wow" and he said "cool"'),
        ('他说"😍 太好了"', '他说"太好了"'),
        ("“😍 So good”", "“So good”"),
        # German quotations open with „ or ‚ and close with “ or ‘.
        (
            "„So gut 😍“ sagt Anna. „🔥 Neu“ im Shop.",
            "„So gut“ sagt Anna. „Neu“ im Shop.",
        ),
        ("„So gut“😍 sagt Anna.", "„So gut“ sagt Anna."),
        ("‚So gut 😍‘ sagt Anna.", "‚So gut‘ sagt Anna."),
    ],
)
def test_remove_emoji_tells_opening_quotes_from_closing_ones(text, expected):
    # A space stays between a word and a quotation, but none is left inside it.
    assert utils.remove_emoji(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("don't 🔥 go", "don't go"),
        ("It's🔥great", "It's great"),
        ("Don't miss 🔥'Epic Night'", "Don't miss 'Epic Night'"),
        ("the dogs'🐶 toys", "the dogs' toys"),
        ("Santa🎅's workshop is open.", "Santa's workshop is open."),
    ],
)
def test_remove_emoji_does_not_take_apostrophes_for_quotes(text, expected):
    assert utils.remove_emoji(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("快来试试吧😍效果真的很棒👍", "快来试试吧效果真的很棒"),
        ("ありがとう😊ございます", "ありがとうございます"),
    ],
)
def test_remove_emoji_adds_no_space_in_chinese_or_japanese(text, expected):
    assert utils.remove_emoji(text) == expected


def test_remove_emoji_keeps_keycaps_in_a_row_apart():
    countdown = "Ready? 3\ufe0f\u20e32\ufe0f\u20e31\ufe0f\u20e3 Go!"
    # Edge TTS reads "321" as "three hundred twenty-one".
    assert utils.remove_emoji(countdown) == "Ready? 3 2 1 Go!"
    assert utils.remove_emoji("1\ufe0f\u20e3Step one") == "1 Step one"


def test_tts_does_not_send_emoji_to_the_voice():
    # Edge TTS reads emoji names aloud: "Ready to grow chart increasing?"
    with patch.object(voice, "_single_tts", return_value=SubMaker()) as single_tts:
        voice.tts(SCRIPT, "en-US-AriaNeural", 1.0, "audio.mp3")

    assert single_tts.call_args.kwargs["text"] == "Ready to grow? Let's go now."


def test_tts_with_pause_tags_does_not_send_emoji_to_the_voice():
    with patch.object(
        voice, "_tts_with_pauses", return_value=SubMaker()
    ) as tts_with_pauses:
        voice.tts("Hi 👋 [pause: 1s] Bye 👋", "en-US-AriaNeural", 1.0, "audio.mp3")

    assert tts_with_pauses.call_args.kwargs["text"] == "Hi [pause: 1s] Bye"


def test_tts_does_not_call_a_voice_for_a_script_made_only_of_emoji():
    with (
        patch.object(voice, "_single_tts") as single_tts,
        patch.object(voice, "_tts_with_pauses") as tts_with_pauses,
        patch.object(voice.logger, "warning") as warning,
    ):
        assert voice.tts("🚀🔥 👍", "en-US-AriaNeural", 1.0, "audio.mp3") is None

    single_tts.assert_not_called()
    tts_with_pauses.assert_not_called()
    warning.assert_called_once_with(
        "the script has no text to narrate once emoji are removed"
    )


def _edge_sub_maker(*words):
    sub_maker = SubMaker()
    for index, word in enumerate(words):
        sub_maker.cues.append(
            Subtitle(
                index=index + 1,
                start=timedelta(seconds=0.1 + index * 0.5),
                end=timedelta(seconds=0.5 + index * 0.5),
                content=word,
            )
        )
    return sub_maker


def test_edge_subtitles_leave_out_emoji(tmp_path):
    # The word boundaries Edge TTS returns once the emoji are not spoken.
    sub_maker = _edge_sub_maker("Ready", "to", "grow", "Let's", "go", "now")
    subtitle_file = tmp_path / "subtitle.srt"

    voice.create_subtitle(sub_maker, SCRIPT, str(subtitle_file))

    items = subtitle.file_to_subtitles(str(subtitle_file))
    assert [item[2] for item in items] == ["Ready to grow", "Let's go now"]
    assert items[1][1] == "00:00:01,600 --> 00:00:03,000"


def test_whisper_subtitles_leave_out_emoji(tmp_path):
    subtitle_file = tmp_path / "subtitle.srt"
    subtitle_file.write_text(
        "1\n00:00:00,000 --> 00:00:01,400\nReady to grow\n\n"
        "2\n00:00:01,500 --> 00:00:02,900\nLet's go now\n\n",
        encoding="utf-8",
    )

    subtitle.correct(str(subtitle_file), SCRIPT)

    items = subtitle.file_to_subtitles(str(subtitle_file))
    assert [item[2] for item in items] == ["Ready to grow", "Let's go now"]


def test_timeline_without_word_boundaries_leaves_out_emoji():
    sub_maker = voice.populate_legacy_submaker_with_full_text(SubMaker(), SCRIPT, 3.0)

    assert sub_maker.subs == ["Ready to grow", "Let's go now"]
