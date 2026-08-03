"""카드 대본을 영상으로."""

import os
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from unittest.mock import MagicMock, patch

from app.models.schema import VideoParams
from app.services import cardnews, cardvideo
from app.services.cardnews import Card
from app.services.cardscript import CardScript


def _script(count=3):
    return CardScript(
        cards=tuple(Card(title=f"제목 {i}") for i in range(count)),
        narrations=tuple(f"나레이션 {i}" for i in range(count)),
    )


@contextmanager
def _task_dir():
    """
    출력 위치는 task 저장소에서 나온다. 테스트는 그 뿌리만 임시 디렉터리로 돌린다.
    """
    with tempfile.TemporaryDirectory() as work:
        with patch.object(cardvideo.utils, "task_dir", return_value=work):
            yield work


@contextmanager
def _silent_moviepy(clip_duration=7.0):
    """
    moviepy 는 함수 안에서 import 된다. 모듈 속성이 아니라 moviepy 쪽을 갈아야
    실제 인코딩 없이 조립 흐름만 확인할 수 있다.
    """
    # 모의 클립도 길이가 있어야 한다. 오디오를 카드 길이에 맞춰 자르거나 늘릴 때
    # 실제로 비교하기 때문이다.
    audio = MagicMock()
    audio.return_value.duration = 2.0
    # ExitStack 은 __enter__ 가 돌려주는 것을 쓴다. 같은 객체를 돌려줘야 길이가 보인다.
    audio.return_value.__enter__.return_value = audio.return_value
    with (
        patch.object(cardvideo, "AudioFileClip", audio),
        patch("moviepy.CompositeAudioClip", MagicMock()),
        patch("moviepy.concatenate_audioclips", MagicMock()),
        patch.object(cardvideo.cardnews, "build_card_news_clip") as build,
    ):
        build.return_value.duration = clip_duration
        yield build


def _params():
    params = VideoParams(video_subject="t")
    params.bgm_type = ""
    params.n_threads = 1
    return params


class TestNarrationDrivesTiming(unittest.TestCase):
    """카드가 화면에 머무는 시간은 그 카드 나레이션의 실제 길이다."""

    def test_each_card_is_held_for_its_own_narration(self):
        """
        통짜 나레이션을 글자 수로 나누면 뒤로 갈수록 화면과 소리가 밀린다.
        카드별로 재야 어긋나지 않는다.
        """
        lengths = iter([1.0, 4.0, 2.0])
        with patch.object(
            cardvideo, "_narrate", side_effect=lambda *a, **k: next(lengths)
        ), _silent_moviepy() as build:
            with _task_dir():
                cardvideo.render_card_news("t", _script(3), _params())

        self.assertEqual(build.call_args.args[1], [1.0, 4.0, 2.0])

    def test_a_card_whose_narration_fails_still_appears(self):
        """
        한 장이 실패했다고 영상 전체를 버리지 않는다. 소리 없이 지나가고
        나머지는 그대로 나온다.
        """
        with patch.object(
            cardvideo, "_narrate", return_value=0.0
        ), _silent_moviepy(7.5) as build:
            with _task_dir():
                cardvideo.render_card_news("t", _script(3), _params())

        self.assertEqual(
            build.call_args.args[1], [cardvideo.FALLBACK_CARD_SECONDS] * 3
        )

    def test_an_empty_narration_is_not_sent_to_the_voice_service(self):
        """빈 글을 합성하면 요금과 시간만 쓰고 아무 소리도 안 나온다."""
        script = CardScript(
            cards=(Card(title="하나"), Card(title="둘")), narrations=("", "   ")
        )
        with patch.object(cardvideo, "_narrate") as narrate, _silent_moviepy(5.0):
            with _task_dir():
                cardvideo.render_card_news("t", script, _params())

        narrate.assert_not_called()


