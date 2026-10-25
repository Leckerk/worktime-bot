"""Кнопочные меню бота (ReplyKeyboardMarkup + InlineKeyboardMarkup).

Основная идея: все настройки меняются нажатием кнопок, команды остаются
как запасной вариант.

Структура:
  • Главное меню (постоянно висит под полем ввода):
        📊 Отчёт | ⚙️ Настройки | ❓ Помощь
    плюс строки быстрого ввода часов: 0 / 0.5 / 1 / 1.5 / 2 / 3 / 4 / 5 —
    нажал кнопку = записал часы за сегодня (или за день, за который бот ждёт ответ).
  • Меню настроек (inline):
        ⏰ Время напоминания | 📅 День отчёта | 🌍 Дни напоминаний | 📊 Статистика
  • Выбор времени: шаг ±15 минут, пресеты, «✅ Сохранить», «🔄 Сбросить».
  • Выбор дня отчёта: страницы по 10 дней (1–28), «⬅️ Назад».
  • Выбор дней недели: чекбоксы вкл/выкл (хотя бы один день должен остаться).
"""

import calendar
from datetime import date

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

# ---------- главное меню ----------

HOURS_QUICK = ["0", "0.5", "1", "1.5", "2", "3"]
HOURS_QUICK_ROW2 = ["4", "5", "0.25", "0.75", "6", "8"]

MAIN_ROWS = [
    ["📊 Отчёт", "⚙️ Настройки", "❓ Помощь"],
    HOURS_QUICK,
    HOURS_QUICK_ROW2,
]

MAIN_MENU = ReplyKeyboardMarkup(
    MAIN_ROWS, resize_keyboard=True, input_field_placeholder="Число часов или кнопка меню…"
)


def main_menu_reply():
    """kwargs для reply_text с главным меню."""
    return {"reply_markup": MAIN_MENU}


# ---------- меню настроек ----------

