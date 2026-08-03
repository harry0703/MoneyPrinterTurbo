"""
텔레그램으로 쇼츠를 만드는 봇.

밖에 있을 때 영상을 만들려면 이 기계에 닿아야 하는데, 봇은 텔레그램 서버로 나가서
새 메시지를 물어보는 방식이라 공인 IP 도 포트 개방도 필요 없다. 완성된 영상은 채팅으로
바로 보내므로 임시 링크를 만들어 둘 필요도 없다.

대본을 먼저 보내 승인을 받고 렌더링한다. 렌더링은 십수 분이 걸리므로, 마음에 들지 않는
대본에 그 시간을 쓰기 전에 멈출 수 있어야 한다.
"""

import json
import os
import threading
import time
from typing import Any
from uuid import uuid4

import requests
from loguru import logger

from app.config import config
from app.models.schema import VideoParams
from app.services import cardscript, cardvideo, daily, llm, task_artifacts
from app.services import task as tm
from app.utils import utils

API_BASE = "https://api.telegram.org"
POLL_TIMEOUT_SECONDS = 50
REQUEST_TIMEOUT_SECONDS = POLL_TIMEOUT_SECONDS + 15
# 봇 파일 전송 한도. 넘으면 텔레그램이 거절하므로 미리 알려준다.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_SUBJECT_LENGTH = 200
# 대본은 프롬프트(키워드 생성)와 TTS 로 흘러간다. 봇에서 들어오는 값도 다른 입구와
# 같은 상한을 받아야 한다. 그 위에 텔레그램 메시지 한도(4096자)가 더 좁은 제약이다.
# 대본 전문과 글자 수를 한 메시지에 실어 버튼을 붙이므로, 넘으면 승인할 방법이 없어진다.
MAX_TELEGRAM_MESSAGE_LENGTH = 4096
# 응답도 외부 입력이다. 통째로 메모리에 올리기 전에 크기를 끊는다.
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
# getUpdates 가 한 번에 돌려줄 업데이트 수. 텔레그램 상한은 100 이다.
MAX_UPDATES_PER_POLL = 20
MAX_SCRIPT_LENGTH = 3500
# 하루에 보여 줄 후보 수. 더 늘리면 고르는 일 자체가 일이 된다.
DAILY_CANDIDATES = 3
# 매일 후보를 보내는 시각(로컬 24시간). 비워 두면 /오늘 을 직접 칠 때만 돈다.
DEFAULT_DAILY_HOUR = ""
# 소스에 못 닿았을 때 다시 볼 때까지 기다리는 시간. 폴링은 초 단위로 도는데
# 그 주기로 다시 물어보면, 장애가 길어질수록 요청과 안내가 하루 종일 쌓인다.
DAILY_RETRY_SECONDS = 15 * 60


class TelegramConfigError(RuntimeError):
    """봇을 켤 수 없는 설정 문제."""


def _bot_token() -> str:
    return str(config.telegram.get("bot_token", "") or "").strip()


def _allowed_chat_id() -> int:
    raw = config.telegram.get("chat_id", "")
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return 0


def _api_url(method: str) -> str:
    # 토큰이 주소에 들어간다. 이 값을 로그나 예외 메시지에 실으면 안 된다.
    return f"{API_BASE}/bot{_bot_token()}/{method}"


def _read_bounded_json(response) -> Any:
    """
    응답 본문을 상한까지만 읽어 파싱한다. 넘으면 ``None``.

    본문 크기는 상대가 정한다. `response.json()` 은 전부 메모리에 올린 뒤 파싱하므로,
    거대한 응답 하나로 이 기계가 흔들릴 수 있다.
    """
    with response:
        raw = response.raw.read(MAX_RESPONSE_BYTES + 1, decode_content=True)
    if len(raw) > MAX_RESPONSE_BYTES:
        logger.warning("telegram returned an oversized body")
        return None
    return json.loads(raw)


def _for_log(value: Any, limit: int = 200) -> str:
    """
    상대가 보낸 문구를 로그에 남길 수 있게 다듬는다.

    길이를 자르고 제어문자를 지운다. 터미널 제어 문자가 섞인 문구를 그대로 흘리면
    로그를 보는 쪽 화면이 조작될 수 있고, 길이 제한이 없으면 로그가 통째로 밀린다.
    """
    text = str(value or "")[:limit]
    return "".join(char for char in text if char.isprintable())


