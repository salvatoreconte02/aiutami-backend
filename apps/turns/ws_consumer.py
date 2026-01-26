from __future__ import annotations

import asyncio
import time

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async

from django.core.cache import cache

# 🔹 import moderazione: timer NO PUSH / tempo sessione / inattivo
from apps.moderation.timers_state import mark_any_activity, mark_user_spoke
from apps.moderation.orchestrator import ModerationOrchestrator
from apps.moderation.triggers import evaluate_time_based_triggers


class TurnsConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer per la gestione dei turni vocali.
    Riceve azioni dal frontend, le valida, chiama TurnManager,
    e notifica tutti gli utenti nella sessione tramite broadcast.
    """

    # -------------------------------------------------------------------------
    # Parametri attesa cache ASR (evita race: stop turno -> Azure finalizza dopo)
    # -------------------------------------------------------------------------
    ASR_CACHE_WAIT_MAX_S = 1.2
    ASR_CACHE_WAIT_STEP_S = 0.15
    ASR_CACHE_STABLE_READS = 2  # letture consecutive uguali per considerare "stabile"

    async def connect(self):
        """
        - Verifica autenticazione.
        - Legge session_id dall'URL route.
        - Verifica che l'utente sia membro della sessione.
        - Aggiunge utente al gruppo WS: turns_{session_id}
        """
        self.session_id = self.scope["url_route"]["kwargs"]["session_id"]
        self.user = self.scope["user"]

        if not self.user.is_authenticated:
            await self.close(code=4001)
            return

        # Controllo membership sessione
        is_member = await self._is_session_member(self.session_id, self.user.id)
        if not is_member:
            await self.close(code=4003)
            return

        self.group_name = f"turns_{self.session_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)

        await self.accept()

    async def disconnect(self, code):
        """
        Rimuove l'utente dal gruppo WS.
        """
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    # -------------------------------------------------------------------------
    # Dispatcher principale: riceve JSON dal frontend
    # -------------------------------------------------------------------------

    async def receive_json(self, content, **kwargs):
        """
        Punto di ingresso per i messaggi WebSocket provenienti dal frontend.

        Ci si aspetta un JSON con almeno:
        - "type": stringa che identifica l'azione richiesta
        """

        message_type = content.get("type")
        if not message_type:
            await self.send_json(
                {
                    "success": False,
                    "error": "MISSING_TYPE",
                }
            )
            return

        # Dispatcher principale
        if message_type == "turns.get_state":
            await self._handle_get_state(content)
            return

        if message_type == "turns.request_speak":
            await self._handle_request_speak(content)
            return

        if message_type == "turns.end_speak":
            await self._handle_end_speak(content)
            return

        if message_type == "turns.request_reserve":
            await self._handle_request_reserve(content)
            return

        if message_type == "turns.ai_start":
            await self._handle_ai_start(content)
            return

        if message_type == "turns.ai_end":
            await self._handle_ai_end(content)
            return

        if message_type == "turns.ping":
            # Polling periodico del frontend (es. ogni 5s) per i trigger a tempo
            await self._handle_ping(content)
            return

        # Default: tipo non riconosciuto
        await self.send_json(
            {
                "success": False,
                "error": "UNKNOWN_TYPE",
                "type": message_type,
            }
        )

    # -------------------------------------------------------------------------
    # HANDLER DELLE AZIONI
    # -------------------------------------------------------------------------

    async def _handle_get_state(self, content):
        """
        Gestisce il messaggio: { "type": "turns.get_state" }.
        Ritorna lo stato corrente al chiamante e, se necessario,
        emette in broadcast eventuali eventi (es. RESERVATION_EXPIRED).
        """
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.send_json(
                {
                    "type": "turns.state",
                    "payload": {
                        "success": False,
                        "error_code": "UNAUTHENTICATED",
                        "error_detail": "Utente non autenticato sulla connessione WS.",
                    },
                }
            )
            return

        from apps.turns.services import TurnManager

        result = TurnManager.get_state(self.session_id, user)

        # Broadcast degli eventi (se presenti)
        await self._broadcast_events(result.events)

        # Risposta diretta al chiamante con lo stato
        await self.send_json(
            {
                "type": "turns.state",
                "payload": result.to_state_dict(),
            }
        )

    async def _handle_request_speak(self, content):
        """
        Gestisce il messaggio: { "type": "turns.request_speak" }.

        Chiede al TurnManager di aprire un turno di speaking umano
        per l'utente corrente, se le regole di dominio lo consentono.
        """
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.send_json(
                {
                    "type": "turns.state",
                    "payload": {
                        "success": False,
                        "error_code": "UNAUTHENTICATED",
                        "error_detail": "Utente non autenticato sulla connessione WS.",
                    },
                }
            )
            return

        # I turni sono gestiti solo in sessioni ACTIVE
        if not await self._ensure_session_active():
            return

        from apps.turns.services import TurnManager

        result = TurnManager.request_speak(self.session_id, user)

        # 🔹 Se il turno umano è effettivamente partito, si aggiorna lo stato dei timer.
        if result.success:
            await self._mark_any_activity()
            await self._mark_user_spoke(user.id)

        # Broadcast degli eventi (HUMAN_STARTED, eventuale RESERVATION_EXPIRED, ecc.)
        await self._broadcast_events(result.events)

        # Risposta diretta al chiamante con lo stato aggiornato / errore
        await self.send_json(
            {
                "type": "turns.state",
                "payload": result.to_state_dict(),
            }
        )

    # -------------------------------------------------------------------------
    # ASR cache helper (attesa breve per final Azure)
    # -------------------------------------------------------------------------

    async def _collect_asr_transcript_with_wait(self, cache_key: str) -> str:
        """
        Legge i segmenti 'final' ASR dalla cache, attendendo brevemente che arrivino.
        Considera 'stabile' quando la lista è uguale per N letture consecutive.
        """
        def _read_parts() -> list[str]:
            try:
                segments = cache.get(cache_key)
                if not isinstance(segments, list):
                    return []
                return [str(s).strip() for s in segments if s and str(s).strip()]
            except Exception:
                return []

        deadline = time.monotonic() + float(self.ASR_CACHE_WAIT_MAX_S)

        last_parts: list[str] = []
        stable = 0

        while True:
            parts = _read_parts()

            if parts:
                if parts == last_parts:
                    stable += 1
                else:
                    stable = 1
                    last_parts = parts

                if stable >= int(self.ASR_CACHE_STABLE_READS):
                    break

            if time.monotonic() >= deadline:
                # timeout: restituisce quanto presente (se presente) o stringa vuota
                last_parts = parts or last_parts
                break

            await asyncio.sleep(float(self.ASR_CACHE_WAIT_STEP_S))

        return " ".join(last_parts).strip() if last_parts else ""

    async def _handle_end_speak(self, content):
        """
        Gestisce il messaggio: { "type": "turns.end_speak" }.

        Pipeline:
        1. chiude il turno umano (TurnManager)
        2. aggiorna i timer NO PUSH
        3. imposta moderation_in_progress = True
        4. esegue la moderazione completa (trigger + LLM) tramite ModerationOrchestrator
        5. apre/chiude eventuali turni AI per i messaggi del moderatore
        6. ripristina moderation_in_progress = False
        7. restituisce lo stato finale dei turni.
        """
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.send_json({
                "type": "turns.state",
                "payload": {
                    "success": False,
                    "error_code": "UNAUTHENTICATED",
                    "error_detail": "Utente non autenticato sulla connessione WS.",
                },
            })
            return

        if not await self._ensure_session_active():
            return

        from apps.turns.services import TurnManager

        # 1) Chiusura del turno umano
        result = TurnManager.end_speak(self.session_id, user)

        if not result.success:
            await self.send_json({
                "type": "turns.state",
                "payload": result.to_state_dict(),
            })
            return

        # 2) Attività ai fini del NO PUSH
        await self._mark_any_activity()

        # Broadcast degli eventi generati dalla chiusura
        await self._broadcast_events(result.events)

        # 3) Entrata nella fase di moderazione: blocco nuovi turni umani
        await self._set_moderation_in_progress(True)

        from apps.turns.services import TurnManager as TM  # alias locale

        # Chiave cache dei final ASR per questo turno
        cache_key = f"asr:final_segments:{str(self.session_id)}:{int(user.id)}"

        try:
            # 4) Esecuzione moderazione completa (trigger + LLM)
            try:
                session_phase = await self._get_session_state(self.session_id)
            except Exception:
                session_phase = "ACTIVE"

            # --- TESTO TURNO: cache final ASR con attesa breve, poi fallback a transcript frontend ---
            last_turn_text = await self._collect_asr_transcript_with_wait(cache_key)

            if not last_turn_text:
                last_turn_text = content.get("transcript", "") or ""
                last_turn_text = str(last_turn_text).strip()

            # Nome parlante (display_name se presente, altrimenti username)
            speaker_name = getattr(user, "display_name", None) or user.get_username()

            decision = await self._run_moderation_orchestrator(
                user_id=user.id,
                last_turn_text=last_turn_text,
                session_phase=session_phase,
                speaker_name=speaker_name,
            )

            # --- DEBUG: invio diretto del messaggio del moderatore LLM al chiamante ---
            if decision.ai_should_speak and decision.ai_message:
                await self.send_json(
                    {
                        "type": "moderation.ai_message",
                        "payload": {"text": decision.ai_message},
                    }
                )
            # ---------------------------------------------------------------------------

            # 5) Esecuzione dei messaggi statici (senza LLM) come veri turni AI
            for msg in decision.static_messages_to_speak:
                ai_start_res = TM.ai_start(self.session_id)
                if ai_start_res.success:
                    await self._mark_any_activity()
                    await self._broadcast_events(ai_start_res.events)

                    # Messaggio del moderatore verso il client (per TTS / UI)
                    await self.send_json({
                        "type": "turns.ai_message",
                        "payload": {"text": msg},
                    })

                    ai_end_res = TM.ai_end(self.session_id)
                    await self._mark_any_activity()
                    await self._broadcast_events(ai_end_res.events)

            # 6) Eventuale intervento AI proposto dall'LLM
            if decision.ai_should_speak and decision.ai_message:
                ai_start_res = TM.ai_start(self.session_id)
                if ai_start_res.success:
                    await self._mark_any_activity()
                    await self._broadcast_events(ai_start_res.events)

                    await self.send_json({
                        "type": "turns.ai_message",
                        "payload": {"text": decision.ai_message},
                    })

                    ai_end_res = TM.ai_end(self.session_id)
                    await self._mark_any_activity()
                    await self._broadcast_events(ai_end_res.events)

        finally:
            # Pulizia cache final ASR consumata (evita riuso tra turni)
            try:
                cache.delete(cache_key)
            except Exception:
                pass

            # 7) Uscita dalla fase di moderazione: si riapre ai turni umani
            await self._set_moderation_in_progress(False)

            # Stato finale dei turni dopo la moderazione
            final_state = TM.get_state(self.session_id, user)

            await self.send_json({
                "type": "turns.state",
                "payload": final_state.to_state_dict(),
            })

    async def _handle_request_reserve(self, content):
        """
        Gestisce il messaggio: { "type": "turns.request_reserve" }.

        Richiede la prenotazione (alzata di mano) per l’utente corrente.
        """
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.send_json(
                {
                    "type": "turns.state",
                    "payload": {
                        "success": False,
                        "error_code": "UNAUTHENTICATED",
                        "error_detail": "Utente non autenticato sulla connessione WS.",
                    },
                }
            )
            return

        if not await self._ensure_session_active():
            return

        from apps.turns.services import TurnManager

        result = TurnManager.request_reserve(self.session_id, user)

        # Broadcast degli eventi (es. RESERVATION_SET)
        await self._broadcast_events(result.events)

        # Risposta diretta al chiamante con lo stato aggiornato / eventuale errore
        await self.send_json(
            {
                "type": "turns.state",
                "payload": result.to_state_dict(),
            }
        )

    async def _handle_ai_start(self, content):
        """
        Gestisce il messaggio: { "type": "turns.ai_start" }.

        Avvia l'intervento dell'AI se consentito dallo stato corrente.
        """
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.send_json(
                {
                    "type": "turns.state",
                    "payload": {
                        "success": False,
                        "error_code": "UNAUTHENTICATED",
                        "error_detail": "Utente non autenticato sulla connessione WS.",
                    },
                }
            )
            return

        if not await self._ensure_session_active():
            return

        from apps.turns.services import TurnManager

        result = TurnManager.ai_start(self.session_id)

        # 🔹 Inizio intervento AI: anche questo resetta il timer NO PUSH.
        if result.success:
            await self._mark_any_activity()

        # Broadcast: AI_STARTED a tutti
        await self._broadcast_events(result.events)

        # Risposta al chiamante
        await self.send_json(
            {
                "type": "turns.state",
                "payload": result.to_state_dict(),
            }
        )

    async def _handle_ai_end(self, content):
        """
        Gestisce il messaggio: { "type": "turns.ai_end" }.

        Termina l'intervento dell'AI se in corso.
        """
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.send_json(
                {
                    "type": "turns.state",
                    "payload": {
                        "success": False,
                        "error_code": "UNAUTHENTICATED",
                        "error_detail": "Utente non autenticato sulla connessione WS.",
                    },
                }
            )
            return

        if not await self._ensure_session_active():
            return

        from apps.turns.services import TurnManager

        result = TurnManager.ai_end(self.session_id)

        # 🔹 Fine intervento AI: anche questo è attività.
        if result.success:
            await self._mark_any_activity()

        # Broadcast degli eventi (AI_ENDED)
        await self._broadcast_events(result.events)

        # Risposta al chiamante
        await self.send_json(
            {
                "type": "turns.state",
                "payload": result.to_state_dict(),
            }
        )

    async def _handle_ping(self, content):
        """
        Gestisce il messaggio: { "type": "turns.ping" }.

        Viene pensato per essere chiamato periodicamente dal frontend
        (es. ogni 5 secondi) per valutare i trigger basati sul tempo:
        - NO PUSH
        - UTENTE INATTIVO
        - TIMER 25'/30'

        Se non ci sono messaggi da dire, risponde soltanto con un ack leggero.
        Se ci sono messaggi, apre e chiude un turno AI per ciascuno.
        """
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            return

        try:
            session_phase = await self._get_session_state(self.session_id)
        except Exception:
            return

        from apps.turns.services import TurnManager

        trig_result = evaluate_time_based_triggers(
            session_id=self.session_id,
            session_phase=session_phase,
        )

        if not trig_result.static_messages_to_speak:
            await self.send_json(
                {
                    "type": "turns.ping_ok",
                    "payload": {"has_messages": False},
                }
            )
            return

        for msg in trig_result.static_messages_to_speak:
            ai_start_res = TurnManager.ai_start(self.session_id)
            if ai_start_res.success:
                await self._mark_any_activity()
                await self._broadcast_events(ai_start_res.events)

                await self.send_json(
                    {
                        "type": "turns.ai_message",
                        "payload": {"text": msg},
                    }
                )

                ai_end_res = TurnManager.ai_end(self.session_id)
                await self._mark_any_activity()
                await self._broadcast_events(ai_end_res.events)

        final_state = TurnManager.get_state(self.session_id, user)
        await self.send_json(
            {
                "type": "turns.state",
                "payload": final_state.to_state_dict(),
            }
        )

    # -------------------------------------------------------------------------
    # UTILITIES
    # -------------------------------------------------------------------------

    async def _broadcast_events(self, events):
        if not events:
            return

        for ev in events:
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "turns.event",
                    "event_type": ev.type,
                    "payload": ev.payload or {},
                },
            )

    async def turns_event(self, event):
        await self.send_json(
            {
                "type": f"turns.{event['event_type'].lower()}",
                "payload": event["payload"],
            }
        )

    # -------------------------------------------------------------------------
    # CHECKS UTILI (sync → async)
    # -------------------------------------------------------------------------

    @database_sync_to_async
    def _is_session_member(self, session_id, user_id: int) -> bool:
        from apps.sessions.models import Session

        return Session.objects.filter(
            id=session_id,
            participants__user_id=user_id,
        ).exists()

    @database_sync_to_async
    def _get_session_state(self, session_id) -> str:
        from apps.sessions.models import Session

        return Session.objects.values_list("state", flat=True).get(id=session_id)

    async def _ensure_session_active(self) -> bool:
        from apps.sessions.models import SessionState

        try:
            current_state = await self._get_session_state(self.session_id)
        except Exception:
            await self.send_json(
                {
                    "type": "turns.state",
                    "payload": {
                        "success": False,
                        "error_code": "SESSION_NOT_FOUND",
                        "error_detail": "Sessione inesistente o non più disponibile.",
                    },
                }
            )
            return False

        if current_state != SessionState.ACTIVE:
            await self.send_json(
                {
                    "type": "turns.state",
                    "payload": {
                        "success": False,
                        "error_code": "SESSION_NOT_ACTIVE",
                        "error_detail": f"I turni sono disponibili solo quando la sessione è in stato ACTIVE (stato corrente: {current_state}).",
                    },
                }
            )
            return False

        return True

    # -------------------------------------------------------------------------
    # WRAPPER SYNC → ASYNC per i timer di moderazione e l'orchestratore
    # -------------------------------------------------------------------------

    @database_sync_to_async
    def _mark_any_activity(self) -> None:
        mark_any_activity(self.session_id)

    @database_sync_to_async
    def _mark_user_spoke(self, user_id: int) -> None:
        mark_user_spoke(self.session_id, user_id)

    @database_sync_to_async
    def _run_moderation_orchestrator(
        self,
        *,
        user_id: int,
        last_turn_text: str,
        session_phase: str,
        speaker_name: str,
    ):
        return ModerationOrchestrator.handle_human_turn_end(
            session_id=self.session_id,
            user_id=user_id,
            last_turn_text=last_turn_text,
            session_phase=session_phase,
            speaker_name=speaker_name,
        )

    @database_sync_to_async
    def _set_moderation_in_progress(self, value: bool) -> None:
        from apps.turns.services import TurnManager
        TurnManager.set_moderation_in_progress(self.session_id, value)