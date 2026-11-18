import copy
import errno
import json
import os
import shutil
import socket
import tempfile
import threading
from contextlib import contextmanager

import toml
from loguru import logger

from app import __version__, paths

root_dir = str(paths.runtime_root())
config_file = f"{root_dir}/config.toml"
_CONTAINER_CGROUP_MARKERS = ("docker", "containerd", "kubepods", "libpod", "podman")
_DOCKER_HOST_GATEWAY_NAME = "host.docker.internal"
_config_save_lock = threading.RLock()
_diagnostics_update_lock = threading.Lock()
_pending_config_lock = threading.RLock()
_pending_config_updates = {}
_pending_config_save_requested = False
_pending_config_flush_scheduled = False
_MISSING = object()
_DELETE = object()
_UTF8_BOM = "\ufeff"


class _SynchronizedConfig(dict):
    """Keep dict usage unchanged while making runtime config writes obey the same lock."""

    def __setitem__(self, key, value):
        # Streamlit writes the current widget values back into config on every full-page rerun. While a video task holds
        # runtime_config_lock, a write whose value hasn't changed has no side effects at all and
        # shouldn't leave the refreshed page stuck in the middle of the form. Writes that really change config still go through the lock below,
        # so the Provider, keys or other global settings can't be switched in the middle of a video being generated.
        current = super().get(key, _MISSING)
        if current is not _MISSING and current == value:
            return
        with _config_save_lock:
            super().__setitem__(key, value)

    def __delitem__(self, key):
        with _config_save_lock:
            super().__delitem__(key)

    def clear(self):
        if not self:
            return
        with _config_save_lock:
            super().clear()

    def pop(self, key, default=_MISSING):
        # ``pop(key, default)`` also doesn't change config when the key doesn't exist. The WebUI uses
        # this form to express "use the default policy", and a refresh must be allowed to complete it directly.
        if key not in self:
            if default is _MISSING:
                raise KeyError(key)
            return default
        with _config_save_lock:
            if default is _MISSING:
                return super().pop(key)
            return super().pop(key, default)

    def setdefault(self, key, default=None):
        # Like __setitem__, setdefault on an existing key is a read-only operation. Returning early
        # keeps page refreshes that only read default config unaffected by the long-task config lock.
        current = super().get(key, _MISSING)
        if current is not _MISSING:
            return current
        with _config_save_lock:
            return super().setdefault(key, default)

    def update(self, *args, **kwargs):
        changes = dict(*args, **kwargs)
        if all(
            (current := dict.get(self, key, _MISSING)) is not _MISSING
            and current == value
            for key, value in changes.items()
        ):
            return
        with _config_save_lock:
            super().update(changes)


def _pending_update_key(config_section, key):
    """Build pending-update keys for the fixed in-process config sections."""
    return id(config_section), key


def update_config_nonblocking(config_section, key, value):
    """
    Update the WebUI runtime config without blocking.

    Video generation holds ``runtime_config_lock``, so a task can't switch Provider, keys or voice config
    midway through. Streamlit widget changes must not wait on this long-task lock,
    or the browser appears frozen. When the lock is free, update immediately; when it's busy, keep only the latest value of each config item
    and apply them together when the current task releases the lock.

    Returns True if the value took effect, False if it was queued for update.
    """
    return update_config_values_nonblocking(config_section, {key: value})


def update_config_values_nonblocking(config_section, changes):
    """Queue related fields from the same operation together, so concurrent application doesn't split the config."""
    # All updates go into the same queue first, then try to acquire the config lock. That way when several pages modify the same
    # config item at once, the order of writes into the queue is the final order, and an earlier thread that acquires the lock can't
    # accidentally delete a value a newer thread already queued.
    with _pending_config_lock:
        for key, value in changes.items():
            _pending_config_updates[_pending_update_key(config_section, key)] = (
                config_section,
                key,
                copy.deepcopy(value),
            )

    acquired = _config_save_lock.acquire(blocking=False)
    if not acquired:
        # Callers usually request a save at the end of this Streamlit rerun, but that step can't be relied on
        # to always run. For example, when the page fails midway or the update happens right as the task is in its exit-save stage, a
        # background refresh thread is still needed to make sure queued values eventually take effect.
        _schedule_deferred_config_flush()
        return False

    try:
        _apply_pending_config_updates_locked()
        return all(
            config_section.get(key, _MISSING) == value
            for key, value in changes.items()
        )
    finally:
        _config_save_lock.release()


