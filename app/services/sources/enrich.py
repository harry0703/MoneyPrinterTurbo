"""
소재의 본문을 읽어 온다.

수집기가 주는 것은 대개 제목과 링크뿐이다. 그것만으로 카드를 쓰면 "설명이 없음"
같은 카드가 나온다 — 지어내지 않는다는 규칙은 지키지만 쓸 재료가 없다. 링크가
가리키는 글을 읽어 와야 카드에 담을 내용이 생긴다.

주소는 밖에서 온다. 아무 주소나 그대로 요청하면 이 기계가 사내망이나 클라우드
메타데이터 주소로 요청을 대신 보내 주는 통로가 된다. 그래서 공인 주소만 받는다.
"""

import ipaddress
import re
import socket
from dataclasses import replace
from html import unescape
from urllib.parse import urljoin, urlparse

import requests
from loguru import logger

from app.services.sources.base import MAX_TEXT_LENGTH, SourceItem

REQUEST_TIMEOUT_SECONDS = 15
MAX_BODY_BYTES = 512 * 1024
MAX_REDIRECTS = 3
GITHUB_README = "https://api.github.com/repos/{owner}/{repo}/readme"
# 이 헤더가 없으면 GitHub 은 base64 를 담은 JSON 을 준다. 읽을 글이 필요하다.
GITHUB_RAW_ACCEPT = "application/vnd.github.raw"
USER_AGENT = "shipcast-source-reader"
# GitHub 은 위 헤더로 받은 README 를 `application/vnd.github.raw` 로 표시한다.
# 마크다운 원문이지만 `text/` 로 오지 않아, 이름을 적어 두지 않으면 걸러진다.
ALLOWED_CONTENT = (
    "text/",
    "application/json",
    "application/xhtml",
    "application/vnd.github",
)
REPO_NAME = re.compile(r"[A-Za-z0-9._-]+")

# 읽을 글이 없는 덩어리들. 태그를 다 지우기 전에 통째로 걷어낸다. 그러지 않으면
# 스크립트 본문이 문장인 척 섞여 들어온다.
_NOISE_BLOCK = re.compile(
    r"<(script|style|head|nav|footer|svg)\b.*?</\1>", re.IGNORECASE | re.DOTALL
)
_TAG = re.compile(r"<[^>]+>")
_BLANKS = re.compile(r"\n{3,}")
# README 맨 위의 배지 줄. 링크와 이미지뿐이라 읽을 내용이 없다.
_BADGE_LINE = re.compile(r"^\s*(\[!\[[^\n]*?\)\s*)+$", re.MULTILINE)


class UnsafeUrl(ValueError):
    """공인 주소가 아니거나 요청을 보낼 수 없는 주소."""


