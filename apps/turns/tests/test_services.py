from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.cache import cache
from unittest.mock import patch

from apps.turns.services import (
    TurnManager,
    TURN_STATE_IDLE,
    TURN_STATE_HUMAN_SPEAKING,
    TURN_STATE_AI_SPEAKING,
)


User = get_user_model()


class TurnManagerTests(TestCase):
    def setUp(self):
        # Pulizia cache ad ogni test per evitare interferenze tra i test
        cache.clear()

        # Creazione di alcuni utenti di test
        self.user1 = User.objects.create_user(
            username="user1", email="user1@example.com", password="pass"
        )
        self.user2 = User.objects.create_user(
            username="user2", email="user2@example.com", password="pass"
        )
        self.user3 = User.objects.create_user(
            username="user3", email="user3@example.com", password="pass"
        )

        # Identificatore fittizio della sessione
        self.session_id = "session-test-1"

    def test_request_speak_from_idle(self):
        """
        Da IDLE, un utente può iniziare a parlare.
        """
        # Stato iniziale
        result_state = TurnManager.get_state(self.session_id, self.user1)
        self.assertTrue(result_state.success)
        self.assertEqual(result_state.state.state, TURN_STATE_IDLE)

        # Richiesta di speaking
        result = TurnManager.request_speak(self.session_id, self.user1)

        self.assertTrue(result.success)
        self.assertEqual(result.state.state, TURN_STATE_HUMAN_SPEAKING)
        self.assertEqual(result.state.current_speaker_user_id, self.user1.id)

        event_types = [e.type for e in result.events]
        self.assertIn("HUMAN_STARTED", event_types)

    def test_second_user_cannot_speak_while_first_is_speaking(self):
        """
        Se user1 sta parlando, user2 viene rifiutato con MIC_BUSY.
        """
        # user1 inizia a parlare
        TurnManager.request_speak(self.session_id, self.user1)

        # user2 prova a parlare
        result = TurnManager.request_speak(self.session_id, self.user2)

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "MIC_BUSY")
        self.assertEqual(result.state.state, TURN_STATE_HUMAN_SPEAKING)
        self.assertEqual(result.state.current_speaker_user_id, self.user1.id)

    def test_reservation_flow(self):
        """
        Flusso completo:
        - user1 parla
        - user2 si prenota
        - user1 termina
        - La finestra prioritaria non si apre subito (aspetta fine moderazione)
        - Dopo la moderazione, la finestra viene aperta con start_reservation_window
        - user2 inizia a parlare dalla prenotazione
        """
        # user1 inizia a parlare
        TurnManager.request_speak(self.session_id, self.user1)

        # user2 si prenota
        res_result = TurnManager.request_reserve(self.session_id, self.user2)
        self.assertTrue(res_result.success)
        self.assertEqual(res_result.state.reservation_user_id, self.user2.id)

        # user1 termina di parlare
        end_result = TurnManager.end_speak(self.session_id, self.user1)
        self.assertTrue(end_result.success)
        self.assertEqual(end_result.state.state, TURN_STATE_IDLE)

        event_types = [e.type for e in end_result.events]
        self.assertIn("HUMAN_ENDED", event_types)
        # La finestra di priorità NON si apre subito (aspetta fine moderazione)
        self.assertNotIn("RESERVATION_WINDOW_STARTED", event_types)
        # La prenotazione esiste ma non ha ancora una scadenza
        self.assertEqual(end_result.state.reservation_user_id, self.user2.id)
        self.assertIsNone(end_result.state.reservation_expires_at)

        # Dopo la moderazione, la finestra viene aperta manualmente
        window_event = TurnManager.start_reservation_window(self.session_id)
        self.assertIsNotNone(window_event)
        self.assertEqual(window_event.type, "RESERVATION_WINDOW_STARTED")

        # user2 parla sfruttando la prenotazione
        speak_result = TurnManager.request_speak(self.session_id, self.user2)
        self.assertTrue(speak_result.success)
        self.assertEqual(speak_result.state.state, TURN_STATE_HUMAN_SPEAKING)
        self.assertEqual(speak_result.state.current_speaker_user_id, self.user2.id)

        # L'evento deve indicare che proviene da prenotazione
        started_events = [e for e in speak_result.events if e.type == "HUMAN_STARTED"]
        self.assertTrue(started_events)
        self.assertTrue(started_events[0].payload.get("from_reservation"))

    def test_ai_start_and_end(self):
        """
        AI può iniziare da IDLE e tornare a IDLE con ai_end.
        """
        # Stato iniziale
        initial = TurnManager.get_state(self.session_id, self.user1)
        self.assertEqual(initial.state.state, TURN_STATE_IDLE)

        # AI inizia a parlare
        start_result = TurnManager.ai_start(self.session_id)
        self.assertTrue(start_result.success)
        self.assertEqual(start_result.state.state, TURN_STATE_AI_SPEAKING)

        event_types = [e.type for e in start_result.events]
        self.assertIn("AI_STARTED", event_types)

        # AI termina
        end_result = TurnManager.ai_end(self.session_id)
        self.assertTrue(end_result.success)
        self.assertEqual(end_result.state.state, TURN_STATE_IDLE)

        event_types = [e.type for e in end_result.events]
        self.assertIn("AI_ENDED", event_types)

    def test_ai_end_does_not_open_reservation_window(self):
        """
        Verifica che ai_end() NON apra la finestra di prenotazione.
        La finestra viene aperta solo da start_reservation_window().
        """
        # user1 parla
        result = TurnManager.request_speak(self.session_id, self.user1)
        self.assertTrue(result.success)

        # user2 si prenota
        result = TurnManager.request_reserve(self.session_id, self.user2)
        self.assertTrue(result.success)

        # user1 termina
        result = TurnManager.end_speak(self.session_id, self.user1)
        self.assertTrue(result.success)

        # AI parla
        result = TurnManager.ai_start(self.session_id)
        self.assertTrue(result.success)

        # AI termina - NON deve aprire la finestra
        result = TurnManager.ai_end(self.session_id)
        self.assertTrue(result.success)

        event_types = [e.type for e in result.events]
        self.assertIn("AI_ENDED", event_types)
        # La finestra NON deve essere aperta da ai_end
        self.assertNotIn("RESERVATION_WINDOW_STARTED", event_types)

        # La prenotazione esiste ma non ha ancora una scadenza
        self.assertEqual(result.state.reservation_user_id, self.user2.id)
        self.assertIsNone(result.state.reservation_expires_at)

        # Solo start_reservation_window apre la finestra
        window_event = TurnManager.start_reservation_window(self.session_id)
        self.assertIsNotNone(window_event)
        self.assertEqual(window_event.type, "RESERVATION_WINDOW_STARTED")


class TurnManagerConclusionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user1 = User.objects.create_user(
            username="user1", email="user1@example.com", password="pass"
        )
        self.session_id = "session-conclusion-test-1"

    def test_request_speak_blocked_in_conclusion_phase(self):
        """
        Human turns should be blocked when session is in CONCLUSION phase.
        """
        # We mock _get_session_phase to return CONCLUSION
        with patch.object(TurnManager, '_get_session_phase', return_value='CONCLUSION'):
            result = TurnManager.request_speak(self.session_id, self.user1)

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "SESSION_IN_CONCLUSION")
        self.assertIn("conclusione", result.error_detail.lower())