def _call(method: str, **payload) -> dict[str, Any] | None:
    """
    봇 API 를 부르고 결과만 돌려준다. 실패는 기록하고 ``None``.

    통신 실패로 봇 전체가 멈추면, 밖에 있는 동안 아무것도 못 하게 된다. 예외를
    올리지 않고 다음 폴링으로 넘어간다. 예외 문구에는 요청 주소가 붙어 나올 수
    있어 토큰이 샐 수 있으므로, 메시지 대신 예외 종류만 남긴다.
    """
    try:
        response = requests.post(
            _api_url(method),
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
            stream=True,
        )
        body = _read_bounded_json(response)
    except Exception as exc:
        logger.warning(f"telegram {method} failed: {type(exc).__name__}")
        return None

    # 응답은 외부 입력이다. 모양을 확인하지 않고 dict 로 다루면, 예상 밖의 본문
    # 하나가 폴링 루프를 끝내 버려 밖에 있는 동안 봇이 죽는다.
    if not isinstance(body, dict):
        logger.warning(f"telegram {method} returned a non-object body")
        return None
    if not body.get("ok"):
        logger.warning(f"telegram {method} rejected: {_for_log(body.get('description'))}")
        return None
    return body.get("result")


def _send(chat_id: int, text: str, buttons: list[list[dict]] | None = None) -> None:
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    _call("sendMessage", **payload)


def _send_video(chat_id: int, video_path: str, caption: str) -> None:
    size = os.path.getsize(video_path)
    if size > MAX_UPLOAD_BYTES:
        _send(
            chat_id,
            f"영상은 만들었는데 {size // (1024 * 1024)}MB 라 봇으로는 보낼 수 없어요.\n"
            f"{video_path}",
        )
        return

    try:
        with open(video_path, "rb") as video_file:
            response = requests.post(
                _api_url("sendVideo"),
                data={"chat_id": chat_id, "caption": caption},
                files={"video": video_file},
                timeout=REQUEST_TIMEOUT_SECONDS * 4,
                stream=True,
            )
        body = _read_bounded_json(response)
        if not isinstance(body, dict) or not body.get("ok"):
            raise RuntimeError("telegram rejected the upload")
    except Exception as exc:
        logger.warning(f"telegram sendVideo failed: {type(exc).__name__}")
        _send(chat_id, f"영상 전송에 실패했어요. 파일은 여기 있습니다.\n{video_path}")


def _answer_callback(callback_id: str) -> None:
    # 누른 버튼의 로딩 표시를 지운다. 안 보내면 클라이언트가 계속 도는 것처럼 보인다.
    _call("answerCallbackQuery", callback_query_id=callback_id)


def _build_params(subject: str, script: str) -> VideoParams:
    """
    저장된 WebUI 설정 위에 대본만 얹는다.

    봇에서 항목을 하나하나 고르게 하면 대화가 길어진다. 화면에서 맞춰 둔 값을 그대로
    쓰고, 봇은 주제와 대본만 받는다.
    """
    saved = config.ui
    return VideoParams(
        video_subject=subject,
        video_script=script,
        video_language=str(saved.get("video_language", "") or ""),
        voice_name=str(saved.get("voice_name", "") or ""),
        voice_rate=float(saved.get("voice_rate", 1.0) or 1.0),
        font_name=str(saved.get("font_name", "") or ""),
        font_size=int(saved.get("font_size", 60) or 60),
        text_fore_color=str(saved.get("text_fore_color", "#FFFFFF") or "#FFFFFF"),
        subtitle_enabled=True,
        layout=str(saved.get("layout", "fullscreen") or "fullscreen"),
        layout_background_color=str(
            saved.get("layout_background_color", "#FFFFFF") or "#FFFFFF"
        ),
        layout_video_height_ratio=float(
            saved.get("layout_video_height_ratio", 0.58) or 0.58
        ),
        layout_corner_radius=int(saved.get("layout_corner_radius", 0) or 0),
        headline_color=str(saved.get("headline_color", "#111111") or "#111111"),
        headline_font_size=int(saved.get("headline_font_size", 86) or 86),
        subtitle_below_video=bool(saved.get("subtitle_below_video", False)),
        subtitle_below_color=str(
            saved.get("subtitle_below_color", "#111111") or "#111111"
        ),
    )


