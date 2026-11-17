"""Post videos to TikTok by driving TikTok Studio in a real Chrome window.

This is unofficial browser automation. It reuses a dedicated Chrome profile that
you log in to once (agent.py tiktok-login). If TikTok changes its upload page,
the selectors below may need updating; failures save a screenshot to logs/.
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, sync_playwright
from playwright.sync_api import TimeoutError as PWTimeout

UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload?from=webapp"
LOGIN_URL = "https://www.tiktok.com/login"


class TikTokSessionError(RuntimeError):
    pass


def _launch(p, profile_dir: Path, headless: bool) -> BrowserContext:
    profile_dir.mkdir(parents=True, exist_ok=True)
    return p.chromium.launch_persistent_context(
        str(profile_dir),
        channel="chrome",
        headless=headless,
        viewport={"width": 1366, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )


def _has_session(ctx: BrowserContext) -> bool:
    return any(
        c["name"] == "sessionid" and c["value"]
        for c in ctx.cookies("https://www.tiktok.com")
    )


def login(profile_dir: Path, timeout_s: int = 900) -> bool:
    """Open Chrome so the user can log in once; the session is kept in profile_dir."""
    with sync_playwright() as p:
        ctx = _launch(p, profile_dir, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(LOGIN_URL)
        print("Log in to TikTok in the Chrome window that just opened.")
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if _has_session(ctx):
                print("TikTok login detected. Saving session...")
                page.wait_for_timeout(4000)
                ctx.close()
                return True
            time.sleep(2)
        ctx.close()
        return False


def _screenshot(page: Page, shot_dir: Path | None, name: str) -> str | None:
    if not shot_dir:
        return None
    shot_dir.mkdir(parents=True, exist_ok=True)
    path = shot_dir / f"tiktok-{name}-{datetime.now():%Y%m%d-%H%M%S}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
        return str(path)
    except Exception:
        return None


def _dismiss_popups(page: Page) -> None:
    # Feature-tour bubbles (react-joyride) and one-off dialogs block clicks.
    for _ in range(6):
        clicked = False
        candidates = [
            page.locator("#react-joyride-portal button, .react-joyride__tooltip button")
                .filter(has_text=re.compile(r"Got it|Next|Done|Skip|OK", re.I)),
            page.get_by_role("button", name=re.compile(r"^(Got it|Not now|Turn on|OK)$", re.I)),
        ]
        for loc in candidates:
            try:
                if loc.count() and loc.first.is_visible():
                    # "Turn on" is the automatic content-check prompt; accept it.
                    loc.first.click(timeout=2000)
                    page.wait_for_timeout(600)
                    clicked = True
                    break
            except Exception:
                pass
        if not clicked:
            break
    # Last resort: an orphaned tour overlay with no button still eats clicks.
    try:
        page.evaluate(
            "document.querySelectorAll('.react-joyride__overlay, #react-joyride-portal')"
            ".forEach(e => e.remove())"
        )
    except Exception:
        pass


def _post_button(page: Page):
    btn = page.locator('button[data-e2e="post_video_button"]')
    if btn.count():
        return btn.first
    return page.get_by_role("button", name=re.compile(r"^\s*Post\s*$", re.I)).first


def _wait_upload_finished(page: Page, timeout_s: int = 600) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        _dismiss_popups(page)
        btn = _post_button(page)
        try:
            ready = (
                btn.is_visible()
                and btn.is_enabled()
                and btn.get_attribute("aria-disabled") != "true"
                and btn.get_attribute("data-disabled") != "true"
            )
        except Exception:
            ready = False
        # The file header shows "Uploading ... 37%" and then "Uploaded (24 MB)" when done.
        # Only look at that status word: captions may legitimately contain "60%".
        uploading = page.get_by_text(re.compile(r"^\s*Uploading\b")).count() > 0
        uploaded = page.get_by_text(re.compile(r"^\s*Uploaded\b")).count() > 0
        if ready and (uploaded or not uploading):
            return
        time.sleep(2)
    raise TimeoutError("TikTok upload did not finish in time")


def _fill_caption(page: Page, caption: str, hashtags: list[str]) -> None:
    editor = page.locator('div[contenteditable="true"]').first
    editor.wait_for(state="visible", timeout=120_000)
    page.wait_for_timeout(2000)  # tour popups appear shortly after the editor
    _dismiss_popups(page)
    editor.click()
    page.keyboard.press("Meta+A")
    page.keyboard.press("Backspace")
    page.keyboard.type(caption.strip() + " ", delay=15)
    for tag in hashtags:
        tag = re.sub(r"[^\w]", "", tag)
        if not tag:
            continue
        page.keyboard.type("#" + tag, delay=60)
        page.wait_for_timeout(1800)  # let the hashtag suggestion list appear
        page.keyboard.type(" ", delay=60)
        page.wait_for_timeout(400)
    page.keyboard.press("Escape")


def upload(
    video_path: str,
    caption: str,
    hashtags: list[str],
    profile_dir: Path,
    headless: bool = False,
    post: bool = True,
    shot_dir: Path | None = None,
) -> dict:
    with sync_playwright() as p:
        ctx = _launch(p, profile_dir, headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            if not _has_session(ctx):
                raise TikTokSessionError("Not logged in to TikTok; run: agent.py tiktok-login")
            page.goto(UPLOAD_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)
            if "login" in page.url:
                raise TikTokSessionError("TikTok session expired; run: agent.py tiktok-login")

            file_input = page.locator('input[type="file"]').first
            file_input.wait_for(state="attached", timeout=60_000)
            file_input.set_input_files(video_path)

            _fill_caption(page, caption, hashtags)
            _wait_upload_finished(page)
            page.wait_for_timeout(2000)

            if not post:
                return {"status": "dry-run", "screenshot": _screenshot(page, shot_dir, "dry-run")}

            _post_button(page).click()
            # TikTok may ask to confirm (e.g. while the content check is still running).
            try:
                page.get_by_role("button", name=re.compile(r"Post now", re.I)).click(timeout=8000)
            except PWTimeout:
                pass

            try:
                page.wait_for_url(re.compile(r"tiktokstudio/content|/manage"), timeout=180_000)
            except PWTimeout:
                if page.get_by_text(re.compile(r"(video|post) (has been|was) (uploaded|posted)|Manage your posts", re.I)).count() == 0:
                    raise TimeoutError("Clicked Post but TikTok never confirmed the upload")
            page.wait_for_timeout(3000)
            return {"status": "posted", "screenshot": _screenshot(page, shot_dir, "posted")}
        except Exception as exc:
            shot = _screenshot(page, shot_dir, "error")
            raise RuntimeError(f"{exc} (screenshot: {shot})") from exc
        finally:
            ctx.close()
