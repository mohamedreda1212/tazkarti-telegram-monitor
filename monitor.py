# -*- coding: utf-8 -*-
"""
بوت مراقبة تذاكر الأهلي على تذكرتي -> إشعار Telegram
وظيفته: يراقب ويبعت إشعار بس. مفيهوش حجز تلقائي ولا تجاوز CAPTCHA.

الإعدادات كلها بتيجي من Environment Variables (على GitHub: Secrets/Variables).
"""
import json
import os
import pathlib
import re
import sys
import datetime

import requests
from playwright.sync_api import sync_playwright

# ============== الإعدادات (غيّرها من GitHub مش من هنا) ==============
MATCH_URL = os.environ.get("MATCH_URL", "ضع_رابط_المباراة_هنا")   # رابط صفحة المباراة
MATCH_NAME = os.environ.get("MATCH_NAME", "")                      # اختياري: اسم المباراة، لو فاضي هيتسحب من الصفحة
TG_TOKEN = os.environ.get("TG_BOT_TOKEN", "")                     # سرّ - من BotFather
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")                      # رقم الشات بتاعك
BOOK_SELECTOR = os.environ.get("BOOK_SELECTOR", "")               # اختياري: CSS selector لزرار الحجز لو عرفته
DEBUG = os.environ.get("DEBUG", "0") == "1"

STATE_FILE = pathlib.Path(__file__).parent / "state.json"
DEBUG_DIR = pathlib.Path(__file__).parent / "debug"

# كلمات الكشف (عدّلها لو الموقع غيّر الصياغة)
SOLD_OUT_WORDS = ["sold out", "soldout", "نفدت", "نفذت", "اكتمل العدد", "نفد"]
NOT_STARTED_WORDS = ["لم يبدأ", "لم يبدا", "قريبا", "قريباً", "coming soon", "not started", "will open", "يبدأ الحجز", "سيبدأ"]
UNAVAILABLE_WORDS = ["غير متاح", "غير متاحة", "not available", "unavailable", "closed", "مغلق"]
BOOK_WORDS = ["احجز", "حجز التذاكر", "حجز تذكرة", "شراء", "book now", "buy ticket", "buy tickets", "book ticket", "book"]
BLOCK_WORDS = ["captcha", "verify you are human", "access denied", "are you a robot"]  # لو ظهرت: مش بنتجاوزها


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "UNKNOWN", "notified_available": False, "last_checked_date": ""}


def save_state(state: dict) -> None:
    state["last_checked_date"] = datetime.date.today().isoformat()
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def contains_any(text: str, words) -> bool:
    t = text.lower()
    return any(w.lower() in t for w in words)