def settings_menu(s: dict, days_label: str) -> InlineKeyboardMarkup:
    cur_time = f"{s['reminder_h']:02d}:{s['reminder_m']:02d}"
    kb = [
        [InlineKeyboardButton(f"⏰ Время напоминания: {cur_time}", callback_data="set:time")],
        [InlineKeyboardButton(f"📅 День отчёта: {s['report_day']}-е число", callback_data="set:day")],
        [InlineKeyboardButton(f"🌍 Дни напоминаний: {days_label}", callback_data="set:days")],
        [
            InlineKeyboardButton("📊 Текущий месяц", callback_data="rep:cur"),
            InlineKeyboardButton("📁 Прошлый месяц", callback_data="rep:last"),
        ],
        [InlineKeyboardButton("↩️ В главное меню", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(kb)


SETTINGS_TEXT = (
    "⚙️ <b>Настройки</b>\n\n"
    "Нажимайте на кнопки, чтобы менять параметры:\n"
    "• ⏰ во сколько приходить ежедневное напоминание;\n"
    "• 📅 какого числа присылать статистику за месяц;\n"
    "• 🌍 в какие дни недели нужно напоминание.\n"
)


# ---------- выбор времени ----------

TIME_PRESETS = ["08:00", "17:00", "18:30", "20:00"]


def time_menu(h: int, m: int) -> InlineKeyboardMarkup:
    presets_row = [InlineKeyboardButton(t, callback_data=f"t:set:{t}") for t in TIME_PRESETS]
    kb = [
        [
            InlineKeyboardButton("⏪ −15 мин", callback_data="t:m15"),
            InlineKeyboardButton("➖ 1 ч", callback_data="t:h1"),
            InlineKeyboardButton("➕ 1 ч", callback_data="t:p1"),
            InlineKeyboardButton("⏩ +15 мин", callback_data="t:p15"),
        ],
        presets_row,
        [
            InlineKeyboardButton("✅ Сохранить", callback_data="t:save"),
            InlineKeyboardButton("🔄 Сбросить на 20:00", callback_data="t:reset"),
        ],
        [InlineKeyboardButton("↩️ Назад", callback_data="set:back")],
    ]
    return InlineKeyboardMarkup(kb)


def time_text(h: int, m: int, saved_note: str = "") -> str:
    base = (
        f"⏰ Выберите время ежедневного напоминания.\n\n"
        f"Текущее значение: <b>{h:02d}:{m:02d}</b>\n\n"
        f"Меняйте шагами ±15 мин / ±1 ч или нажмите готовый пресет, "
        f"затем «✅ Сохранить»."
    )
    if saved_note:
        base += f"\n\n{saved_note}"
    return base


def shift_minutes(h: int, m: int, delta: int) -> tuple[int, int]:
    total = (h * 60 + m + delta) % (24 * 60)
    return total // 60, total % 60


# ---------- выбор дня отчёта ----------

DAYS_PER_PAGE = 10


def day_menu(page: int, current: int) -> InlineKeyboardMarkup:
    start = page * DAYS_PER_PAGE + 1
    end = min(start + DAYS_PER_PAGE - 1, 28)
    row = []
    for d in range(start, end + 1):
        label = f"✅ {d}" if d == current else str(d)
        row.append(InlineKeyboardButton(label, callback_data=f"d:{d}"))
    # выравниваем ряд по 5 кнопок
    kb = [row[i : i + 5] for i in range(0, len(row), 5)]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"d:page:{page - 1}"))
    if end < 28:
        nav.append(InlineKeyboardButton("Вперёд ➡️", callback_data=f"d:page:{page + 1}"))
    nav.append(InlineKeyboardButton("↩️ Отмена", callback_data="set:back"))
    kb.append(nav)
    return InlineKeyboardMarkup(kb)


def day_text(current: int) -> str:
    return (
        "📅 Выберите день месяца, когда присылать статистику за прошедший месяц.\n\n"
        f"Сейчас: <b>{current}-е число</b> (в 10:00).\n\n"
        "Доступны дни 1–28, чтобы отчёт приходил в любом месяце."
    )


# ---------- выбор дней недели ----------

WEEK_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEK_RU = {
    "mon": "Пн", "tue": "Вт", "wed": "Ср", "thu": "Чт",
    "fri": "Пт", "sat": "Сб", "sun": "Вс",
}


def days_menu(active: list[str]) -> InlineKeyboardMarkup:
    row = []
    for wd in WEEK_ORDER:
        mark = "✅" if wd in active else "▫️"
        row.append(InlineKeyboardButton(f"{mark} {WEEK_RU[wd]}", callback_data=f"w:{wd}"))
    kb = [
        row[:4],      # Пн–Чт
        row[4:],      # Пт, Сб, Вс
        [
            InlineKeyboardButton("Без воскресенья", callback_data="w:preset:mon-sat"),
            InlineKeyboardButton("Только будни", callback_data="w:preset:mon-fri"),
        ],
        [
            InlineKeyboardButton("✅ Сохранить", callback_data="w:save"),
            InlineKeyboardButton("↩️ Назад", callback_data="set:back"),
        ],
    ]
    return InlineKeyboardMarkup(kb)


def days_text(active: list[str]) -> str:
    labels = ", ".join(WEEK_RU[d] for d in WEEK_ORDER if d in active) or "— ничего не выбрано —"
    return (
        "🌍 Выберите дни недели, в которые приходить с напоминанием "
        "(по умолчанию — кроме воскресенья).\n\n"
        f"Выбрано: <b>{labels}</b>\n\n"
        "Нажмите на день, чтобы включить/выключить, затем «✅ Сохранить». "
        "Хотя бы один день должен быть выбран."
    )


def days_label(active: list[str]) -> str:
    """Короткая подпись для главного экрана настроек, напр. 'Пн–Сб'."""
    if active == ["mon", "tue", "wed", "thu", "fri", "sat"]:
        return "Пн–Сб"
    if active == WEEK_ORDER[:5]:
        return "Пн–Пт"
    if active == WEEK_ORDER:
        return "Все дни"
    return ", ".join(WEEK_RU[d] for d in WEEK_ORDER if d in active) or "—"


# ---------- вспомогательное ----------

def clamp_report_day(day: int, year: int, month: int) -> int:
    """Не нужно, если ограничиваемся 28, но оставляем защиту."""
    return max(1, min(day, calendar.monthrange(year, month)[1]))


def is_hours_button(text: str) -> bool:
    return text in {*HOURS_QUICK, *HOURS_QUICK_ROW2}
