"""Motion Studio: storyboard validation, writer repair, key handling, uploads, timing and API."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import asgi
from app.config import config
from app.models.motion import LlmSettings, MotionJobRequest, Storyboard
from app.services.motion import jobs, pipeline, speech, writer
from app.services.motion.errors import MotionError
from app.services.motion.speech import Speech

FIXTURE = Path(__file__).resolve().parents[1] / "resources" / "motion_storyboard.json"
SECRET = "sk-test-SECRET-key-1234567890"


def fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def job_request(**llm) -> MotionJobRequest:
    return MotionJobRequest(
        title="Minimum due trap", topic="Credit card minimum due", voice="hi-IN-MadhurNeural",
        llm=LlmSettings(**{"provider": "openai", "model": "gpt-5-mini", "api_key": SECRET, **llm}),
    )


def tiny_glb(extensions_required=()) -> bytes:
    body = json.dumps({"asset": {"version": "2.0"}, "extensionsRequired": list(extensions_required)}).encode()
    body += b" " * (-len(body) % 4)
    return b"glTF" + (2).to_bytes(4, "little") + (20 + len(body)).to_bytes(4, "little") + \
        len(body).to_bytes(4, "little") + b"JSON" + body


class TestStoryboard(unittest.TestCase):
    def test_fixture_validates_and_tags_get_shorts(self):
        board = Storyboard.model_validate(fixture())
        self.assertEqual(len(board.beats), 6)
        self.assertIn("#MinimumDue", board.youtube.hashtags)
        self.assertIn("#Shorts", board.youtube.hashtags)

    def test_layout_without_its_fields_is_rejected(self):
        data = fixture()
        del data["beats"][2]["left"]
        with self.assertRaises(ValidationError) as caught:
            Storyboard.model_validate(data)
        self.assertIn("compare beat needs: left", str(caught.exception))

    def test_extract_json_tolerates_fences_and_chatter(self):
        self.assertEqual(writer.extract_json('Sure!\n```json\n{"a": 1}\n```\nEnjoy'), {"a": 1})
        self.assertEqual(writer.extract_json('Here: {"a": {"b": 2}} done'), {"a": {"b": 2}})
        with self.assertRaises(ValueError):
            writer.extract_json("no json here")


class TestWriter(unittest.TestCase):
    def test_one_repair_round_fixes_a_bad_reply(self):
        broken = fixture()
        del broken["youtube"]
        replies = iter([json.dumps(broken), json.dumps(fixture())])
        with mock.patch.object(writer, "complete", side_effect=lambda s, m: next(replies)) as complete:
            board = writer.write(job_request())
        self.assertEqual(len(board.beats), 6)
        repair = complete.call_args_list[1].args[1][-1]["content"]
        self.assertIn("youtube", repair)

    def test_two_bad_replies_fail_with_a_plain_message(self):
        with mock.patch.object(writer, "complete", return_value="not json"):
            with self.assertRaises(MotionError) as caught:
                writer.write(job_request())
        self.assertIn("didn't match the required format", str(caught.exception))

    def test_provider_error_text_never_contains_the_key(self):
        error = Exception(f"bad request for key {SECRET} at https://api.example")
        message = writer.friendly_error(error, writer.PROVIDERS["openai"], SECRET)
        self.assertNotIn(SECRET, message)

    def test_keyless_provider_never_falls_back_to_server_env_keys(self):
        import litellm

        settings = LlmSettings(provider="custom", model="m", base_url="http://127.0.0.1:9/v1")
        reply = mock.Mock(choices=[mock.Mock(message=mock.Mock(content="{}"))])
        with mock.patch.object(litellm, "completion", return_value=reply) as completion:
            writer.complete(settings, [])
        self.assertEqual(completion.call_args.kwargs["api_key"], "no-key")

    def test_custom_endpoint_errors_are_not_reflected(self):
        error = Exception("internal admin page body: secret-ish details")
        message = writer.friendly_error(error, writer.PROVIDERS["custom"], None)
        self.assertNotIn("admin page", message)

    def test_missing_key_is_caught_before_any_call(self):
        with self.assertRaises(MotionError):
            writer.complete(LlmSettings(provider="anthropic", model="claude-sonnet-5-5"), [])

    def test_key_is_hidden_in_repr_and_dumps(self):
        request = job_request()
        self.assertNotIn(SECRET, repr(request))
        self.assertNotIn(SECRET, request.model_dump_json())


class TestTiming(unittest.TestCase):
    def test_breaks_follow_punctuation_and_beat_end(self):
        words = [{"text": t} for t in ["Hello", "there", "friend"]]
        speech.mark_breaks(words, "Hello, there friend")
        self.assertEqual([w.get("br") for w in words], [True, False, True])

    def test_tokens_written_without_spaces_become_one_caption_word(self):
        spoken = ["या", "cybercrime", ".", "gov", ".", "in", "पर"]
        words = [{"text": t, "start": i, "end": i + 0.5} for i, t in enumerate(spoken)]
        joined = speech.join_glued(words, "या cybercrime.gov.in पर, ok")
        self.assertEqual([w["text"] for w in joined], ["या", "cybercrime.gov.in", "पर"])
        self.assertEqual((joined[1]["start"], joined[1]["end"]), (1, 5.5))
        self.assertEqual(words[1]["text"], "cybercrime")  # input left untouched
        missing = [{"text": "x", "start": 0, "end": 1}]
        self.assertEqual(speech.join_glued(missing, "other text"), missing)

    def test_emphasis_finds_the_spoken_word(self):
        words = [{"text": "सबसे", "start": 1.0}, {"text": "महंगी", "start": 1.4}, {"text": "गलती", "start": 1.9}]
        self.assertEqual(speech.emphasis_time(words, "महंगी"), 1.4)
        self.assertIsNone(speech.emphasis_time(words, "missing"))

    def test_scene_storyboard_times_beats_and_drops_narration(self):
        board = Storyboard.model_validate(fixture())
        beats = [(i * 5.0, i * 5.0 + 4.5) for i in range(6)]
        words = [{"text": "महंगी", "start": 1.2, "end": 1.5}]
        scene = pipeline.scene_storyboard(board, Speech(words, beats, 31.0), {"kind": "none"})
        self.assertEqual(scene["beats"][0]["start"], 0.0)
        self.assertEqual(scene["beats"][0]["emph"], 1.2)
        self.assertNotIn("say", scene["beats"][0])
        self.assertEqual(scene["duration"], 31.0)


class TestCharacters(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.multiple(jobs, UPLOADS_DIR=Path(self.tmp.name) / "up", PRESETS_DIR=Path(self.tmp.name) / "pre")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_valid_files_are_saved_and_resolved(self):
        glb = jobs.save_upload("chiku.glb", tiny_glb())
        png = jobs.save_upload("me.png", b"\x89PNG\r\n\x1a\n" + b"0" * 20)
        self.assertEqual((glb["kind"], png["kind"]), ("glb", "image"))
        self.assertEqual(jobs.resolve_character(glb["id"]).suffix, ".glb")

    def test_bad_files_are_rejected_with_a_reason(self):
        cases = [("a.exe", b"MZ"), ("a.png", b"GIF89a"), ("a.glb", b"glTF" + b"\0" * 30),
                 ("a.glb", tiny_glb(["KHR_draco_mesh_compression"]))]
        for name, data in cases:
            with self.subTest(name=name), self.assertRaises(MotionError):
                jobs.save_upload(name, data)

    def test_unknown_or_traversal_ids_do_not_resolve(self):
        for cid in ("up-missing", "preset-..", "up-../../config"):
            with self.subTest(cid=cid), self.assertRaises(MotionError):
                jobs.resolve_character(cid)


class TestJobRunner(unittest.TestCase):
    def test_finished_job_exposes_no_key(self):
        board = Storyboard.model_validate(fixture())
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(jobs, "JOBS_DIR", Path(tmp)), \
                mock.patch.object(writer, "write", return_value=board), \
                mock.patch.object(pipeline, "prepare", return_value=Speech([], [], 40.0)), \
                mock.patch.object(jobs, "_render"):
            job = jobs.Job(id="0123456789abcdef", title="t", secret=[job_request()])
            jobs._run(job, None)
            saved = (Path(tmp) / job.id / "youtube.json").read_text(encoding="utf-8")
        self.assertEqual(job.status, "done")
        self.assertEqual(job.secret, [])
        self.assertNotIn(SECRET, json.dumps(job.public(), ensure_ascii=False) + saved)

    def test_cancelling_a_queued_job_releases_the_key(self):
        job = jobs.Job(id="0123456789abcdef", title="t", secret=[job_request()])
        jobs.cancel(job)
        self.assertEqual((job.status, job.secret), ("cancelled", []))
        with mock.patch.object(writer, "write") as write:
            jobs._run(job, None)
        write.assert_not_called()

    def test_writer_failure_message_reaches_the_job(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(jobs, "JOBS_DIR", Path(tmp)), \
                mock.patch.object(writer, "write", side_effect=MotionError("OpenAI rejected the API key.")):
            job = jobs.Job(id="0123456789abcdef", title="t", secret=[job_request()])
            jobs._run(job, None)
        self.assertEqual((job.status, job.message), ("failed", "OpenAI rejected the API key."))


class TestRendererPaths(unittest.TestCase):
    def test_only_engine_and_job_files_are_served(self):
        from app.services.motion import renderer

        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp).resolve()
            handler = renderer._Handler.__new__(renderer._Handler)
            handler.roots = {"/engine/": renderer.ENGINE_DIR.resolve(), "/job/": job}
            self.assertEqual(Path(handler.translate_path("/job/words.json?x=1")), job / "words.json")
            self.assertTrue(handler.translate_path("/engine/auto.js").endswith("auto.js"))
            for bad in ("/job/../secret.txt", "/engine/../../config.toml", "/other/x", "/job/%2e%2e/x"):
                with self.subTest(path=bad):
                    self.assertTrue(handler.translate_path(bad).endswith("__missing__"))


class TestRendererLoop(unittest.TestCase):
    """render() with a stand-in Playwright (CI has no browser): frames reach ffmpeg, progress is reported."""

    def fake_playwright(self, page_errors=()):
        page = mock.Mock()
        page.screenshot.return_value = b"jpeg"
        page.on.side_effect = lambda event, cb: [cb(e) for e in page_errors] if event == "pageerror" else None
        browser = mock.Mock(new_page=mock.Mock(return_value=page))
        pw = mock.Mock()
        pw.chromium.launch.return_value = browser
        manager = mock.MagicMock()
        manager.__enter__.return_value = pw
        module = mock.Mock(sync_playwright=mock.Mock(return_value=manager))
        return module, page

    def job_dir(self, tmp):
        job = Path(tmp)
        (job / "words.json").write_text("[]", encoding="utf-8")
        (job / "env.json").write_text("[]", encoding="utf-8")
        (job / "storyboard.json").write_text(json.dumps({"duration": 0.2}), encoding="utf-8")
        return job

    def test_every_frame_is_piped_to_ffmpeg(self):
        from app.services.motion import renderer

        module, page = self.fake_playwright()
        ffmpeg = mock.Mock()
        ffmpeg.wait.return_value = 0
        ffmpeg.poll.return_value = 0
        reports = []
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("sys.modules", {"playwright.sync_api": module}), \
                mock.patch.object(renderer.subprocess, "Popen", return_value=ffmpeg):
            out = renderer.render(self.job_dir(tmp), lambda done, total: reports.append((done, total)))
        self.assertEqual(out.name, "video.mp4")
        self.assertEqual(ffmpeg.stdin.write.call_count, 6)  # 0.2 s at 30 fps
        self.assertEqual(reports[-1], (6, 6))
        page.goto.assert_called_once()

    def test_a_broken_scene_stops_before_rendering(self):
        from app.services.motion import renderer

        module, _ = self.fake_playwright(page_errors=["ReferenceError: x is not defined"])
        ffmpeg = mock.Mock()
        ffmpeg.poll.return_value = None
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("sys.modules", {"playwright.sync_api": module}), \
                mock.patch.object(renderer.subprocess, "Popen", return_value=ffmpeg), self.assertRaises(RuntimeError):
            renderer.render(self.job_dir(tmp))
        ffmpeg.kill.assert_called_once()


class TestSpeechSynthesis(unittest.TestCase):
    def test_beats_are_joined_with_exact_offsets(self):
        import numpy as np

        async def fake_tts(text, voice):
            return b"", [{"text": "Hello,", "start": 0.1, "end": 0.4}, {"text": "there", "start": 0.5, "end": 0.9}]

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(speech, "_synthesize", new=fake_tts), \
                mock.patch.object(speech, "_decode", return_value=np.zeros(speech.SAMPLE_RATE, np.int16)):
            result = speech.synthesize(["Hello, there", "Hello, there"], "en-US-AndrewNeural", Path(tmp))
            written = sorted(p.name for p in Path(tmp).iterdir())
        gap = speech.BEAT_GAP_S
        self.assertEqual(result.beats, [(0.0, 1.0), (round(1 + gap, 3), round(2 + gap, 3))])
        self.assertEqual(result.words[2]["start"], round(0.1 + 1 + gap, 3))
        self.assertEqual([w.get("br") for w in result.words], [True, True, True, True])
        self.assertAlmostEqual(result.duration, 2 + gap + speech.HOLD_S, places=2)
        self.assertEqual(written, ["audio.m4a", "env.json", "words.json"])

    def test_voice_failures_become_plain_messages(self):
        async def offline(text, voice):
            raise OSError("network down")

        with self.assertRaises(MotionError):
            speech.synthesize(["x"], "xx-Unknown", Path("."))
        with mock.patch.object(speech, "_synthesize", new=offline), self.assertRaises(MotionError) as caught:
            speech.synthesize(["x"], "en-US-AndrewNeural", Path("."))
        self.assertIn("voice service", str(caught.exception))


class TestPipelinePrepare(unittest.TestCase):
    def test_character_and_scene_are_staged_for_the_renderer(self):
        board = Storyboard.model_validate(fixture())
        voice = Speech([], [(i * 5.0, i * 5.0 + 4.0) for i in range(6)], 31.0)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(speech, "synthesize", return_value=voice):
            src = Path(tmp) / "Me.PNG"
            src.write_bytes(b"png")
            job = Path(tmp) / "job"
            job.mkdir()
            pipeline.prepare(job, board, "hi-IN-MadhurNeural", src)
            scene = json.loads((job / "storyboard.json").read_text(encoding="utf-8"))
            copied = (job / "character.png").is_file()
        self.assertTrue(copied)
        self.assertEqual(scene["character"], {"kind": "image", "url": "/job/character.png"})
        self.assertEqual(len(scene["beats"]), 6)


class FakeRender:
    def __init__(self, lines, code=0):
        self.stdout, self.returncode, self.pid = iter(lines), code, 0

    def wait(self):
        return self.returncode

    def poll(self):
        return self.returncode


class TestRenderStage(unittest.TestCase):
    def run_render(self, popen):
        job = jobs.Job(id="0123456789abcdef", title="t")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(jobs.subprocess, "Popen", side_effect=popen):
            try:
                jobs._render(job, Path(tmp))
                return job, None
            except MotionError as error:
                return job, error

    def test_progress_lines_drive_the_job(self):
        job, error = self.run_render(lambda cmd, **kw: FakeRender(["noise\n", "progress 5 10\n", "progress 10 10\n"]))
        self.assertIsNone(error)
        self.assertEqual(job.progress, 1.0)

    def test_failures_map_to_a_fix(self):
        def missing_playwright(cmd, **kw):
            kw["stderr"].write("ModuleNotFoundError: No module named 'playwright'")
            kw["stderr"].flush()
            return FakeRender([], 1)

        _, error = self.run_render(missing_playwright)
        self.assertIn("uv pip install playwright", str(error))
        _, error = self.run_render(lambda cmd, **kw: FakeRender([], 1))
        self.assertIn("render.log", str(error))

    def test_timeout_says_so(self):
        def slow(cmd, **kw):
            return FakeRender([], 1)

        with mock.patch.object(jobs.threading, "Timer") as timer:
            timer.return_value.start.side_effect = lambda: timer.call_args.args[1]()
            with mock.patch.object(jobs, "_kill_tree"):
                _, error = self.run_render(slow)
        self.assertIn("took longer than", str(error))


class TestApi(unittest.TestCase):
    def setUp(self):
        self.original = dict(config.app)
        config.app["api_key"] = ""
        self.client = TestClient(asgi.app)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original)

    def test_options_list_providers_and_voices(self):
        data = self.client.get("/api/v1/motion/options").json()["data"]
        self.assertIn("anthropic", [p["id"] for p in data["providers"]])
        self.assertIn("hi-IN-MadhurNeural", [v["id"] for v in data["voices"]])

    def test_create_job_never_echoes_the_key(self):
        body = job_request().model_dump(mode="json")
        body["llm"]["api_key"] = SECRET
        with mock.patch.object(jobs, "submit", return_value=jobs.Job(id="0123456789abcdef", title="t")) as submit:
            response = self.client.post("/api/v1/motion/jobs", json=body)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SECRET, response.text)
        self.assertEqual(submit.call_args.args[0].llm.api_key.get_secret_value(), SECRET)

    def test_validation_errors_do_not_echo_the_key(self):
        body = job_request().model_dump(mode="json")
        body["llm"]["api_key"] = SECRET
        del body["title"]
        response = self.client.post("/api/v1/motion/jobs", json=body)
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(SECRET, response.text)

    def test_rejects_unknown_voice_and_bad_ids(self):
        body = job_request().model_dump(mode="json")
        body["voice"] = "xx-XX-Nobody"
        self.assertEqual(self.client.post("/api/v1/motion/jobs", json=body).status_code, 400)
        self.assertEqual(self.client.get("/api/v1/motion/jobs/not-a-job").status_code, 400)
        self.assertEqual(self.client.get("/api/v1/motion/jobs/0123456789abcdef").status_code, 404)

    def test_server_key_protects_motion_routes(self):
        config.app["api_key"] = "server-secret"
        self.assertEqual(self.client.get("/api/v1/motion/options").status_code, 401)
        ok = self.client.get("/api/v1/motion/options", headers={"x-api-key": "server-secret"})
        self.assertEqual(ok.status_code, 200)

    def test_upload_then_fetch_a_character(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.multiple(jobs, UPLOADS_DIR=Path(tmp) / "up", PRESETS_DIR=Path(tmp) / "pre"):
            ok = self.client.post("/api/v1/motion/characters", files={"file": ("chiku.glb", tiny_glb(), "model/gltf-binary")})
            bad = self.client.post("/api/v1/motion/characters", files={"file": ("x.png", b"GIF89a", "image/png")})
            fetched = self.client.get(f"/api/v1/motion/characters/{ok.json()['data']['id']}")
            missing = self.client.get("/api/v1/motion/characters/up-nothing")
        self.assertEqual((ok.status_code, bad.status_code, fetched.status_code, missing.status_code), (200, 400, 200, 404))
        self.assertEqual(fetched.content[:4], b"glTF")

    def test_status_cancel_and_video_routes(self):
        job = jobs.Job(id="fedcba9876543210", title="My: video?", status="writing", secret=[job_request()])
        jobs._jobs[job.id] = job
        self.addCleanup(jobs._jobs.pop, job.id, None)
        self.assertEqual(self.client.get(f"/api/v1/motion/jobs/{job.id}").json()["data"]["status"], "writing")
        self.assertEqual(self.client.get(f"/api/v1/motion/jobs/{job.id}/video").status_code, 404)
        self.assertEqual(self.client.post(f"/api/v1/motion/jobs/{job.id}/cancel").status_code, 200)
        self.assertTrue(job.cancelled)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(jobs, "JOBS_DIR", Path(tmp)):
            (Path(tmp) / job.id).mkdir()
            (Path(tmp) / job.id / "video.mp4").write_bytes(b"mp4")
            job.status = "done"
            video = self.client.get(f"/api/v1/motion/jobs/{job.id}/video")
        self.assertEqual(video.status_code, 200)
        self.assertIn("My-video", video.headers["content-disposition"])

    def test_queue_limit_answers_429(self):
        body = job_request().model_dump(mode="json")
        body["llm"]["api_key"] = SECRET
        with mock.patch.object(jobs, "submit", side_effect=jobs.Busy()):
            self.assertEqual(self.client.post("/api/v1/motion/jobs", json=body).status_code, 429)

    def test_engine_scripts_are_served_as_javascript(self):
        response = self.client.get("/motion-engine/auto.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("javascript", response.headers["content-type"])


if __name__ == "__main__":
    unittest.main()
