"""Телеграм-бот для учёта сверхурочных часов.

Как это работает:
  • Каждый день (в выбранные дни недели, по умолчанию — кроме воскресенья)
    в настроенное время (по умолчанию 20:00) бот присылает напоминание:
    "Сколько часов сверхурочно сегодня?"
  • Вы отвечаете числом (например, `2` или `1.5`) или нажимаете кнопку с часами
    в главном меню — бот сохраняет запись за этот день.
  • В начале каждого месяца (по умолчанию 1-го числа в 10:00) бот присылает
    статистику за прошедший месяц.
  • Все настройки меняются кнопками: ⚙️ Настройки в главном меню.

Команды (кнопки дублируют их, команды остаются запасным вариантом):
  /start   — регистрация и главное меню
  /menu    — показать главные кнопки
  /settings— меню настроек (кнопками)
  /settime 20:30 — изменить время ежедневного напоминания
  /setday 5      — изменить день месяца для отчёта (1-28)
  /report        — статистика за текущий месяц
  /last          — статистика за прошлый месяц
  /today 2       — вручную записать часы за сегодня
  /set 2026-10-15 3 — записать часы за конкретный день
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
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import menus
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
    days_lbl = menus.days_label(s["remind_days"])
    await update.message.reply_text(
        "👋 Привет! Я бот для учёта рабочего времени.\n\n"
        f"Каждый день ({days_lbl}) в {s['reminder_h']:02d}:{s['reminder_m']:02d} "
        "я буду спрашивать, сколько часов сверхурочных вы работали. "
        "Ответьте числом (например, 2 или 1.5) или нажмите кнопку с часами "
        "в нижнем меню — часы запишутся за сегодня.\n\n"
        f"В отчётный день месяца ({s['report_day']}-е число) пришлю статистику "
        "за прошлый месяц.\n\n"
        "Кнопки под полем ввода:\n"
        "• 📊 Отчёт — статистика за текущий месяц\n"
        "• ⚙️ Настройки — время напоминания, день отчёта, дни недели (всё кнопками)\n"
        "• ❓ Помощь — справка по командам",
        **menus.main_menu_reply(),
    )


async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показывает главные кнопки (если пользователь их скрыл)."""
    await update.message.reply_text("Меню:", **menus.main_menu_reply())


HELP_TEXT = (
    "ℹ️ <b>Как пользоваться</b>\n\n"
    "<b>Кнопками (основной способ):</b>\n"
    "• Кнопки с числами (0, 0.5, 1, 1.5 …) — записать столько часов сверхурочных "
    "за сегодня (или за день, на который бот ждёт ответ после напоминания).\n"
    "• 📊 Отчёт — статистика за текущий месяц.\n"
    "• ⚙️ Настройки — выбор времени напоминания, дня отчёта и дней недели "
    "только кнопками, без команд.\n\n"
    "<b>Команды (необязательно):</b>\n"
    "/settime HH:MM — время напоминания (по умолчанию 20:00)\n"
    "/setday N — день месяца для отчёта (1–28)\n"
    "/report — статистика за текущий месяц\n"
    "/last — статистика за прошлый месяц\n"
    "/today 2 — записать часы за сегодня вручную\n"
    "/set YYYY-MM-DD 3 — записать за конкретный день\n"
    "/menu — показать кнопки главного меню\n"
    "/settings — настройки"
)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML,
                                   **menus.main_menu_reply())


