"""Test default behavior dei nuovi metodi opzionali su TaskDefinition."""

from django.test import SimpleTestCase

from apps.tasks.base import TaskDefinition


class _StubTask(TaskDefinition):
    """Stub minimale per testare i default."""

    @property
    def key(self) -> str:
        return "_stub"

    @property
    def display_name(self) -> str:
        return "Stub"

    @property
    def min_participants(self) -> int:
        return 2

    @property
    def max_participants(self) -> int:
        return 4

    @property
    def fixed_size(self) -> bool:
        return False


class TaskDefinitionIndividualRankingDefaultsTests(SimpleTestCase):
    def setUp(self) -> None:
        self.task = _StubTask()

    def test_requires_individual_ranking_phase_default_false(self) -> None:
        self.assertFalse(self.task.requires_individual_ranking_phase())

    def test_individual_ranking_duration_seconds_default_480(self) -> None:
        self.assertEqual(self.task.individual_ranking_duration_seconds(), 480)

    def test_individual_ranking_model_default_none(self) -> None:
        self.assertIsNone(self.task.individual_ranking_model())

    def test_default_individual_ranking_default_empty(self) -> None:
        self.assertEqual(self.task.default_individual_ranking(), [])

    def test_expected_items_set_default_empty(self) -> None:
        self.assertEqual(self.task.expected_items_set(), set())
