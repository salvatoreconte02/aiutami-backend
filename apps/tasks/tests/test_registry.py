"""
Test del registry dei task plugin.

Verifica il contratto di base:
  - register() aggiunge un task
  - get_task() lo ritrova
  - get_task() su chiave ignota solleva TaskNotFound
  - register() su chiave già presente solleva TaskAlreadyRegistered
  - all_keys() e task_choices() riflettono lo stato del registry

Usa un task "dummy" definito inline per evitare dipendenze da plugin concreti
(che in Step 0 non esistono ancora).
"""

from django.test import SimpleTestCase

from apps.tasks.base import TaskDefinition
from apps.tasks.registry import (
    TaskAlreadyRegistered,
    TaskNotFound,
    _reset_for_tests,
    _restore_for_tests,
    _snapshot_for_tests,
    all_keys,
    get_task,
    register,
    task_choices,
)


class _DummyTask(TaskDefinition):
    def __init__(self, key: str, display_name: str) -> None:
        self._key = key
        self._display_name = display_name

    @property
    def key(self) -> str:
        return self._key

    @property
    def display_name(self) -> str:
        return self._display_name


class RegistryTests(SimpleTestCase):
    def setUp(self) -> None:
        # Salva lo stato reale del registry (contiene i task registrati da
        # TasksConfig.ready() al boot Django) e parte pulito per isolamento.
        self._snapshot = _snapshot_for_tests()
        _reset_for_tests()

    def tearDown(self) -> None:
        # Ripristina il registry allo stato reale pre-test, così i task
        # registrati da TasksConfig.ready() restano disponibili per gli
        # altri test della suite.
        _restore_for_tests(self._snapshot)

    def test_register_and_get(self) -> None:
        task = _DummyTask("foo", "Foo Task")
        register(task)
        self.assertIs(get_task("foo"), task)

    def test_get_unknown_raises(self) -> None:
        with self.assertRaises(TaskNotFound):
            get_task("does_not_exist")

    def test_register_duplicate_raises(self) -> None:
        register(_DummyTask("foo", "Foo"))
        with self.assertRaises(TaskAlreadyRegistered):
            register(_DummyTask("foo", "Foo Bis"))

    def test_all_keys_sorted(self) -> None:
        register(_DummyTask("bravo", "B"))
        register(_DummyTask("alpha", "A"))
        register(_DummyTask("charlie", "C"))
        self.assertEqual(all_keys(), ["alpha", "bravo", "charlie"])

    def test_task_choices_shape(self) -> None:
        register(_DummyTask("alpha", "Alpha Task"))
        register(_DummyTask("bravo", "Bravo Task"))
        choices = task_choices()
        self.assertEqual(
            choices,
            [("alpha", "Alpha Task"), ("bravo", "Bravo Task")],
        )

    def test_abstract_cannot_instantiate(self) -> None:
        # TaskDefinition è astratta: istanziarla direttamente deve fallire.
        with self.assertRaises(TypeError):
            TaskDefinition()  # type: ignore[abstract]

    def test_repr_contains_key(self) -> None:
        task = _DummyTask("foo", "Foo")
        self.assertIn("foo", repr(task))
