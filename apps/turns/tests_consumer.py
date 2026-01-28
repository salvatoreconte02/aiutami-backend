from django.test import TestCase
from django.core.cache import cache

from apps.turns.ws_consumer import TurnsConsumer


class TriggerTaskInfrastructureTests(TestCase):
    def setUp(self):
        cache.clear()
        # Clear any existing trigger tasks
        TurnsConsumer._trigger_tasks.clear()

    def tearDown(self):
        cache.clear()
        TurnsConsumer._trigger_tasks.clear()

    def test_trigger_tasks_dict_exists(self):
        """TurnsConsumer should have class-level _trigger_tasks dict."""
        self.assertIsInstance(TurnsConsumer._trigger_tasks, dict)

    def test_get_trigger_lock_returns_lock(self):
        """_get_trigger_lock should return an asyncio.Lock."""
        import asyncio
        lock = TurnsConsumer._get_trigger_lock()
        self.assertIsInstance(lock, asyncio.Lock)

    def test_get_trigger_lock_returns_same_instance(self):
        """_get_trigger_lock should return the same lock instance."""
        lock1 = TurnsConsumer._get_trigger_lock()
        lock2 = TurnsConsumer._get_trigger_lock()
        self.assertIs(lock1, lock2)
