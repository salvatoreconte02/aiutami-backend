"""
Test per il plugin LostAtSeaTask.

Verifica registrazione, proprietà, config (items, expert ranking, scoring),
validazione ranking, endpoint API, report e submission.
"""

from unittest.mock import MagicMock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from apps.sessions.models import Session, SessionParticipant, SessionState, ParticipantRole
from apps.tasks.registry import get_task, all_keys
from apps.tasks.lost_at_sea.task import LostAtSeaTask
from apps.tasks.lost_at_sea.config import (
    LOST_AT_SEA_ITEMS,
    EXPERT_RANKING,
    compute_error_score,
    MAX_ERROR_SCORE,
)
from apps.tasks.lost_at_sea.models import LostAtSeaRanking

User = get_user_model()


# ---------------------------------------------------------------------------
# Registrazione
# ---------------------------------------------------------------------------

class LostAtSeaRegistrationTests(SimpleTestCase):
    def test_registered_at_boot(self) -> None:
        task = get_task("lost_at_sea")
        self.assertIsInstance(task, LostAtSeaTask)

    def test_key_and_display_name(self) -> None:
        task = get_task("lost_at_sea")
        self.assertEqual(task.key, "lost_at_sea")
        self.assertEqual(task.display_name, "Lost at Sea")

    def test_listed_in_all_keys(self) -> None:
        self.assertIn("lost_at_sea", all_keys())


# ---------------------------------------------------------------------------
# Partecipanti
# ---------------------------------------------------------------------------

class LostAtSeaParticipantsTests(SimpleTestCase):
    def setUp(self) -> None:
        self.task = get_task("lost_at_sea")

    def test_min_participants(self) -> None:
        self.assertEqual(self.task.min_participants, 3)

    def test_max_participants(self) -> None:
        self.assertEqual(self.task.max_participants, 6)

    def test_not_fixed_size(self) -> None:
        self.assertFalse(self.task.fixed_size)


# ---------------------------------------------------------------------------
# Config e scoring
# ---------------------------------------------------------------------------

class LostAtSeaConfigTests(SimpleTestCase):
    def test_15_items(self) -> None:
        self.assertEqual(len(LOST_AT_SEA_ITEMS), 15)

    def test_expert_ranking_covers_all_items(self) -> None:
        self.assertEqual(set(LOST_AT_SEA_ITEMS), set(EXPERT_RANKING.keys()))

    def test_expert_ranking_is_1_to_15(self) -> None:
        self.assertEqual(sorted(EXPERT_RANKING.values()), list(range(1, 16)))

    def test_perfect_score(self) -> None:
        perfect = sorted(LOST_AT_SEA_ITEMS, key=lambda item: EXPERT_RANKING[item])
        self.assertEqual(compute_error_score(perfect), 0)

    def test_worst_score(self) -> None:
        worst = sorted(LOST_AT_SEA_ITEMS, key=lambda item: -EXPERT_RANKING[item])
        self.assertEqual(compute_error_score(worst), MAX_ERROR_SCORE)

    def test_known_score(self) -> None:
        # Scambiamo solo i primi due (specchio rank 1, carburante rank 2)
        perfect = sorted(LOST_AT_SEA_ITEMS, key=lambda item: EXPERT_RANKING[item])
        swapped = [perfect[1], perfect[0]] + perfect[2:]
        # diff per item 0: |1 - 2| = 1, item 1: |2 - 1| = 1, rest = 0
        self.assertEqual(compute_error_score(swapped), 2)

    def test_items_are_in_italian(self) -> None:
        item_text = " ".join(LOST_AT_SEA_ITEMS)
        self.assertIn("barba", item_text)
        self.assertIn("carburante", item_text)
        self.assertIn("acqua", item_text)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

class LostAtSeaPromptTests(SimpleTestCase):
    def setUp(self) -> None:
        self.task = get_task("lost_at_sea")

    def test_task_context_block_not_empty(self) -> None:
        for mode in ("normal", "forced_conclusion"):
            block = self.task.task_context_block(mode)
            self.assertTrue(len(block) > 0, f"Block for {mode} is empty")

    def test_normal_block_contains_scenario(self) -> None:
        # Default Italian
        block = self.task.task_context_block("normal")
        self.assertIn("Atlantico", block)
        self.assertIn("consenso", block)

    def test_normal_block_english_contains_scenario(self) -> None:
        block = self.task.task_context_block("normal", language="English")
        self.assertIn("Atlantic", block)
        self.assertIn("consensus", block)

    def test_normal_block_contains_ground_rules(self) -> None:
        # Default Italian
        block = self.task.task_context_block("normal")
        self.assertIn("voto a maggioranza", block)
        self.assertIn("conflitto", block)

    def test_normal_block_english_contains_ground_rules(self) -> None:
        block = self.task.task_context_block("normal", language="English")
        self.assertIn("majority vote", block)
        self.assertIn("conflict", block.lower())

    def test_intro_message_tail_contains_rules(self) -> None:
        tail = self.task.intro_message_tail()
        self.assertIn("Lost at Sea", tail)
        self.assertIn("15 oggetti", tail)
        self.assertIn("consenso", tail)

    def test_llm_scenario_payload(self) -> None:
        payload = self.task.llm_scenario_payload()
        self.assertEqual(payload["type"], "lost_at_sea")
        self.assertIn("objective", payload)


