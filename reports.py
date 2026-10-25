"""Генерация текстов отчётов."""

import calendar
from datetime import date

from storage import month_entries

MONTHS = [
    "", "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
]


def format_report(chat_id: int, year: int, month: int) -> str:
    """Статистика сверхурочных за месяц."""
    rows = month_entries(chat_id, year, month)
    title = f"📊 Сверхурочные за {MONTHS[month]} {year} г.\n"
    if not rows:
        return title + "\nЗаписей за этот месяц нет."

    lines = []
    total = 0.0
    for r in rows:
        d = date.fromisoformat(r["day"])
        wd = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"][d.weekday()]
        h = r["hours"]
        total += h
        h_str = f"{h:g}"
        lines.append(f"• {d.day:02d}.{month:02d} ({wd}): {h_str} ч.")

    days = len(rows)
    avg = total / days if days else 0
    last_day = calendar.monthrange(year, month)[1]

    body = "\n".join(lines)
    return (
        f"{title}\n{body}\n\n"
        f"Итого: <b>{total:g} ч.</b> за {days} дн.\n"
        f"Среднее в день: {avg:.1f} ч.\n"
        f"Всего рабочих дней в месяце (без воскресенья): "
        f"{sum(1 for i in range(1, last_day + 1) if date(year, month, i).weekday() != 6)}\n"
    )
