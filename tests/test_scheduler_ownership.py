from datetime import datetime, timedelta
import unittest
from unittest.mock import patch
from core.scheduler import UltronScheduler


class ScheduledOwnershipTests(unittest.TestCase):
    def test_concurrent_time_and_owner_isolation(self):
        with patch("threading.Thread.start"), patch("time.time", return_value=1000):
            scheduler = UltronScheduler()
            when = datetime.now() + timedelta(hours=1)
            first = scheduler.schedule_message("ana", "fixture", "one", when)
            second = scheduler.schedule_message("rui", "fixture", "two", when)
            self.assertNotEqual(first, second)
            self.assertEqual([x["id"] for x in scheduler.list_scheduled("ana")], [first])
            self.assertFalse(scheduler.cancel_task(second, "ana"))
            self.assertTrue(scheduler.cancel_task(first, "ana"))
            self.assertEqual(scheduler.list_scheduled("ana"), [])
            self.assertEqual(len(scheduler.tasks), 1)