def update_logging_options(level, log_requests):
    """Publish runtime snapshots and persistence intents serially, without waiting for the generation task's long config lock."""
    from app.utils.logging_utils import get_logging_options, set_logging_options

    with _diagnostics_update_lock:
        set_logging_options(level, log_requests)
        level, log_requests = get_logging_options()
        return update_config_values_nonblocking(
            diagnostics, {"log_level": level, "log_requests": log_requests}
        )


def delete_config_nonblocking(config_section, key):
    """
    Delete a WebUI config item without blocking.

    "Use default" needs to really remove the config item, not write an empty string. While a video task holds the config
    lock, the delete intent overrides earlier queued updates for the same item and is executed after the task ends.
    """
    with _pending_config_lock:
        _pending_config_updates[_pending_update_key(config_section, key)] = (
            config_section,
            key,
            _DELETE,
        )

    acquired = _config_save_lock.acquire(blocking=False)
    if not acquired:
        _schedule_deferred_config_flush()
        return False

    try:
        _apply_pending_config_updates_locked()
        return key not in config_section
    finally:
        _config_save_lock.release()


def _apply_pending_config_updates_locked():
    """Apply the latest config values staged by the WebUI while holding the config write lock."""
    with _pending_config_lock:
        updates = list(_pending_config_updates.values())
        _pending_config_updates.clear()
        # Keep holding the pending-update lock while applying config. Threads reading the "current value + pending value" snapshot
        # can then only see the complete state before or after applying, never a half-updated config set.
        for config_section, key, value in updates:
            if value is _DELETE:
                config_section.pop(key, None)
            else:
                config_section[key] = value
    return bool(updates)


def snapshot_config_with_pending(config_section):
    """
    Return an effective snapshot of a config section, merging WebUI updates not yet applied.

    While a video task holds the lock, global config can't be rewritten, but users can still prepare the next piece of content. When LLM requests
    use this snapshot, the Provider, model and key just selected in the UI take part in the new request, while
    the running video task is unaffected.
    """
    with _pending_config_lock:
        snapshot = dict(config_section)
        section_id = id(config_section)
        for (pending_section_id, key), (_, _, value) in _pending_config_updates.items():
            if pending_section_id != section_id:
                continue
            if value is _DELETE:
                snapshot.pop(key, None)
            else:
                snapshot[key] = copy.deepcopy(value)
    return snapshot


def _flush_pending_config_locked(*, suppress_save_errors):
    """Apply and save all currently pending config while holding the config write lock."""
    global _pending_config_save_requested

    updates_applied = _apply_pending_config_updates_locked()
    with _pending_config_lock:
        save_requested = _pending_config_save_requested
        _pending_config_save_requested = False

    if not updates_applied and not save_requested:
        return True

    try:
        save_config()
        return True
    except Exception as exc:
        # The in-memory config was applied successfully, so on save failure only the pending-save marker is kept. A video task shouldn't
        # be judged failed because the config file is temporarily unwritable; the next page interaction triggers a save again.
        with _pending_config_lock:
            _pending_config_save_requested = True
        if not suppress_save_errors:
            raise
        logger.exception(f"failed to save deferred runtime config: {exc}")
        return False


def _run_deferred_config_flush():
    """Wait for the long task to release the config lock, and reliably flush config updates accumulated meanwhile."""
    global _pending_config_flush_scheduled

    while True:
        with _config_save_lock:
            flush_succeeded = _flush_pending_config_locked(
                suppress_save_errors=True
            )

        with _pending_config_lock:
            has_pending_work = bool(
                _pending_config_updates or _pending_config_save_requested
            )
            if not flush_succeeded or not has_pending_work:
                _pending_config_flush_scheduled = False
                return