class ShortsBot:
    """한 사람만 쓰는 봇이라 상태는 메모리에 둔다."""

    def __init__(self):
        self.chat_id = _allowed_chat_id()
        self.offset = 0
        self.pending: dict[str, str] = {}
        self.rendering = False
        self._lock = threading.Lock()
        # 오늘 보여 준 후보. 버튼을 누르면 여기서 찾는다.
        self.candidates: dict[str, object] = {}
        # 기록 파일에 못 쓴 날을 위한 대비. 저장이 실패해도 이번 실행 동안에는
        # 같은 목록을 다시 보내지 않는다.
        self.offered_date = ""
        self.retry_daily_after = 0.0

    # ---- 매일 ----

    def _daily_hour(self) -> int | None:
        """설정된 발송 시각. 안 정했으면 ``None``."""
        raw = str(config.telegram.get("daily_hour", DEFAULT_DAILY_HOUR) or "").strip()
        if not raw:
            return None
        try:
            hour = int(raw)
        except ValueError:
            logger.warning("telegram daily_hour is not a number, skipping the schedule")
            return None
        return hour if 0 <= hour <= 23 else None

    def maybe_run_daily(self, now=None) -> bool:
        """
        정해진 시각이 지났고 오늘 아직 안 보냈으면 후보를 보낸다.

        날짜로 기억한다. 시각만 보면 그 시간대 안에서 폴링이 도는 동안 계속
        보내게 되고, 몇 분마다 같은 목록이 온다. 그 날짜는 파일에 남긴다.
        """
        hour = self._daily_hour()
        if hour is None:
            return False

        now = now or time.localtime()
        today = time.strftime("%Y-%m-%d", now)
        # 파일에서 읽는다. 메모리에만 두면 봇을 다시 켤 때마다 그날 목록이 또 나간다.
        if now.tm_hour < hour:
            return False
        if self.offered_date == today or daily.load_last_run() == today:
            return False
        # 실패한 뒤에는 잠시 쉰다. 폴링 주기로 다시 물어보면 장애가 이어지는 동안
        # 요청과 안내가 계속 쌓인다.
        if time.monotonic() < self.retry_daily_after:
            return False

        # 마친 다음에 날짜를 적는다. 먼저 적으면 잠깐의 장애가 그날의 모든
        # 재시도를 막는다.
        if not self._offer_today():
            self.retry_daily_after = time.monotonic() + DAILY_RETRY_SECONDS
            return False

        # 못 써도 이번 실행 동안에는 다시 보내지 않는다. 저장 실패가 폴링마다
        # 같은 목록을 보내는 일로 번지면 안 된다.
        self.offered_date = today
        if not daily.save_last_run(today):
            logger.warning("could not record today's daily run; it may repeat on restart")
        return True

    # ---- 오늘의 소재 ----

    def _offer_today(self) -> bool:
        """
        오늘 다룰 만한 것을 찾아 후보로 보여 준다. 오늘 몫을 마쳤으면 ``True``.

        새 글이 없는 날도 마친 것이다. 못 닿았을 때만 안 마친 것으로 둔다 —
        둘을 같이 다루면 한쪽은 하루를 통째로 건너뛰고 다른 쪽은 폴링마다
        같은 안내를 보낸다.
        """
        # 새로 훑기 전에 지난 목록을 버린다. 남겨 두면 어제 버튼이 오늘도 먹혀,
        # 이미 만든 소재를 다시 만들게 된다.
        self.candidates = {}
        _send(self.chat_id, "오늘 올라온 것 보는 중…")
        run = daily.pick_items(limit=DAILY_CANDIDATES)
        if not run.source_reachable:
            _send(self.chat_id, "지금 소스에 못 닿았어요. 이따 다시 볼게요.")
            return False
        if not run.picks:
            # 오늘 새 글이 없는 것도 정상적인 결과다. 실패로 치면 그날 내내
            # 폴링마다 같은 안내가 나간다.
            _send(self.chat_id, "새로 다룰 만한 게 없어요. 내일 다시 볼게요.")
            return True

        for index, pick in enumerate(run.picks, start=1):
            token = uuid4().hex[:8]
            self.candidates[token] = pick.item
            _send(
                self.chat_id,
                f"{index}. {pick.item.title}\n{pick.reason}\n"
                f"{pick.item.url or pick.item.discussion_url}",
                buttons=[[{"text": "이걸로", "callback_data": f"pick:{token}"}]],
            )
        return True

    def _draft_cards(self, item) -> None:
        """고른 소재로 카드 대본을 만들어 승인을 받는다."""
        _send(self.chat_id, "카드 만드는 중…")
        script = cardscript.build_card_script(item)
        if not script:
            _send(self.chat_id, "이 소재로는 카드가 안 나왔어요. 다른 걸 골라 주세요.")
            return

        draft_id = uuid4().hex[:8]
        self.pending = {
            "subject": item.title,
            "script": script.narration_text,
            "draft_id": draft_id,
            "card_script": script,
            "item": item,
        }
        lines = []
        for card in script.cards:
            lines.append(f"[{card.index_label}] {card.title}")
            lines.extend(f"    · {bullet}" for bullet in card.body)
        _send(
            self.chat_id,
            "\n".join(lines)[:MAX_TELEGRAM_MESSAGE_LENGTH - 100],
            buttons=[
                [
                    {"text": "승인", "callback_data": f"approve:{draft_id}"},
                    {"text": "취소", "callback_data": f"cancel:{draft_id}"},
                ]
            ],
        )

    def _render_cards(self, item, script) -> None:
        """카드뉴스를 만들어 보낸다."""
        task_id = utils.get_uuid()
        try:
            params = _build_params("", "")
            # 렌더러는 매니페스트를 보완만 한다. 없으면 아무것도 안 남으므로
            # 여기서 먼저 만든다. 이 경로로 만든 영상도 무엇으로 만들었는지
            # 되짚을 수 있어야 한다.
            task_artifacts.write_script_data(
                task_id,
                {
                    "source": {
                        "name": item.source,
                        "item_id": item.item_id,
                        "title": item.title,
                        "url": item.url,
                        "discussion_url": item.discussion_url,
                        "points": item.points,
                    },
                    "cards": [
                        {
                            "title": card.title,
                            "bullets": list(card.body),
                            "narration": narration,
                        }
                        for card, narration in zip(script.cards, script.narrations)
                    ],
                    "params": params.model_dump(mode="json"),
                },
            )
            result = cardvideo.render_card_news(task_id, script, params)
            if not result:
                _send(self.chat_id, "영상 생성에 실패했어요. 로그를 확인해 주세요.")
                return
            # 만든 것만 기록한다. 후보로 보여 주기만 한 소재는 내일 다시 나온다.
            daily.mark_used(item)
            _send_video(self.chat_id, result.video_path, caption=item.title)
        except Exception as exc:
            logger.error(
                f"telegram card render failed: {task_id}, "
                f"{type(exc).__name__}: {llm.sanitize_error_message(exc)}"
            )
            _send(self.chat_id, f"영상 생성 중 오류가 났어요: {type(exc).__name__}")
        finally:
            with self._lock:
                self.rendering = False

    # ---- 대본 ----

    def _draft_script(self, subject: str) -> None:
        _send(self.chat_id, "대본 쓰는 중…")
        script = llm.generate_script(
            video_subject=subject,
            language=str(config.ui.get("video_language", "") or ""),
            paragraph_number=3,
            script_style="story",
        )
        if not script or script.startswith("Error:"):
            _send(self.chat_id, "대본 생성에 실패했어요. 잠시 후 다시 해보세요.")
            return

        self._offer_draft(subject, script)

    def _offer_draft(self, subject: str, script: str) -> None:
        """대본을 승인 대기에 올리고 버튼을 붙여 보낸다."""
        script = str(script or "").strip()[:MAX_SCRIPT_LENGTH]
        if not script:
            return

        # 어느 대본에 대한 버튼인지 표시해 둔다. 다시 뽑은 뒤 예전 메시지의 승인을
        # 누르면, 보고 있는 것과 다른 대본이 만들어진다.
        draft_id = uuid4().hex[:8]
        self.pending = {"subject": subject, "script": script, "draft_id": draft_id}
        _send(
            self.chat_id,
            f"{script}\n\n— {len(script)}자",
            buttons=[
                [
                    {"text": "승인", "callback_data": f"approve:{draft_id}"},
                    {"text": "다시 뽑기", "callback_data": f"retry:{draft_id}"},
                    {"text": "취소", "callback_data": f"cancel:{draft_id}"},
                ]
            ],
        )

    # ---- 렌더링 ----

    def _render(self, subject: str, script: str) -> None:
        task_id = utils.get_uuid()
        try:
            params = _build_params(subject, script)
            result = tm.start(task_id=task_id, params=params, stop_at="video")
            videos = (result or {}).get("videos") or []
            if not videos:
                _send(self.chat_id, "영상 생성에 실패했어요. 로그를 확인해 주세요.")
                return
            _send_video(self.chat_id, videos[0], caption=subject)
        except Exception as exc:
            # 파이프라인 전체를 감싸므로 제공자 예외가 그대로 올라온다. 그 메시지에는
            # 자격 증명이 붙은 주소가 섞일 수 있어, 트레이스백째로 남기지 않는다.
            logger.error(
                f"telegram render failed: {task_id}, "
                f"{type(exc).__name__}: {llm.sanitize_error_message(exc)}"
            )
            _send(self.chat_id, f"영상 생성 중 오류가 났어요: {type(exc).__name__}")
        finally:
            with self._lock:
                self.rendering = False

    def _start_render(self) -> None:
        with self._lock:
            if self.rendering:
                _send(self.chat_id, "이미 만들고 있어요. 끝나면 보내드릴게요.")
                return
            self.rendering = True

        subject = self.pending.get("subject", "")
        script = self.pending.get("script", "")
        card_script = self.pending.get("card_script")
        item = self.pending.get("item")
        self.pending = {}
        _send(self.chat_id, "만들기 시작했어요. 십 분쯤 걸립니다.")
        # 폴링을 막지 않도록 따로 돌린다. 렌더링 중에도 명령을 받을 수 있어야 한다.
        if card_script is not None:
            target, arguments = self._render_cards, (item, card_script)
        else:
            target, arguments = self._render, (subject, script)
        threading.Thread(target=target, args=arguments, daemon=True).start()

    # ---- 수신 ----

    def _handle_message(self, message: dict) -> None:
        text = str(message.get("text", "") or "").strip()
        if not text:
            return

        if text.startswith("/새영상") or text.startswith("/new"):
            subject = text.split(maxsplit=1)[1].strip() if " " in text else ""
            if not subject:
                _send(self.chat_id, "주제를 함께 보내주세요. 예: /새영상 닭가슴살 맛있게 먹는 법")
                return
            self._draft_script(subject[:MAX_SUBJECT_LENGTH])
            return

        if text.startswith("/오늘") or text.startswith("/today"):
            self._offer_today()
            return

        if text.startswith("/상태") or text.startswith("/status"):
            _send(self.chat_id, "만드는 중이에요." if self.rendering else "쉬고 있어요.")
            return

        if text.startswith("/"):
            _send(self.chat_id, "쓸 수 있는 명령: /오늘, /새영상 <주제>, /상태")
            return

        # 명령이 아닌 글은 대본을 직접 고쳐 보낸 것으로 본다.
        if self.pending:
            self._offer_draft(self.pending.get("subject", ""), text)

    def _handle_callback(self, callback: dict) -> None:
        _answer_callback(str(callback.get("id", "")))
        action, _, draft_id = str(callback.get("data", "") or "").partition(":")

        if action == "pick":
            # 한 번 고른 버튼은 쓴다. 남겨 두면 만든 뒤에 또 눌러 같은 것을
            # 다시 만들게 된다.
            item = self.candidates.pop(draft_id, None)
            if item is None:
                _send(self.chat_id, "지난 목록의 버튼이에요. /오늘 로 다시 불러 주세요.")
                return
            self._draft_cards(item)
            return

        if not self.pending.get("script"):
            _send(self.chat_id, "승인할 대본이 없어요. /새영상 부터 시작해 주세요.")
            return
        if draft_id != self.pending.get("draft_id"):
            # 다시 뽑은 뒤 예전 메시지의 버튼을 누른 경우. 보고 있는 것과 다른
            # 대본을 만들어 주는 편이 더 나쁘다.
            _send(self.chat_id, "지난 대본의 버튼이에요. 마지막으로 보낸 대본에서 눌러주세요.")
            return

        if action == "approve":
            self._start_render()
        elif action == "retry":
            subject = self.pending.get("subject", "")
            if subject:
                self._draft_script(subject)
        elif action == "cancel":
            self.pending = {}
            _send(self.chat_id, "취소했어요.")

    def handle_update(self, update: dict) -> None:
        """
        업데이트 하나를 처리한다. 허용한 대화가 아니면 아무것도 하지 않는다.

        봇 이름은 누구나 검색할 수 있다. 여기서 막지 않으면 모르는 사람이 이 기계에서
        영상 생성을 돌리고 모델 사용료를 쓰게 된다.
        """
        source = update.get("message") or update.get("callback_query") or {}
        chat = source.get("chat") or (source.get("message") or {}).get("chat") or {}
        incoming_chat_id = chat.get("id")

        # 그룹 대화 id 를 넣어 두면 그 방의 누구나 이 기계에서 렌더링을 돌릴 수 있다.
        # 한 사람이 쓰는 봇이므로 1:1 대화만 받는다.
        if chat.get("type") not in (None, "private"):
            logger.warning("ignored a telegram update from a non-private chat")
            return

        if not self.chat_id:
            # 최초 설정. chat_id 를 알아야 설정에 적을 수 있는데, 그 값은 실제로
            # 메시지를 받아 봐야 안다. 터미널에만 남기고 아무 동작도 하지 않는다.
            logger.info(
                "telegram chat id (config.toml 의 [telegram] chat_id 에 적으세요): "
                f"{incoming_chat_id}"
            )
            return

        if incoming_chat_id != self.chat_id:
            logger.warning("ignored a telegram update from an unexpected chat")
            return

        if "message" in update:
            self._handle_message(update["message"])
        elif "callback_query" in update:
            self._handle_callback(update["callback_query"])

    def poll_once(self) -> None:
        updates = _call(
            "getUpdates",
            offset=self.offset,
            timeout=POLL_TIMEOUT_SECONDS,
            limit=MAX_UPDATES_PER_POLL,
        )
        if not isinstance(updates, list):
            return
        for update in updates:
            if not isinstance(update, dict):
                continue
            try:
                self.offset = int(update.get("update_id", 0)) + 1
            except (TypeError, ValueError):
                # 이 업데이트의 번호를 읽지 못하면 offset 을 옮길 수 없다. 건너뛰면
                # 같은 것을 계속 다시 받으므로, 하나 올려 앞으로 나아간다.
                self.offset += 1
                continue
            try:
                self.handle_update(update)
            except Exception:
                logger.exception("failed to handle a telegram update")

    def run(self) -> None:
        if not self.chat_id:
            logger.warning(
                "telegram chat_id 가 비어 있습니다. 봇에게 아무 메시지나 보내면 "
                "여기에 chat id 가 찍힙니다. 그 값을 config.toml 에 적고 다시 켜세요."
            )
        else:
            logger.info("telegram bot started")
            _send(self.chat_id, "준비됐어요. /오늘 로 오늘 올라온 것부터 보세요.")
        while True:
            if self.chat_id:
                try:
                    self.maybe_run_daily()
                except Exception:
                    logger.exception("the daily pick failed")
            self.poll_once()
            # getUpdates 가 롱 폴링이라 보통은 여기서 쉬지 않는다. 통신이 계속
            # 실패할 때 초당 수십 번 재시도하지 않도록 짧게 눕는다.
            time.sleep(1)


def run_bot() -> int:
    if not _bot_token():
        raise TelegramConfigError(
            "config.toml 의 [telegram] bot_token 이 비어 있습니다. "
            "@BotFather 에서 봇을 만들고 토큰을 넣으세요."
        )
    ShortsBot().run()
    return 0