def fetch_page():
    """يفتح الصفحة بمتصفح حقيقي (لأن تذكرتي بتعتمد على JavaScript) ويرجّع (النص، عناوين، أزرار، عنوان الصفحة)"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(locale="ar-EG", viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.goto(MATCH_URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)  # نستنى الـ JS يخلص رسم

        text = page.inner_text("body")
        title = page.title()
        h1 = ""
        try:
            h1 = page.locator("h1").first.inner_text(timeout=2000)
        except Exception:
            pass

        # كل الأزرار/اللينكات اللي مش جوه الهيدر/الفوتر/القايمة، ومعاها حالة disabled
        buttons = page.evaluate(
            """() => [...document.querySelectorAll('a, button, [role=button]')]
                .filter(e => !e.closest('header, nav, footer'))
                .map(e => ({
                    text: (e.innerText || e.getAttribute('aria-label') || '').trim(),
                    disabled: e.disabled === true || e.getAttribute('aria-disabled') === 'true'
                              || e.classList.contains('disabled'),
                    href: e.getAttribute('href') || ''
                }))
                .filter(b => b.text && b.text.length < 60)"""
        )
        selector_hit = False
        if BOOK_SELECTOR:
            try:
                el = page.locator(BOOK_SELECTOR).first
                selector_hit = el.count() > 0 and el.is_enabled()
            except Exception:
                selector_hit = False

        if DEBUG:
            DEBUG_DIR.mkdir(exist_ok=True)
            (DEBUG_DIR / "page_text.txt").write_text(text, encoding="utf-8")
            (DEBUG_DIR / "buttons.json").write_text(json.dumps(buttons, ensure_ascii=False, indent=2), encoding="utf-8")
            page.screenshot(path=str(DEBUG_DIR / "screenshot.png"), full_page=True)
        browser.close()
    return text, title, h1, buttons, selector_hit


def detect_status(text, buttons, selector_hit) -> str:
    """بيرجّع: AVAILABLE / SOLD_OUT / NOT_STARTED / UNAVAILABLE / UNKNOWN"""
    if contains_any(text, BLOCK_WORDS):
        return "UNKNOWN"  # في حماية/CAPTCHA: مش بنتخطاها، ونعتبر الفحص فاشل
    if len(text.strip()) < 50:
        return "UNKNOWN"  # الصفحة مرسمتش كويس

    if contains_any(text, SOLD_OUT_WORDS):
        return "SOLD_OUT"
    if contains_any(text, NOT_STARTED_WORDS):
        return "NOT_STARTED"

    book_button = any(
        (not b["disabled"]) and contains_any(b["text"], BOOK_WORDS) for b in buttons
    )
    if selector_hit or book_button:
        return "AVAILABLE"
    if contains_any(text, UNAVAILABLE_WORDS):
        return "UNAVAILABLE"
    return "UNAVAILABLE"


def send_telegram(match_name: str) -> None:
    missing = [k for k, v in {"TG_BOT_TOKEN": TG_TOKEN, "TG_CHAT_ID": TG_CHAT_ID}.items() if not v]
    if missing:
        raise RuntimeError(f"ناقص إعدادات: {', '.join(missing)}")
    text = (
        "🔔 تذاكر الأهلي أصبحت متاحة!\n\n"
        f"🏟️ المباراة: {match_name}\n"
        "🎟️ الحالة: متاحة للحجز\n"
        "🔗 رابط الحجز:\n"
        f"{MATCH_URL}\n\n"
        "⚡ ادخل واحجز بسرعة."
    )
    r = requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={"chat_id": TG_CHAT_ID, "text": text},
        timeout=30,
    )
    if r.status_code >= 300 or not r.json().get("ok"):
        raise RuntimeError(f"Telegram رجّع خطأ {r.status_code}: {r.text}")
    print("تم إرسال رسالة Telegram ✅")


def main() -> int:
    test_mode = "--test" in sys.argv
    if test_mode:
        send_telegram(MATCH_NAME or "مباراة تجريبية - الأهلي")
        return 0

    if "ضع_رابط" in MATCH_URL:
        print("❌ لازم تحط MATCH_URL")
        return 1

    state = load_state()
    try:
        text, title, h1, buttons, selector_hit = fetch_page()
    except Exception as e:
        print(f"فشل فتح الصفحة (مش مشكلة، هنحاول تاني): {e}")
        save_state(state)
        return 0

    status = detect_status(text, buttons, selector_hit)
    match_name = MATCH_NAME or h1 or title or "مباراة الأهلي"
    print(f"الحالة المكتشفة: {status} | آخر حالة محفوظة: {state.get('status')} | المباراة: {match_name}")

    if status == "UNKNOWN":
        save_state(state)  # منغيّرش الحالة المحفوظة عشان منبعتش تنبيه مكرر
        return 0

    if status == "AVAILABLE":
        if not state.get("notified_available"):
            send_telegram(match_name)          # لو فشل هيرمي Exception ومش هنسجل إننا بعتنا
            state["notified_available"] = True
        else:
            print("اتبعت إشعار قبل كده لنفس الحالة، مش هبعت تاني.")
    else:
        state["notified_available"] = False    # رجعت مش متاحة: جاهزين لإشعار جديد لو نزلت تاني

    state["status"] = status
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
