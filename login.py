"""התחברות חד-פעמית לאתר עם חשבון גוגל.

פותח חלון Chrome רגיל (לא אוטומטי, כדי שגוגל לא יחסום את ההתחברות)
עם פרופיל נפרד של הבוט. מתחברים ידנית, סוגרים את החלון, וההתחברות נשמרת
לבוט.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

URL = os.environ.get("CHAT_URL", "https://chabad.ai")
PROFILE_DIR = BASE_DIR / os.environ.get("PROFILE_DIR", "browser_profile")

CHROME_PATHS = [
    os.environ.get("BROWSER_EXECUTABLE", ""),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    shutil.which("google-chrome") or "",
    shutil.which("google-chrome-stable") or "",
]


def find_chrome() -> str | None:
    for path in CHROME_PATHS:
        if path and Path(path).is_file():
            return path
    return None


def main() -> None:
    chrome = find_chrome()
    if not chrome:
        sys.exit("לא נמצא Google Chrome. התקן אותו מ-https://www.google.com/chrome והרץ שוב.")
    PROFILE_DIR.mkdir(exist_ok=True)
    print("נפתח חלון Chrome. התחבר לאתר עם חשבון הגוגל שלך,")
    print("ודא שאתה רואה את תיבת הצ'אט, ואז סגור את החלון.")
    subprocess.run([chrome, f"--user-data-dir={PROFILE_DIR}", "--no-first-run", URL])
    print("ההתחברות נשמרה. עכשיו אפשר להפעיל את הבוט.")


if __name__ == "__main__":
    main()
