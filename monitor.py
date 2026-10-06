# -*- coding: utf-8 -*-
"""
بوت مراقبة تذاكر الأهلي على تذكرتي -> إشعار Telegram
وظيفته: يراقب ويبعت إشعار بس.
مفيهوش حجز تلقائي ولا تجاوز CAPTCHA.

الإعدادات كلها بتيجي من Environment Variables
(على GitHub: Secrets / Variables).
"""

import json
import os
import pathlib
import sys
import datetime

import requests
from playwright.sync_api import sync_playwright


# ============================================================
# الإعدادات
# ============================================================

MATCH_URL = os.environ.get(
    "MATCH_URL",
    "ضع_رابط_المباراة_هنا"
)

MATCH_NAME = os.environ.get(
    "MATCH_NAME",
    ""
)

TG_TOKEN = os.environ.get(
    "TG_BOT_TOKEN",
    ""
)

TG_CHAT_ID = os.environ.get(
    "TG_CHAT_ID",
    ""
)

BOOK_SELECTOR = os.environ.get(
    "BOOK_SELECTOR",
    ""
)

# Debug يشتغل إما من Environment Variable
# أو من الأمر: python monitor.py --debug
DEBUG = (
    os.environ.get("DEBUG", "0") == "1"
    or "--debug" in sys.argv
)


STATE_FILE = pathlib.Path(__file__).parent / "state.json"

DEBUG_DIR = pathlib.Path(__file__).parent / "debug"


# ============================================================
# كلمات الكشف
# ============================================================

SOLD_OUT_WORDS = [
    "sold out",
    "soldout",
    "نفدت",
    "نفذت",
    "اكتمل العدد",
    "نفد"
]

NOT_STARTED_WORDS = [
    "لم يبدأ",
    "لم يبدا",
    "قريبا",
    "قريباً",
    "coming soon",
    "not started",
    "will open",
    "يبدأ الحجز",
    "سيبدأ"
]

UNAVAILABLE_WORDS = [
    "غير متاح",
    "غير متاحة",
    "not available",
    "unavailable",
    "closed",
    "مغلق"
]

BOOK_WORDS = [
    "احجز",
    "حجز التذاكر",
    "حجز تذكرة",
    "شراء",
    "book now",
    "buy ticket",
    "buy tickets",
    "book ticket",
    "book"
]

BLOCK_WORDS = [
    "captcha",
    "verify you are human",
    "access denied",
    "are you a robot"
]


# ============================================================
# قراءة وحفظ الحالة
# ============================================================

def load_state() -> dict:
    try:
        return json.loads(
            STATE_FILE.read_text(
                encoding="utf-8"
            )
        )

    except Exception:
        return {
            "status": "UNKNOWN",
            "notified_available": False,
            "last_checked_date": ""
        }


