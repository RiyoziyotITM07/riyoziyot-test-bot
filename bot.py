
import os
import re
import sqlite3
import logging
from contextlib import closing

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.error import TelegramError
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

logging.basicConfig(level=logging.INFO)

TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
CHANNEL_ID = os.environ["CHANNEL_ID"]
CHANNEL_URL = os.environ["CHANNEL_URL"]
DB_PATH = os.getenv("DB_PATH", "tests.db")


def connect():
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.execute("PRAGMA busy_timeout=30000")
    return db


with closing(connect()) as db:
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""
        CREATE TABLE IF NOT EXISTS tests (
            code TEXT PRIMARY KEY,
            answer TEXT NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS results (
            user_id INTEGER,
            code TEXT,
            score INTEGER,
            total INTEGER,
            answers TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, code)
        )
    """)
    db.commit()


def join_buttons():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "Kanalga a'zo bo'lish",
            url=CHANNEL_URL
        )],
        [InlineKeyboardButton(
            "A'zolikni tekshirish",
            callback_data="check_join"
        )]
    ])


async def is_member(context, user_id):
    if user_id == ADMIN_ID:
        return True

    try:
        member = await context.bot.get_chat_member(
            CHANNEL_ID, user_id
        )
        return (
            member.status in (
                "creator", "administrator", "member"
            )
            or (
                member.status == "restricted"
                and member.is_member
            )
        )
    except TelegramError:
        logging.exception("A'zolik tekshiruvi xatosi")
        return False


async def require_member(update, context):
    if await is_member(
        context, update.effective_user.id
    ):
        return True

    await update.effective_message.reply_text(
        "Test ishlash uchun avval kanalimizga "
        "a'zo bo'ling.",
        reply_markup=join_buttons()
    )
    return False


async def start(update, context):
    if not await require_member(update, context):
        return

    await update.message.reply_text(
        "RIYOZIYOT ITM TEST BOT\n\n"
        "Testlar ro'yxati: /tests\n"
        "Javob yuborish:\n"
        "/test TEST1 ABCDABCD\n\n"
        "Telegram ID: /id"
    )


async def check_join(update, context):
    query = update.callback_query

    if await is_member(context, query.from_user.id):
        await query.answer(
            "A'zolik tasdiqlandi!",
            show_alert=True
        )
        await query.message.reply_text(
            "Endi test topshirishingiz mumkin.\n"
            "Testlar: /tests"
        )
    else:
        await query.answer(
            "Siz hali kanalga a'zo emassiz "
            "yoki a'zolikni tekshirib bo'lmadi.",
            show_alert=True
        )


async def my_id(update, context):
    await update.message.reply_text(
        f"Telegram ID: {update.effective_user.id}"
    )


async def tests(update, context):
    if not await require_member(update, context):
        return

    with closing(connect()) as db:
        rows = db.execute(
            "SELECT code, length(answer) "
            "FROM tests ORDER BY code LIMIT 50"
        ).fetchall()

    if not rows:
        await update.message.reply_text(
            "Hozircha test mavjud emas."
        )
        return

    message = "Mavjud testlar:\n\n"
    for code, count in rows:
        message += f"{code} - {count} ta savol\n"

    await update.message.reply_text(message)


async def add(update, context):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text(
            "Bu buyruq faqat administrator uchun."
        )
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            "Namuna: /add TEST1 ABCDABCD"
        )
        return

    code, answer = [
        x.upper() for x in context.args
    ]

    if (
        not re.fullmatch(
            r"[A-Z0-9_-]{1,30}", code
        )
        or not re.fullmatch(
            r"[ABCD]{1,500}", answer
        )
    ):
        await update.message.reply_text(
            "Test kodi yoki javoblar noto'g'ri."
        )
        return

    with closing(connect()) as db:
        existing = db.execute(
            "SELECT 1 FROM tests WHERE code=?",
            (code,)
        ).fetchone()

        if existing:
            await update.message.reply_text(
                "Bu test mavjud. Uni o'zgartirish "
                "uchun /replace buyrug'ini ishlating."
            )
            return

        db.execute(
            "INSERT INTO tests VALUES (?, ?)",
            (code, answer)
        )
        db.commit()

    await update.message.reply_text(
        f"Test saqlandi!\n"
        f"Test: {code}\n"
        f"Savollar: {len(answer)} ta"
    )


async def replace(update, context):
    if update.effective_user.id != ADMIN_ID:
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            "Namuna: /replace TEST1 ABCDABCD"
        )
        return

    code, answer = [
        x.upper() for x in context.args
    ]

    if (
        not re.fullmatch(
            r"[A-Z0-9_-]{1,30}", code
        )
        or not re.fullmatch(
            r"[ABCD]{1,500}", answer
        )
    ):
        await update.message.reply_text(
            "Kod yoki kalit noto'g'ri."
        )
        return

    with closing(connect()) as db:
        existing = db.execute(
            "SELECT 1 FROM tests WHERE code=?",
            (code,)
        ).fetchone()

        if not existing:
            await update.message.reply_text(
                "Test topilmadi."
            )
            return

        db.execute(
            "UPDATE tests SET answer=? "
            "WHERE code=?",
            (answer, code)
        )
        db.execute(
            "DELETE FROM results WHERE code=?",
            (code,)
        )
        db.commit()

    await update.message.reply_text(
        "Kalit yangilandi. "
        "Eski natijalar tozalandi."
    )


async def test(update, context):
    if not await require_member(update, context):
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            "Namuna: /test TEST1 ABCDABCD"
        )
        return

    code, answers = [
        x.upper() for x in context.args
    ]

    if (
        not re.fullmatch(
            r"[A-Z0-9_-]{1,30}", code
        )
        or not re.fullmatch(
            r"[ABCD]{1,500}", answers
        )
    ):
        await update.message.reply_text(
            "Javoblarni faqat A, B, C, D "
            "harflari bilan yuboring."
        )
        return

    with closing(connect()) as db:
        row = db.execute(
            "SELECT answer FROM tests WHERE code=?",
            (code,)
        ).fetchone()

        if not row:
            await update.message.reply_text(
                "Bunday test mavjud emas."
            )
            return

        key = row[0]

        if len(answers) != len(key):
            await update.message.reply_text(
                f"{len(key)} ta javob kerak.\n"
                f"Siz {len(answers)} ta yubordingiz."
            )
            return

        score = sum(
            a == b for a, b in zip(answers, key)
        )

        mistakes = [
            str(i)
            for i, (a, b) in enumerate(
                zip(answers, key), 1
            )
            if a != b
        ]

        try:
            db.execute(
                "INSERT INTO results "
                "(user_id, code, score, total, answers) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    update.effective_user.id,
                    code,
                    score,
                    len(key),
                    answers
                )
            )
            db.commit()

        except sqlite3.IntegrityError:
            await update.message.reply_text(
                "Siz bu testni avval topshirgansiz."
            )
            return

    await update.message.reply_text(
        f"RIYOZIYOT ITM - NATIJA\n\n"
        f"Test: {code}\n"
        f"To'g'ri: {score}\n"
        f"Noto'g'ri: {len(key) - score}\n"
        f"Foiz: {score / len(key) * 100:.1f}%\n"
        f"Xato savollar: "
        f"{', '.join(mistakes) or 'Yo‘q'}"
    )


async def reyting(update, context):
    if update.effective_user.id != ADMIN_ID:
        return

    if len(context.args) != 1:
        await update.message.reply_text(
            "Namuna: /reyting TEST1"
        )
        return

    code = context.args[0].upper()

    with closing(connect()) as db:
        rows = db.execute(
            "SELECT user_id, score, total "
            "FROM results WHERE code=? "
            "ORDER BY score DESC, created_at ASC "
            "LIMIT 100",
            (code,)
        ).fetchall()

    if not rows:
        await update.message.reply_text(
            "Hozircha natijalar yo'q."
        )
        return

    message = f"{code} reytingi:\n"

    for i, (user_id, score, total) in enumerate(
        rows, 1
    ):
        line = (
            f"{i}. ID {user_id}: "
            f"{score}/{total}\n"
        )
        if len(message) + len(line) > 3900:
            await update.message.reply_text(message)
            message = ""
        message += line

    if message:
        await update.message.reply_text(message)


async def error_handler(update, context):
    logging.error(
        "Bot xatosi: %r", context.error
    )


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", my_id))
    app.add_handler(CommandHandler("tests", tests))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("replace", replace))
    app.add_handler(CommandHandler("test", test))
    app.add_handler(CommandHandler("reyting", reyting))

    app.add_handler(
        CallbackQueryHandler(
            check_join,
            pattern="^check_join$"
        )
    )

    app.add_error_handler(error_handler)
    app.run_polling()


if __name__ == "__main__":
    main()
