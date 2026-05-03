"""
Test per il refactor lingua-parametrica del moderatore (apr 2026).

Verifica che:
- Il system prompt italiano (default) e inglese (env) abbiano marker corretti
- Il prompt inietti la directive di lingua nei punti previsti
- Le scenario blocks per-task supportino entrambe le lingue
- I payload llm_scenario_payload localizzino le action strings
- I fallback forced_conclusion localizzino i messaggi
"""

from __future__ import annotations

from django.test import SimpleTestCase, override_settings

from apps.moderation.service import ModerationService
from apps.moderation import prompts as moderation_prompts
from apps.tasks.registry import get_task


class NormalModePromptLanguageTests(SimpleTestCase):
    """Default Italian + switch English via override_settings."""

    def test_default_language_is_italian(self) -> None:
        """No env var → directive dice Italian e non Italian."""
        prompt = ModerationService._build_normal_mode_prompt(
            task=get_task("generic")
        )
        self.assertIn("write `message_to_say` and `updated_summary` in Italian", prompt)
        self.assertNotIn("(in English)", prompt)

    @override_settings(MODERATOR_OUTPUT_LANGUAGE="English")
    def test_english_via_settings(self) -> None:
        """Setting=English → directive dice English."""
        prompt = ModerationService._build_normal_mode_prompt(
            task=get_task("generic")
        )
        self.assertIn("write `message_to_say` and `updated_summary` in English", prompt)
        self.assertNotIn("(in Italian)", prompt)

    @override_settings(MODERATOR_OUTPUT_LANGUAGE="French")
    def test_arbitrary_language_passed_through(self) -> None:
        """Qualsiasi stringa setta la directive testualmente."""
        prompt = ModerationService._build_normal_mode_prompt(
            task=get_task("generic")
        )
        self.assertIn("French", prompt)

    def test_language_anchor_appears_at_end_recency_bias(self) -> None:
        """L'ultima riga del prompt deve essere il REMINDER di lingua
        (recency bias mitigation per code-switching)."""
        prompt = ModerationService._build_normal_mode_prompt(
            task=get_task("generic")
        )
        last_lines = prompt.strip().splitlines()[-2:]
        last_chunk = "\n".join(last_lines)
        self.assertIn("REMINDER", last_chunk)
        self.assertIn("Italian", last_chunk)

    def test_prompt_has_two_language_anchors(self) -> None:
        """Mitigation code-switching: directive ripetuta in opening + JSON
        schema + final reminder. Conta almeno 3 occorrenze di 'Italian' nel
        default IT (opening, JSON schema, final reminder, e altri rinforzi)."""
        prompt = ModerationService._build_normal_mode_prompt(
            task=get_task("generic")
        )
        count = prompt.count("Italian")
        self.assertGreaterEqual(
            count, 3, f"Expected >=3 'Italian' anchors, got {count}"
        )


class ForcedConclusionPromptLanguageTests(SimpleTestCase):
    def test_default_italian(self) -> None:
        prompt = ModerationService._build_forced_conclusion_system_prompt(
            task=get_task("nasa_moon_survival")
        )
        self.assertIn("Italian", prompt)

    @override_settings(MODERATOR_OUTPUT_LANGUAGE="English")
    def test_english_via_settings(self) -> None:
        prompt = ModerationService._build_forced_conclusion_system_prompt(
            task=get_task("nasa_moon_survival")
        )
        self.assertIn("English", prompt)
        # Lo scenario block deve essere in inglese
        self.assertIn("Moon", prompt)


class TaskContextBlockLanguageTests(SimpleTestCase):
    """Scenario blocks per-task selezionano IT vs EN."""

    def test_murder_mystery_italian(self) -> None:
        task = get_task("murder_mystery")
        block = task.task_context_block("normal", language="Italian")
        self.assertIn("assassino", block)
        self.assertNotIn("murderer", block)

    def test_murder_mystery_english(self) -> None:
        task = get_task("murder_mystery")
        block = task.task_context_block("normal", language="English")
        self.assertIn("murderer", block)
        self.assertNotIn("assassino", block)

    def test_nasa_moon_italian_default(self) -> None:
        task = get_task("nasa_moon_survival")
        block = task.task_context_block("normal")  # default Italian
        self.assertIn("Luna", block)

    def test_nasa_moon_english(self) -> None:
        task = get_task("nasa_moon_survival")
        block = task.task_context_block("normal", language="English")
        self.assertIn("Moon", block)
        self.assertNotIn("Luna ", block)  # space avoids matching "Lunar"

    def test_lost_at_sea_italian_default(self) -> None:
        task = get_task("lost_at_sea")
        block = task.task_context_block("normal")
        self.assertIn("Atlantico", block)

    def test_lost_at_sea_english(self) -> None:
        task = get_task("lost_at_sea")
        block = task.task_context_block("normal", language="English")
        self.assertIn("Atlantic", block)

    def test_generic_returns_empty_in_both_languages(self) -> None:
        task = get_task("generic")
        for lang in ("Italian", "English"):
            self.assertEqual(task.task_context_block("normal", language=lang), "")