def save_state(state: dict) -> None:

    state["last_checked_date"] = (
        datetime.date.today().isoformat()
    )

    STATE_FILE.write_text(
        json.dumps(
            state,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


# ============================================================
# البحث عن كلمات
# ============================================================

def contains_any(text: str, words) -> bool:

    t = text.lower()

    return any(
        word.lower() in t
        for word in words
    )


# ============================================================
# فتح صفحة تذكرتي
# ============================================================

def fetch_page():

    """
    يفتح الصفحة باستخدام Playwright
    لأن الموقع يعتمد على JavaScript.

    يرجع:

    text
    title
    h1
    buttons
    selector_hit
    """

    print("========================================")
    print("بدء فحص صفحة تذكرتي")
    print("========================================")

    print(f"رابط المباراة: {MATCH_URL}")

    if DEBUG:
        print("DEBUG MODE: ON")

    else:
        print("DEBUG MODE: OFF")

    print("فتح المتصفح...")

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        ctx = browser.new_context(
            locale="ar-EG",
            viewport={
                "width": 1280,
                "height": 900
            }
        )

        page = ctx.new_page()

        print("فتح صفحة المباراة...")

        page.goto(
            MATCH_URL,
            wait_until="networkidle",
            timeout=60000
        )

        print("الصفحة فتحت بنجاح.")

        print("انتظار JavaScript...")

        page.wait_for_timeout(3000)

        # ----------------------------------------------------
        # نص الصفحة
        # ----------------------------------------------------

        text = page.inner_text("body")

        print(
            f"حجم نص الصفحة: {len(text)} حرف"
        )

        # ----------------------------------------------------
        # عنوان الصفحة
        # ----------------------------------------------------

        title = page.title()

        print(
            f"عنوان الصفحة: {title}"
        )

        # ----------------------------------------------------
        # H1
        # ----------------------------------------------------

        h1 = ""

        try:

            h1 = page.locator(
                "h1"
            ).first.inner_text(
                timeout=2000
            )

        except Exception:

            pass

        print(
            f"H1: {h1}"
        )

        # ----------------------------------------------------
        # الأزرار والروابط
        # ----------------------------------------------------

        buttons = page.evaluate(
            """
            () => [...document.querySelectorAll(
                'a, button, [role=button]'
            )]
            .filter(
                e => !e.closest(
                    'header, nav, footer'
                )
            )
            .map(
                e => ({
                    text: (
                        e.innerText ||
                        e.getAttribute('aria-label') ||
                        ''
                    ).trim(),

                    disabled:
                        e.disabled === true ||
                        e.getAttribute(
                            'aria-disabled'
                        ) === 'true' ||
                        e.classList.contains(
                            'disabled'
                        ),

                    href:
                        e.getAttribute('href') ||
                        ''
                })
            )
            .filter(
                b =>
                    b.text &&
                    b.text.length < 60
            )
            """
        )

        print(
            f"عدد الأزرار والروابط المكتشفة: {len(buttons)}"
        )

        # ----------------------------------------------------
        # طباعة الأزرار في Debug
        # ----------------------------------------------------

        if DEBUG:

            print("")
            print("========== BUTTONS ==========")

            for button in buttons:

                print(
                    f"TEXT: {button['text']}"
                )

                print(
                    f"DISABLED: {button['disabled']}"
                )

                print(
                    f"HREF: {button['href']}"
                )

                print("-----------------------------")

        # ----------------------------------------------------
        # BOOK_SELECTOR
        # ----------------------------------------------------

        selector_hit = False

        if BOOK_SELECTOR:

            print(
                f"فحص BOOK_SELECTOR: {BOOK_SELECTOR}"
            )

            try:

                el = page.locator(
                    BOOK_SELECTOR
                ).first

                selector_hit = (
                    el.count() > 0
                    and el.is_enabled()
                )

            except Exception:

                selector_hit = False

        # ----------------------------------------------------
        # حفظ ملفات Debug
        # ----------------------------------------------------

        if DEBUG:

            print("")
            print(
                "حفظ ملفات Debug..."
            )

            DEBUG_DIR.mkdir(
                exist_ok=True
            )

            # نص الصفحة
            (
                DEBUG_DIR /
                "page_text.txt"
            ).write_text(
                text,
                encoding="utf-8"
            )

            # الأزرار
            (
                DEBUG_DIR /
                "buttons.json"
            ).write_text(
                json.dumps(
                    buttons,
                    ensure_ascii=False,
                    indent=2
                ),
                encoding="utf-8"
            )

            # Screenshot
            page.screenshot(
                path=str(
                    DEBUG_DIR /
                    "screenshot.png"
                ),
                full_page=True
            )

            print(
                "تم حفظ ملفات Debug."
            )

        browser.close()

    print("تم إغلاق المتصفح.")

    return (
        text,
        title,
        h1,
        buttons,
        selector_hit
    )


# ============================================================
# تحديد حالة التذاكر
# ============================================================

def detect_status(
    text,
    buttons,
    selector_hit
) -> str:

    """
    يرجع واحدة من:

    AVAILABLE
    SOLD_OUT
    NOT_STARTED
    UNAVAILABLE
    UNKNOWN
    """

    print("")
    print("========================================")
    print("تحليل حالة التذاكر")
    print("========================================")

    # --------------------------------------------------------
    # CAPTCHA / حماية
    # --------------------------------------------------------

    if contains_any(
        text,
        BLOCK_WORDS
    ):

        print(
            "⚠️ تم اكتشاف CAPTCHA أو حماية."
        )

        return "UNKNOWN"

    # --------------------------------------------------------
    # صفحة فارغة
    # --------------------------------------------------------

    if len(text.strip()) < 50:

        print(
            "⚠️ نص الصفحة قليل جدًا."
        )

        return "UNKNOWN"

    # --------------------------------------------------------
    # SOLD OUT
    # --------------------------------------------------------

    if contains_any(
        text,
        SOLD_OUT_WORDS
    ):

        print(
            "❌ التذاكر نفدت."
        )

        return "SOLD_OUT"

    # --------------------------------------------------------
    # NOT STARTED
    # --------------------------------------------------------

    if contains_any(
        text,
        NOT_STARTED_WORDS
    ):

        print(
            "⏳ الحجز لم يبدأ."
        )

        return "NOT_STARTED"

    # --------------------------------------------------------
    # زر الحجز
    # --------------------------------------------------------

    book_button = any(
        (
            not button["disabled"]
            and contains_any(
                button["text"],
                BOOK_WORDS
            )
        )
        for button in buttons
    )

    if selector_hit:

        print(
            "🎟️ تم العثور على BOOK_SELECTOR."
        )

        return "AVAILABLE"

    if book_button:

        print(
            "🎟️ تم العثور على زر حجز متاح."
        )

        return "AVAILABLE"

    # --------------------------------------------------------
    # UNAVAILABLE
    # --------------------------------------------------------

    if contains_any(
        text,
        UNAVAILABLE_WORDS
    ):

        print(
            "❌ التذاكر غير متاحة."
        )

        return "UNAVAILABLE"

    # --------------------------------------------------------
    # Default
    # --------------------------------------------------------

    print(
        "❌ لم يتم العثور على زر حجز."
    )

    return "UNAVAILABLE"


# ============================================================
# إرسال Telegram
# ============================================================

def send_telegram(
    match_name: str
) -> None:

    missing = [
        key
        for key, value in {
            "TG_BOT_TOKEN": TG_TOKEN,
            "TG_CHAT_ID": TG_CHAT_ID
        }.items()
        if not value
    ]

    if missing:

        raise RuntimeError(
            "ناقص إعدادات: "
            + ", ".join(missing)
        )

    message = (
        "🔔 تذاكر الأهلي أصبحت متاحة!\n\n"
        f"🏟️ المباراة: {match_name}\n"
        "🎟️ الحالة: متاحة للحجز\n"
        "🔗 رابط الحجز:\n"
        f"{MATCH_URL}\n\n"
        "⚡ ادخل واحجز بسرعة."
    )

    response = requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={
            "chat_id": TG_CHAT_ID,
            "text": message
        },
        timeout=30
    )

    if (
        response.status_code >= 300
        or not response.json().get("ok")
    ):

        raise RuntimeError(
            f"Telegram رجّع خطأ "
            f"{response.status_code}: "
            f"{response.text}"
        )

    print(
        "تم إرسال رسالة Telegram ✅"
    )


# ============================================================
# Main
# ============================================================

def main() -> int:

    print("")
    print("========================================")
    print("Tazkarti Telegram Monitor")
    print("========================================")

    # --------------------------------------------------------
    # Test Telegram
    # --------------------------------------------------------

    test_mode = "--test" in sys.argv

    if test_mode:

        print(
            "تشغيل Test Telegram..."
        )

        send_telegram(
            MATCH_NAME
            or
            "مباراة تجريبية - الأهلي"
        )

        return 0

    # --------------------------------------------------------
    # التأكد من MATCH_URL
    # --------------------------------------------------------

    if (
        not MATCH_URL
        or
        "ضع_رابط" in MATCH_URL
    ):

        print(
            "❌ لازم تحط MATCH_URL"
        )

        return 1

    # --------------------------------------------------------
    # قراءة الحالة السابقة
    # --------------------------------------------------------

    state = load_state()

    print(
        f"الحالة المحفوظة سابقًا: "
        f"{state.get('status')}"
    )

    # --------------------------------------------------------
    # فحص الصفحة
    # --------------------------------------------------------

    try:

        (
            text,
            title,
            h1,
            buttons,
            selector_hit
        ) = fetch_page()

    except Exception as error:

        print(
            "❌ فشل فتح الصفحة:"
        )

        print(error)

        print(
            "هنحاول في التشغيل القادم."
        )

        save_state(state)

        return 0

    # --------------------------------------------------------
    # اكتشاف الحالة
    # --------------------------------------------------------

    status = detect_status(
        text,
        buttons,
        selector_hit
    )

    # --------------------------------------------------------
    # اسم المباراة
    # --------------------------------------------------------

    match_name = (
        MATCH_NAME
        or h1
        or title
        or "مباراة الأهلي"
    )

    print("")
    print("========================================")
    print("النتيجة النهائية")
    print("========================================")

    print(
        f"الحالة المكتشفة: {status}"
    )

    print(
        f"آخر حالة محفوظة: "
        f"{state.get('status')}"
    )

    print(
        f"المباراة: {match_name}"
    )

    # --------------------------------------------------------
    # UNKNOWN
    # --------------------------------------------------------

    if status == "UNKNOWN":

        print(
            "⚠️ الحالة UNKNOWN."
        )

        print(
            "لن يتم إرسال أي إشعار."
        )

        save_state(state)

        return 0

    # --------------------------------------------------------
    # AVAILABLE
    # --------------------------------------------------------

    if status == "AVAILABLE":

        if not state.get(
            "notified_available"
        ):

            print(
                "🎉 التذاكر متاحة!"
            )

            print(
                "إرسال Telegram..."
            )

            send_telegram(
                match_name
            )

            state[
                "notified_available"
            ] = True

        else:

            print(
                "تم إرسال إشعار قبل كده "
                "لنفس الحالة."
            )

            print(
                "لن يتم إرسال إشعار مكرر."
            )

    # --------------------------------------------------------
    # Not Available
    # --------------------------------------------------------

    else:

        state[
            "notified_available"
        ] = False

        print(
            "التذاكر ليست متاحة حاليًا."
        )

    # --------------------------------------------------------
    # حفظ الحالة
    # --------------------------------------------------------

    state["status"] = status

    save_state(state)

    print("")
    print(
        "تم حفظ الحالة بنجاح ✅"
    )

    return 0


# ============================================================
# تشغيل البرنامج
# ============================================================

if __name__ == "__main__":

    sys.exit(
        main()
    )