# ---------------------------------------------------------------------------
# Fallback conclusion
# ---------------------------------------------------------------------------

class LostAtSeaFallbackTests(SimpleTestCase):
    def setUp(self) -> None:
        self.task = get_task("lost_at_sea")

    def test_timer_expired(self) -> None:
        body = self.task.fallback_forced_conclusion_body("riassunto", "timer_expired")
        self.assertIn("tempo", body.lower())
        self.assertIn("ranking finale", body)

    def test_all_participants_ready(self) -> None:
        body = self.task.fallback_forced_conclusion_body("riassunto", "all_participants_ready")
        self.assertIn("concludere", body.lower())
        self.assertIn("ranking", body)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

class LostAtSeaReportTests(SimpleTestCase):
    def setUp(self) -> None:
        self.task = get_task("lost_at_sea")

    def test_report_title(self) -> None:
        self.assertEqual(self.task.report_title(), "REPORT LOST AT SEA")

    def test_report_llm_prompt(self) -> None:
        prompt = self.task.build_report_llm_prompt()
        self.assertIn("Lost at Sea", prompt)
        # Marker EN del nuovo prompt parametrizzato
        self.assertIn("error score", prompt.lower())

    def test_report_pdf_sections_empty_when_no_ranking(self) -> None:
        from reportlab.lib.styles import getSampleStyleSheet
        reportlab_styles = getSampleStyleSheet()
        styles = {"section": reportlab_styles["Heading2"], "body": reportlab_styles["Normal"]}
        fake_session = MagicMock()
        context = {"has_ranking": False}
        sections = self.task.build_report_pdf_sections(fake_session, context, styles)
        self.assertTrue(len(sections) > 0)  # Shows "nessun ranking" message


# ---------------------------------------------------------------------------
# Submission (con DB)
# ---------------------------------------------------------------------------

class LostAtSeaSubmissionTests(TestCase):
    def setUp(self) -> None:
        self.task = get_task("lost_at_sea")
        self.user = User.objects.create_user(username="host_sea", password="test1234")
        self.session = Session.objects.create(
            title="Test Lost at Sea",
            context="lost_at_sea",
            min_size=3,
            max_size=6,
            host=self.user,
        )

    def test_no_ranking_submissions_received_false(self) -> None:
        self.assertFalse(self.task.all_submissions_received(self.session))

    def test_with_ranking_not_final_submissions_received_false(self) -> None:
        participant = SessionParticipant.objects.create(
            session=self.session, user=self.user, role=ParticipantRole.HOST,
        )
        perfect = sorted(LOST_AT_SEA_ITEMS, key=lambda item: EXPERT_RANKING[item])
        LostAtSeaRanking.objects.create(
            session=self.session,
            submitted_by=participant,
            ranked_items=perfect,
            is_final=False,
        )
        self.assertFalse(self.task.all_submissions_received(self.session))

    def test_with_ranking_final_submissions_received_true(self) -> None:
        participant = SessionParticipant.objects.create(
            session=self.session, user=self.user, role=ParticipantRole.HOST,
        )
        perfect = sorted(LOST_AT_SEA_ITEMS, key=lambda item: EXPERT_RANKING[item])
        LostAtSeaRanking.objects.create(
            session=self.session,
            submitted_by=participant,
            ranked_items=perfect,
            is_final=True,
        )
        self.assertTrue(self.task.all_submissions_received(self.session))

    def test_submission_summary_none_without_ranking(self) -> None:
        self.assertIsNone(self.task.submission_summary(self.session))

    def test_submission_summary_with_ranking(self) -> None:
        participant = SessionParticipant.objects.create(
            session=self.session, user=self.user, role=ParticipantRole.HOST,
        )
        perfect = sorted(LOST_AT_SEA_ITEMS, key=lambda item: EXPERT_RANKING[item])
        LostAtSeaRanking.objects.create(
            session=self.session,
            submitted_by=participant,
            ranked_items=perfect,
        )
        summary = self.task.submission_summary(self.session)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["error_score"], 0)
        self.assertEqual(len(summary["items_detail"]), 15)


