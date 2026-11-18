import errno
import re
import threading
import time
import tomllib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import toml
import pytest

from app.config import config
from app.models.llm_provider import LLM_PROVIDER_REGISTRY, get_llm_provider


class TestConfigPersistence:
    @staticmethod
    def _wait_for_deferred_flush(timeout=1):
        """Wait for the config refresh thread to exit, so concurrent tests don't share background state."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with config._pending_config_lock:
                if not config._pending_config_flush_scheduled:
                    return
            time.sleep(0.005)
        raise AssertionError("deferred config flush did not finish")

    @staticmethod
    def _load_example_config():
        config_path = Path(__file__).resolve().parents[2] / "config.example.toml"
        return tomllib.loads(config_path.read_text(encoding="utf-8"))

    def test_example_config_documents_runtime_settings(self):
        """The example config should show the services, materials and advanced runtime parameters users need to maintain by hand."""
        example_config = self._load_example_config()
        app_config = example_config["app"]

        assert example_config["listen_host"] == "0.0.0.0"
        assert example_config["listen_port"] == 8080
        assert example_config["log_level"] == "DEBUG"
        assert app_config["video_source"] in {
            "pexels",
            "pixabay",
            "coverr",
            "volcengine_seedance",
            "ofox",
            "metaso_minimax",
            "muapi",
            "loomloom",
            "local",
        }
        assert "match_materials_to_script" in app_config
        assert app_config["script_generation_backend"] == "local"
        assert app_config["loomloom_api_token"] == ""
        assert app_config["loomloom_video_run_timeout_seconds"] == 1800
        assert app_config["volcengine_seedance_api_key"] == ""
        assert app_config["volcengine_seedance_base_url"].startswith("https://")
        assert app_config["volcengine_seedance_model"]
        assert app_config["ofox_api_key"] == ""
        assert app_config["ofox_base_url"].startswith("https://")
        assert app_config["ofox_text_to_video_model"]
        assert app_config["metaso_minimax_api_key"] == ""
        assert app_config["metaso_minimax_base_url"].startswith("https://")
        assert app_config["metaso_minimax_resolution"] in {"768P", "2K"}
        assert app_config["muapi_api_key"] == ""
        assert app_config["muapi_base_url"].startswith("https://")
        assert app_config["muapi_video_endpoint"]
        assert app_config["muapi_resolution"]
        assert app_config["muapi_min_duration"] == 3
        assert app_config["muapi_max_duration"] == 12
        assert app_config["useapi_api_token"] == ""
        assert app_config["useapi_video_model"] == "veo-3.1-lite"
        assert app_config["useapi_resolution"] == ""
        assert app_config["useapi_upscale"] == ""
        assert app_config["useapi_poll_interval"] == 10
        assert app_config["useapi_run_timeout"] == 1800
        assert app_config["useapi_image_model"] == "nano-banana-2-lite"
        assert "loomloom_market_listing_id" not in app_config
        assert "loomloom_video_market_listing_id" not in app_config
        assert app_config["shengsuanyun_api_key"] == ""
        assert example_config["voxcpm"] == {
            "base_url": "https://api.modelbest.cn/v1",
            "api_key": "",
            "model_id": "",
            "voice_id": "default",
        }
        # Video-to-Music reads music_base_url from [elevenlabs] and, unlike the
        # API key, it has no environment-variable fallback: if the example omits
        # it there is no documented way to route the endpoint through a proxy.
        assert example_config["elevenlabs"] == {
            "api_key": "",
            "model_id": "eleven_multilingual_v2",
            "music_base_url": "https://api.elevenlabs.io",
            "music_model_id": "music_v2",
            "music_timeout": 600,
        }
        assert example_config["whisper"]["device"] == "cpu"

    def test_example_config_covers_llm_provider_registry(self):
        """Configurable Provider fields in the Registry must be discoverable in the example file."""
        app_config = self._load_example_config()["app"]

        for provider in LLM_PROVIDER_REGISTRY:
            if provider.show_api_key:
                assert provider.config_key("api_key") in app_config
            if provider.show_base_url:
                assert provider.config_key("base_url") in app_config
            if provider.requires_model_name:
                assert provider.config_key("model_name") in app_config
            for field in provider.extra_fields:
                assert provider.config_key(field.config_suffix) in app_config

    def test_example_ui_block_documents_every_pinnable_default(self):
        """The [ui] comment block must list every key the code actually reads from [ui].

        This block is the only entry point for users to pin initial defaults by hand, so listing only some keys makes settings
        silently ineffective: a user who wrote [ui].subtitle_display_mode following the example may never know it exists because the example
        didn't mention it. The assertion is derived from the source code, so it fails first when a new pinnable field is added.
        """
        project_root = Path(__file__).resolve().parents[2]
        ui_block = (project_root / "config.example.toml").read_text(
            encoding="utf-8"
        ).split("[ui]", 1)[1]
        documented = set(re.findall(r"^#\s*([a-z_]+)\s*=", ui_block, re.MULTILINE))

        schema_text = (project_root / "app/models/schema.py").read_text(
            encoding="utf-8"
        )
        pinnable = set(re.findall(r'config\.ui\.get\(\s*"([a-z_]+)"', schema_text))
        pinnable |= set(
            re.findall(r'_get_valid_ui_choice\(\s*"([a-z_]+)"', schema_text)
        )
        cli_text = (project_root / "cli.py").read_text(encoding="utf-8")
        pinnable |= set(
            re.findall(r'_ui_config_value\(\s*\w+\s*,\s*"([a-z_]+)"', cli_text)
        )

        assert pinnable <= documented, sorted(pinnable - documented)

    def test_load_config_accepts_repeated_utf8_bom_without_rewriting_file(self):
        """A duplicate BOM shouldn't stop Windows users from starting, nor rewrite the existing config."""
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            original_content = b"\xef\xbb\xbf\xef\xbb\xbf[app]\nvideo_source = \"pexels\"\n"
            config_path.write_bytes(original_content)

            with patch.object(config, "config_file", str(config_path)):
                loaded_config = config.load_config()

            assert loaded_config["app"]["video_source"] == "pexels"
            assert config_path.read_bytes() == original_content

    def test_load_config_still_rejects_invalid_toml_after_bom_normalization(self):
        """BOM tolerance must not mask real syntax errors, and a clear diagnostic log should be kept on failure."""
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text("[app\nvideo_source = \"pexels\"\n", encoding="utf-8")

            with (
                patch.object(config, "config_file", str(config_path)),
                patch.object(config.logger, "error") as error_mock,
                pytest.raises(toml.TomlDecodeError),
            ):
                config.load_config()

            error_message = str(error_mock.call_args.args[0])
            assert str(config_path) in error_message
            assert "TomlDecodeError" in error_message

    def test_load_config_recovers_empty_config_directory(self):
        """Docker can create an empty directory at a missing file bind-mount path."""
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.toml"
            config_path.mkdir()
            (root / "config.example.toml").write_text(
                '[app]\nvideo_source = "pexels"\n', encoding="utf-8"
            )

            with (
                patch.object(config, "root_dir", temp_dir),
                patch.object(config, "config_file", str(config_path)),
            ):
                loaded_config = config.load_config()

            assert loaded_config["app"]["video_source"] == "pexels"
            assert config_path.is_file()

    def test_load_config_preserves_nonempty_config_directory(self):
        """A mistaken config.toml directory must not be recursively deleted."""
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.toml"
            config_path.mkdir()
            sentinel = config_path / "user-data.txt"
            sentinel.write_text("keep this file", encoding="utf-8")
            (root / "config.example.toml").write_text(
                '[app]\nvideo_source = "pexels"\n', encoding="utf-8"
            )

            with (
                patch.object(config, "root_dir", temp_dir),
                patch.object(config, "config_file", str(config_path)),
            ):
                with pytest.raises(IsADirectoryError, match="config.toml"):
                    config.load_config()

            assert sentinel.read_text(encoding="utf-8") == "keep this file"

    def test_kimi_uses_current_default_model(self):
        """When Kimi has no model override configured, the current release's default model should be used."""
        provider = get_llm_provider("moonshot")

        assert provider is not None
        assert provider.resolve_model_name("") == "kimi-k3"

    def test_upload_post_settings_belong_to_app_section(self):
        """Publishing config must be under the app node, so the example file matches the path read at runtime."""
        example_config = self._load_example_config()
        upload_post_keys = {
            "upload_post_enabled",
            "upload_post_api_key",
            "upload_post_username",
            "upload_post_platforms",
            "upload_post_auto_upload",
            "upload_post_youtube_privacy_status",
            "upload_post_max_pending_tasks",
        }

        assert upload_post_keys <= example_config["app"].keys()
        assert upload_post_keys.isdisjoint(example_config.get("ui", {}).keys())

    def test_save_config_uses_parseable_atomic_output(self):
        """
        Config saving writes a temp file first and then atomically replaces. The test also confirms the output is still valid TOML,
        and that no temp file is left in the config directory after a successful save.
        """
        original_cfg = dict(config._cfg)
        original_app = dict(config.app)
        try:
            with TemporaryDirectory() as temp_dir:
                config_path = Path(temp_dir) / "config.toml"
                config.app["atomic_save_test"] = "ok"
                with (
                    patch.object(config, "root_dir", temp_dir),
                    patch.object(config, "config_file", str(config_path)),
                ):
                    config.save_config()

                saved_config = tomllib.loads(config_path.read_text(encoding="utf-8"))
                assert saved_config["app"]["atomic_save_test"] == "ok"
                assert list(Path(temp_dir).glob(".config-*.toml.tmp")) == []
        finally:
            config.app.clear()
            config.app.update(original_app)
            config._cfg.clear()
            config._cfg.update(original_cfg)

    def test_save_config_falls_back_for_bind_mounted_file(self):
        """
        A Docker Desktop single-file mount point can't be replaced by os.replace. On EBUSY it
        should overwrite in place inside the lock, making sure the final content is complete, parseable and leaves no temp file.
        """
        original_cfg = dict(config._cfg)
        original_app = dict(config.app)
        try:
            with TemporaryDirectory() as temp_dir:
                config_path = Path(temp_dir) / "config.toml"
                config_path.write_text("[app]\nold_value = true\n", encoding="utf-8")
                config.app["bind_mount_save_test"] = "ok"

                with (
                    patch.object(config, "root_dir", temp_dir),
                    patch.object(config, "config_file", str(config_path)),
                    patch.object(
                        config.os,
                        "replace",
                        side_effect=OSError(
                            errno.EBUSY,
                            "Device or resource busy",
                        ),
                    ),
                    patch.object(config.logger, "warning") as warning_mock,
                ):
                    config.save_config()

                saved_config = tomllib.loads(config_path.read_text(encoding="utf-8"))
                assert saved_config["app"]["bind_mount_save_test"] == "ok"
                assert list(Path(temp_dir).glob(".config-*.toml.tmp")) == []
                warning_mock.assert_called_once()
        finally:
            config.app.clear()
            config.app.update(original_app)
            config._cfg.clear()
            config._cfg.update(original_cfg)

    def test_save_config_does_not_hide_other_replace_errors(self):
        """Non-EBUSY errors must still be raised, not disguise permission or disk failures as a successful save."""
        original_cfg = dict(config._cfg)
        original_app = dict(config.app)
        try:
            with TemporaryDirectory() as temp_dir:
                config_path = Path(temp_dir) / "config.toml"
                config_path.write_text("[app]\nold_value = true\n", encoding="utf-8")
                config.app["replace_error_test"] = "not-saved"

                with (
                    patch.object(config, "root_dir", temp_dir),
                    patch.object(config, "config_file", str(config_path)),
                    patch.object(
                        config.os,
                        "replace",
                        side_effect=OSError(errno.EACCES, "Permission denied"),
                    ),
                ):
                    try:
                        config.save_config()
                    except OSError as exc:
                        assert exc.errno == errno.EACCES
                    else:
                        raise AssertionError("expected config save to fail")

                saved_config = tomllib.loads(config_path.read_text(encoding="utf-8"))
                assert saved_config["app"]["old_value"] is True
                assert list(Path(temp_dir).glob(".config-*.toml.tmp")) == []
        finally:
            config.app.clear()
            config.app.update(original_app)
            config._cfg.clear()
            config._cfg.update(original_cfg)

    def test_save_config_round_trips_windows_paths_and_nbsp(self):
        """
        A Windows path with a folder that starts with "x" (xiaoming, x64) and
        a non-breaking space must load back unchanged: toml 0.10.2's encoder
        wrote such paths as invalid TOML and the space as the text "xa0".
        """
        values = {
            ("app", "ffmpeg_path"): r"C:\Users\xiaoming\ffmpeg\bin\ffmpeg.exe",
            ("app", "material_directory"): r"D:\videos\x64",
            ("ui", "custom_bgm_file"): r"C:\Users\xiaoming\Music\bgm.mp3",
            ("ui", "video_script_prompt"): "Ton\N{NO-BREAK SPACE}: humoristique",
            # TOML, unlike JSON, requires DEL to be escaped.
            ("ui", "custom_system_prompt"): "Say \"hi\".\n\tThen stop.\x7f",
        }
        sections = {"app": config.app, "ui": config.ui}
        original_cfg = dict(config._cfg)
        original_app = dict(config.app)
        original_ui = dict(config.ui)
        try:
            with TemporaryDirectory() as temp_dir:
                config_path = Path(temp_dir) / "config.toml"
                for (section, key), value in values.items():
                    sections[section][key] = value
                with (
                    patch.object(config, "root_dir", temp_dir),
                    patch.object(config, "config_file", str(config_path)),
                ):
                    config.save_config()

                content = config_path.read_text(encoding="utf-8")
                for loaded in (
                    config._load_toml_config(str(config_path)),
                    tomllib.loads(content),
                ):
                    for (section, key), value in values.items():
                        assert loaded[section][key] == value
        finally:
            config.app.clear()
            config.app.update(original_app)
            config.ui.clear()
            config.ui.update(original_ui)
            config._cfg.clear()
            config._cfg.update(original_cfg)

    def test_runtime_config_lock_blocks_concurrent_config_writes(self):
        """While a long task holds the run lock, other sessions can't rewrite global config midway through the task."""
        write_started = threading.Event()
        write_finished = threading.Event()

        def update_config():
            write_started.set()
            config.app["runtime_lock_test"] = "updated"
            write_finished.set()

        config.app.pop("runtime_lock_test", None)
        with config.runtime_config_lock():
            worker = threading.Thread(target=update_config)
            worker.start()
            assert write_started.wait(timeout=1)
            assert not write_finished.wait(timeout=0.05)

        worker.join(timeout=1)
        assert write_finished.is_set()
        config.app.pop("runtime_lock_test", None)

    def test_runtime_config_lock_allows_idempotent_page_writes(self):
        """When the page is refreshed during generation, writing back identical widget values must not block the full-page render."""
        key = "runtime_lock_idempotent_test"
        config.app[key] = "unchanged"
        write_finished = threading.Event()

        def write_same_value():
            config.app[key] = "unchanged"
            assert config.app.setdefault(key, "other") == "unchanged"
            config.app.update({key: "unchanged"})
            assert config.app.pop("runtime_lock_missing_key", None) is None
            write_finished.set()

        with config.runtime_config_lock():
            worker = threading.Thread(target=write_same_value)
            worker.start()
            assert write_finished.wait(timeout=0.2)

        worker.join(timeout=1)
        assert config.app[key] == "unchanged"
        config.app.pop(key, None)

    def test_try_runtime_config_lock_returns_immediately_when_busy(self):
        """The preview lock must not wait for the long task to release global config; when busy it should let the UI prompt a retry immediately."""
        attempted = threading.Event()
        result = []

        def try_lock():
            with config.try_runtime_config_lock() as acquired:
                result.append(acquired)
            attempted.set()

        with config.runtime_config_lock():
            worker = threading.Thread(target=try_lock)
            worker.start()
            assert attempted.wait(timeout=0.2)

        worker.join(timeout=1)
        assert result == [False]

        with config.try_runtime_config_lock() as acquired:
            assert acquired is True

    def test_nonblocking_update_is_applied_after_runtime_task_finishes(self):
        """WebUI changes must not wait for the long task, and the latest values must be applied and saved after the task ends."""
        key = "nonblocking_runtime_update_test"
        original_value = config.app.get(key, config._MISSING)
        update_finished = threading.Event()
        update_result = []

        def update_config():
            update_result.append(
                config.update_config_nonblocking(config.app, key, "updated")
            )
            update_finished.set()

        try:
            with patch.object(config, "save_config") as save_config:
                with config.runtime_config_lock():
                    worker = threading.Thread(target=update_config)
                    worker.start()
                    assert update_finished.wait(timeout=0.2)
                    assert update_result == [False]
                    assert config.app.get(key) != "updated"

                worker.join(timeout=1)
                assert config.app[key] == "updated"
                save_config.assert_called_once()
        finally:
            if original_value is config._MISSING:
                config.app.pop(key, None)
            else:
                config.app[key] = original_value

    def test_nonblocking_update_keeps_only_latest_value(self):
        """When the same widget is changed repeatedly during a task, only the last choice should be applied."""
        key = "nonblocking_latest_value_test"
        original_value = config.app.get(key, config._MISSING)
        updates_finished = threading.Event()

        def update_config():
            assert not config.update_config_nonblocking(config.app, key, "first")
            assert not config.update_config_nonblocking(config.app, key, "latest")
            updates_finished.set()

        try:
            with patch.object(config, "save_config"):
                with config.runtime_config_lock():
                    worker = threading.Thread(target=update_config)
                    worker.start()
                    assert updates_finished.wait(timeout=0.2)

                worker.join(timeout=1)
                assert config.app[key] == "latest"
        finally:
            if original_value is config._MISSING:
                config.app.pop(key, None)
            else:
                config.app[key] = original_value

    def test_nonblocking_delete_is_applied_after_runtime_task_finishes(self):
        """When switching back to the default option, deleting config also must not block the running video task."""
        key = "nonblocking_runtime_delete_test"
        config.app[key] = "custom"
        delete_finished = threading.Event()
        delete_result = []

        def delete_config():
            delete_result.append(config.delete_config_nonblocking(config.app, key))
            delete_finished.set()

        try:
            with patch.object(config, "save_config") as save_config:
                with config.runtime_config_lock():
                    worker = threading.Thread(target=delete_config)
                    worker.start()
                    assert delete_finished.wait(timeout=0.2)
                    assert delete_result == [False]
                    assert config.app[key] == "custom"

                worker.join(timeout=1)
                assert key not in config.app
                save_config.assert_called_once()
        finally:
            config.app.pop(key, None)

    def test_try_save_config_returns_immediately_while_runtime_task_is_active(self):
        """When a page rerun requests a save it must not wait for the video task to release the config lock."""
        save_finished = threading.Event()
        save_result = []

        def save_config():
            save_result.append(config.try_save_config())
            save_finished.set()

        with patch.object(config, "save_config") as blocking_save:
            with config.runtime_config_lock():
                worker = threading.Thread(target=save_config)
                worker.start()
                assert save_finished.wait(timeout=0.2)
                assert save_result == [False]

            worker.join(timeout=1)
            blocking_save.assert_called_once()

        self._wait_for_deferred_flush()

    def test_try_runtime_lock_flushes_updates_queued_during_operation(self):
        """When a short operation releases the config lock, page changes that arrived meanwhile must also be applied and saved."""
        key = "try_runtime_queued_update_test"
        original_value = config.app.get(key, config._MISSING)
        update_finished = threading.Event()

        def queue_update():
            assert not config.update_config_nonblocking(config.app, key, "updated")
            update_finished.set()

        try:
            with patch.object(config, "save_config") as save_config:
                with config.try_runtime_config_lock() as acquired:
                    assert acquired is True
                    worker = threading.Thread(target=queue_update)
                    worker.start()
                    assert update_finished.wait(timeout=0.2)
                    assert config.app.get(key) != "updated"

                worker.join(timeout=1)
                assert config.app[key] == "updated"
                save_config.assert_called_once()

            self._wait_for_deferred_flush()
        finally:
            if original_value is config._MISSING:
                config.app.pop(key, None)
            else:
                config.app[key] = original_value

    def test_update_queued_during_save_is_flushed_after_lock_release(self):
        """New changes made during the exit save must not stay in the queue nor be overwritten by earlier values."""
        key = "late_runtime_update_test"
        original_value = config.app.get(key, config._MISSING)
        runtime_entered = threading.Event()
        release_runtime = threading.Event()
        first_save_started = threading.Event()
        release_first_save = threading.Event()
        second_save_finished = threading.Event()
        save_count = 0
        save_count_lock = threading.Lock()

        def blocking_save():
            nonlocal save_count
            with save_count_lock:
                save_count += 1
                current_save = save_count
            if current_save == 1:
                first_save_started.set()
                assert release_first_save.wait(timeout=1)
            elif current_save == 2:
                second_save_finished.set()

        def hold_runtime_lock():
            with config.runtime_config_lock():
                runtime_entered.set()
                assert release_runtime.wait(timeout=1)

        try:
            with patch.object(config, "save_config", side_effect=blocking_save):
                runtime_worker = threading.Thread(target=hold_runtime_lock)
                runtime_worker.start()
                assert runtime_entered.wait(timeout=1)

                assert not config.update_config_nonblocking(config.app, key, "first")
                release_runtime.set()
                assert first_save_started.wait(timeout=1)

                # The first save round already took a config snapshot, so a value arriving now must be applied and saved
                # again by the background refresh thread after the lock is released, and the final result should reflect that value.
                assert not config.update_config_nonblocking(config.app, key, "latest")
                release_first_save.set()

                runtime_worker.join(timeout=1)
                assert not runtime_worker.is_alive()
                assert second_save_finished.wait(timeout=1)
                assert config.app[key] == "latest"
                assert save_count == 2

            self._wait_for_deferred_flush()
        finally:
            release_runtime.set()
            release_first_save.set()
            if original_value is config._MISSING:
                config.app.pop(key, None)
            else:
                config.app[key] = original_value

    def test_config_snapshot_includes_pending_updates(self):
        """While video generation holds the lock, new LLM requests should see the latest UI choices rather than the old config."""
        keys = {
            "llm_provider": "pending-provider",
            "pending-provider_api_key": "pending-key",
            "pending-provider_model_name": "pending-model",
        }
        original_values = {key: config.app.get(key, config._MISSING) for key in keys}
        updates_finished = threading.Event()

        def queue_updates():
            for key, value in keys.items():
                assert not config.update_config_nonblocking(config.app, key, value)
            updates_finished.set()

        try:
            with patch.object(config, "save_config"):
                with config.runtime_config_lock():
                    worker = threading.Thread(target=queue_updates)
                    worker.start()
                    assert updates_finished.wait(timeout=0.2)

                    snapshot = config.snapshot_config_with_pending(config.app)
                    assert all(snapshot[key] == value for key, value in keys.items())
                    assert config.app.get("llm_provider") != "pending-provider"

                worker.join(timeout=1)

            self._wait_for_deferred_flush()
        finally:
            for key, original_value in original_values.items():
                if original_value is config._MISSING:
                    config.app.pop(key, None)
                else:
                    config.app[key] = original_value
