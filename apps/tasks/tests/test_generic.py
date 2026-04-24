"""
Test per il plugin GenericTask.

Verifica registrazione, proprietà, e che tutti i metodi ereditati dalla
base class ritornino i valori corretti per un task senza scenario e senza
submission.
"""

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from apps.tasks.registry import get_task, all_keys
from apps.tasks.generic.task import GenericTask


class GenericRegistrationTests(SimpleTestCase):
    def test_registered_at_boot(self) -> None:
        task = get_task("generic")
        self.assertIsInstance(task, GenericTask)

    def test_key_and_display_name(self) -> None:
        task = get_task("generic")
        self.assertEqual(task.key, "generic")
        self.assertEqual(task.display_name, "Discussione generica")

    def test_listed_in_all_keys(self) -> None:
        self.assertIn("generic", all_keys())


class GenericParticipantsTests(SimpleTestCase):
    def setUp(self) -> None:
        self.task = get_task("generic")

    def test_min_participants(self) -> None:
        self.assertEqual(self.task.min_participants, 2)

    def test_max_participants(self) -> None:
        self.assertEqual(self.task.max_participants, 8)

    def test_not_fixed_size(self) -> None:
        self.assertFalse(self.task.fixed_size)


class GenericPromptTests(SimpleTestCase):
    def setUp(self) -> None:
        self.task = get_task("generic")

    def test_task_context_block_empty(self) -> None:
        for mode in ("normal", "forced_conclusion"):
            self.assertEqual(self.task.task_context_block(mode), "")

    def test_llm_scenario_payload_empty(self) -> None:
        self.assertEqual(self.task.llm_scenario_payload(), {})

    def test_intro_message_tail(self) -> None:
        tail = self.task.intro_message_tail()
        self.assertIn("Pronto alla conclusione", tail)


class GenericSubmissionTests(SimpleTestCase):
    def setUp(self) -> None:
        self.task = get_task("generic")

    def test_all_submissions_always_true(self) -> None:
        fake_session = MagicMock()
        self.assertTrue(self.task.all_submissions_received(fake_session))

    def test_submission_summary_none(self) -> None:
        fake_session = MagicMock()
        self.assertIsNone(self.task.submission_summary(fake_session))


class GenericReportTests(SimpleTestCase):
    def setUp(self) -> None:
        self.task = get_task("generic")

    def test_report_title(self) -> None:
        self.assertEqual(self.task.report_title(), "REPORT SESSIONE")

    def test_report_llm_prompt_not_empty(self) -> None:
        prompt = self.task.build_report_llm_prompt()
        self.assertIn("report", prompt.lower())

    def test_report_pdf_sections_empty(self) -> None:
        fake_session = MagicMock()
        sections = self.task.build_report_pdf_sections(fake_session, {}, {})
        self.assertEqual(sections, [])

    def test_report_fallback_empty(self) -> None:
        self.assertEqual(self.task.build_report_fallback({}), [])

    def test_collect_report_context_empty(self) -> None:
        fake_session = MagicMock()
        self.assertEqual(self.task.collect_report_context(fake_session), {})


class GenericFallbackConclusionTests(SimpleTestCase):
    def setUp(self) -> None:
        self.task = get_task("generic")

    def test_timer_expired(self) -> None:
        body = self.task.fallback_forced_conclusion_body("riassunto", "timer_expired")
        self.assertIn("tempo", body.lower())
        self.assertIn("riassunto", body)
        self.assertNotIn("colpevole", body)
        self.assertNotIn("votato", body)

    def test_all_participants_ready(self) -> None:
        body = self.task.fallback_forced_conclusion_body("riassunto", "all_participants_ready")
        self.assertIn("concludere", body.lower())
        self.assertIn("riassunto", body)

    def test_other_reason(self) -> None:
        body = self.task.fallback_forced_conclusion_body("riassunto", "other")
        self.assertIn("riassunto", body)