class TestTimelineStaysAligned(unittest.TestCase):
    """화면과 소리가 어긋나지 않는 것이 이 설계의 이유 전부다."""

    def test_a_failed_card_is_padded_with_silence(self):
        """
        실패한 카드를 오디오에서 빼 버리면 그 뒤 카드의 소리가 화면보다 먼저
        나오고, 어긋남이 끝까지 남는다.
        """
        lengths = iter([2.0, 0.0, 3.0])
        with (
            patch.object(cardvideo, "_narrate", side_effect=lambda *a, **k: next(lengths)),
            patch.object(cardvideo, "_silence_clip") as silence,
            _silent_moviepy(7.5),
            patch.object(cardvideo, "AudioFileClip") as audio,
        ):
            audio.return_value.duration = 2.0
            audio.return_value.__enter__.return_value = audio.return_value
            with _task_dir():
                cardvideo.render_card_news("t", _script(3), _params())

        # 소리가 난 카드 둘은 파일에서, 실패한 하나는 무음으로. 합쳐서 셋이어야
        # 카드와 순서가 맞는다.
        self.assertEqual(audio.call_count, 2)
        # 실패한 카드 자리에 그 길이만큼의 무음이 들어갔는지. (길이가 모자란 카드를
        # 채우느라 무음이 더 불릴 수 있으므로 호출 횟수로 보지 않는다.)
        asked = [call.args[0] for call in silence.call_args_list]
        self.assertIn(cardvideo.FALLBACK_CARD_SECONDS, asked)

    def test_a_narration_shorter_than_the_floor_still_lines_up(self):
        """
        영상 쪽은 카드 길이를 최소 0.5 초로 올린다. 오디오가 0.3 초 그대로면 그
        차이만큼 다음 카드가 먼저 나오고, 이후 전부 밀린다.
        """
        with (
            patch.object(cardvideo, "_narrate", return_value=0.3),
            _silent_moviepy(1.5) as build,
        ):
            with _task_dir():
                cardvideo.render_card_news("t", _script(3), _params())

        for seconds in build.call_args.args[1]:
            self.assertGreaterEqual(seconds, cardnews.MIN_CARD_SECONDS)

    def test_a_narration_longer_than_the_cap_is_brought_back(self):
        """상한을 넘긴 나레이션은 영상 쪽에서 잘린다. 오디오도 같이 잘려야 한다."""
        with (
            patch.object(cardvideo, "_narrate", return_value=5_000.0),
            _silent_moviepy(60.0) as build,
        ):
            with _task_dir():
                cardvideo.render_card_news("t", _script(1), _params())

        self.assertEqual(build.call_args.args[1], [cardnews.MAX_CARD_SECONDS])

    def test_the_render_resizes_each_segment_to_its_card(self):
        """
        조각을 맞추는 함수가 있어도 조립할 때 안 쓰면 소용이 없다. 나레이션 길이와
        클립 길이가 다른 상황을 만들어 실제로 지나가는지 본다.
        """
        with (
            patch.object(cardvideo, "_narrate", return_value=5.0),
            patch.object(cardvideo, "_silence_clip") as silence,
            _silent_moviepy(15.0),
            patch("moviepy.concatenate_audioclips"),
        ):
            with _task_dir():
                cardvideo.render_card_news("t", _script(3), _params())

        # 모의 클립은 2 초, 카드는 5 초. 매번 3 초씩 채워야 한다.
        self.assertTrue(silence.called, "조각을 카드 길이에 맞추지 않았다")
        self.assertAlmostEqual(silence.call_args.args[0], 3.0)

    def test_a_short_narration_is_padded_to_the_card_length(self):
        """
        오디오 조각 하나가 카드보다 짧으면 그 차이만큼 뒤가 당겨진다. 조각의
        길이를 카드에 맞춰야 두 타임라인이 같은 길이로 간다.
        """
        source = MagicMock()
        source.duration = 1.0
        source.__enter__ = MagicMock(return_value=source)
        source.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(cardvideo, "AudioFileClip", return_value=source),
            patch.object(cardvideo, "_silence_clip") as silence,
            patch("moviepy.concatenate_audioclips") as concat,
        ):
            with ExitStack() as clips:
                cardvideo._audio_segment(clips, "card.mp3", 3.0)

        self.assertAlmostEqual(silence.call_args.args[0], 2.0)
        concat.assert_called_once()

    def test_a_long_narration_is_trimmed_to_the_card_length(self):
        """길면 카드가 넘어간 뒤에도 소리가 남아 다음 카드를 덮는다."""
        source = MagicMock()
        source.duration = 9.0
        source.__enter__ = MagicMock(return_value=source)
        source.__exit__ = MagicMock(return_value=False)

        with patch.object(cardvideo, "AudioFileClip", return_value=source):
            with ExitStack() as clips:
                cardvideo._audio_segment(clips, "card.mp3", 4.0)

        source.subclipped.assert_called_once_with(0, 4.0)

    def test_padding_does_not_depend_on_an_external_tool(self):
        """
        ffmpeg 로 무음 파일을 만들다 실패하면 그 자리가 비고, 어긋난 영상이 나온다.
        타임라인을 맞추는 일이 외부 도구의 성공 여부에 걸려서는 안 된다.
        """
        with patch.object(cardvideo.voice, "generate_silent_audio") as external:
            clip = cardvideo._silence_clip(2.5)
            try:
                self.assertAlmostEqual(clip.duration, 2.5, places=2)
            finally:
                clip.close()

        external.assert_not_called()

    def test_every_source_reader_is_closed(self):
        """
        합쳐진 클립만 닫으면 자식 리더가 남는다. 반복 렌더링에서 ffmpeg 프로세스와
        파일 잠금이 쌓인다.
        """
        opened = []

        def make_clip(*_args, **_kwargs):
            clip = MagicMock()
            clip.duration = 2.0
            clip.__enter__ = MagicMock(return_value=clip)
            clip.__exit__ = MagicMock(return_value=False)
            opened.append(clip)
            return clip

        with (
            patch.object(cardvideo, "_narrate", return_value=2.0),
            _silent_moviepy(6.0),
            patch.object(cardvideo, "AudioFileClip", side_effect=make_clip),
        ):
            with _task_dir():
                cardvideo.render_card_news("t", _script(3), _params())

        self.assertEqual(len(opened), 3)
        for clip in opened:
            self.assertTrue(clip.__exit__.called, "원본 리더가 닫히지 않았다")

    def test_the_voice_volume_is_applied_once(self):
        """
        제공자에 따라 TTS 단계에서도 음량을 건다. 두 번 걸면 0.2 를 넣은 사람이
        0.04 를 듣는다.
        """
        params = _params()
        params.voice_volume = 0.2
        with tempfile.TemporaryDirectory() as work:
            with (
                patch.object(cardvideo.voice, "tts", return_value=object()) as tts,
                patch.object(cardvideo.voice, "get_audio_duration", return_value=1.0),
                patch.object(cardvideo.os.path, "exists", return_value=True),
            ):
                cardvideo._narrate("말", os.path.join(work, "c.mp3"), params)

        self.assertEqual(tts.call_args.kwargs["voice_volume"], 1.0)


