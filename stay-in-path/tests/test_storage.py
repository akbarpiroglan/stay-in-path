import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from storage import Store


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name) / 'test.db')

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_yesno_and_timed_habits(self):
        self.store.add_habit('Read', 'yesno')
        self.store.add_habit('Coding', 'time', 120)
        read, coding = self.store.habits()
        self.store.set_log(read['id'], 1)
        self.store.set_log(coding['id'], 60)
        self.assertEqual(self.store.log_value(read['id']), 1)
        self.assertEqual(self.store.log_value(coding['id']), 60)
        self.assertAlmostEqual(self.store.calendar(1)[date.today().isoformat()], 0.75)

    def test_focus_records_seconds_and_increments_minutes(self):
        self.store.add_habit('Coding', 'time', 60)
        hid = self.store.habits()[0]['id']
        self.store.add_focus(hid, 90)
        self.store.add_focus(hid, 30)
        self.assertAlmostEqual(self.store.log_value(hid), 2.0)
        self.assertEqual(self.store.db.execute('SELECT SUM(seconds) FROM focus_sessions').fetchone()[0], 120)

    def test_streak_yesterday_counts_until_end_of_today(self):
        self.store.add_habit('Walk', 'yesno')
        hid = self.store.habits()[0]['id']
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        self.store.db.execute('UPDATE habits SET created_on=? WHERE id=?',(yesterday,hid))
        self.store.db.commit()
        self.store.set_log(hid, 1, yesterday)
        self.assertEqual(self.store.streaks(hid),(1,1))
        self.store.set_log(hid, 1)
        self.assertEqual(self.store.streaks(hid),(2,2))

    def test_archive_does_not_erase_logs(self):
        self.store.add_habit('Study', 'yesno')
        hid = self.store.habits()[0]['id']
        self.store.set_log(hid, 1)
        self.store.delete_habit(hid)
        self.assertEqual(self.store.habits(), [])
        self.assertEqual(self.store.log_value(hid), 1)

    def test_restore_and_permanent_delete(self):
        self.store.add_habit('Study', 'yesno')
        hid = self.store.habits()[0]['id']
        self.store.set_log(hid, 1)
        self.store.delete_habit(hid)
        self.assertEqual([h['id'] for h in self.store.archived_habits()], [hid])
        self.store.restore_habit(hid)
        self.assertEqual([h['id'] for h in self.store.habits()], [hid])
        self.assertEqual(self.store.archived_habits(), [])
        self.store.delete_habit_permanently(hid)
        self.assertEqual(self.store.habits(), [])
        self.assertEqual(self.store.archived_habits(), [])
        self.assertEqual(self.store.log_value(hid), 0.0)

    def test_update_habit(self):
        self.store.add_habit('Code', 'time', 30)
        hid = self.store.habits()[0]['id']
        self.store.update_habit(hid, 'Deep work', 45)
        habit = self.store.habits()[0]
        self.assertEqual((habit['name'], habit['goal_minutes']), ('Deep work', 45))
        with self.assertRaises(ValueError):
            self.store.update_habit(hid, '   ', 45)
        with self.assertRaises(ValueError):
            self.store.update_habit(9999, 'Ghost', 10)

    def test_focus_state_roundtrip(self):
        self.store.add_habit('Code', 'time', 60)
        hid = self.store.habits()[0]['id']
        self.assertIsNone(self.store.focus_state())
        self.store.save_focus_state(hid, 125.5, False, '2026-10-26T10:00:00')
        state = self.store.focus_state()
        self.assertEqual(state['habit_id'], hid)
        self.assertAlmostEqual(state['running_seconds'], 125.5)
        self.assertFalse(state['paused'])
        self.assertEqual(state['segment_start'], '2026-10-26T10:00:00')
        self.store.clear_focus_state()
        self.assertIsNone(self.store.focus_state())

    def test_mission_validation(self):
        self.store.save_mission('Publish MVP', 2, 5, '2026-12-15')
        self.assertEqual(self.store.get_mission()['completed'], 2)
        with self.assertRaises(ValueError):
            self.store.save_mission('Publish MVP', 6, 5, '')

    def test_weekly_review(self):
        self.store.add_habit('Study', 'yesno')
        hid = self.store.habits()[0]['id']
        self.store.set_log(hid, 1)
        info = self.store.weekly_review()
        self.assertEqual(info['end'], date.today().isoformat())
        self.assertTrue(0 <= info['completion'] <= 100)
        self.assertEqual(info['habit_rates'][0][0],'Study')

    def test_weekly_review_previous_week_window(self):
        self.store.add_habit('Study', 'yesno')
        hid = self.store.habits()[0]['id']
        today = date.today()
        prev_start = today - timedelta(days=today.weekday()) - timedelta(days=7)
        self.store.db.execute('UPDATE habits SET created_on=? WHERE id=?',
                              ((prev_start - timedelta(days=30)).isoformat(), hid))
        self.store.db.commit()
        for i in range(7):
            self.store.set_log(hid, 1, (prev_start + timedelta(days=i)).isoformat())
        info = self.store.weekly_review(today)
        self.assertEqual(info['previous_completion'], 100)
        self.assertEqual(info['completion'], 0)


if __name__=='__main__':
    unittest.main()
