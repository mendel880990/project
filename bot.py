"""בוט טלגרם שמעביר שאלות לאתר chabad.ai ומחזיר את התשובות שלו בלבד."""

import asyncio
import io
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from chat_site import AnswerTimeoutError, ChatSite, NotLoggedInError

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("bot")

TELEGRAM_LIMIT = 4096

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USER_IDS = {int(x) for x in os.environ.get("ALLOWED_USER_IDS", "").replace(" ", "").split(",") if x}

site = ChatSite(
    url=os.environ.get("CHAT_URL", "https://chabad.ai"),
    profile_dir=BASE_DIR / os.environ.get("PROFILE_DIR", "browser_profile"),
    headless=os.environ.get("HEADLESS", "true").lower() != "false",
    browser_channel=os.environ.get("BROWSER_CHANNEL", "chrome"),
    input_selector=os.environ.get("INPUT_SELECTOR", ""),
    answer_selector=os.environ.get("ANSWER_SELECTOR", ""),
    answer_timeout=float(os.environ.get("ANSWER_TIMEOUT", "180")),
    stable_seconds=float(os.environ.get("STABLE_SECONDS", "4")),
    executable_path=os.environ.get("BROWSER_EXECUTABLE", ""),
)


async def authorized(update: Update) -> bool:
    user = update.effective_user
    if user and user.id in ALLOWED_USER_IDS:
        return True
    if not ALLOWED_USER_IDS:
        await update.effective_message.reply_text(
            f"מספר הזיהוי שלך בטלגרם: {user.id}\n"
            "הכנס אותו לקובץ ‎.env בשורה ALLOWED_USER_IDS והפעל את הבוט מחדש."
        )
    else:
        log.warning("Rejected message from user %s", user.id if user else "?")
    return False


async def keep_typing(chat, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await chat.send_action(ChatAction.TYPING)
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=4)
        except asyncio.TimeoutError:
            pass


def split_message(text: str) -> list[str]:
    chunks = []
    while len(text) > TELEGRAM_LIMIT:
        cut = text.rfind("\n", 0, TELEGRAM_LIMIT)
        if cut < TELEGRAM_LIMIT // 2:
            cut = TELEGRAM_LIMIT
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    chunks.append(text)
    return chunks


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await authorized(update):
        return
    await update.message.reply_text(
        "שלום! שלח לי שאלה בחסידות ואעביר אותה ל-chabad.ai.\n\n"
        "/new – שיחה חדשה\n"
        "/debug – צילום מסך של האתר (לבדיקת תקלות)"
    )


async def new_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await authorized(update):
        return
    await site.new_chat()
    await update.message.reply_text("נפתחה שיחה חדשה.")


async def debug_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await authorized(update):
        return
    await update.message.reply_photo(await site.screenshot(), caption="המצב הנוכחי של האתר")
    html = io.BytesIO((await site.html()).encode("utf-8"))
    await update.message.reply_document(html, filename="page.html")


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await authorized(update):
        return
    question = update.message.text
    stop = asyncio.Event()
    typing = asyncio.create_task(keep_typing(update.effective_chat, stop))
    try:
        answer = await site.ask(question)
    except NotLoggedInError:
        answer = (
            "לא מצאתי את תיבת הצ'אט באתר. כנראה שפג תוקף ההתחברות.\n"
            "סגור את הבוט, הרץ את ההתחברות מחדש (login), ואז הפעל אותו שוב."
        )
    except AnswerTimeoutError:
        answer = "לא התקבלה תשובה מהאתר בזמן. נסה שוב, או שלח /debug כדי לראות מה קורה."
    except Exception:
        log.exception("Failed to get answer")
        answer = "אירעה שגיאה. טוען את האתר מחדש, נסה שוב בעוד רגע."
        try:
            await site.new_chat()
        except Exception:
            log.exception("Reload failed")
    finally:
        stop.set()
        await typing
    for chunk in split_message(answer):
        await update.message.reply_text(chunk)


async def post_init(app: Application) -> None:
    await site.start()
    log.info("Browser ready, bot is running")


async def post_shutdown(app: Application) -> None:
    await site.close()


def main() -> None:
    if not TOKEN:
        raise SystemExit("חסר TELEGRAM_BOT_TOKEN בקובץ ‎.env")
    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("new", new_cmd))
    app.add_handler(CommandHandler("debug", debug_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.run_polling()


if __name__ == "__main__":
    main()
