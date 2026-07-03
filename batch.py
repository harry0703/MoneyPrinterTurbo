"""Batch queue runner.

Generate many videos in one go from a list of subjects (or full job specs) and
copy every finished video into an output directory you choose. Jobs are pulled
from a worker pool, so you can control how many run at the same time.

Examples
--------
Subjects on the command line::

    python batch.py --subject "Benefits of walking" --subject "How to save money"

Subjects from a plain-text file (one per line, ``#`` starts a comment)::

    python batch.py --jobs-file jobs.txt --output-dir /output

Full control from a JSON file (a list of objects with VideoParams fields)::

    python batch.py --jobs-file jobs.json --concurrency 2 --output-dir /output

Inside Docker (writes to the host folder mapped by MPT_OUTPUT_DIR in .env)::

    docker compose run --rm api python batch.py --jobs-file jobs.txt
"""

import argparse
import json
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Sequence

from loguru import logger

from app.models.schema import MaterialInfo, VideoParams
from app.services import task as tm
from app.utils import utils

_STOP_AT_CHOICES = ["script", "terms", "audio", "subtitle", "materials", "video"]

# The WebUI picks a TTS voice from a dropdown, but batch/CLI jobs have none by
# default and Edge TTS then fails with "Invalid voice ''". Pick a sensible free
# Edge voice from the job's language so unattended batches just work.
_DEFAULT_VOICES = {
    "es": "es-ES-ElviraNeural-Female",
    "ca": "ca-ES-JoanaNeural-Female",
    "en": "en-US-JennyNeural-Female",
    "fr": "fr-FR-DeniseNeural-Female",
    "de": "de-DE-KatjaNeural-Female",
}
_FALLBACK_VOICE = "en-US-JennyNeural-Female"


def _default_voice_for_language(language: str) -> str:
    prefix = (language or "").strip().lower().split("-")[0]
    return _DEFAULT_VOICES.get(prefix, _FALLBACK_VOICE)


def _video_params_fields() -> set:
    # Pydantic v2 exposes model_fields; fall back to v1 __fields__ just in case.
    fields = getattr(VideoParams, "model_fields", None)
    if fields is None:
        fields = getattr(VideoParams, "__fields__", {})
    return set(fields.keys())


def _slugify(text: str, max_length: int = 60) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return (text or "video")[:max_length]


def _coerce_materials(value):
    if not value:
        return None
    materials = []
    for entry in value:
        if isinstance(entry, MaterialInfo):
            materials.append(entry)
        elif isinstance(entry, str):
            # Actual duration is detected later during processing; 0 is a placeholder.
            materials.append(MaterialInfo(provider="local", url=entry, duration=0))
        elif isinstance(entry, dict):
            materials.append(MaterialInfo(**entry))
    return materials or None


def load_jobs(subjects: Sequence[str], jobs_file: str | None) -> List[dict]:
    """Build the job list from repeated --subject flags and/or a jobs file."""
    jobs: List[dict] = []
    for subject in subjects or []:
        subject = subject.strip()
        if subject:
            jobs.append({"video_subject": subject})

    if jobs_file:
        with open(jobs_file, "r", encoding="utf-8") as fp:
            content = fp.read()
        if jobs_file.lower().endswith(".json"):
            data = json.loads(content)
            if isinstance(data, dict):
                data = data.get("jobs", [])
            for item in data:
                if isinstance(item, str):
                    jobs.append({"video_subject": item})
                elif isinstance(item, dict):
                    jobs.append(dict(item))
                else:
                    raise ValueError(f"invalid job entry: {item!r}")
        else:
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                jobs.append({"video_subject": line})

    return jobs


def build_params(job: dict, defaults: dict) -> VideoParams:
    merged = {**defaults, **job}
    allowed = _video_params_fields()
    kwargs = {}
    for key, value in merged.items():
        if key == "task_id" or value is None:
            continue
        if key not in allowed:
            logger.warning(f"ignoring unknown job field: {key}")
            continue
        if key == "video_materials":
            value = _coerce_materials(value)
            if value is None:
                continue
        kwargs[key] = value

    if not kwargs.get("video_subject") and not kwargs.get("video_script"):
        raise ValueError("each job needs a 'video_subject' (or 'video_script')")
    if not kwargs.get("voice_name"):
        kwargs["voice_name"] = _default_voice_for_language(
            kwargs.get("video_language", "")
        )
    return VideoParams(**kwargs)


