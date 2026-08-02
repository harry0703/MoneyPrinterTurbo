#!/usr/bin/env python3
"""텔레그램 봇 실행 진입점. `python telegram_bot.py` 로 켠다."""

from loguru import logger

from app.services.telegram_bot import TelegramConfigError, run_bot

if __name__ == "__main__":
    try:
        raise SystemExit(run_bot())
    except TelegramConfigError as exc:
        logger.error(str(exc))
        raise SystemExit(2) from None
    except KeyboardInterrupt:
        raise SystemExit(0) from None