def _schedule_deferred_config_flush():
    """Ensure at most one background thread is waiting to flush config at any time."""
    global _pending_config_flush_scheduled

    with _pending_config_lock:
        if _pending_config_flush_scheduled:
            return
        _pending_config_flush_scheduled = True

    try:
        threading.Thread(
            target=_run_deferred_config_flush,
            name="mpt-config-flush",
            daemon=True,
        ).start()
    except Exception:
        # No worker owns this reservation when construction/start fails.
        # Leave queued updates and the save request intact so a later call
        # can schedule another flush rather than silently waiting forever.
        with _pending_config_lock:
            _pending_config_flush_scheduled = False
        raise


def try_save_config():
    """
    Save the WebUI config without blocking; when the lock is busy, saving is deferred until the current long task ends.

    Regular API, CLI and maintenance scripts can still call ``save_config`` for the original blocking write semantics;
    only Streamlit reruns use this function, so the page doesn't stop responding for a long time while waiting on a video task.
    """
    global _pending_config_save_requested

    with _pending_config_lock:
        _pending_config_save_requested = True

    acquired = _config_save_lock.acquire(blocking=False)
    if not acquired:
        _schedule_deferred_config_flush()
        return False

    try:
        return _flush_pending_config_locked(suppress_save_errors=False)
    finally:
        _config_save_lock.release()


@contextmanager
def runtime_config_lock():
    """
    Prevent other WebUI sessions from rewriting config during a complete operation that depends on global config.

    The project binds to the local loopback address by default, and config is still a single-user global config. This lightweight lock mainly
    protects long operations such as generation and preview, so another tab can't switch Provider or keys midway.
    """
    with _config_save_lock:
        # If the background refresh thread hadn't been scheduled yet when the previous short operation released the lock, the new task must
        # apply the queue before reading global config such as Provider and keys, rather than running the whole pipeline with stale config.
        _flush_pending_config_locked(suppress_save_errors=True)
        try:
            yield
        finally:
            _flush_pending_config_locked(suppress_save_errors=True)


@contextmanager
def try_runtime_config_lock():
    """
    Try to acquire the runtime config lock and return immediately whether it succeeded.

    A WebUI preview is a short operation triggered by the user and shouldn't wait minutes while a background video task holds the lock.
    Callers can tell the user to retry later when the lock isn't acquired; once acquired, it still guarantees that during the preview
    Provider, key and model config can't be modified by other sessions.
    """
    acquired = _config_save_lock.acquire(blocking=False)
    try:
        if acquired:
            _flush_pending_config_locked(suppress_save_errors=True)
        yield acquired
    finally:
        if acquired:
            _flush_pending_config_locked(suppress_save_errors=True)
            _config_save_lock.release()


def is_running_in_container(
    dockerenv_path: str = "/.dockerenv",
    containerenv_path: str = "/run/.containerenv",
    cgroup_path: str = "/proc/1/cgroup",
) -> bool:
    """
    Decide whether the current process is running inside a container.

    This check is mainly used to choose the default Ollama address:
    - When running directly on a machine, `localhost` points to the user's machine itself;
    - Inside a Docker container, `localhost` points to the container itself, and reaching the host's Ollama
      usually requires `host.docker.internal`.

    Checking only whether `/proc/1/cgroup` exists isn't enough, because ordinary Linux has that file too.
    True is returned only when a clear container marker is detected, so non-Docker Linux users aren't affected.
    The parameter is kept as an injectable path so unit tests can cover different runtime environments.
    """
    if os.path.isfile(dockerenv_path) or os.path.isfile(containerenv_path):
        return True

    try:
        with open(cgroup_path, mode="r", encoding="utf-8") as fp:
            cgroup_content = fp.read().lower()
    except OSError:
        return False

    return any(marker in cgroup_content for marker in _CONTAINER_CGROUP_MARKERS)


def _can_resolve_hostname(hostname: str) -> bool:
    try:
        socket.gethostbyname(hostname)
    except OSError:
        return False
    return True


def _decode_linux_route_gateway(hex_gateway: str) -> str:
    # The Gateway in /proc/net/route is little-endian hex, e.g. 010011AC means
    # 172.17.0.1. It's parsed separately so that, when native Linux Docker has no
    # host.docker.internal DNS record, the host on the container's default gateway can still be tried.
    if len(hex_gateway) != 8:
        raise ValueError("invalid gateway length")

    octets = [
        str(int(hex_gateway[index : index + 2], 16)) for index in range(6, -1, -2)
    ]
    return ".".join(octets)


