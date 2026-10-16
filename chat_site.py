"""מפעיל את אתר הצ'אט (chabad.ai) דרך דפדפן אוטומטי.

הבוט לא משתמש בשום מודל AI או מקור מידע אחר: הוא מקליד את השאלה באתר,
מחכה שהתשובה תסתיים, ומעתיק אותה כמו שהיא.
"""

import asyncio
import difflib
import logging
import time
from pathlib import Path

from playwright.async_api import BrowserContext, Page, async_playwright

log = logging.getLogger(__name__)

# שדות קלט אפשריים של צ'אט, לפי סדר עדיפות. אפשר לעקוף עם INPUT_SELECTOR.
INPUT_CANDIDATES = [
    "textarea",
    "[contenteditable='true']",
    "input[type='text']",
]

# מבנים נפוצים של הודעת תשובה באתרי צ'אט. אפשר לעקוף עם ANSWER_SELECTOR.
ANSWER_CANDIDATES = [
    "[data-message-author-role='assistant']",
    "[data-role='assistant']",
    "[class*='assistant-message']",
    "[class*='bot-message']",
    "[class*='ai-message']",
    ".markdown",
    ".prose",
]


class NotLoggedInError(Exception):
    """האתר לא מציג תיבת צ'אט, כנראה כי צריך להתחבר מחדש."""


class AnswerTimeoutError(Exception):
    """לא התקבלה תשובה בזמן שהוגדר."""


class ChatSite:
    def __init__(
        self,
        url: str,
        profile_dir: Path,
        headless: bool = True,
        browser_channel: str = "chrome",
        input_selector: str = "",
        answer_selector: str = "",
        answer_timeout: float = 180,
        stable_seconds: float = 4,
        executable_path: str = "",
    ):
        self.url = url
        self.profile_dir = profile_dir
        self.headless = headless
        self.browser_channel = browser_channel
        self.input_selector = input_selector
        self.answer_selector = answer_selector
        self.answer_timeout = answer_timeout
        self.stable_seconds = stable_seconds
        self.executable_path = executable_path
        self._pw = None
        self._ctx: BrowserContext | None = None
        self._page: Page | None = None

    async def start(self) -> None:
        self._pw = await async_playwright().start()
        launch_args = dict(
            user_data_dir=str(self.profile_dir),
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
            viewport={"width": 1280, "height": 900},
            locale="he-IL",
        )
        if self.executable_path:
            launch_args["executable_path"] = self.executable_path
        elif self.browser_channel:
            launch_args["channel"] = self.browser_channel
        self._ctx = await self._pw.chromium.launch_persistent_context(**launch_args)
        self._page = self._ctx.pages[0] if self._ctx.pages else await self._ctx.new_page()
        await self.new_chat()

    async def close(self) -> None:
        if self._ctx:
            await self._ctx.close()
        if self._pw:
            await self._pw.stop()

    async def new_chat(self) -> None:
        """טוען את האתר מחדש, כלומר פותח שיחה חדשה."""
        await self._page.goto(self.url, wait_until="domcontentloaded")
        try:
            await self._page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass  # אתרים עם חיבור פתוח תמידי לא מגיעים ל-networkidle

    async def screenshot(self) -> bytes:
        return await self._page.screenshot(full_page=True)

    async def html(self) -> str:
        return await self._page.content()

    async def ask(self, question: str) -> str:
        page = self._page
        box = await self._find_input()
        if box is None:
            raise NotLoggedInError(page.url)

        before_body = await page.inner_text("body")
        before_answers = await self._answer_snapshot()

        await box.click()
        tag = (await box.evaluate("e => e.tagName")).lower()
        if tag in ("textarea", "input"):
            await box.fill(question)
        else:  # contenteditable
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Delete")
            await page.keyboard.insert_text(question)
        await page.keyboard.press("Enter")

        return await self._wait_for_answer(question, before_body, before_answers)

    async def _find_input(self):
        selectors = [self.input_selector] if self.input_selector else INPUT_CANDIDATES
        for selector in selectors:
            loc = self._page.locator(selector)
            for i in reversed(range(await loc.count())):
                el = loc.nth(i)
                if await el.is_visible() and await el.is_editable():
                    return el
        return None

    async def _answer_snapshot(self) -> dict[str, list[str]]:
        selectors = [self.answer_selector] if self.answer_selector else ANSWER_CANDIDATES
        snapshot = {}
        for selector in selectors:
            try:
                snapshot[selector] = await self._page.locator(selector).all_inner_texts()
            except Exception:
                snapshot[selector] = []
        return snapshot

    async def _current_answer(self, question, before_body, before_answers) -> str:
        q = question.strip()
        # 1. הודעת תשובה מזוהה: הודעה חדשה, או שההודעה האחרונה השתנתה.
        after = await self._answer_snapshot()
        for selector, texts in after.items():
            old = before_answers.get(selector, [])
            if not texts:
                continue
            last = texts[-1].strip()
            if last and last != q and (len(texts) > len(old) or last != (old[-1].strip() if old else "")):
                return last
        if self.answer_selector:
            return ""
        # 2. גיבוי: הטקסט שנוסף לעמוד מאז ששלחנו את השאלה, בלי השאלה עצמה.
        after_body = await self._page.inner_text("body")
        return _added_text(before_body, after_body, q)

    async def _wait_for_answer(self, question, before_body, before_answers) -> str:
        deadline = time.monotonic() + self.answer_timeout
        last_text, stable_since = "", None
        while time.monotonic() < deadline:
            await asyncio.sleep(1)
            text = await self._current_answer(question, before_body, before_answers)
            if not text:
                continue
            if text != last_text:
                last_text, stable_since = text, time.monotonic()
            elif time.monotonic() - stable_since >= self.stable_seconds:
                return text  # הטקסט הפסיק להשתנות, התשובה הסתיימה
        if last_text:
            log.warning("Answer still changing at timeout; returning partial text")
            return last_text
        raise AnswerTimeoutError()


def _added_text(before: str, after: str, question: str) -> str:
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    question_lines = {line.strip() for line in question.splitlines() if line.strip()}
    added = []
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)
    for op, _, _, j1, j2 in matcher.get_opcodes():
        if op in ("insert", "replace"):
            added.extend(after_lines[j1:j2])
    lines = [line for line in added if line.strip() and line.strip() not in question_lines]
    return "\n".join(lines).strip()