def run_one(
    index: int,
    total: int,
    job: dict,
    defaults: dict,
    output_dir: str,
    stop_at: str,
) -> dict:
    subject = job.get("video_subject") or job.get("video_script") or "video"
    task_id = job.get("task_id") or utils.get_uuid()
    info = {
        "index": index,
        "subject": subject,
        "task_id": task_id,
        "status": "failed",
        "outputs": [],
    }

    try:
        params = build_params(job, defaults)
    except Exception as e:
        info["error"] = f"invalid job: {e}"
        logger.error(f"[{index}/{total}] invalid job '{subject}': {e}")
        return info

    logger.info(f"[{index}/{total}] start '{subject}' (task {task_id}, stop_at={stop_at})")
    try:
        result = tm.start(task_id=task_id, params=params, stop_at=stop_at)
    except Exception as e:
        info["error"] = str(e)
        logger.exception(f"[{index}/{total}] '{subject}' crashed")
        return info

    if not result:
        info["error"] = "generation failed (see logs above)"
        logger.error(f"[{index}/{total}] '{subject}' failed")
        return info

    videos = result.get("videos") or [] if isinstance(result, dict) else []
    slug = _slugify(subject)
    copied = []
    for n, video_path in enumerate(videos, start=1):
        if not video_path or not os.path.isfile(video_path):
            continue
        suffix = f"-{n}" if len(videos) > 1 else ""
        dest = os.path.join(output_dir, f"{index:03d}-{slug}{suffix}.mp4")
        try:
            shutil.copyfile(video_path, dest)
            copied.append(dest)
        except Exception as e:
            logger.error(f"[{index}/{total}] failed to copy {video_path} -> {dest}: {e}")

    info["outputs"] = copied
    # A partial run (stop_at != "video") has no final videos but still succeeded.
    info["status"] = "done" if (copied or stop_at != "video") else "no-output"
    logger.success(f"[{index}/{total}] done '{subject}' -> {len(copied)} file(s)")
    return info


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Batch queue video generation")
    parser.add_argument(
        "--subject",
        action="append",
        dest="subjects",
        default=[],
        help="a video subject; repeat for multiple videos",
    )
    parser.add_argument(
        "--jobs-file",
        help="path to a .txt (one subject per line) or .json (list of job objects) file",
    )
    parser.add_argument(
        "--output-dir",
        default=os.environ.get("MPT_BATCH_OUTPUT", "storage/output"),
        help="where finished videos are copied (default: $MPT_BATCH_OUTPUT or storage/output)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="how many videos to generate at the same time (default: 1)",
    )
    parser.add_argument(
        "--stop-at",
        default="video",
        choices=_STOP_AT_CHOICES,
        help="stop each job early at this stage (default: video = full render)",
    )
    # Global defaults applied to every job unless the job overrides them.
    parser.add_argument("--video-language", default=None)
    parser.add_argument("--video-source", default=None)
    parser.add_argument("--video-aspect", default=None)
    parser.add_argument("--video-count", type=int, default=None)
    parser.add_argument("--voice-name", default=None)
    args = parser.parse_args(argv)

    jobs = load_jobs(args.subjects, args.jobs_file)
    if not jobs:
        parser.error("no jobs found: pass --subject and/or --jobs-file")

    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    defaults = {
        key: value
        for key, value in {
            "video_language": args.video_language,
            "video_source": args.video_source,
            "video_aspect": args.video_aspect,
            "video_count": args.video_count,
            "voice_name": args.voice_name,
        }.items()
        if value is not None
    }

    total = len(jobs)
    concurrency = max(1, args.concurrency)
    logger.info(
        f"batch: {total} job(s), concurrency={concurrency}, "
        f"stop_at={args.stop_at}, output={output_dir}"
    )

    results: List[dict] = []
    if concurrency == 1:
        for i, job in enumerate(jobs, start=1):
            results.append(run_one(i, total, job, defaults, output_dir, args.stop_at))
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {
                pool.submit(
                    run_one, i, total, job, defaults, output_dir, args.stop_at
                ): i
                for i, job in enumerate(jobs, start=1)
            }
            for future in as_completed(futures):
                results.append(future.result())

    results.sort(key=lambda item: item["index"])
    manifest_path = os.path.join(output_dir, "batch-manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fp:
        json.dump({"total": total, "results": results}, fp, ensure_ascii=False, indent=2)

    succeeded = sum(1 for item in results if item["status"] in ("done", "no-output"))
    logger.success(f"batch finished: {succeeded}/{total} succeeded. manifest: {manifest_path}")
    print(
        json.dumps(
            {
                "succeeded": succeeded,
                "total": total,
                "output_dir": output_dir,
                "manifest": manifest_path,
            },
            ensure_ascii=False,
        )
    )
    return 0 if succeeded == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