class TestNarrationRetry(unittest.TestCase):
    def test_a_provider_exception_does_not_kill_the_render(self):
        """
        제공자는 실패를 반환값이 아니라 예외로 알리기도 한다. 그대로 두면
        재시도도 무음 처리도 건너뛰고 영상 전체가 죽는다.
        """
        with tempfile.TemporaryDirectory() as work:
            with patch.object(
                cardvideo.voice, "tts", side_effect=RuntimeError("provider down")
            ):
                seconds = cardvideo._narrate(
                    "말", os.path.join(work, "card.mp3"), _params()
                )
        self.assertEqual(seconds, 0.0)

    def test_a_provider_exception_is_not_logged_with_credentials(self):
        """예외 문구에 자격 증명이 붙은 주소가 섞여 나올 수 있다."""
        leaky = RuntimeError("failed https://user:hunter2@tts.example.com")
        with tempfile.TemporaryDirectory() as work:
            with (
                patch.object(cardvideo.voice, "tts", side_effect=leaky),
                patch.object(cardvideo.logger, "warning") as warning,
            ):
                cardvideo._narrate("말", os.path.join(work, "c.mp3"), _params())

        logged = " ".join(str(call.args[0]) for call in warning.call_args_list)
        self.assertNotIn("hunter2", logged)

    def test_a_stale_file_from_a_previous_run_is_not_reused(self):
        """
        같은 task 를 다시 돌리면 지난 실행의 파일이 남아 있다. 합성이 조용히
        실패했을 때 그 파일이 있으면, 예전 소리가 새 카드에 붙는다.
        """
        with tempfile.TemporaryDirectory() as work:
            target = os.path.join(work, "card.mp3")
            with open(target, "wb") as stale:
                stale.write(b"old audio")

            with (
                patch.object(cardvideo.voice, "tts", return_value=object()),
                # 지난 파일이 남아 있으면 그 길이가 새 카드의 길이로 보고된다.
                patch.object(cardvideo.voice, "get_audio_duration", return_value=9.0),
            ):
                seconds = cardvideo._narrate("말", target, _params())

        self.assertEqual(seconds, 0.0, "예전 실행의 소리를 새 카드에 붙였다")

    def test_a_file_that_cannot_be_cleared_is_a_failure(self):
        """
        못 지웠다면 옛 파일이 그 자리에 그대로 있다는 뜻이다. 그 상태로 합성에
        들어가면 실패해도 옛 소리가 성공처럼 통과한다.
        """
        with tempfile.TemporaryDirectory() as work:
            target = os.path.join(work, "card.mp3")
            open(target, "wb").write(b"old")
            with (
                patch.object(cardvideo.os, "remove", side_effect=PermissionError("no")),
                patch.object(cardvideo.voice, "tts", return_value=object()) as tts,
                patch.object(cardvideo.voice, "get_audio_duration", return_value=9.0),
            ):
                seconds = cardvideo._narrate("말", target, _params())

        self.assertEqual(seconds, 0.0)
        tts.assert_not_called()

    def test_a_missing_file_is_not_a_failure(self):
        """처음 만드는 카드는 지울 파일이 없다."""
        with tempfile.TemporaryDirectory() as work:
            target = os.path.join(work, "card.mp3")
            with (
                patch.object(cardvideo.voice, "tts", return_value=object()),
                patch.object(cardvideo.voice, "get_audio_duration", return_value=3.0),
                patch.object(cardvideo.os.path, "exists", return_value=True),
            ):
                self.assertEqual(cardvideo._narrate("말", target, _params()), 3.0)

    def test_a_failed_synthesis_is_retried(self):
        """일시적인 실패 하나로 그 카드가 조용해지지 않게 한다."""
        params = _params()
        with tempfile.TemporaryDirectory() as work:
            target = os.path.join(work, "card.mp3")

            def tts(**kwargs):
                # 두 번째 시도에서만 파일을 남긴다.
                if tts.calls:
                    open(kwargs["voice_file"], "wb").write(b"x")
                tts.calls += 1
                return object() if tts.calls > 1 else None

            tts.calls = 0
            with (
                patch.object(cardvideo.voice, "tts", side_effect=tts),
                patch.object(cardvideo.voice, "get_audio_duration", return_value=3.0),
            ):
                self.assertEqual(cardvideo._narrate("말", target, params), 3.0)

    def test_giving_up_reports_no_duration(self):
        with tempfile.TemporaryDirectory() as work:
            with patch.object(cardvideo.voice, "tts", return_value=None):
                seconds = cardvideo._narrate(
                    "말", os.path.join(work, "card.mp3"), _params()
                )
        self.assertEqual(seconds, 0.0)


