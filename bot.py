"""Телеграм-бот для учёта сверхурочных часов.

Как это работает:
  • Каждый день, кроме воскресенья, в настроенное время (по умолчанию 20:00)
    бот присылает напоминание: "Сколько часов сверхурочно сегодня?"
  • Вы отвечаете числом (например, `2` или `1.5`) — бот сохраняет запись за этот день.
  • В начале каждого месяца (по умолчанию 1-го числа в 10:00) бот присылает
    статистику за прошедший месяц. Также команду /report можно вызвать вручную.

Команды:
  /start   — регистрация и справка
  /settime 20:30 — изменить время ежедневного напоминания
  /setday 5      — изменить день месяца для отчёта (1-28)
  /report        — статистика за текущий месяц
  /last          — статистика за прошлый месяц
  /today 2       — вручную записать часы за сегодня
  /set 2026-10-15 3 — записать часы за конкретный день
  /settings      — показать текущие настройки
  /help          — справка

Запуск:
  export TELEGRAM_BOT_TOKEN="..."
  python bot.py
"""

import logging
import os
import re
from datetime import date, datetime

import telegram
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import storage
from reports import format_report

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
log = logging.getLogger("worktime-bot")

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
# Часовой пояс, в котором живут пользователи (для напоминаний/отчётов).
TZ = os.environ.get("BOT_TZ", "Europe/Moscow")

BOT: "telegram.Bot | None" = None  # инициализируется в main()

TIME_RE = re.compile(r"^(\d{1,2})[:.](\d{2})$")
NUM_RE = re.compile(r"^\d{1,2}([.,]\d{1,2})?$")


def parse_hours(text: str) -> float | None:
    t = text.strip().replace(",", ".")
    # допускаем "2 ч", "1.5 hours" и т.п. — отрезаем всё, начиная с первой буквы
    t = re.split(r"[а-яa-z]", t)[0].strip().rstrip(". ")
    if not NUM_RE.match(t):
        return None
    v = float(t)
    return v if 0 <= v <= 24 else None


# ---------------- команды ----------------

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    storage.upsert_user(chat_id)
    s = storage.get_settings(chat_id)
    sched = ctx.bot_data.get("scheduler")
    if sched:
        schedule_user(chat_id, sched)
    await update.message.reply_text(
        "👋 Привет! Я бот для учёта рабочего времени.\n\n"
        f"Каждый день, кроме воскресенья, в {s['reminder_h']:02d}:{s['reminder_m']:02d} "
        "я буду спрашивать, сколько часов сверхурочных вы работали. "
        "Просто ответьте числом — например, 2 или 1.5.\n\n"
        f"В отчётный день месяца ({s['report_day']}-е число) пришлю статистику за прошлый месяц.\n\n"
        "Команды:\n"
        "/settime HH:MM — время напоминания (по умолчанию 20:00)\n"
        "/setday N — день месяца для отчёта (1–28)\n"
        "/report — статистика за текущий месяц\n"
        "/last — статистика за прошлый месяц\n"
        "/today 2 — записать часы за сегодня вручную\n"
        "/set YYYY-MM-DD 3 — записать за конкретный день\n"
        "/settings — мои настройки\n"
        "/help — справка",
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, ctx)