def _resolved_addresses(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise UnsafeUrl(f"cannot resolve the host: {type(exc).__name__}") from None
    return [info[4][0] for info in infos]


def _is_public_address(address: str) -> bool:
    """공인 주소면 ``True``. 루프백·사설망·링크로컬은 전부 아니다."""
    try:
        # 링크로컬은 범위 표기(`fe80::1%en0`)가 붙어 오기도 한다. 그 형태는
        # 파싱되지 않고, 파싱되지 않는 주소는 공인이 아닌 것으로 본다.
        return ipaddress.ip_address(address).is_global
    except ValueError:
        return False


def assert_public_url(url: str) -> None:
    """
    공인 http(s) 주소인지 본다. 아니면 ``UnsafeUrl``.

    스킴만 보면 모자란다. ``http://localhost`` 나 사내 이름 하나로 이 기계가
    내부망에 대신 요청을 보내게 되므로, 그 이름이 실제로 가리키는 주소까지 본다.
    """
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise UnsafeUrl("the url cannot be parsed") from exc

    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeUrl("only http and https are allowed")

    for address in _resolved_addresses(parsed.hostname):
        if not _is_public_address(address):
            # 루프백, 사설망, 링크로컬(클라우드 메타데이터 포함)이 전부 여기서 걸린다.
            raise UnsafeUrl(f"the host resolves to a non-public address: {address}")


def _peer_address(response) -> str:
    """실제로 연결된 상대의 주소. 알 수 없으면 빈 문자열."""
    connection = getattr(response.raw, "_connection", None)
    sock = getattr(connection, "sock", None)
    try:
        return str(sock.getpeername()[0])
    except (AttributeError, IndexError, OSError, TypeError):
        return ""


def assert_public_peer(response) -> None:
    """
    실제로 붙은 상대가 공인 주소인지 본다. 아니면 ``UnsafeUrl``.

    이름을 확인한 것과 그 이름으로 연결된 곳이 같다는 보장은 없다. 이름을 쥔
    쪽이 확인할 때는 공인 주소를, 연결할 때는 사내 주소를 내놓으면 앞의 검사만으로는
    통과한다. 본문을 읽기 전에 붙은 곳을 다시 본다.
    """
    # 어디에 붙었는지 알아내지 못하면 빈 값이 오고, 그것도 공인 주소가 아니다.
    # 확인할 수 없는 것을 통과시키면 검사가 있으나 마나다.
    peer = _peer_address(response)
    if not _is_public_address(peer):
        raise UnsafeUrl(f"the connection reached a non-public address: {peer or '?'}")


def _read_bounded_text(response) -> str:
    """본문을 상한까지만 읽는다. 읽을 글이 아니면 빈 문자열."""
    content_type = str(response.headers.get("Content-Type", "")).lower()
    # 종류를 밝히지 않은 응답도 여기서 걸린다. 무엇인지 모르는 바이트를 글자로
    # 바꿔 프롬프트에 실을 이유가 없다.
    if not content_type.startswith(ALLOWED_CONTENT):
        logger.info(f"skipping a body of an unusable type: {content_type[:60] or '(none)'}")
        return ""

    raw = response.raw.read(MAX_BODY_BYTES, decode_content=True)
    return raw.decode("utf-8", errors="replace")


def _get(url: str, accept: str = "") -> str:
    """
    주소 하나를 읽어 본문을 돌려준다. 못 읽으면 빈 문자열.

    리다이렉트는 직접 따라간다. requests 에 맡기면 중간에 사설 주소로 튀는 것을
    볼 수 없다 — 첫 주소만 공인이면 통과한다.
    """
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept

    for _ in range(MAX_REDIRECTS + 1):
        try:
            assert_public_url(url)
            response = requests.get(
                url,
                timeout=REQUEST_TIMEOUT_SECONDS,
                stream=True,
                allow_redirects=False,
                headers=headers,
            )
        except UnsafeUrl as exc:
            logger.warning(f"refusing to read a source body: {exc}")
            return ""
        except Exception as exc:
            logger.warning(f"could not read a source body: {type(exc).__name__}")
            return ""

        with response:
            try:
                assert_public_peer(response)
                location = response.headers.get("Location", "")
                if response.is_redirect and location:
                    # 상대 주소로 보내는 곳이 많다. 원래 주소에 붙여야 다음 검사가
                    # 통한다. 붙이는 것 자체가 실패할 수 있는 값이라 안에서 한다.
                    url = urljoin(url, location)
                    continue
            except UnsafeUrl as exc:
                logger.warning(f"refusing to read a source body: {exc}")
                return ""
            except ValueError as exc:
                logger.warning(f"could not follow a redirect: {type(exc).__name__}")
                return ""

            if response.status_code >= 400:
                logger.info(f"a source body responded {response.status_code}")
                return ""
            return _read_bounded_text(response)

    logger.warning("too many redirects while reading a source body")
    return ""


def _github_repo(url: str) -> tuple[str, str] | None:
    """GitHub 저장소 주소면 ``(owner, repo)``. 아니면 ``None``."""
    parsed = urlparse(url)
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    if any(part in {".", ".."} for part in parts):
        # 서버가 정규화하면 다른 곳을 가리키는 주소다. 앞 두 칸만 보고 저장소를
        # 정하면 엉뚱한 프로젝트의 README 로 카드를 쓰게 된다.
        return None
    owner, repo = parts[0], parts[1].removesuffix(".git")
    # 이 두 값이 다시 주소가 된다. 저장소 이름에 쓸 수 있는 글자만 받는다.
    if not REPO_NAME.fullmatch(owner) or not REPO_NAME.fullmatch(repo):
        return None
    return owner, repo


def strip_markup(text: str) -> str:
    """읽을 글만 남긴다."""
    text = _NOISE_BLOCK.sub(" ", text)
    text = _TAG.sub(" ", text)
    text = unescape(text)
    text = _BADGE_LINE.sub("", text)
    lines = [line.strip() for line in text.splitlines()]
    return _BLANKS.sub("\n\n", "\n".join(lines)).strip()


def fetch_body(url: str, limit: int = MAX_TEXT_LENGTH) -> str:
    """
    링크가 가리키는 글을 읽어 온다. 못 읽으면 빈 문자열.

    GitHub 저장소면 README 를 읽는다. 저장소 첫 화면 HTML 에서 긁어내는 것보다
    깨끗하고, 그 글이 곧 프로젝트가 자기를 설명하는 말이다.
    """
    url = str(url or "").strip()
    if not url:
        return ""

    repository = _github_repo(url)
    if repository:
        owner, repo = repository
        body = _get(
            GITHUB_README.format(owner=owner, repo=repo), accept=GITHUB_RAW_ACCEPT
        )
        if body:
            return strip_markup(body)[:limit]
        logger.info(f"no readme for {owner}/{repo}, reading the page instead")

    return strip_markup(_get(url))[:limit]


def with_body(item: SourceItem) -> SourceItem:
    """
    본문이 비어 있으면 채워서 돌려준다. 못 채우면 받은 그대로.

    새 ``SourceItem`` 으로 돌려주므로 길이 제한과 제어문자 제거가 다른 소재와
    똑같이 걸린다. 밖에서 읽어 온 글이라 그 정규화가 특히 중요하다.
    """
    if item.text or not item.url:
        return item

    body = fetch_body(item.url)
    if not body:
        return item

    logger.info(f"read {len(body)} characters of body for {item.source}:{item.item_id}")
    return replace(item, text=body)