class TestOutput(unittest.TestCase):
    def test_the_result_reports_what_was_made(self):
        """호출자는 파일 경로와 길이를 알아야 다음 단계로 넘길 수 있다."""
        with patch.object(
            cardvideo, "_narrate", return_value=2.0
        ), _silent_moviepy(6.0):
            with _task_dir():
                result = cardvideo.render_card_news("t", _script(3), _params())

        self.assertIsNotNone(result)
        self.assertEqual(result.card_count, 3)
        # 합쳐진 오디오 경로를 따로 알려주지 않는다. 조각 하나를 전체인 척 내놓는
        # 필드가 있으면 받는 쪽이 그걸 나레이션 전체로 쓴다.
        self.assertFalse(hasattr(result, "audio_path"))
        self.assertAlmostEqual(result.duration, 6.0)
        self.assertTrue(result.video_path.endswith("cardnews.mp4"))

    def test_a_script_with_no_cards_makes_nothing(self):
        script = CardScript(cards=(), narrations=())
        with _task_dir():
            self.assertIsNone(cardvideo.render_card_news("t", script, _params()))


class TestArtifacts(unittest.TestCase):
    def test_the_rendered_values_are_recorded(self):
        """
        요청한 카드 수와 실제로 그려진 수, 요청한 나레이션 길이와 실제 노출 시간이
        다를 수 있다. 기록에는 실제 값이 남아야 한다.
        """
        lengths = iter([2.0, 0.0, 0.2])
        with (
            patch.object(cardvideo, "_narrate", side_effect=lambda *a, **k: next(lengths)),
            patch.object(cardvideo.task_artifacts, "patch_script_data") as patched,
            _silent_moviepy(5.0),
        ):
            with _task_dir():
                cardvideo.render_card_news("t", _script(3), _params())

        recorded = patched.call_args.kwargs["card_news"]
        self.assertEqual(recorded["cards"], 3)
        # 두 번째 카드는 소리 없이 지나갔고, 세 번째는 하한까지 늘어났다.
        self.assertEqual(recorded["silent_cards"], [2])
        self.assertEqual(recorded["durations"][2], cardnews.MIN_CARD_SECONDS)


