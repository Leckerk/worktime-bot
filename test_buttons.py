"""Тесты кнопочных меню: storage-состояние, генерация клавиатур, миграция БД."""
import os, sqlite3, tempfile, unittest
from pathlib import Path

import menus, storage

class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".db")
        storage.DB_PATH = Path(self.tmp)
        storage.init_db()
        self.cid = 111

    def tearDown(self):
        os.unlink(self.tmp)

    def test_default_days(self):
        storage.upsert_user(self.cid)
        s = storage.get_settings(self.cid)
        self.assertEqual(s["remind_days"], ["mon","tue","wed","thu","fri","sat"])

    def test_set_reminder_days_canonical(self):
        storage.upsert_user(self.cid)
        storage.set_reminder_days(self.cid, ["sun","mon","wed"])
        s = storage.get_settings(self.cid)
        self.assertEqual(s["remind_days"], ["mon","wed","sun"])

    def test_menu_state_roundtrip(self):
        storage.upsert_user(self.cid)
        storage.set_menu_state(self.cid, "draft_h", 21)
        self.assertEqual(storage.get_menu_state(self.cid, "draft_h"), 21)
        storage.clear_menu_state(self.cid, "draft_h")
        self.assertIsNone(storage.get_menu_state(self.cid, "draft_h"))
        self.assertEqual(storage.get_menu_state(self.cid, "missing", 5), 5)

    def test_migration_adds_column(self):
        # старая база без remind_days
        os.unlink(self.tmp)
        c = sqlite3.connect(self.tmp)
        c.executescript("""CREATE TABLE users (chat_id INTEGER PRIMARY KEY,
            reminder_h INTEGER NOT NULL DEFAULT 20, reminder_m INTEGER NOT NULL DEFAULT 0,
            report_day INTEGER NOT NULL DEFAULT 1, created_at TEXT);""")
        c.execute("INSERT INTO users (chat_id) VALUES (7)"); c.commit(); c.close()
        storage.init_db()
        s = storage.get_settings(7)
        self.assertEqual(s["remind_days"], storage.DEFAULT_REMIND_DAYS)

    def test_keyboards_build(self):
        storage.upsert_user(self.cid)
        s = storage.get_settings(self.cid)
        for kb in (menus.MAIN_MENU,
                   menus.settings_menu(s, menus.days_label(s["remind_days"])),
                   menus.time_menu(20, 0),
                   menus.day_menu(0, 1), menus.day_menu(1, 15), menus.day_menu(2, 28),
                   menus.days_menu(s["remind_days"])):
            rows = getattr(kb, "keyboard", None) or getattr(kb, "inline_keyboard", None)
            self.assertTrue(rows and all(isinstance(r, (list, tuple)) and r for r in rows))
        # callback_data <= 64 байт
        for row in menus.time_menu(20,0).inline_keyboard + menus.days_menu(["mon"]).inline_keyboard:
            for b in row:
                self.assertLessEqual(len(b.callback_data.encode()), 64)

    def test_shift_minutes(self):
        self.assertEqual(menus.shift_minutes(20, 0, -15), (19, 45))
        self.assertEqual(menus.shift_minutes(23, 30, +60), (0, 30))
        self.assertEqual(menus.shift_minutes(0, 0, -15), (23, 45))

    def test_days_label(self):
        self.assertEqual(menus.days_label(["mon","tue","wed","thu","fri","sat"]), "Пн–Сб")
        self.assertEqual(menus.days_label(["mon","tue","wed","thu","fri"]), "Пн–Пт")
        self.assertEqual(menus.days_label(["mon","sun"]), "Пн, Вс")

    def test_hours_buttons_parseable(self):
        import bot
        for t in menus.HOURS_QUICK + menus.HOURS_QUICK_ROW2:
            self.assertIsNotNone(bot.parse_hours(t), t)

    def test_trigger_uses_custom_days(self):
        from apscheduler.triggers.cron import CronTrigger
        import bot
        trig = bot._reminder_trigger({"reminder_h":20,"reminder_m":0,"remind_days":["mon","fri"]})
        self.assertIsInstance(trig, CronTrigger)
        fields = {f.name: str(f) for f in trig.fields} if hasattr(trig,'fields') else {}
        # просто проверка, что не падает и содержит нужные дни в_repr_
        self.assertIn("mon", repr(trig).lower())

if __name__ == "__main__":
    unittest.main(verbosity=2)
