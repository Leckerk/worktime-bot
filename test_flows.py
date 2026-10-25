"""Интеграционный прогон обработчиков с мок-объектами Update/CallbackQuery."""
import asyncio, tempfile, types
from pathlib import Path
import storage, bot

storage.DB_PATH = Path(tempfile.mktemp(suffix=".db"))
storage.init_db()
CID = 42
storage.upsert_user(CID)

sent = []

class FakeMsg:
    def __init__(self, text): self.text = text
    async def reply_text(self, t, **kw): sent.append(("reply", t))

class FakeQ:
    def __init__(self, data): self.data = data; self.edited = None
    async def edit_message_text(self, t, **kw): self.edited = (t, kw); sent.append(("edit", t))
    async def answer(self, *a, **k): sent.append(("answer", a, k))

def upd_msg(text):
    u = types.SimpleNamespace()
    u.effective_chat = types.SimpleNamespace(id=CID)
    u.message = FakeMsg(text)
    u.callback_query = None
    return u

def upd_cb(data):
    u = types.SimpleNamespace()
    u.effective_chat = types.SimpleNamespace(id=CID)
    u.message = None
    u.callback_query = FakeQ(data)
    return u


class FakeBot:
    async def send_message(self, chat_id, text, **kw): sent.append(("send", text))

bot.BOT = FakeBot()

ctx = types.SimpleNamespace(bot_data={}, args=[])

async def main():
    # главное меню кнопками
    await bot.on_message(upd_msg("⚙️ Настройки"), ctx)
    await bot.on_message(upd_msg("❓ Помощь"), ctx)
    # часы кнопкой и текстом
    storage.set_pending(CID, "2026-10-25")
    await bot.on_message(upd_msg("1.5"), ctx)
    assert storage.month_entries(CID, 2026, 10)[0]["hours"] == 1.5
    await bot.on_message(upd_msg("📊 Отчёт"), ctx)

    # inline: время +15 -> сохранить
    await bot.on_callback(upd_cb("set:time"), ctx)
    await bot.on_callback(upd_cb("t:p15"), ctx)
    await bot.on_callback(upd_cb("t:save"), ctx)
    s = storage.get_settings(CID)
    assert (s["reminder_h"], s["reminder_m"]) == (20, 15), s
    # пресет времени
    await bot.on_callback(upd_cb("t:set:08:00"), ctx)
    await bot.on_callback(upd_cb("t:save"), ctx)
    assert storage.get_settings(CID)["reminder_h"] == 8

    # день отчёта: страница 2, выбрать 15
    await bot.on_callback(upd_cb("set:day"), ctx)
    await bot.on_callback(upd_cb("d:page:1"), ctx)
    await bot.on_callback(upd_cb("d:15"), ctx)
    assert storage.get_settings(CID)["report_day"] == 15

    # дни недели: снять sat, добавить sun, сохранить
    await bot.on_callback(upd_cb("set:days"), ctx)
    await bot.on_callback(upd_cb("w:sat"), ctx)
    await bot.on_callback(upd_cb("w:sun"), ctx)
    await bot.on_callback(upd_cb("w:save"), ctx)
    assert storage.get_settings(CID)["remind_days"] == ["mon","tue","wed","thu","fri","sun"]
    # пресет только будни
    await bot.on_callback(upd_cb("w:preset:mon-fri"), ctx)
    await bot.on_callback(upd_cb("w:save"), ctx)
    assert storage.get_settings(CID)["remind_days"] == ["mon","tue","wed","thu","fri"]
    # пустой набор запрещён
    for d in ["mon","tue","wed","thu","fri"]:
        await bot.on_callback(upd_cb(f"w:{d}"), ctx)
    await bot.on_callback(upd_cb("w:save"), ctx)
    assert storage.get_settings(CID)["remind_days"] == ["mon","tue","wed","thu","fri"]
    # отчёты из настроек
    await bot.on_callback(upd_cb("rep:cur"), ctx)
    await bot.on_callback(upd_cb("rep:last"), ctx)
    await bot.on_callback(upd_cb("menu:main"), ctx)
    print("ALL FLOWS OK, replies:", len(sent))

asyncio.run(main())