def get_container_default_gateway_ip(route_path: str = "/proc/net/route") -> str:
    """
    Read the default gateway IP inside a Linux container.

    Docker Desktop usually provides `host.docker.internal`, but native Linux Docker
    doesn't necessarily provide this DNS name by default. The default gateway can usually serve as a fallback address for
    reaching host services; if the user's Ollama only listens on 127.0.0.1, the user still needs to make
    Ollama listen on a host network interface or configure `ollama_base_url` manually.
    """
    try:
        with open(route_path, mode="r", encoding="utf-8") as fp:
            route_lines = fp.readlines()
    except OSError:
        return ""

    for line in route_lines[1:]:
        fields = line.strip().split()
        if len(fields) < 8:
            continue

        destination = fields[1]
        gateway = fields[2]
        if (
            destination != "00000000"
            or fields[7] != "00000000"
            or gateway == "00000000"
        ):
            continue

        try:
            return _decode_linux_route_gateway(gateway)
        except ValueError:
            logger.warning(f"invalid container gateway route entry: {line.strip()}")
            return ""

    return ""


def get_default_ollama_base_url() -> str:
    """
    Return the default OpenAI-compatible base_url for Ollama.

    This isn't used when the user explicitly configures `ollama_base_url`; it only handles "the best default
    when not configured". Inside a container it points to the host by default; when running directly on a machine it points to localhost.
    """
    if not is_running_in_container():
        return "http://localhost:11434/v1"

    if _can_resolve_hostname(_DOCKER_HOST_GATEWAY_NAME):
        return f"http://{_DOCKER_HOST_GATEWAY_NAME}:11434/v1"

    gateway_ip = get_container_default_gateway_ip()
    if gateway_ip:
        logger.info(
            "host.docker.internal is not resolvable, fallback to container "
            f"default gateway for Ollama: {gateway_ip}"
        )
        return f"http://{gateway_ip}:11434/v1"

    logger.warning(
        "failed to resolve host.docker.internal and container default gateway; "
        "fallback to host.docker.internal for Ollama"
    )
    return f"http://{_DOCKER_HOST_GATEWAY_NAME}:11434/v1"


def _load_toml_config(config_path: str):
    """
    Load TOML, tolerating duplicate UTF-8 BOMs that Windows editors may write.

    ``utf-8-sig`` only removes one BOM at the start of the file. Some Windows editors or
    unzip/save flows may write a BOM again, letting a second invisible character into the TOML
    parser and causing an error on the first line. A read-only normalization is done here only after standard parsing fails,
    without writing back to the original file, so API Keys the user already filled in aren't accidentally overwritten.
    """
    try:
        return toml.load(config_path)
    except (toml.TomlDecodeError, UnicodeDecodeError) as exc:
        logger.warning(
            "load config failed, retry with UTF-8 BOM compatibility: "
            f"path={config_path}, error={type(exc).__name__}: {exc}"
        )

    try:
        with open(config_path, mode="r", encoding="utf-8-sig") as fp:
            config_content = fp.read()

        normalized_content = config_content.lstrip(_UTF8_BOM)
        removed_bom_count = len(config_content) - len(normalized_content)
        if removed_bom_count:
            logger.warning(
                "removed repeated UTF-8 BOM characters while loading config: "
                f"path={config_path}, count={removed_bom_count}"
            )
        return toml.loads(normalized_content)
    except (toml.TomlDecodeError, UnicodeDecodeError) as exc:
        logger.error(
            "config file is not valid TOML after UTF-8 BOM normalization: "
            f"path={config_path}, error={type(exc).__name__}: {exc}"
        )
        raise



def _initialize_config_from_example(example_file):
    """Publish a complete first-boot config without replacing another writer."""
    fd, temp_path = tempfile.mkstemp(
        prefix=".config-init-", suffix=".toml.tmp",
        dir=os.path.dirname(os.path.abspath(config_file)),
    )
    try:
        with os.fdopen(fd, "wb") as destination:
            with open(example_file, "rb") as source:
                shutil.copyfileobj(source, destination)
            destination.flush()
            os.fsync(destination.fileno())
        try:
            if os.name == "nt":
                # Windows rename refuses an existing destination. POSIX rename
                # overwrites it, so use an exclusive hard-link publication there.
                os.rename(temp_path, config_file)
            else:
                os.link(temp_path, config_file)
        except FileExistsError:
            return False
        except OSError as exc:
            raise OSError(
                exc.errno,
                "cannot safely initialize config.toml; copy config.example.toml "
                "to config.toml before starting the application",
            ) from exc
        return True
    finally:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            # A successful Windows rename consumed the temporary path.
            pass