async def cmd_settime(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    storage.upsert_user(chat_id)
    args = ctx.args[0] if ctx.args else ""
    m = TIME_RE.match(args.strip())
    if not m:
        await update.message.reply_text(
            "Формат: /settime 20:30\n\nИли откройте ⚙️ Настройки → ⏰ Время напоминания.",
            **menus.main_menu_reply(),
        )
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
        await update.message.reply_text(
            "Формат: /setday 5 (день месяца 1–28)\n\n"
            "Или откройте ⚙️ Настройки → 📅 День отчёта.",
            **menus.main_menu_reply(),
        )
        return
    if not 1 <= d <= 28:
        await update.message.reply_text("День месяца должен быть от 1 до 28.")
        return
    storage.set_report_day(chat_id, d)
    sched = ctx.bot_data.get("scheduler")
    if sched:
        schedule_user(chat_id, sched)
    await update.message.reply_text(f"📅 Отчёт будет приходить {d}-го числа.")


async def show_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE,
                        edit_mode: bool = False) -> None:
    """Экран настроек с inline-кнопками."""
    chat_id = update.effective_chat.id
    s = storage.get_settings(chat_id)
    if not s:
        await update.message.reply_text("Вы ещё не зарегистрированы. Нажмите /start.")
        return
    markup = menus.settings_menu(s, menus.days_label(s["remind_days"]))
    if edit_mode and update.callback_query:
        await update.callback_query.edit_message_text(
            menus.SETTINGS_TEXT, parse_mode=ParseMode.HTML, reply_markup=markup
        )
    else:
        # сначала обычный ответ, затем прикрепляем главные кнопки под полем ввода
        await update.message.reply_text(
            menus.SETTINGS_TEXT, parse_mode=ParseMode.HTML, reply_markup=markup
        )
        await update.message.reply_text("Меню:", **menus.main_menu_reply())


async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await show_settings(update, ctx)


async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    storage.upsert_user(chat_id)
    if not ctx.args:
        # без аргумента предлагаем быстрые кнопки с часами
        await update.message.reply_text(
            "Нажмите кнопку с числом часов или отправьте число, например: 2",
            reply_markup=menus.MAIN_MENU,
        )
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
    await update.message.reply_text(text, parse_mode=ParseMode.HTML,
                                    **menus.main_menu_reply())


async def cmd_last(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    y, m = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    text = format_report(update.effective_chat.id, y, m)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML,
                                    **menus.main_menu_reply())