class LLMScenarioPayloadLanguageTests(SimpleTestCase):
    """llm_scenario_payload localizza le action strings."""

    def test_murder_mystery_vote_action_italian(self) -> None:
        task = get_task("murder_mystery")
        payload = task.llm_scenario_payload(
            "forced_conclusion", language="Italian"
        )
        self.assertEqual(payload["vote_action"], "selezionare il colpevole")

    def test_murder_mystery_vote_action_english(self) -> None:
        task = get_task("murder_mystery")
        payload = task.llm_scenario_payload(
            "forced_conclusion", language="English"
        )
        self.assertEqual(payload["vote_action"], "select the murderer")

    def test_nasa_moon_submission_action_localized(self) -> None:
        task = get_task("nasa_moon_survival")
        it = task.llm_scenario_payload(
            "forced_conclusion", language="Italian"
        )
        en = task.llm_scenario_payload(
            "forced_conclusion", language="English"
        )
        self.assertIn("ranking finale", it["submission_action"])
        self.assertIn("final ranking", en["submission_action"])

    def test_lost_at_sea_submission_outcome_localized(self) -> None:
        task = get_task("lost_at_sea")
        it = task.llm_scenario_payload(
            "forced_conclusion", language="Italian"
        )
        en = task.llm_scenario_payload(
            "forced_conclusion", language="English"
        )
        self.assertIn("US Coast Guard", it["submission_outcome"])
        self.assertIn("US Coast Guard", en["submission_outcome"])

    def test_normal_objective_localized(self) -> None:
        task = get_task("nasa_moon_survival")
        it = task.llm_scenario_payload("normal", language="Italian")
        en = task.llm_scenario_payload("normal", language="English")
        self.assertIn("consenso", it["objective"])
        self.assertIn("consensus", en["objective"])


class FallbackForcedConclusionLanguageTests(SimpleTestCase):
    """fallback_forced_conclusion_body localizza i messaggi TTS."""

    def test_murder_mystery_italian(self) -> None:
        task = get_task("murder_mystery")
        body = task.fallback_forced_conclusion_body(
            "Discussione X", "timer_expired", language="Italian"
        )
        self.assertIn("Il tempo a disposizione", body)
        self.assertIn("colpevole", body)

    def test_murder_mystery_english(self) -> None:
        task = get_task("murder_mystery")
        body = task.fallback_forced_conclusion_body(
            "Discussion X", "timer_expired", language="English"
        )
        self.assertIn("Time is up", body)
        self.assertIn("murderer", body)

    def test_nasa_moon_english_recap(self) -> None:
        task = get_task("nasa_moon_survival")
        body = task.fallback_forced_conclusion_body(
            "Recap", "all_participants_ready", language="English"
        )
        self.assertIn("conclude the session", body)
        self.assertIn("NASA experts", body)

    def test_lost_at_sea_english_recap(self) -> None:
        task = get_task("lost_at_sea")
        body = task.fallback_forced_conclusion_body(
            "Recap", "all_participants_ready", language="English"
        )
        self.assertIn("US Coast Guard experts", body)


class ReportLLMPromptLanguageTests(SimpleTestCase):
    def test_default_italian_in_directive(self) -> None:
        for task_key in (
            "murder_mystery",
            "nasa_moon_survival",
            "lost_at_sea",
            "generic",
        ):
            task = get_task(task_key)
            prompt = task.build_report_llm_prompt()  # default Italian
            self.assertIn("Italian", prompt, f"missing in {task_key}")

    def test_english_directive(self) -> None:
        for task_key in (
            "murder_mystery",
            "nasa_moon_survival",
            "lost_at_sea",
            "generic",
        ):
            task = get_task(task_key)
            prompt = task.build_report_llm_prompt(language="English")
            self.assertIn("English", prompt, f"missing in {task_key}")
            self.assertNotIn("in Italian", prompt)


class PromptsModuleDirectAPITests(SimpleTestCase):
    """Smoke test sul modulo apps/moderation/prompts.py chiamato direttamente."""

    def test_build_normal_mode_prompt_italian(self) -> None:
        task = get_task("generic")
        prompt = moderation_prompts.build_normal_mode_prompt(
            task, language="Italian"
        )
        self.assertIn("Italian", prompt)
        self.assertGreater(len(prompt), 1000)  # prompt sostanzioso

    def test_build_normal_mode_prompt_english(self) -> None:
        task = get_task("generic")
        prompt = moderation_prompts.build_normal_mode_prompt(
            task, language="English"
        )
        self.assertIn("English", prompt)

    def test_build_forced_conclusion_prompt(self) -> None:
        task = get_task("murder_mystery")
        prompt = moderation_prompts.build_forced_conclusion_prompt(
            task, language="Italian"
        )
        self.assertIn("Italian", prompt)
        self.assertIn("murder mystery", prompt.lower())