class TestOutputLocation(unittest.TestCase):
    def test_the_output_location_comes_from_the_task(self):
        """
        경로를 인자로 받으면 그 값을 검사할 책임이 생긴다. 여기서 만드는 파일은
        지우고 덮어쓰는 것들이라, 잘못된 위치를 받으면 남의 파일을 건드린다.
        """
        import inspect

        signature = inspect.signature(cardvideo.render_card_news)
        self.assertNotIn("output_dir", signature.parameters)

    def test_everything_is_written_under_the_task_directory(self):
        with (
            patch.object(cardvideo, "_narrate", return_value=2.0),
            _silent_moviepy(6.0),
        ):
            with _task_dir() as work:
                result = cardvideo.render_card_news("t", _script(3), _params())

        # 공용 검사기가 realpath 로 푼다. macOS 의 /var 는 /private/var 로 바뀐다.
        self.assertTrue(result.video_path.startswith(os.path.realpath(work)))

    def test_a_task_name_cannot_point_outside_the_task_directory(self):
        """
        task 이름도 밖에서 오는 값이다. 여기서 만드는 파일은 지우고 덮어쓰는
        것들이라, 작업 디렉터리를 벗어나면 남의 파일을 건드린다.
        """
        for hostile in ("../../etc", "/etc", "sub/../../../etc"):
            with self.subTest(task_id=hostile):
                with (
                    patch.object(cardvideo, "_narrate") as narrate,
                    _silent_moviepy(6.0),
                    _task_dir(),
                ):
                    result = cardvideo.render_card_news(
                        hostile, _script(3), _params()
                    )

                self.assertIsNone(result)
                narrate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
