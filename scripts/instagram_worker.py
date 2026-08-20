# /// script
# requires-python = ">=3.11"
# dependencies = ["instagrapi>=2.16.1", "requests[socks]>=2.32"]
# # requests[socks] : sans PySocks, un proxy socks5:// lève
# # "Missing dependencies for SOCKS support" au lieu de fonctionner.
# ///
"""
Instagram Reels 发布工作进程。

单独存在的原因：instagrapi 锁定 ``pillow>=12.2``，而 MoviePy 需要
``pillow<12``。两者无法安装在同一个环境里，因此这里通过 PEP 723 内联依赖
声明，由 ``uv run`` 在独立环境中执行，主项目的依赖树完全不受影响。

协议：stdin 读入一个 JSON 请求，stdout 输出一行 JSON 结果。所有诊断信息
写到 stderr，避免污染结果。凭据只在内存中使用，任何情况下都不打印。
"""

import json
import sys
import time
from pathlib import Path

MAX_CAPTION_LENGTH = 2200
# Instagram 服务端偶发 5xx 很常见，且通常在几十秒内自行恢复。
_TRANSIENT_RETRIES = 3
_TRANSIENT_BACKOFF_SECONDS = (5, 15, 40)


def classify_error(text: str) -> str:
    """
    判断一次失败属于哪一类。

    先判限流再判其它：429 的报文里带着 "Max retries exceeded"，若按"超时/重试"
    的字样归类，就会把"请你慢一点"当成"网络抖了一下"，然后立刻再撞三次——
    urllib3 自己已经重试过一轮，叠加之后是几百次请求打在一个明确要求退避的
    接口上，只会把限制拖得更久。
    """
    text = text.lower()
    if any(marker in text for marker in ("429", "feedback_required", "spam",
                                         "rate limit", "please wait")):
        return "rate_limit"
    if "challenge" in text or "checkpoint" in text:
        return "challenge"
    if "login_required" in text or "not logged" in text:
        return "auth"
    if "out of date" in text or "upgrade your app" in text:
        return "app_version"
    if any(marker in text for marker in ("500", "502", "503", "504",
                                         "timed out", "connection reset")):
        return "transient"
    return "upload"


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def respond(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def _looks_like_pydantic_response_bug(error: Exception) -> bool:
    """
    识别 instagrapi 的已知响应解析缺陷。

    上传本身成功，但返回体里的 ``clips_metadata`` 等字段与库内模型不匹配，
    导致抛出校验异常。此时不能直接判定失败，必须回查账号最新作品。
    """
    text = str(error)
    return "validation error" in text.lower()


def _calm_retries(client) -> None:
    """
    收紧底层 HTTP 重试，尤其是不对 429 重试。

    instagrapi 的会话默认会对 429 反复重试，一次登录因此可能变成几百个请求，
    最后抛出的还是 "too many 429 error responses"。限流的正确回应是停下来等，
    继续敲只会延长限制、并在账号上留下一串失败记录。5xx 仍然重试，那才是
    真的服务端抖动。
    """
    try:
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
    except ImportError:  # pragma: no cover - requests 是 instagrapi 的依赖
        return

    retry = Retry(
        total=2,
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=None,
        backoff_factor=2,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    for session_attribute in ("private", "public"):
        session = getattr(client, session_attribute, None)
        if session is None:
            continue
        session.mount("https://", adapter)
        session.mount("http://", adapter)


def _client_with_session(request: dict):
    """
    建立客户端，优先复用既有会话。

    每次都用账号密码重新登录，会让 Instagram 观察到"同一账号不断出现新设备"，
    这是触发验证挑战和封禁的主要原因。这里始终复用会话文件中的设备标识，
    只有在会话确实失效时才重新登录，并保留原设备指纹。
    """
    from instagrapi import Client

    session_file = Path(request["session_file"])
    client = Client()
    client.delay_range = list(request.get("delay_range") or [2, 5])
    _calm_retries(client)

    proxy = (request.get("proxy") or "").strip()
    if proxy:
        client.set_proxy(proxy)

    reused = False
    previous_uuids = None

    if session_file.exists():
        try:
            client.load_settings(session_file)
            previous_uuids = client.get_settings().get("uuids")
            # 廉价的鉴权请求：能返回账号信息说明会话仍然有效。
            client.account_info()
            reused = True
            log("session reused")
        except Exception as exc:
            log(f"stored session unusable, re-login required: {type(exc).__name__}")

    if not reused:
        sessionid = (request.get("sessionid") or "").strip()
        username = request.get("username") or ""
        password = request.get("password") or ""
        if not sessionid and not (username and password):
            raise PermissionError(
                "stored session is invalid and no credentials were provided"
            )

        # 保留旧设备指纹再登录，避免 Instagram 把重新登录当成新设备。
        if previous_uuids:
            client.set_settings({})
            client.set_uuids(previous_uuids)

        if sessionid:
            # 用浏览器里已经登录好的会话换取客户端会话。私有 API 的账密登录
            # 会校验客户端版本号，而 instagrapi 内置的版本一旦过期就会被拒，
            # 那串版本号又必须与真实应用一致，改不出来。已有的会话绕开这一步。
            client.login_by_sessionid(sessionid)
            log("logged in from a browser session id")
        else:
            verification_code = (request.get("verification_code") or "").strip()
            client.login(username, password, verification_code=verification_code)
            log("logged in with credentials")

    session_file.parent.mkdir(parents=True, exist_ok=True)
    client.dump_settings(session_file)
    return client, reused


def _find_recent_upload(client, since_timestamp: float):
    """
    上传抛出解析异常后，回查账号最近作品确认是否真的已经发布。

    比匹配异常文本可靠：无论库的错误信息怎么变化，只要作品出现在账号里
    就说明发布成功，可以避免重复投稿。
    """
    try:
        user_id = client.user_id
        medias = client.user_medias(user_id, amount=1)
    except Exception as exc:
        log(f"could not verify recent uploads: {type(exc).__name__}")
        return None

    if not medias:
        return None

    media = medias[0]
    taken_at = getattr(media, "taken_at", None)
    if taken_at is None:
        return None

    # 只接受本次尝试之后出现的作品，避免把历史作品误判成本次结果。
    if taken_at.timestamp() + 60 < since_timestamp:
        return None
    return media


def _music_extra_data(client, query: str, video_duration_ms: int):
    """
    构造带背景音乐的发布参数。

    原实现把重叠时长写死成 61 秒，视频长度一变音乐区间就不再对应。这里
    按实际视频时长计算。
    """
    tracks = client.search_music(query)
    if not tracks:
        log(f"no Instagram track matched: {query}")
        return None

    track = tracks[0]
    log(f"track matched: {track.title} - {track.display_artist}")
    return {
        "clips_audio_metadata": {
            "original": {"volume_level": 1.0},
            "audio": {
                "is_saved": "0",
                "artist_name": track.display_artist,
                "audio_asset_id": str(track.id),
                "audio_cluster_id": str(track.audio_cluster_id),
                "track_name": track.title,
                "is_picked_precapture": "1",
            },
        },
        "music_params": {
            "audio_asset_id": str(track.id),
            "audio_cluster_id": str(track.audio_cluster_id),
            "audio_asset_start_time_in_ms": 0,
            "derived_content_start_time_in_ms": 0,
            "overlap_duration_in_ms": max(1000, int(video_duration_ms)),
            "audio_muted": False,
        },
    }


def _publish(client, request: dict) -> dict:
    video_path = Path(request["video_path"])
    caption = (request.get("caption") or "")[:MAX_CAPTION_LENGTH]

    extra_data = {}
    music_query = (request.get("music_query") or "").strip()
    if music_query:
        try:
            music = _music_extra_data(
                client, music_query, int(request.get("video_duration_ms") or 0)
            )
            if music:
                extra_data = music
        except Exception as exc:
            # 配乐是增强项，失败时继续发布无音轨版本，不牺牲整条流程。
            log(f"music lookup failed, publishing without it: {type(exc).__name__}")

    last_error = None
    for attempt in range(1, _TRANSIENT_RETRIES + 1):
        started_at = time.time()
        try:
            media = client.clip_upload(video_path, caption=caption, extra_data=extra_data)
            return {
                "ok": True,
                "media_pk": str(media.pk),
                "code": media.code,
                "url": f"https://www.instagram.com/reel/{media.code}/",
                "verified_after_error": False,
            }
        except Exception as exc:
            last_error = exc
            if _looks_like_pydantic_response_bug(exc):
                media = _find_recent_upload(client, started_at)
                if media is not None:
                    log("upload succeeded despite a response parsing error")
                    return {
                        "ok": True,
                        "media_pk": str(media.pk),
                        "code": media.code,
                        "url": f"https://www.instagram.com/reel/{media.code}/",
                        "verified_after_error": True,
                    }

            # 只有真正的服务端抖动值得重试。限流、验证挑战和登录失效再试都
            # 只会加重问题，而且是在账号上留下记录。
            if classify_error(str(exc)) == "transient" and attempt < _TRANSIENT_RETRIES:
                delay = _TRANSIENT_BACKOFF_SECONDS[attempt - 1]
                log(f"transient failure, retrying in {delay}s (attempt {attempt})")
                time.sleep(delay)
                continue
            break

    return {
        "ok": False,
        "error_type": classify_error(str(last_error)),
        "error": str(last_error),
    }


def main() -> int:
    try:
        request = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        respond({"ok": False, "error_type": "protocol", "error": f"invalid request: {exc}"})
        return 2

    try:
        client, reused = _client_with_session(request)
    except PermissionError as exc:
        respond({"ok": False, "error_type": "config", "error": str(exc)})
        return 1
    except Exception as exc:
        text = str(exc).lower()
        error_type = "challenge" if ("challenge" in text or "checkpoint" in text) else "auth"
        respond({"ok": False, "error_type": error_type, "error": str(exc)})
        return 1

    action = request.get("action") or "publish"
    if action == "check":
        respond({"ok": True, "session_reused": reused, "username": client.username})
        return 0

    result = _publish(client, request)
    result["session_reused"] = reused
    respond(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
