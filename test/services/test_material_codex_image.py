"""Codex images use the existing sequential image material/render path."""

import io
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from app.config import config
from app.models.schema import ImageMotion, VideoAspect
from app.services import codex_image, material


def png_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (80, 120), "purple").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def context():
    return codex_image.CodexImageContext("image-responses-model", 300, 41)


@pytest.fixture
def image_environment(monkeypatch, tmp_path, context):
    monkeypatch.setitem(config.app, "material_directory", str(tmp_path))
    monkeypatch.setitem(config.app, "openai_image_prompt_template", "WRONG {term}")
    monkeypatch.setattr(codex_image, "capture_context", lambda: context)
    monkeypatch.setattr(codex_image, "assert_current", lambda value: None)


def download(context, **kwargs):
    options = dict(
        task_id="codex-images-test",
        search_terms=["first", "second", "third"],
        source="codex_image",
        audio_duration=10,
        max_clip_duration=5,
        image_motion=ImageMotion.static,
        codex_image_context=context,
    )
    options.update(kwargs)
    return material.download_videos(**options)


def test_generate_png_and_independent_prompt(image_environment, context, tmp_path):
    with patch.object(
        codex_image, "generate_image", return_value=png_bytes()
    ) as generate:
        items = material.generate_images_codex(
            "pyramid construction",
            5,
            VideoAspect.landscape,
            str(tmp_path),
            context=context,
        )
    assert len(items) == 1
    item = items[0]
    assert item.provider == "codex_image"
    assert item.duration == 5
    assert item.source_info["provider"] == "codex_image"
    assert item.source_info["rendition"] == {"id": None, "width": 80, "height": 120}
    assert Path(item.url).is_file()
    with Image.open(item.url) as image:
        assert image.format == "PNG"
        assert image.size == (80, 120)
    prompt, submitted_context = generate.call_args.args
    assert "pyramid construction" in prompt
    assert "16:9" in prompt
    assert "WRONG" not in prompt
    assert submitted_context is context


@pytest.mark.parametrize("duration", [0, -1])
def test_nonpositive_duration_never_generates(image_environment, context, duration):
    with (
        patch.object(codex_image, "generate_image") as generate,
        patch.object(codex_image, "capture_context") as capture,
        patch.object(material, "_persist_material_sources"),
    ):
        assert download(None, audio_duration=duration) == []
        assert material.generate_images_codex("term", duration) == []
    generate.assert_not_called()
    capture.assert_not_called()


def test_sequential_stop_motion_context_and_provenance(image_environment, context):
    with (
        patch.object(
            codex_image, "generate_image", return_value=png_bytes()
        ) as generate,
        patch.object(
            material,
            "_render_openai_image_video",
            side_effect=["first.mp4", "second.mp4"],
        ) as render,
        patch.object(material, "_persist_material_sources") as persist,
        patch.object(material, "_search_videos_with_cache") as cache,
    ):
        assert download(context) == ["first.mp4", "second.mp4"]
    assert generate.call_count == 2
    assert all(call.args[1] is context for call in generate.call_args_list)
    assert all(
        call.kwargs["image_motion"] == ImageMotion.static
        for call in render.call_args_list
    )
    assert [record["provider"] for record in persist.call_args.args[1]] == [
        "codex_image"
    ] * 2
    cache.assert_not_called()


@pytest.mark.parametrize("failure", ["invalid_image", "uncertain", "save", "render"])
def test_failure_never_generates_next_term(image_environment, context, failure):
    image_data = b"not an image" if failure == "invalid_image" else png_bytes()
    generation_error = codex_image.CodexImageError("codex.image.uncertain")
    with (
        patch.object(
            codex_image, "generate_image", return_value=image_data
        ) as generate,
        patch.object(
            material,
            "_render_openai_image_video",
            return_value="" if failure == "render" else "clip.mp4",
        ) as render,
        patch.object(material, "_persist_material_sources") as persist,
    ):
        if failure == "uncertain":
            generate.side_effect = generation_error
        if failure == "save":
            with patch.object(
                material, "_save_openai_image_file", side_effect=OSError("private path")
            ):
                with pytest.raises(material.CodexImageMaterialError) as error:
                    download(context)
        else:
            with pytest.raises(material.CodexImageMaterialError) as error:
                download(context)
    assert generate.call_count == 1
    assert render.call_count == (1 if failure == "render" else 0)
    assert "private path" not in str(error.value)
    persist.assert_called()


def test_account_change_while_rendering_cannot_publish(image_environment, context):
    changed = False

    def assert_current(value):
        if changed:
            raise codex_image.CodexImageError("codex.oauth.changed")

    def render(*args, **kwargs):
        nonlocal changed
        changed = True
        return "old-account.mp4"

    with (
        patch.object(codex_image, "assert_current", side_effect=assert_current),
        patch.object(
            codex_image, "generate_image", return_value=png_bytes()
        ) as generate,
        patch.object(material, "_render_openai_image_video", side_effect=render),
        patch.object(material, "_persist_material_sources") as persist,
    ):
        with pytest.raises(material.CodexImageMaterialError) as error:
            download(context)
    assert error.value.key == "codex.oauth.changed"
    assert generate.call_count == 1
    assert persist.call_args.args[1] == []


def test_direct_material_call_snapshots_once(image_environment, context):
    with (
        patch.object(codex_image, "capture_context", return_value=context) as capture,
        patch.object(codex_image, "generate_image", return_value=png_bytes()),
        patch.object(material, "_render_openai_image_video", return_value="clip.mp4"),
        patch.object(material, "_persist_material_sources"),
    ):
        assert len(download(None)) == 2
    capture.assert_called_once_with()


def test_stale_context_is_rejected_before_generation(image_environment, context):
    with (
        patch.object(
            codex_image,
            "assert_current",
            side_effect=codex_image.CodexImageError("codex.oauth.changed"),
        ),
        patch.object(codex_image, "generate_image") as generate,
    ):
        with pytest.raises(material.CodexImageMaterialError) as error:
            download(context)
    assert error.value.key == "codex.oauth.changed"
    generate.assert_not_called()


def test_failed_second_image_keeps_prior_provenance(image_environment, context):
    with (
        patch.object(
            codex_image,
            "generate_image",
            side_effect=[
                png_bytes(),
                codex_image.CodexImageError("codex.image.uncertain"),
            ],
        ) as generate,
        patch.object(material, "_render_openai_image_video", return_value="first.mp4"),
        patch.object(material, "_persist_material_sources") as persist,
    ):
        with pytest.raises(material.CodexImageMaterialError):
            download(context)
    assert generate.call_count == 2
    assert len(persist.call_args.args[1]) == 1
    assert persist.call_args.args[1][0]["local_file"] == "first.mp4"