def load_config():
    os.makedirs(root_dir, mode=0o700, exist_ok=True)
    # Docker may create an empty directory when a missing config.toml is bind-mounted.
    # Only remove that empty placeholder; a nonempty directory may contain user data.
    if os.path.isdir(config_file):
        try:
            os.rmdir(config_file)
        except FileNotFoundError:
            # Another initializer already removed this empty bind-mount stub.
            pass
        except OSError as exc:
            if exc.errno == errno.EBUSY:
                # The directory is the bind mount itself, so it cannot be
                # removed from inside the container; it must be fixed on the host.
                raise IsADirectoryError(
                    f"{config_file} is a directory because config.toml did not exist "
                    "on the host when Docker mounted it. Stop the containers, delete "
                    "the empty config.toml folder next to the docker-compose file, "
                    "copy config.example.toml to config.toml there, then start again"
                ) from exc
            # Another initializer may already have replaced the empty Docker
            # stub with its complete regular file. Accept only that race, not
            # permission failures or a still-present/nonempty directory.
            if not (
                isinstance(exc, NotADirectoryError) and os.path.isfile(config_file)
            ):
                raise IsADirectoryError(
                    f"{config_file} is a directory and cannot be used as the config file; "
                    "move or rename it, then restart"
                ) from exc

    if not os.path.isfile(config_file):
        example_file = f"{root_dir}/config.example.toml"
        if not os.path.isfile(example_file):
            example_file = str(paths.config_template())
        if os.path.isfile(example_file):
            if _initialize_config_from_example(example_file):
                logger.info("copy config.example.toml to config.toml")

    logger.info(f"load config from file: {config_file}")

    return _load_toml_config(config_file)


class _ConfigTomlEncoder(toml.TomlEncoder):
    """
    Write strings as JSON strings, which are also valid TOML basic strings.

    toml 0.10.2's own string encoder (uiri/toml#404) drops the escaping of
    every backslash up to the last one followed by "x", so a Windows path
    with a folder such as "xiaoming" or "x64" is written as invalid TOML.
    It also writes a non-breaking space as the text "xa0".
    """

    def __init__(self):
        super().__init__()
        self.dump_funcs[str] = self._dump_str

    @staticmethod
    def _dump_str(value):
        # TOML, unlike JSON, also requires DEL to be escaped.
        return json.dumps(str(value), ensure_ascii=False).replace("\x7f", "\\u007f")


def save_config():
    """
    Atomically save the runtime config.

    Different Streamlit sessions may trigger config saves at nearly the same time. When overwriting config.toml directly,
    another thread might read partially written TOML content. An in-process reentrant lock serializes
    saves here, writing to a temp file in the same directory first, then atomically replacing the target via os.replace.

    A Docker Desktop single-file bind mount makes config.toml itself the mount point,
    and the Linux kernel doesn't allow replacing a mount point via rename/replace, returning EBUSY.
    In that case the file can only be overwritten in place inside the lock; other exceptions are still raised, so permission, disk
    or path errors aren't masked.

    This keeps the project's existing single-user global config semantics without introducing a complex multi-user config system;
    it mainly prevents config file corruption with multiple tabs or rapid reruns.
    """
    with _config_save_lock:
        config_to_save = dict(_cfg)
        config_to_save["app"] = dict(app)
        config_to_save["azure"] = dict(azure)
        config_to_save["siliconflow"] = dict(siliconflow)
        config_to_save["minimax_tts"] = dict(minimax_tts)
        config_to_save["elevenlabs"] = dict(elevenlabs)
        config_to_save["chatterbox"] = dict(chatterbox)
        config_to_save["kokoro"] = dict(kokoro)
        config_to_save["fish_audio"] = dict(fish_audio)
        config_to_save["voxcpm"] = dict(voxcpm)
        config_to_save["ui"] = dict(ui)
        config_to_save["diagnostics"] = dict(diagnostics)
        serialized_config = toml.dumps(config_to_save, encoder=_ConfigTomlEncoder())

        # A full WebUI rerun calls save at the end. Return directly when the content hasn't changed, so every
        # click on an ordinary widget doesn't cause a disk write and fsync.
        try:
            with open(config_file, mode="r", encoding="utf-8") as f:
                if f.read() == serialized_config:
                    _cfg.clear()
                    _cfg.update(config_to_save)
                    return
        except (OSError, UnicodeError):
            pass

        temp_path = ""
        try:
            fd, temp_path = tempfile.mkstemp(
                prefix=".config-",
                suffix=".toml.tmp",
                dir=root_dir,
            )
            with os.fdopen(fd, mode="w", encoding="utf-8") as f:
                f.write(serialized_config)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.replace(temp_path, config_file)
            except OSError as exc:
                if exc.errno != errno.EBUSY:
                    raise

                logger.warning(
                    "atomic config replacement is unavailable for the mounted "
                    f"file, fallback to in-place write: {config_file}"
                )
                with open(config_file, mode="w", encoding="utf-8") as f:
                    f.write(serialized_config)
                    f.flush()
                    os.fsync(f.fileno())
            _cfg.clear()
            _cfg.update(config_to_save)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)