# ---------------- сообщения ----------------

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Ответ на напоминание / кнопка быстрого ввода часов / кнопки главного меню."""
    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()

    # --- кнопки главного меню ---
    if text == "⚙️ Настройки":
        storage.upsert_user(chat_id)
        await show_settings(update, ctx)
        return
    if text == "📊 Отчёт":
        await cmd_report(update, ctx)
        return
    if text == "❓ Помощь":
        await cmd_help(update, ctx)
        return

    # --- числа (обычный ответ или кнопка быстрого ввода часов) ---
    hours = parse_hours(text)
    if hours is None:
        await update.message.reply_text(
            "Не понял 🤔 Ответьте числом часов, например: 2 или 1.5\n"
            "Или нажмите кнопку с часами внизу / используйте /today 2."
        )
        return
    storage.upsert_user(chat_id)
    day = storage.pop_pending(chat_id) or storage.today()
    storage.save_entry(chat_id, day, hours)
    note = " (за день напоминания)" if day != storage.today() else ""
    await update.message.reply_text(
        f"✅ Сохранено: {hours:g} ч.{note} за {day}. Спасибо!",
        **menus.main_menu_reply(),
    )


# ---------------- inline-кнопки настроек ----------------

def _reschedule(chat_id: int, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    sched = ctx.bot_data.get("scheduler")
    if sched:
        schedule_user(chat_id, sched)


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data or ""
    chat_id = update.effective_chat.id
    s = storage.get_settings(chat_id)
    if not s:
        await q.answer("Сначала нажмите /start", show_alert=True)
        return

    try:
        # ----- навигация -----
        if data == "menu:main":
            await q.edit_message_text(
                "Главное меню — кнопки под полем ввода 🙂",
                reply_markup=menus.MAIN_MENU,
            )
        elif data in ("set:back",):
            await show_settings(update, ctx, edit_mode=True)

        elif data == "set:time":
            storage.set_menu_state(chat_id, "draft_h", s["reminder_h"])
            storage.set_menu_state(chat_id, "draft_m", s["reminder_m"])
            await q.edit_message_text(
                menus.time_text(s["reminder_h"], s["reminder_m"]),
                parse_mode=ParseMode.HTML, reply_markup=menus.time_menu(s["reminder_h"], s["reminder_m"]),
            )
        elif data.startswith("t:"):
            await _cb_time(update, ctx, data[2:])
        elif data == "set:day":
            page = max(0, (s["report_day"] - 1) // menus.DAYS_PER_PAGE)
            await q.edit_message_text(
                menus.day_text(s["report_day"]),
                parse_mode=ParseMode.HTML, reply_markup=menus.day_menu(page, s["report_day"]),
            )
        elif data.startswith("d:"):
            await _cb_day(update, ctx, data[2:])
        elif data == "set:days":
            storage.set_menu_state(chat_id, "draft_days", ",".join(s["remind_days"]))
            await q.edit_message_text(
                menus.days_text(s["remind_days"]),
                parse_mode=ParseMode.HTML, reply_markup=menus.days_menu(s["remind_days"]),
            )
        elif data.startswith("w:"):
            await _cb_week(update, ctx, data[2:])

        elif data == "rep:cur":
            now = datetime.now()
            await BOT.send_message(chat_id, format_report(chat_id, now.year, now.month),
                                   parse_mode=ParseMode.HTML)
            await q.answer("Отчёт отправлен отдельным сообщением ⬇️")
        elif data == "rep:last":
            now = datetime.now()
            y, m = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
            await BOT.send_message(chat_id, format_report(chat_id, y, m),
                                   parse_mode=ParseMode.HTML)
            await q.answer("Отчёт отправлен отдельным сообщением ⬇️")
        else:
            await q.answer()
    except telegram.error.BadRequest as e:
        # сообщение не изменилось / устарело — просто подтверждаем нажатие
        log.debug("callback BadRequest: %s", e)
        await q.answer()


async def _cb_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE, action: str):
    q = update.callback_query
    chat_id = update.effective_chat.id
    h = int(storage.get_menu_state(chat_id, "draft_h", 20))
    m = int(storage.get_menu_state(chat_id, "draft_m", 0))

    if action.startswith("set:"):
        hh, mm = action[4:].split(":")
        h, m = int(hh), int(mm)
    elif action == "m15":
        h, m = menus.shift_minutes(h, m, -15)
    elif action == "p15":
        h, m = menus.shift_minutes(h, m, +15)
    elif action == "h1":
        h, m = menus.shift_minutes(h, m, -60)
    elif action == "p1":
        h, m = menus.shift_minutes(h, m, +60)
    elif action == "reset":
        h, m = 20, 0
    elif action == "save":
        saved_h = int(storage.get_menu_state(chat_id, "draft_h", h))
        saved_m = int(storage.get_menu_state(chat_id, "draft_m", m))
        storage.set_reminder_time(chat_id, saved_h, saved_m)
        _reschedule(chat_id, ctx)
        storage.clear_menu_state(chat_id, "draft_h")
        storage.clear_menu_state(chat_id, "draft_m")
        await show_settings(update, ctx, edit_mode=True)
        await q.answer(f"Сохранено: напоминание в {saved_h:02d}:{saved_m:02d} ✅")
        return
    else:
        await q.answer()
        return

    storage.set_menu_state(chat_id, "draft_h", h)
    storage.set_menu_state(chat_id, "draft_m", m)
    await q.edit_message_text(
        menus.time_text(h, m), parse_mode=ParseMode.HTML, reply_markup=menus.time_menu(h, m)
    )
    await q.answer()


async def _cb_day(update: Update, ctx: ContextTypes.DEFAULT_TYPE, arg: str):
    q = update.callback_query
    chat_id = update.effective_chat.id
    s = storage.get_settings(chat_id)
    if arg.startswith("page:"):
        page = int(arg[5:])
        await q.edit_message_text(
            menus.day_text(s["report_day"]),
            parse_mode=ParseMode.HTML, reply_markup=menus.day_menu(page, s["report_day"]),
        )
        await q.answer()
        return
    d = int(arg)
    storage.set_report_day(chat_id, d)
    _reschedule(chat_id, ctx)
    await show_settings(update, ctx, edit_mode=True)
    await q.answer(f"Отчёт теперь {d}-го числа ✅")


async def _cb_week(update: Update, ctx: ContextTypes.DEFAULT_TYPE, arg: str):
    q = update.callback_query
    chat_id = update.effective_chat.id
    raw = storage.get_menu_state(chat_id, "draft_days", "")
    active = [d for d in str(raw).split(",") if d]

    if arg.startswith("preset:"):
        spec = arg.split(":", 1)[1]  # 'mon-sat' / 'mon-fri'
        a, b = spec.split("-")
        i, j = menus.WEEK_ORDER.index(a), menus.WEEK_ORDER.index(b)
        active = menus.WEEK_ORDER[i : j + 1]
    elif arg == "save":
        if not active:
            await q.answer("Выберите хотя бы один день! ⚠️", show_alert=True)
            return
        storage.set_reminder_days(chat_id, active)
        _reschedule(chat_id, ctx)
        storage.clear_menu_state(chat_id, "draft_days")
        await show_settings(update, ctx, edit_mode=True)
        await q.answer(f"Сохранено: {menus.days_label(active)} ✅")
        return
    elif arg in menus.WEEK_ORDER:
        if arg in active:
            active.remove(arg)
        else:
            active.append(arg)
    else:
        await q.answer()
        return

    active_sorted = [d for d in menus.WEEK_ORDER if d in active]
    storage.set_menu_state(chat_id, "draft_days", ",".join(active_sorted))
    await q.edit_message_text(
        menus.days_text(active_sorted),
        parse_mode=ParseMode.HTML, reply_markup=menus.days_menu(active_sorted),
    )
    await q.answer()


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

    for job_id in (_reminder_job_id(chat_id), _report_job_id(chat_id)):
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
        day_of_week=",".join(s.get("remind_days") or storage.DEFAULT_REMIND_DAYS),
        timezone=TZ,
    )


def _report_trigger(s: dict) -> CronTrigger:
    return CronTrigger(day=s["report_day"], hour=10, minute=0, timezone=TZ)


async def send_reminder(chat_id: int):
    """В выбранные дни недели в настроенное время: спросить часы за сегодня."""
    s = storage.get_settings(chat_id)
    if not s:
        return
    day = storage.today()
    storage.set_pending(chat_id, day)
    try:
        await BOT.send_message(
            chat_id,
            f"⏰ Напоминание: сколько часов сверхурочных вы работали сегодня "
            f"({datetime.now().strftime('%d.%m')})?\n\n"
            f"Нажмите кнопку с числом часов внизу или ответьте текстом, "
            f"например: 2 или 1.5\n(0 — если сегодня не перерабатывали)",
            reply_markup=menus.MAIN_MENU,
        )
    except telegram.error.TelegramError as e:
        log.warning("Не удалось отправить напоминание %s: %s", chat_id, e)


async def send_month_report(chat_id: int):
    """В настроенный день месяца: статистика за прошедший месяц."""
    now = datetime.now()
    y, m = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    text = format_report(chat_id, y, m)
    try:
        await BOT.send_message(chat_id, text, parse_mode=ParseMode.HTML,
                               reply_markup=menus.MAIN_MENU)
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

    # команды /start и /help — через меню команд Telegram
    commands = [
        ("start", "Начать / главное меню"),
        ("menu", "Показать кнопки"),
        ("settings", "Настройки (кнопками)"),
        ("report", "Статистика за текущий месяц"),
        ("last", "Статистика за прошлый месяц"),
        ("today", "Записать часы за сегодня, напр. /today 2"),
        ("set", "Записать за день, напр. /set 2026-10-15 3"),
        ("settime", "Время напоминания, напр. /settime 20:30"),
        ("setday", "День отчёта 1–28, напр. /setday 5"),
        ("help", "Справка"),
    ]
    app.bot_data["commands"] = [telegram.BotCommand(c, d) for c, d in commands]

    async def post_init(application: Application) -> None:
        await application.set_my_commands(application.bot_data["commands"])

    app.post_init = _on_startup_with_commands(post_init)

    app.add_handler(CommandHandler(["start"], cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler(["help"], cmd_help))
    app.add_handler(CommandHandler("settime", cmd_settime))
    app.add_handler(CommandHandler("setday", cmd_setday))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("set", cmd_set))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("last", cmd_last))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_handler(CallbackQueryHandler(on_callback))

    app.post_shutdown = on_shutdown

    log.info("Бот запущен. Часовой пояс: %s", TZ)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


def _on_startup_with_commands(post_init_fn):
    """Объединяет установку команд и запуск планировщика в одном post_init."""

    async def combined(application: Application) -> None:
        await on_startup(application)
        await post_init_fn(application)

    return combined


if __name__ == "__main__":
    main()
