"""
Verifica che il plugin MurderMysteryTask sia registrato correttamente al
boot Django tramite apps/tasks/apps.py:TasksConfig.ready().

Non testa ancora comportamento funzionale (prompt, intro, report, submission):
in Step 1 il plugin è un wrapper invisibile con solo `key` e `display_name`.
"""

from django.test import SimpleTestCase

from apps.tasks.registry import get_task, all_keys
from apps.tasks.murder_mystery.task import MurderMysteryTask


class MurderMysteryRegistrationTests(SimpleTestCase):
    def test_registered_at_boot(self) -> None:
        task = get_task("murder_mystery")
        self.assertIsInstance(task, MurderMysteryTask)

    def test_key_and_display_name(self) -> None:
        task = get_task("murder_mystery")
        self.assertEqual(task.key, "murder_mystery")
        self.assertEqual(task.display_name, "Murder Mystery")

    def test_listed_in_all_keys(self) -> None:
        self.assertIn("murder_mystery", all_keys())
