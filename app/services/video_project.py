"""Opt-in, local revision rendering. No providers, credentials or publishing.

Run ``python -m app.services.video_project --help``. Prepared footage and audio
can come from an existing MoneyPrinter task; this module does not regenerate them.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from typing import Callable, Iterator
from uuid import uuid4

PREPARED_FORMATS = "mov,matroska,avi,mpegts,mpegvideo,ogg,flv,wav,mp3,flac,aac"
SCHEMA_VERSION = 1
RENDERER_VERSION = "local-ffmpeg-v1"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class ProjectError(ValueError):
    pass


class RenderCancelled(ProjectError):
    pass


def _identifier(value: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ProjectError("IDs must be 1–64 letters, digits, underscores or hyphens")
    return value


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            json.dump(value, target, sort_keys=True, indent=2, allow_nan=False)
            target.flush()
            os.fsync(target.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def _lock(path: Path, timeout: float = 30) -> Iterator[None]:
    """OS-owned locks are released after process death; no stale PID deletion."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"0")
            handle.flush()
        end = time.monotonic() + timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (OSError, BlockingIOError):
                if time.monotonic() >= end:
                    raise ProjectError(
                        "project is busy; retry when the active operation finishes"
                    )
                time.sleep(0.05)
        try:
            yield
        finally:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_UN)


@dataclass(frozen=True)
class RenderSettings:
    width: int = 1080
    height: int = 1920
    fps: int = 30
    narration_volume: float = 1.0
    bgm_volume: float = 0.15

    @classmethod
    def parse(cls, value: dict) -> RenderSettings:
        if not isinstance(value, dict) or set(value) - set(cls.__dataclass_fields__):
            raise ProjectError(
                "unknown render settings; credentials/provider configuration are unsupported"
            )
        result = cls(**value)
        for name, limit in (("width", 4096), ("height", 4096), ("fps", 120)):
            number = getattr(result, name)
            if type(number) is not int or not 1 <= number <= limit:
                raise ProjectError(f"{name} must be an integer from 1 to {limit}")
        if result.width % 2 or result.height % 2:
            raise ProjectError("H.264 dimensions must be even")
        for name in ("narration_volume", "bgm_volume"):
            number = getattr(result, name)
            if (
                isinstance(number, bool)
                or not isinstance(number, (int, float))
                or not math.isfinite(number)
                or not 0 <= number <= 4
            ):
                raise ProjectError(f"{name} must be finite and between 0 and 4")
        return result


@dataclass(frozen=True)
class Stage:
    key: str
    kind: str
    fingerprint: str
    dependencies: tuple[str, ...]
    scene_id: str | None = None