_cfg = load_config()
diagnostics = _SynchronizedConfig(_cfg.get("diagnostics", {}))
app = _SynchronizedConfig(_cfg.get("app", {}))
whisper = _cfg.get("whisper", {})
proxy = _cfg.get("proxy", {})
azure = _SynchronizedConfig(_cfg.get("azure", {}))
siliconflow = _SynchronizedConfig(_cfg.get("siliconflow", {}))
minimax_tts = _SynchronizedConfig(_cfg.get("minimax_tts", {}))
elevenlabs = _SynchronizedConfig(_cfg.get("elevenlabs", {}))
chatterbox = _SynchronizedConfig(_cfg.get("chatterbox", {}))
kokoro = _SynchronizedConfig(_cfg.get("kokoro", {}))
fish_audio = _SynchronizedConfig(_cfg.get("fish_audio", {}))
voxcpm = _SynchronizedConfig(_cfg.get("voxcpm", {}))
ui = _SynchronizedConfig(
    _cfg.get(
        "ui",
        {
            "hide_log": False,
        },
    )
)

hostname = socket.gethostname()

log_level = _cfg.get("log_level", "DEBUG")
listen_host = _cfg.get("listen_host", "0.0.0.0")
listen_port = _cfg.get("listen_port", 8080)
project_name = _cfg.get("project_name", "MoneyPrinterTurbo")
project_description = _cfg.get(
    "project_description",
    "<a href='https://github.com/harry0703/MoneyPrinterTurbo'>https://github.com/harry0703/MoneyPrinterTurbo</a>",
)
project_version = _cfg.get("project_version", __version__)
reload_debug = False

app["redis_host"] = os.getenv(
    "MPT_APP_REDIS_HOST",
    os.getenv("REDIS_HOST", app.get("redis_host", "localhost")),
)

ffmpeg_path = app.get("ffmpeg_path", "")
if ffmpeg_path:
    # config.toml also allows the "~" / "${VAR}" forms: expand first, then check existence,
    # otherwise isfile() never holds and the config is silently ignored.
    ffmpeg_path = os.path.expanduser(os.path.expandvars(ffmpeg_path))
    if os.path.isfile(ffmpeg_path):
        os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg_path

# IMAGEIO_FFMPEG_EXE set directly by the user may also use the "~" / "${VAR}" forms
# (issue #1662). MoviePy 2.x reads this variable through imageio at import time
# and fixes it as moviepy.config.FFMPEG_BINARY, never resolving it again afterwards; so the expansion must
# happen in this module (the earliest shared dependency of every entry point, imported before moviepy),
# so the encoding stage gets the real path.
_env_ffmpeg = os.environ.get("IMAGEIO_FFMPEG_EXE")
if _env_ffmpeg:
    os.environ["IMAGEIO_FFMPEG_EXE"] = os.path.expanduser(
        os.path.expandvars(_env_ffmpeg)
    )

logger.info(f"{project_name} v{project_version}")