async def cmd_settime(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    storage.upsert_user(chat_id)
    args = ctx.args[0] if ctx.args else ""
    m = TIME_RE.match(args.strip())
    if not m:
        await update.message.reply_text("Формат: /settime 20:30")
        return
    h, mn = int(m.group(1)), int(m.group(2))
    if not (0 <= h <= 23 and 0 <= mn <= 59):
        await update.message.reply_text("Некорректное время.")
        return
    storage.set_reminder_time(chat_id, h, mn)
    sched = ctx.bot_data.get("scheduler")
    if sched:
        schedule_user(chat_id, sched)
    await update.message.reply_text(f"⏰ Напоминание установлено на {h:02d}:{mn:02d}.")


async def cmd_setday(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    storage.upsert_user(chat_id)
    try:
        d = int(ctx.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Формат: /setday 5 (день месяца 1–28)")
        return
    if not 1 <= d <= 28:
        await update.message.reply_text("День месяца должен быть от 1 до 28.")
        return
    storage.set_report_day(chat_id, d)
    sched = ctx.bot_data.get("scheduler")
    if sched:
        schedule_user(chat_id, sched)
    await update.message.reply_text(f"📅 Отчёт будет приходить {d}-го числа.")


async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = storage.get_settings(update.effective_chat.id)
    if not s:
        await update.message.reply_text("Вы ещё не зарегистрированы. Нажмите /start.")
        return
    await update.message.reply_text(
        f"⏰ Напоминание: ежедневно (кроме вс) в {s['reminder_h']:02d}:{s['reminder_m']:02d}\n"
        f"📅 Отчёт: {s['report_day']}-го числа каждого месяца\n"
        f"🌍 Часовой пояс: {TZ}"
    )


async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    storage.upsert_user(chat_id)
    if not ctx.args:
        await update.message.reply_text("Формат: /today 2")
        return
    hours = parse_hours(ctx.args[0])
    if hours is None:
        await update.message.reply_text("Нужно число часов, например 2 или 1.5")
        return
    day = storage.today()
    storage.save_entry(chat_id, day, hours)
    await update.message.reply_text(f"✅ Записано: {hours:g} ч. за {day}.")


async def cmd_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    storage.upsert_user(chat_id)
    if len(ctx.args) < 2:
        await update.message.reply_text("Формат: /set 2026-10-15 3")
        return
    try:
        d = date.fromisoformat(ctx.args[0])
    except ValueError:
        await update.message.reply_text("Дата в формате YYYY-MM-DD.")
        return
    hours = parse_hours(ctx.args[1])
    if hours is None:
        await update.message.reply_text("Нужно число часов, например 2 или 1.5")
        return
    storage.save_entry(chat_id, d.isoformat(), hours)
    await update.message.reply_text(f"✅ Записано: {hours:g} ч. за {d.isoformat()}.")


async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    text = format_report(update.effective_chat.id, now.year, now.month)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_last(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    y, m = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    text = format_report(update.effective_chat.id, y, m)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ---------------- сообщения ----------------

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Ответ на напоминание: просто число — сохраняем за «pending» днём."""
    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()
    hours = parse_hours(text)
    if hours is None:
        await update.message.reply_text(
            "Не понял 🤔 Ответьте числом часов, например: 2 или 1.5\n"
            "Или используйте /today 2."
        )
        return
    storage.upsert_user(chat_id)
    day = storage.pop_pending(chat_id) or storage.today()
    storage.save_entry(chat_id, day, hours)
    await update.message.reply_text(f"✅ Сохранено: {hours:g} ч. за {day}. Спасибо!")


# ---------------- планировщик ----------------

def _reminder_job_id(chat_id: int) -> str:
    return f"reminder-{chat_id}"


def _report_job_id(chat_id: int) -> str:
    return f"report-{chat_id}"


def schedule_user(chat_id: int, sched: AsyncIOScheduler) -> None:
    """Создаёт/обновляет задачи напоминания и месячного отчёта для пользователя."""
    s = storage.get_settings(chat_id)
    if not s:
        return

    for job_id, trigger in (
        (
            _reminder_job_id(chat_id),
            CronTrigger(
                hour=s["reminder_h"], minute=s["reminder_m"],
                day_of_week="mon-sat",  # без воскресенья
                timezone=TZ,
            ),
        ),
        (
            _report_job_id(chat_id),
            CronTrigger(
                day=s["report_day"], hour=10, minute=0,
                timezone=TZ,
            ),
        ),
    ):
        if sched.get_job(job_id):
            sched.remove_job(job_id)

    sched.add_job(
        send_reminder, trigger=_reminder_trigger(s), args=[chat_id],
        id=_reminder_job_id(chat_id), replace_existing=True,
    )
    sched.add_job(
        send_month_report, trigger=_report_trigger(s), args=[chat_id],
        id=_report_job_id(chat_id), replace_existing=True,
    )


def _reminder_trigger(s: dict) -> CronTrigger:
    return CronTrigger(
        hour=s["reminder_h"], minute=s["reminder_m"],
        day_of_week="mon-sat", timezone=TZ,
    )


def _report_trigger(s: dict) -> CronTrigger:
    return CronTrigger(day=s["report_day"], hour=10, minute=0, timezone=TZ)


async def send_reminder(chat_id: int):
    """Каждый день (кроме вс) в настроенное время: спросить часы за сегодня."""
    s = storage.get_settings(chat_id)
    if not s:
        return
    day = storage.today()
    storage.set_pending(chat_id, day)
    try:
        await BOT.send_message(
            chat_id,
            f"⏰ Напоминание: сколько часов сверхурочных вы работали сегодня "
            f"({datetime.now().strftime('%d.%m')})?\n"
            f"Ответьте числом, например: 2 или 1.5\n"
            f"(0 — если сегодня не перерабатывали)",
        )
    except telegram.error.TelegramError as e:
        log.warning("Не удалось отправить напоминание %s: %s", chat_id, e)


async def send_month_report(chat_id: int):
    """В настроенный день месяца: статистика за прошедший месяц."""
    now = datetime.now()
    y, m = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    text = format_report(chat_id, y, m)
    try:
        await BOT.send_message(chat_id, text, parse_mode=ParseMode.HTML)
    except telegram.error.TelegramError as e:
        log.warning("Не удалось отправить отчёт %s: %s", chat_id, e)


# ---------------- запуск ----------------

async def on_startup(app: Application):
    sched = AsyncIOScheduler(timezone=TZ)
    app.bot_data["scheduler"] = sched
    for row in storage.all_users():
        schedule_user(row["chat_id"], sched)
    sched.start()
    log.info("Планировщик запущен, пользователей: %s", len(storage.all_users()))


async def on_shutdown(app: Application):
    sched = app.bot_data.get("scheduler")
    if sched:
        sched.shutdown(wait=False)


def main() -> None:
    global BOT
    if not TOKEN:
        raise SystemExit(
            "Укажите токен бота: export TELEGRAM_BOT_TOKEN='123:ABC...'"
        )
    storage.init_db()

    app = Application.builder().token(TOKEN).build()
    BOT = app.bot

    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler("settime", cmd_settime))
    app.add_handler(CommandHandler("setday", cmd_setday))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("set", cmd_set))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("last", cmd_last))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    app.post_init = on_startup
    app.post_shutdown = on_shutdown

    log.info("Бот запущен. Часовой пояс: %s", TZ)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