def _tool_version(executable: str) -> str:
    try:
        result = subprocess.run(
            [executable, "-version"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return result.stdout.splitlines()[0]
    except (OSError, subprocess.SubprocessError, IndexError) as exc:
        raise ProjectError(f"working {executable} is required") from exc


def stage_graph(spec: dict) -> list[Stage]:
    """Pure dependency selection: BGM never invalidates an individual scene."""
    stages: list[Stage] = []
    scene_fingerprints: list[str] = []
    settings = RenderSettings.parse(spec["settings"])
    transform = [RENDERER_VERSION, spec["toolchain"]]
    for scene in spec["scenes"]:
        scene_id = scene["id"]
        audio = _fingerprint(
            [
                transform,
                "audio",
                scene["narration"],
                scene.get("audio"),
                scene["duration"] if not scene["audio"] else None,
                settings.narration_volume,
            ]
        )
        timing = _fingerprint(
            [
                transform,
                "timing",
                audio,
                scene["duration"] if not scene["audio"] else None,
            ]
        )
        render_inputs = [
            transform, "scene", timing, scene["footage"],
            settings.width, settings.height, settings.fps,
        ]
        # Default-zero offsets retain fingerprints of existing revisions.
        if scene.get("footage_start", 0.0):
            render_inputs.append(["footage_start", scene["footage_start"]])
        render = _fingerprint(render_inputs)
        stages.extend(
            [
                Stage(f"{scene_id}:audio", "audio", audio, (), scene_id),
                Stage(
                    f"{scene_id}:timing",
                    "timing",
                    timing,
                    (f"{scene_id}:audio",),
                    scene_id,
                ),
                Stage(
                    f"{scene_id}:scene",
                    "scene",
                    render,
                    (f"{scene_id}:audio", f"{scene_id}:timing"),
                    scene_id,
                ),
            ]
        )
        scene_fingerprints.append(render)
    assembly = _fingerprint([transform, "assembly", scene_fingerprints])
    final = _fingerprint(
        [transform, "export", assembly, spec.get("bgm"), settings.bgm_volume]
    )
    stages.extend(
        [
            Stage(
                "assembly",
                "assembly",
                assembly,
                tuple(f"{s['id']}:scene" for s in spec["scenes"]),
            ),
            Stage("export", "export", final, ("assembly",)),
        ]
    )
    return stages


class VideoProject:
    """A local project store. All reusable artifacts belong to this project."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.directory / ".project.lock"

    def _read(self, path: Path) -> dict:
        with path.open(encoding="utf-8") as source:
            return json.load(source)

    def metadata(self) -> dict:
        return self._read(self.directory / "project.json")

    def _revision_path(self, revision: str) -> Path:
        return self.directory / "revisions" / _identifier(revision)

    def revision(self, revision: str | None = None) -> dict:
        revision = revision or self.metadata()["current_revision"]
        return self._read(self._revision_path(revision) / "spec.json")

    def _asset(self, value: str, relative_to: Path) -> dict:
        path = Path(value)
        if not path.is_absolute():
            path = relative_to / path
        if not path.is_file():
            raise ProjectError(f"missing local asset: {value}")
        folder = self.directory / "assets"
        folder.mkdir(exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".asset-", dir=folder)
        try:
            with path.open("rb") as source, os.fdopen(fd, "wb") as target:
                shutil.copyfileobj(source, target)
                target.flush()
                os.fsync(target.fileno())
            digest = _digest(Path(name))
            destination = folder / digest
            os.replace(name, destination)
            return {
                "sha256": digest,
                "path": str(destination.relative_to(self.directory)),
            }
        finally:
            Path(name).unlink(missing_ok=True)

    def create_revision(self, request: dict, *, relative_to: str | Path = ".") -> dict:
        """Snapshot caller-supplied prepared media; unknown/credential fields fail."""
        if not isinstance(request, dict) or set(request) - {
            "project_id",
            "scenes",
            "settings",
            "bgm",
        }:
            raise ProjectError(
                "unknown project fields; this manifest accepts prepared local media only"
            )
        project_id = _identifier(request["project_id"])
        settings = RenderSettings.parse(request.get("settings", {}))
        raw_scenes = request.get("scenes")
        if not isinstance(raw_scenes, list) or not 1 <= len(raw_scenes) <= 100:
            raise ProjectError("provide between 1 and 100 scenes")
        scenes = []
        for raw in raw_scenes:
            if not isinstance(raw, dict) or set(raw) - {
                "id",
                "footage",
                "footage_start",
                "audio",
                "narration",
                "duration",
            }:
                raise ProjectError("unknown scene fields")
            scene_id = _identifier(raw["id"])
            footage_start = raw.get("footage_start", 0.0)
            try:
                finite_footage_start = math.isfinite(footage_start)
            except (TypeError, OverflowError):
                finite_footage_start = False
            if (
                isinstance(footage_start, bool)
                or not isinstance(footage_start, (int, float))
                or not finite_footage_start
                or footage_start < 0
            ):
                raise ProjectError("footage_start must be finite and nonnegative")
            narration = raw.get("narration", "")
            if not isinstance(narration, str) or len(narration) > 100000:
                raise ProjectError("narration must be text under 100000 characters")
            duration = raw.get("duration", 5.0)
            if (
                isinstance(duration, bool)
                or not isinstance(duration, (int, float))
                or not math.isfinite(duration)
                or not 0 < duration <= 3600
            ):
                raise ProjectError(
                    "scene duration must be finite and between 0 and 3600 seconds"
                )
            if narration and not raw.get("audio"):
                raise ProjectError(
                    "narration requires prepared audio; this renderer does not generate speech"
                )
            scenes.append(
                {
                    "id": scene_id,
                    "narration": narration,
                    "footage_start": footage_start,
                    "duration": duration,
                    "footage": self._asset(raw["footage"], Path(relative_to)),
                    "audio": self._asset(raw["audio"], Path(relative_to))
                    if raw.get("audio")
                    else None,
                }
            )
        if len({s["id"] for s in scenes}) != len(scenes):
            raise ProjectError("scene IDs must be unique and retained across revisions")
        bgm = (
            self._asset(request["bgm"], Path(relative_to))
            if request.get("bgm")
            else None
        )
        revision_id = uuid4().hex
        spec = {
            "schema_version": SCHEMA_VERSION,
            "project_id": project_id,
            "revision_id": revision_id,
            "scenes": scenes,
            "settings": asdict(settings),
            "bgm": bgm,
            "toolchain": {
                "ffmpeg": _tool_version("ffmpeg"),
                "ffprobe": _tool_version("ffprobe"),
            },
        }
        with _lock(self.lock_path):
            metadata_path = self.directory / "project.json"
            metadata = (
                self._read(metadata_path)
                if metadata_path.exists()
                else {
                    "schema_version": SCHEMA_VERSION,
                    "project_id": project_id,
                    "last_successful_export": None,
                }
            )
            if metadata["project_id"] != project_id:
                raise ProjectError("directory already belongs to another project")
            spec["parent_revision"] = metadata.get("current_revision")
            _atomic_json(self._revision_path(revision_id) / "spec.json", spec)
            _atomic_json(
                self._revision_path(revision_id) / "status.json",
                {"state": "pending", "stages": {}},
            )
            metadata["current_revision"] = revision_id
            _atomic_json(metadata_path, metadata)
        return spec

    def _asset_path(self, asset: dict) -> Path:
        path = self.directory / "assets" / asset["sha256"]
        if path.is_symlink() or not path.is_file() or _digest(path) != asset["sha256"]:
            raise ProjectError(
                "source snapshot failed integrity validation; create a new revision from the original asset"
            )
        return path

    def _cached(self, stage: Stage, dependencies: dict | None = None) -> dict | None:
        folder = self.directory / "artifacts" / stage.fingerprint
        record_path = folder / "record.json"
        if not record_path.is_file():
            return None
        try:
            record = self._read(record_path)
            digest = record["sha256"]
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                return None
            suffix = (
                ".json"
                if stage.kind == "timing"
                else ".wav"
                if stage.kind == "audio"
                else ".mp4"
            )
            media = folder / f"output-{digest}{suffix}"
            if dependencies is not None:
                actual_dependencies = []
                for key in stage.dependencies:
                    if key not in dependencies:
                        return None
                    actual_dependencies.append(
                        {
                            "fingerprint": dependencies[key]["fingerprint"],
                            "sha256": dependencies[key]["sha256"],
                        }
                    )
                if record.get("dependencies") != actual_dependencies:
                    return None
            if (
                not media.is_symlink()
                and record["fingerprint"] == stage.fingerprint
                and record["sha256"] == _digest(media)
                and record["size"] == media.stat().st_size
            ):
                return {**record, "path": str(media)}
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def plan(self, revision: str | None = None) -> list[dict]:
        spec = self.revision(revision)
        for scene in spec["scenes"]:
            self._asset_path(scene["footage"])
            if scene["audio"]:
                self._asset_path(scene["audio"])
        if spec["bgm"]:
            self._asset_path(spec["bgm"])
        parent = (
            {
                stage.key: stage.fingerprint
                for stage in stage_graph(self.revision(spec["parent_revision"]))
            }
            if spec["parent_revision"]
            else {}
        )
        planned = []
        verified = {}
        for stage in stage_graph(spec):
            cached = self._cached(stage, verified)
            if cached:
                verified[stage.key] = cached
            reason = (
                "matching dependencies and verified bytes"
                if cached
                else (
                    "dependencies changed since parent revision"
                    if stage.key in parent and parent[stage.key] != stage.fingerprint
                    else "artifact failed integrity validation"
                    if (
                        self.directory / "artifacts" / stage.fingerprint / "record.json"
                    ).exists()
                    else "no completed artifact for these dependencies"
                )
            )
            planned.append(
                {
                    **asdict(stage),
                    "action": "reuse" if cached else "build",
                    "reason": reason,
                }
            )
        return planned

    def status(self, revision: str | None = None) -> dict:
        revision = revision or self.metadata()["current_revision"]
        return self._read(self._revision_path(revision) / "status.json")

    def cancel(self, revision: str | None = None) -> None:
        with _lock(self.lock_path):
            revision = revision or self.metadata()["current_revision"]
            self.revision(revision)
            _atomic_json(
                self._revision_path(revision) / "cancel.json", {"cancelled": True}
            )

    def _run(self, arguments: list[str], cancel: Path, timeout: float) -> str:
        if cancel.exists():
            raise RenderCancelled("revision cancelled")
        # Prepared media may contain playlist references. Never let an input
        # silently initiate network access; allow local files and pipes only.
        secured_arguments = []
        for argument in arguments:
            if argument == "-i":
                secured_arguments.extend(["-protocol_whitelist", "file,pipe"])
            secured_arguments.append(argument)
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(
                secured_arguments, stdout=subprocess.PIPE, stderr=errors, text=True
            )
            deadline = time.monotonic() + timeout
            try:
                while True:
                    if cancel.exists():
                        raise RenderCancelled("revision cancelled")
                    if time.monotonic() >= deadline:
                        raise ProjectError("media command exceeded its stage deadline")
                    try:
                        stdout, _ = process.communicate(timeout=0.1)
                        break
                    except subprocess.TimeoutExpired:
                        pass
                if process.returncode:
                    errors.seek(0, os.SEEK_END)
                    size = errors.tell()
                    errors.seek(max(0, size - 8192))
                    raise ProjectError(
                        "media command failed: "
                        + errors.read().decode(errors="replace")
                    )
                return stdout
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()

    def render(
        self,
        revision: str | None = None,
        *,
        retry: bool = False,
        ffmpeg: str = "ffmpeg",
        ffprobe: str = "ffprobe",
        stage_timeout: float = 600,
        on_stage: Callable[[Stage, bool], None] | None = None,
    ) -> dict:
        if not math.isfinite(stage_timeout) or stage_timeout <= 0:
            raise ProjectError("stage timeout must be finite and positive")
        spec = self.revision(revision)
        revision = spec["revision_id"]
        folder = self._revision_path(revision)
        cancel = folder / "cancel.json"
        # One writer per revision, different revisions may build independently.
        with _lock(folder / ".render.lock"):
            status = self.status(revision)
            if (
                status["state"] in {"failed", "cancelled", "running"} or cancel.exists()
            ) and not retry:
                raise ProjectError(
                    "interrupted/failed/cancelled revision requires explicit --retry"
                )
            if retry:
                cancel.unlink(missing_ok=True)
            status["state"] = "running"
            status.pop("error", None)
            _atomic_json(folder / "status.json", status)
            results = {}
            current_stage = None
            try:
                actual_tools = {
                    "ffmpeg": _tool_version(ffmpeg),
                    "ffprobe": _tool_version(ffprobe),
                }
                if actual_tools != spec["toolchain"]:
                    raise ProjectError(
                        "FFmpeg toolchain changed; create a revision to rebuild with its new fingerprint"
                    )
                self.plan(revision)  # Verify source snapshots before starting.
                for stage in stage_graph(spec):
                    current_stage = stage.key
                    if cancel.exists():
                        raise RenderCancelled("revision cancelled")
                    cached = self._cached(stage, results)
                    reused = cached is not None
                    if on_stage:
                        on_stage(stage, reused)
                    if cancel.exists():
                        raise RenderCancelled("revision cancelled")
                    if cached is None:
                        cached = self._build(
                            stage, spec, results, ffmpeg, ffprobe, cancel, stage_timeout
                        )
                    results[stage.key] = cached
                    status["stages"][stage.key] = {
                        "fingerprint": stage.fingerprint,
                        "reused": reused,
                        "sha256": cached["sha256"],
                    }
                    _atomic_json(folder / "status.json", status)
                with _lock(self.lock_path):
                    if cancel.exists():
                        raise RenderCancelled("revision cancelled")
                    metadata = self.metadata()
                    promoted = metadata["current_revision"] == revision
                    if promoted:
                        metadata["last_successful_export"] = {
                            "revision_id": revision,
                            **results["export"],
                        }
                        _atomic_json(self.directory / "project.json", metadata)
                    status.update(
                        state="succeeded", promoted=promoted, export=results["export"]
                    )
                    _atomic_json(folder / "status.json", status)
                return status
            except BaseException as exc:
                status.update(
                    state="cancelled"
                    if isinstance(exc, (RenderCancelled, KeyboardInterrupt))
                    else "failed",
                    failed_stage=current_stage,
                    error=str(exc),
                )
                _atomic_json(folder / "status.json", status)
                raise

    def _build(
        self,
        stage: Stage,
        spec: dict,
        results: dict,
        ffmpeg: str,
        ffprobe: str,
        cancel: Path,
        timeout: float,
    ) -> dict:
        scene = next((s for s in spec["scenes"] if s["id"] == stage.scene_id), None)
        settings = RenderSettings.parse(spec["settings"])
        work = self.directory / ".work"
        work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="stage-", dir=work) as temporary:
            temporary = Path(temporary)
            suffix = (
                ".json"
                if stage.kind == "timing"
                else ".wav"
                if stage.kind == "audio"
                else ".mp4"
            )
            output = temporary / ("output" + suffix)
            base = [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-threads",
                "1",
                "-filter_threads",
                "1",
            ]
            if stage.kind == "audio":
                if scene["audio"]:
                    source = [
                        "-format_whitelist",
                        PREPARED_FORMATS,
                        "-i",
                        str(self._asset_path(scene["audio"])),
                    ]
                else:
                    source = [
                        "-f",
                        "lavfi",
                        "-i",
                        "anullsrc=r=48000:cl=stereo",
                        "-t",
                        str(scene["duration"]),
                    ]
                self._run(
                    base
                    + source
                    + [
                        "-vn",
                        "-af",
                        f"volume={settings.narration_volume}",
                        "-ar",
                        "48000",
                        "-ac",
                        "2",
                        "-c:a",
                        "pcm_s16le",
                        str(output),
                    ],
                    cancel,
                    timeout,
                )
            elif stage.kind == "timing":
                audio = results[f"{scene['id']}:audio"]["path"]
                duration = float(
                    self._run(
                        [
                            ffprobe,
                            "-v",
                            "error",
                            "-show_entries",
                            "format=duration",
                            "-of",
                            "default=noprint_wrappers=1:nokey=1",
                            audio,
                        ],
                        cancel,
                        timeout,
                    ).strip()
                )
                if not math.isfinite(duration) or not 0 < duration <= 3600:
                    raise ProjectError(
                        "prepared audio duration must be between 0 and 3600 seconds"
                    )
                _atomic_json(output, {"duration": duration})
            elif stage.kind == "scene":
                duration = self._read(Path(results[f"{scene['id']}:timing"]["path"]))[
                    "duration"
                ]
                vf = f"scale={settings.width}:{settings.height}:force_original_aspect_ratio=increase,crop={settings.width}:{settings.height},setsar=1,fps={settings.fps}"
                self._run(
                    base
                    + [
                        "-stream_loop",
                        "-1",
                        "-ss",
                        str(scene.get("footage_start", 0.0)),
                        "-format_whitelist",
                        PREPARED_FORMATS,
                        "-i",
                        str(self._asset_path(scene["footage"])),
                        "-i",
                        results[f"{scene['id']}:audio"]["path"],
                        "-map",
                        "0:v:0",
                        "-map",
                        "1:a:0",
                        "-vf",
                        vf,
                        "-t",
                        str(duration),
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "aac",
                        "-ar",
                        "48000",
                        "-ac",
                        "2",
                        "-movflags",
                        "+faststart",
                        str(output),
                    ],
                    cancel,
                    timeout,
                )
            elif stage.kind == "assembly":
                # Relative numeric links avoid concat syntax/path injection, including apostrophes.
                for index, scene_spec in enumerate(spec["scenes"]):
                    shutil.copyfile(
                        results[f"{scene_spec['id']}:scene"]["path"],
                        temporary / f"{index}.mp4",
                    )
                listing = temporary / "concat.txt"
                listing.write_text(
                    "".join(
                        f"file '{index}.mp4'\n" for index in range(len(spec["scenes"]))
                    ),
                    encoding="utf-8",
                )
                self._run(
                    base
                    + [
                        "-f",
                        "concat",
                        "-safe",
                        "1",
                        "-i",
                        str(listing),
                        "-c",
                        "copy",
                        "-movflags",
                        "+faststart",
                        str(output),
                    ],
                    cancel,
                    timeout,
                )
            elif spec["bgm"] and settings.bgm_volume:
                mix = f"[1:a]volume={settings.bgm_volume}[music];[0:a][music]amix=inputs=2:duration=first:normalize=0[a]"
                self._run(
                    base
                    + [
                        "-i",
                        results["assembly"]["path"],
                        "-stream_loop",
                        "-1",
                        "-format_whitelist",
                        PREPARED_FORMATS,
                        "-i",
                        str(self._asset_path(spec["bgm"])),
                        "-filter_complex",
                        mix,
                        "-map",
                        "0:v:0",
                        "-map",
                        "[a]",
                        "-c:v",
                        "copy",
                        "-c:a",
                        "aac",
                        "-movflags",
                        "+faststart",
                        str(output),
                    ],
                    cancel,
                    timeout,
                )
            else:
                shutil.copyfile(results["assembly"]["path"], output)
            if cancel.exists():
                raise RenderCancelled("revision cancelled")
            with output.open("rb") as completed:
                os.fsync(completed.fileno())
            record = {
                "fingerprint": stage.fingerprint,
                "sha256": _digest(output),
                "size": output.stat().st_size,
                "renderer_version": RENDERER_VERSION,
                "kind": stage.kind,
                "dependencies": [
                    {
                        "fingerprint": results[key]["fingerprint"],
                        "sha256": results[key]["sha256"],
                    }
                    for key in stage.dependencies
                ],
            }
            destination = self.directory / "artifacts" / stage.fingerprint
            with _lock(self.lock_path):
                # Another revision may have finished the same fingerprint. Keep its
                # committed bytes immutable instead of replacing a live export.
                existing = self._cached(stage, results)
                if existing is not None:
                    return existing
                # Media first, commit record last. Interrupted writes are never trusted.
                destination.mkdir(parents=True, exist_ok=True)
                published = destination / f"output-{record['sha256']}{suffix}"
                os.replace(output, published)
                _atomic_json(destination / "record.json", record)
            return {**record, "path": str(published)}

    def compare(self, before: str, after: str) -> list[dict]:
        left = {stage.key: stage for stage in stage_graph(self.revision(before))}
        right = {stage.key: stage for stage in stage_graph(self.revision(after))}
        return [
            {
                "stage": key,
                "change": "added"
                if key not in left
                else "removed"
                if key not in right
                else "unchanged"
                if left[key].fingerprint == right[key].fingerprint
                else "changed",
            }
            for key in sorted(left.keys() | right.keys())
        ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Revision-aware local video projects (prepared media, no API calls)"
    )
    parser.add_argument(
        "--project",
        required=True,
        help="Project directory; project-scoped snapshots and artifacts",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    revise = commands.add_parser(
        "revise",
        help="Create/current-select an immutable revision from a JSON manifest",
    )
    revise.add_argument("manifest")
    revise.add_argument("--preset", help="Reusable validated render-settings JSON")
    for name in ("plan", "status", "cancel"):
        commands.add_parser(name).add_argument("--revision")
    render = commands.add_parser("render")
    render.add_argument("--revision")
    render.add_argument("--retry", action="store_true")
    render.add_argument("--stage-timeout", type=float, default=600)
    compare = commands.add_parser("compare")
    compare.add_argument("before")
    compare.add_argument("after")
    preset = commands.add_parser(
        "save-preset",
        help="Export current render settings without assets or credentials",
    )
    preset.add_argument("output")
    args = parser.parse_args(argv)
    try:
        project = VideoProject(args.project)
        if args.command == "revise":
            manifest = Path(args.manifest).resolve()
            with manifest.open(encoding="utf-8") as source:
                request = json.load(source)
            if args.preset:
                with Path(args.preset).open(encoding="utf-8") as source:
                    request["settings"] = asdict(
                        RenderSettings.parse(json.load(source))
                    )
            result = project.create_revision(request, relative_to=manifest.parent)
        elif args.command == "render":
            result = project.render(
                args.revision, retry=args.retry, stage_timeout=args.stage_timeout
            )
        elif args.command == "compare":
            result = project.compare(args.before, args.after)
        elif args.command == "save-preset":
            result = project.revision()["settings"]
            _atomic_json(Path(args.output), result)
        elif args.command == "cancel":
            project.cancel(args.revision)
            result = {"cancel_requested": True}
        else:
            result = getattr(project, args.command)(args.revision)
        print(json.dumps(result, indent=2))
        return 0
    except (ProjectError, OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"video project: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