# ---------------------------------------------------------------------------
# Endpoint API
# ---------------------------------------------------------------------------

@override_settings(CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}})
class LostAtSeaRankingEndpointTests(TestCase):
    def setUp(self) -> None:
        self.host = User.objects.create_user(username="host_sea_ep", password="test1234")
        self.member = User.objects.create_user(username="member_sea_ep", password="test1234")
        self.outsider = User.objects.create_user(username="outsider_sea_ep", password="test1234")

        self.session = Session.objects.create(
            title="Test Lost at Sea EP",
            context="lost_at_sea",
            min_size=3,
            max_size=6,
            host=self.host,
            state=SessionState.ACTIVE,
        )
        self.host_participant = SessionParticipant.objects.create(
            session=self.session, user=self.host, role=ParticipantRole.HOST,
        )
        self.member_participant = SessionParticipant.objects.create(
            session=self.session, user=self.member, role=ParticipantRole.PARTICIPANT,
        )

        self.perfect_ranking = sorted(LOST_AT_SEA_ITEMS, key=lambda item: EXPERT_RANKING[item])

        self.client = APIClient()

    def _url(self, suffix="ranking/"):
        return f"/api/tasks/lost-at-sea/sessions/{self.session.id}/{suffix}"

    # --- PUT ranking ---

    def test_put_ranking_as_host_creates(self) -> None:
        self.client.force_authenticate(user=self.host)
        resp = self.client.put(
            self._url(), {"ranked_items": self.perfect_ranking}, format="json"
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.data["success"])
        self.assertEqual(LostAtSeaRanking.objects.count(), 1)

    def test_put_ranking_as_host_updates(self) -> None:
        self.client.force_authenticate(user=self.host)
        self.client.put(
            self._url(), {"ranked_items": self.perfect_ranking}, format="json"
        )
        swapped = [self.perfect_ranking[1], self.perfect_ranking[0]] + self.perfect_ranking[2:]
        resp = self.client.put(
            self._url(), {"ranked_items": swapped}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(LostAtSeaRanking.objects.count(), 1)
        ranking = LostAtSeaRanking.objects.get(session=self.session)
        self.assertEqual(ranking.ranked_items, swapped)

    def test_put_ranking_as_member_forbidden(self) -> None:
        self.client.force_authenticate(user=self.member)
        resp = self.client.put(
            self._url(), {"ranked_items": self.perfect_ranking}, format="json"
        )
        self.assertEqual(resp.status_code, 403)

    def test_put_ranking_as_outsider_forbidden(self) -> None:
        self.client.force_authenticate(user=self.outsider)
        resp = self.client.put(
            self._url(), {"ranked_items": self.perfect_ranking}, format="json"
        )
        self.assertEqual(resp.status_code, 403)

    def test_put_ranking_wrong_state(self) -> None:
        self.session.state = SessionState.LOBBY
        self.session.save()
        self.client.force_authenticate(user=self.host)
        resp = self.client.put(
            self._url(), {"ranked_items": self.perfect_ranking}, format="json"
        )
        self.assertEqual(resp.status_code, 409)

    def test_put_ranking_invalid_items(self) -> None:
        self.client.force_authenticate(user=self.host)
        resp = self.client.put(
            self._url(), {"ranked_items": ["invalid_item"] * 15}, format="json"
        )
        self.assertEqual(resp.status_code, 400)

    def test_put_ranking_wrong_count(self) -> None:
        self.client.force_authenticate(user=self.host)
        resp = self.client.put(
            self._url(), {"ranked_items": self.perfect_ranking[:10]}, format="json"
        )
        self.assertEqual(resp.status_code, 400)

    def test_put_ranking_duplicates(self) -> None:
        self.client.force_authenticate(user=self.host)
        dupes = [self.perfect_ranking[0]] * 15
        resp = self.client.put(
            self._url(), {"ranked_items": dupes}, format="json"
        )
        self.assertEqual(resp.status_code, 400)

    def test_put_ranking_not_a_list(self) -> None:
        self.client.force_authenticate(user=self.host)
        resp = self.client.put(
            self._url(), {"ranked_items": "not a list"}, format="json"
        )
        self.assertEqual(resp.status_code, 400)

    # --- GET ranking ---

    def test_get_ranking_empty(self) -> None:
        self.client.force_authenticate(user=self.member)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data["ranked_items"])

    def test_get_ranking_after_put(self) -> None:
        self.client.force_authenticate(user=self.host)
        self.client.put(
            self._url(), {"ranked_items": self.perfect_ranking}, format="json"
        )
        self.client.force_authenticate(user=self.member)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["ranked_items"], self.perfect_ranking)

    def test_get_ranking_as_outsider_forbidden(self) -> None:
        self.client.force_authenticate(user=self.outsider)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 403)

    # --- GET ranking-status ---

    def test_ranking_status_no_ranking(self) -> None:
        self.client.force_authenticate(user=self.member)
        resp = self.client.get(self._url("ranking-status/"))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["has_ranking"])

    def test_ranking_status_with_ranking(self) -> None:
        self.client.force_authenticate(user=self.host)
        self.client.put(
            self._url(), {"ranked_items": self.perfect_ranking}, format="json"
        )
        self.client.force_authenticate(user=self.member)
        resp = self.client.get(self._url("ranking-status/"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["has_ranking"])

    def test_ranking_status_includes_is_final(self) -> None:
        self.client.force_authenticate(user=self.host)
        self.client.put(
            self._url(), {"ranked_items": self.perfect_ranking}, format="json"
        )
        resp = self.client.get(self._url("ranking-status/"))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["is_final"])

    # --- PUT ranking in CONCLUSION ---

    def test_put_ranking_in_conclusion(self) -> None:
        self.session.state = SessionState.CONCLUSION
        self.session.save()
        self.client.force_authenticate(user=self.host)
        resp = self.client.put(
            self._url(), {"ranked_items": self.perfect_ranking}, format="json"
        )
        self.assertIn(resp.status_code, (200, 201))

    def test_put_ranking_in_closed_forbidden(self) -> None:
        self.session.state = SessionState.CLOSED
        self.session.save()
        self.client.force_authenticate(user=self.host)
        resp = self.client.put(
            self._url(), {"ranked_items": self.perfect_ranking}, format="json"
        )
        self.assertEqual(resp.status_code, 409)

    # --- GET ranking includes is_final ---

    def test_get_ranking_includes_is_final(self) -> None:
        self.client.force_authenticate(user=self.host)
        self.client.put(
            self._url(), {"ranked_items": self.perfect_ranking}, format="json"
        )
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["is_final"])

    # --- POST submit ---

    def test_submit_ranking_success(self) -> None:
        self.client.force_authenticate(user=self.host)
        self.client.put(
            self._url(), {"ranked_items": self.perfect_ranking}, format="json"
        )
        self.session.state = SessionState.CONCLUSION
        self.session.save()
        resp = self.client.post(self._url("ranking/submit/"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["success"])
        self.assertTrue(resp.data["is_final"])
        ranking = LostAtSeaRanking.objects.get(session=self.session)
        self.assertTrue(ranking.is_final)

    def test_submit_ranking_not_in_conclusion(self) -> None:
        self.client.force_authenticate(user=self.host)
        self.client.put(
            self._url(), {"ranked_items": self.perfect_ranking}, format="json"
        )
        resp = self.client.post(self._url("ranking/submit/"))
        self.assertEqual(resp.status_code, 409)

    def test_submit_ranking_as_member_forbidden(self) -> None:
        self.client.force_authenticate(user=self.host)
        self.client.put(
            self._url(), {"ranked_items": self.perfect_ranking}, format="json"
        )
        self.session.state = SessionState.CONCLUSION
        self.session.save()
        self.client.force_authenticate(user=self.member)
        resp = self.client.post(self._url("ranking/submit/"))
        self.assertEqual(resp.status_code, 403)

    def test_submit_ranking_no_ranking_exists(self) -> None:
        self.session.state = SessionState.CONCLUSION
        self.session.save()
        self.client.force_authenticate(user=self.host)
        resp = self.client.post(self._url("ranking/submit/"))
        self.assertEqual(resp.status_code, 400)

    def test_submit_ranking_already_final(self) -> None:
        self.client.force_authenticate(user=self.host)
        self.client.put(
            self._url(), {"ranked_items": self.perfect_ranking}, format="json"
        )
        self.session.state = SessionState.CONCLUSION
        self.session.save()
        self.client.post(self._url("ranking/submit/"))
        resp = self.client.post(self._url("ranking/submit/"))
        self.assertEqual(resp.status_code, 400)

    def test_submit_ranking_outsider_forbidden(self) -> None:
        self.session.state = SessionState.CONCLUSION
        self.session.save()
        self.client.force_authenticate(user=self.outsider)
        resp = self.client.post(self._url("ranking/submit/"))
        self.assertEqual(resp.status_code, 403)
