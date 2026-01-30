from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import ClassVar, Dict

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async

from django.core.cache import cache

from apps.turns.services import TurnManager, PRIORITY_WINDOW_SECONDS

# 🔹 import moderazione: timer NO PUSH / tempo sessione / inattivo
from apps.moderation.timers_state import mark_any_activity, mark_user_spoke
from apps.moderation.orchestrator import ModerationOrchestrator
from apps.moderation.triggers import evaluate_time_based_triggers
from apps.tts.service import TTSService
from apps.webrtc.audio_hub import get_hub, AI_MODERATOR_ID

logger = logging.getLogger(__name__)

# Transcript storage constants
TRANSCRIPT_KEY_PREFIX = "session"
TRANSCRIPT_TTL = 60 * 60 * 24  # 24 hours


def _append_to_session_transcript(session_id: str, entry: dict) -> None:
    """
    Appende un'entry al transcript della sessione in Redis.

    Args:
        session_id: ID della sessione
        entry: Dict con type, text, e altri campi
    """
    key = f"{TRANSCRIPT_KEY_PREFIX}:{session_id}:transcript"
    serialized = json.dumps(entry)

    # Django cache non ha rpush nativo, usiamo get/set
    existing = cache.get(key) or []
    existing.append(serialized)
    cache.set(key, existing, timeout=TRANSCRIPT_TTL)


class TurnsConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer per la gestione dei turni vocali.
    Riceve azioni dal frontend, le valida, chiama TurnManager,
    e notifica tutti gli utenti nella sessione tramite broadcast.
    """

    # -------------------------------------------------------------------------
    # Background trigger task management (class-level, shared across instances)
    # -------------------------------------------------------------------------
    _trigger_tasks: ClassVar[Dict[str, asyncio.Task]] = {}
    _trigger_tasks_lock: ClassVar[asyncio.Lock] = None  # Lazy init

    @classmethod
    def _get_trigger_lock(cls) -> asyncio.Lock:
        """Lazy initialization del lock per evitare problemi con event loop."""
        if cls._trigger_tasks_lock is None:
            cls._trigger_tasks_lock = asyncio.Lock()
        return cls._trigger_tasks_lock

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

        # Avvia il background task per i trigger temporali
        await self._maybe_start_trigger_task()

    async def disconnect(self, code):
        """
        Rimuove l'utente dal gruppo WS.
        """
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

        # Ferma il background task per i trigger temporali
        # Nota: in un'implementazione più sofisticata, si potrebbe contare
        # i client connessi e fermare solo quando l'ultimo si disconnette
        if hasattr(self, "session_id"):
            await self._maybe_stop_trigger_task()

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
        from channels.db import database_sync_to_async

        result = await database_sync_to_async(TurnManager.request_speak)(self.session_id, user)

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

        # NOTA: La finestra di prenotazione NON viene più aperta qui.
        # Verrà aperta DOPO la moderazione (in ai_end se l'AI parla,
        # oppure manualmente alla fine di questo metodo se l'AI non parla).

        # 3) Entrata nella fase di moderazione: blocco nuovi turni umani
        await self._set_moderation_in_progress(True)
        logger.info(
            "[MODERATION][START] session=%s user=%s",
            self.session_id, user.id
        )

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

            # Append human turn to session transcript
            if last_turn_text:
                _append_to_session_transcript(self.session_id, {
                    "type": "human",
                    "user_id": str(user.id),
                    "speaker_name": speaker_name,
                    "text": last_turn_text,
                    "timestamp": datetime.utcnow().isoformat()
                })

            decision = await self._run_moderation_orchestrator(
                user_id=user.id,
                last_turn_text=last_turn_text,
                session_phase=session_phase,
                speaker_name=speaker_name,
            )

            logger.info(
                "[MODERATION][DECISION] session=%s hard_action=%s ai_should_speak=%s "
                "static_msgs=%d transition_to_conclusion=%s",
                self.session_id,
                decision.hard_action,
                decision.ai_should_speak,
                len(decision.static_messages_to_speak),
                decision.should_transition_to_conclusion,
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
                if msg.use_tts:
                    # Messaggio con TTS - esegui come turno AI completo
                    await self._execute_tts_message(msg.text)
                else:
                    # Solo testo - broadcast a tutti i partecipanti
                    payload = {"text": msg.text, "use_tts": False}
                    if msg.trigger_type:
                        payload["trigger_type"] = msg.trigger_type
                    await self.channel_layer.group_send(
                        self.group_name,
                        {
                            "type": "turns.event",
                            "event_type": "STATIC_MESSAGE",
                            "payload": payload,
                        },
                    )

            # 6) Eventuale intervento AI proposto dall'LLM con TTS
            if decision.ai_should_speak and decision.ai_message:
                # 6.1 Start AI turn
                ai_start_res = TM.ai_start(self.session_id)
                if not ai_start_res.success:
                    logger.warning(
                        "[MODERATION][AI_START_BLOCKED] session=%s error=%s detail=%s",
                        self.session_id, ai_start_res.error_code, ai_start_res.error_detail
                    )
                if ai_start_res.success:
                    await self._mark_any_activity()
                    await self._broadcast_events(ai_start_res.events)

                    # 6.2 Set AI as speaker in audio hub
                    hub = get_hub(self.session_id)
                    hub.init_ai_track()
                    hub.set_speaker(AI_MODERATOR_ID)

                    # 6.3 TTS streaming with injection to hub
                    tts = TTSService()
                    tts_result = await tts.synthesize_stream(
                        text=decision.ai_message,
                        on_audio_chunk=lambda pcm, samples, sr: self._inject_ai_audio(hub, pcm, samples, sr)
                    )

                    # 6.4 Fallback if TTS fails
                    if not tts_result.success:
                        logger.warning(f"TTS failed: {tts_result.error}, fallback to text")
                        await self.send_json({
                            "type": "turns.ai_message",
                            "payload": {"text": decision.ai_message}
                        })

                    # 6.5 Append to session transcript
                    _append_to_session_transcript(self.session_id, {
                        "type": "ai",
                        "text": decision.ai_message,
                        "trigger": "llm_decision",
                        "timestamp": datetime.utcnow().isoformat()
                    })

                    # 6.6 End AI turn (synchronous with audio end)
                    hub.set_speaker(None)
                    ai_end_res = TM.ai_end(self.session_id)
                    await self._mark_any_activity()
                    await self._broadcast_events(ai_end_res.events)

                    # 6.7 Se ai_end ha aperto una finestra di prenotazione, schedula il timer
                    for ev in ai_end_res.events:
                        if ev.type == "RESERVATION_WINDOW_STARTED":
                            asyncio.create_task(
                                self._schedule_reservation_expiration(
                                    session_id=self.session_id,
                                    user_id=ev.payload["user_id"],
                                )
                            )

            # 7) Gestione transizione a CONCLUSION (timer 30 min scaduto)
            if decision.should_transition_to_conclusion:
                # Set the reason for conclusion before transitioning
                await self._set_conclusion_reason("timer_expired")
                transitioned = await self._transition_session_to_conclusion()
                if transitioned:
                    # Broadcast del cambio di stato sessione
                    await self.channel_layer.group_send(
                        f"sessions_{self.session_id}",
                        {
                            "type": "session.state_changed",
                            "new_state": "CONCLUSION",
                        },
                    )
                    # Execute FORCED_CONCLUSION immediately
                    await self._execute_forced_conclusion()

            # 8) Flush messaggi TTS pendenti (accodati durante la moderazione)
            await self._flush_pending_tts_messages()

        finally:
            # Pulizia cache final ASR consumata (evita riuso tra turni)
            try:
                cache.delete(cache_key)
            except Exception:
                pass

            # 7) Uscita dalla fase di moderazione: si riapre ai turni umani
            await self._set_moderation_in_progress(False)
            logger.info(
                "[MODERATION][END] session=%s user=%s",
                self.session_id, user.id
            )

            # 8) Se c'è una prenotazione e la finestra non è stata ancora aperta
            #    (cioè l'AI non ha parlato), aprila ora.
            reservation_event = TM.start_reservation_window(self.session_id)
            if reservation_event is not None:
                await self._broadcast_events([reservation_event])
                # Schedula il timer per l'expiration
                asyncio.create_task(
                    self._schedule_reservation_expiration(
                        session_id=self.session_id,
                        user_id=reservation_event.payload["user_id"],
                    )
                )

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
            if msg.use_tts:
                # Messaggio con TTS - esegui come turno AI completo
                await self._execute_tts_message(msg.text)
            else:
                # Solo testo - broadcast a tutti i partecipanti
                payload = {"text": msg.text, "use_tts": False}
                if msg.trigger_type:
                    payload["trigger_type"] = msg.trigger_type
                await self.channel_layer.group_send(
                    self.group_name,
                    {
                        "type": "turns.event",
                        "event_type": "STATIC_MESSAGE",
                        "payload": payload,
                    },
                )

        # Flush messaggi TTS pendenti
        await self._flush_pending_tts_messages()

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

    async def _schedule_reservation_expiration(
        self,
        session_id: str,
        user_id: int
    ):
        """
        Task asincrono che aspetta la scadenza della finestra di priorità
        e invia RESERVATION_EXPIRED se la reservation è ancora attiva.
        """
        await asyncio.sleep(PRIORITY_WINDOW_SECONDS)

        # Verifica e expira (sync method wrapped)
        event = await database_sync_to_async(
            TurnManager.expire_reservation_if_pending
        )(session_id, user_id)

        if event:
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "turns.event",
                    "event_type": event.type,
                    "payload": event.payload,
                },
            )

    async def turns_event(self, event):
        await self.send_json(
            {
                "type": f"turns.{event['event_type'].lower()}",
                "payload": event["payload"],
            }
        )

    async def trigger_ready_to_conclude(self, event):
        """
        Handler per messaggi ready_to_conclude inviati dal view.
        Esegue il messaggio TTS e, se trigger_conclusion=True, transiziona a CONCLUSION.

        Se qualcuno sta parlando, accoda il messaggio invece di eseguirlo subito.
        """
        text = event.get("text", "")
        trigger_conclusion = event.get("trigger_conclusion", False)

        if text:
            # Check if someone is speaking - queue if so
            from apps.turns.services import TurnManager
            from apps.moderation.pending_messages import enqueue_message

            state = TurnManager.get_state_only(self.session_id)
            if state and state.state != "IDLE":
                # Queue the message for later execution
                enqueue_message(
                    self.session_id,
                    text,
                    "READY_TO_CONCLUDE",
                    trigger_conclusion=trigger_conclusion,
                )
                logger.info(
                    "[READY_TO_CONCLUDE][QUEUED] session=%s trigger_conclusion=%s",
                    self.session_id, trigger_conclusion
                )
                return  # Don't execute TTS or transition now
            else:
                # Execute TTS immediately
                await self._execute_tts_message(text)

        # Only transition if we executed immediately (not queued)
        if trigger_conclusion:
            # Set the reason for conclusion before transitioning
            await self._set_conclusion_reason("all_participants_ready")
            transitioned = await self._transition_session_to_conclusion()
            if transitioned:
                await self.channel_layer.group_send(
                    f"sessions_{self.session_id}",
                    {
                        "type": "sessions.event",
                        "event_type": "STATE_CHANGED",
                        "new_state": "CONCLUSION",
                    },
                )
                # Execute FORCED_CONCLUSION immediately
                await self._execute_forced_conclusion()

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

    async def _inject_ai_audio(self, hub, pcm: bytes, samples: int, sample_rate: int):
        """Wrapper async per inject_ai_audio."""
        hub.inject_ai_audio(pcm, samples, sample_rate)

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

    @database_sync_to_async
    def _transition_session_to_conclusion(self) -> bool:
        """
        Cambia la fase della sessione da ACTIVE a CONCLUSION.
        Restituisce True se la transizione è avvenuta, False altrimenti.
        """
        from apps.sessions.models import Session, SessionState
        from django.utils import timezone

        try:
            session = Session.objects.get(pk=self.session_id)
            if session.state == SessionState.ACTIVE:
                session.state = SessionState.CONCLUSION
                session.conclusion_at = timezone.now()
                session.save(update_fields=["state", "conclusion_at"])
                return True
        except Session.DoesNotExist:
            pass
        return False

    async def _execute_forced_conclusion(self) -> None:
        """
        Esegue il trigger FORCED_CONCLUSION immediatamente dopo la transizione.
        Chiama l'LLM per generare il messaggio di chiusura.
        """
        from apps.moderation.state import load_moderation_state, save_moderation_state
        from apps.moderation.service import ModerationService

        # Load moderation state
        state = await database_sync_to_async(load_moderation_state)(self.session_id)

        if state.forced_conclusion_done:
            logger.info("[FORCED_CONCLUSION][SKIP] session=%s already done", self.session_id)
            return

        logger.info("[FORCED_CONCLUSION][START] session=%s", self.session_id)

        # Determine conclusion reason
        conclusion_reason = state.conclusion_reason or "timer_expired"

        # Get session duration
        try:
            duration_minutes = await self._get_session_duration_minutes()
        except Exception:
            duration_minutes = 30

        # Call LLM with forced_conclusion mode
        result = await database_sync_to_async(ModerationService.call_llm_for_conclusion)(
            summary_in=state.summary,
            conclusion_reason=conclusion_reason,
            session_duration_minutes=duration_minutes,
        )

        # Execute TTS message
        if result.get("message_to_say"):
            await self._execute_tts_message(result["message_to_say"])

        # Mark as done
        state.forced_conclusion_done = True
        state.summary = result.get("updated_summary", state.summary)
        await database_sync_to_async(save_moderation_state)(self.session_id, state)

        logger.info("[FORCED_CONCLUSION][END] session=%s", self.session_id)

    @database_sync_to_async
    def _get_session_duration_minutes(self) -> int:
        """Calcola la durata della sessione in minuti."""
        from apps.sessions.models import Session
        from django.utils import timezone

        try:
            session = Session.objects.get(pk=self.session_id)
            if session.started_at:
                delta = timezone.now() - session.started_at
                return int(delta.total_seconds() / 60)
        except Session.DoesNotExist:
            pass
        return 30  # Default

    @database_sync_to_async
    def _set_conclusion_reason(self, reason: str) -> None:
        """Imposta il motivo della conclusione nello stato di moderazione."""
        from apps.moderation.state import load_moderation_state, save_moderation_state

        state = load_moderation_state(self.session_id)
        state.conclusion_reason = reason
        save_moderation_state(self.session_id, state)

    # -------------------------------------------------------------------------
    # Background trigger task lifecycle
    # -------------------------------------------------------------------------

    async def _maybe_start_trigger_task(self) -> None:
        """
        Avvia il background task per i trigger temporali se:
        - La sessione è in stato ACTIVE
        - Non esiste già un task per questa sessione
        """
        lock = self._get_trigger_lock()
        async with lock:
            if self.session_id in self._trigger_tasks:
                return

            try:
                session_state = await self._get_session_state(self.session_id)
            except Exception:
                return

            if session_state != "ACTIVE":
                return

            # Inizializza il timer per NO_PUSH (se non già impostato)
            await self._mark_any_activity()

            task = asyncio.create_task(self._trigger_loop(self.session_id))
            self._trigger_tasks[self.session_id] = task
            logger.info(
                "[TRIGGER_TASK][START] session=%s",
                self.session_id,
            )

    async def _maybe_stop_trigger_task(self) -> None:
        """
        Ferma il background task per i trigger temporali se esiste.
        Chiamato quando l'ultimo client si disconnette.
        """
        lock = self._get_trigger_lock()
        async with lock:
            task = self._trigger_tasks.pop(self.session_id, None)
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                logger.info(
                    "[TRIGGER_TASK][STOP] session=%s",
                    self.session_id,
                )

    async def _trigger_loop(self, session_id: str) -> None:
        """
        Loop che ogni 5s valuta i trigger temporali.

        - Se nessuno sta parlando e ci sono messaggi, li esegue
        - Se qualcuno sta parlando e ci sono messaggi TTS, li accoda
        - Svuota la coda se IDLE e ci sono messaggi pendenti
        - Se timer 30 scade, transiziona la sessione a CONCLUSION
        """
        logger.info("[TRIGGER_LOOP][STARTED] session=%s", session_id)

        while True:
            try:
                await asyncio.sleep(5)

                logger.debug("[TRIGGER_LOOP][TICK] session=%s", session_id)

                try:
                    session_phase = await self._get_session_state(session_id)
                except Exception as e:
                    logger.warning("[TRIGGER_LOOP][GET_STATE_ERROR] session=%s error=%s", session_id, e)
                    continue

                logger.debug("[TRIGGER_LOOP][PHASE] session=%s phase=%s", session_id, session_phase)

                # Valuta trigger temporali
                try:
                    trig_result = await database_sync_to_async(evaluate_time_based_triggers)(
                        session_id=session_id,
                        session_phase=session_phase,
                    )
                except Exception as e:
                    logger.error("[TRIGGER_LOOP][EVAL_ERROR] session=%s error=%s", session_id, e, exc_info=True)
                    continue

                logger.info(
                    "[TRIGGER_LOOP][RESULT] session=%s messages=%d transition=%s",
                    session_id, len(trig_result.static_messages_to_speak), trig_result.should_transition_to_conclusion
                )

                # Esegui/accoda i messaggi
                # Se should_transition_to_conclusion, passa il flag ai messaggi accodati
                message_was_queued = False
                if trig_result.static_messages_to_speak:
                    message_was_queued = await self._execute_static_messages(
                        trig_result.static_messages_to_speak,
                        trigger_conclusion=trig_result.should_transition_to_conclusion,
                    )

                # Gestione transizione a CONCLUSION (timer 30 scaduto via background)
                # NON transizionare se il messaggio TTS è stato accodato - la transizione
                # avverrà quando il messaggio viene eseguito in _flush_pending_tts_messages
                if trig_result.should_transition_to_conclusion and not message_was_queued:
                    # Set the reason for conclusion before transitioning
                    await self._set_conclusion_reason("timer_expired")
                    transitioned = await database_sync_to_async(self._transition_session_to_conclusion)()
                    if transitioned:
                        logger.info("[TRIGGER_LOOP][TRANSITION] session=%s -> CONCLUSION", session_id)
                        await self.channel_layer.group_send(
                            f"sessions_{session_id}",
                            {
                                "type": "sessions.event",
                                "event_type": "STATE_CHANGED",
                                "new_state": "CONCLUSION",
                            },
                        )
                        # Execute FORCED_CONCLUSION immediately
                        await self._execute_forced_conclusion()

                # Svuota coda messaggi pendenti se IDLE
                await self._flush_pending_tts_messages()

            except asyncio.CancelledError:
                logger.info("[TRIGGER_LOOP][CANCELLED] session=%s", session_id)
                raise
            except Exception as e:
                logger.error("[TRIGGER_LOOP][ERROR] session=%s error=%s", session_id, e, exc_info=True)

    async def _execute_static_messages(
        self,
        messages: list,
        trigger_conclusion: bool = False,
    ) -> bool:
        """
        Esegue i messaggi statici in base al flag use_tts.

        - use_tts=True: TTS audio via WebRTC (o accodato se qualcuno sta parlando)
        - use_tts=False: solo testo via WebSocket

        Args:
            messages: Lista di StaticMessage da eseguire
            trigger_conclusion: Se True, i messaggi TTS accodati avranno trigger_conclusion=True

        Returns:
            True se almeno un messaggio TTS è stato accodato (non eseguito subito), False altrimenti
        """
        from apps.turns.services import TurnManager
        from apps.moderation.triggers import StaticMessage
        from apps.moderation.pending_messages import enqueue_message

        message_was_queued = False

        for msg in messages:
            if not isinstance(msg, StaticMessage):
                continue

            if msg.use_tts:
                # Verifica se qualcuno sta parlando
                state = TurnManager.get_state_only(self.session_id)
                if state and state.state != "IDLE":
                    # Accoda il messaggio (con trigger_conclusion se applicabile)
                    enqueue_message(
                        self.session_id,
                        msg.text,
                        "TRIGGER",
                        trigger_conclusion=trigger_conclusion,
                    )
                    logger.info(
                        "[TRIGGER][QUEUED] session=%s text=%s trigger_conclusion=%s",
                        self.session_id, msg.text[:50], trigger_conclusion
                    )
                    message_was_queued = True
                else:
                    # Esegui TTS immediatamente
                    await self._execute_tts_message(msg.text)
            else:
                # Solo testo, invia via WebSocket
                payload = {"text": msg.text, "use_tts": False}
                if msg.trigger_type:
                    payload["trigger_type"] = msg.trigger_type
                await self.channel_layer.group_send(
                    self.group_name,
                    {
                        "type": "turns.event",
                        "event_type": "STATIC_MESSAGE",
                        "payload": payload,
                    },
                )

        return message_was_queued

    async def _execute_tts_message(self, text: str) -> None:
        """
        Esegue un singolo messaggio TTS via WebRTC.
        Apre turno AI, riproduce audio, chiude turno.
        """
        from apps.turns.services import TurnManager

        logger.info("[TTS_MESSAGE][START] session=%s text=%s", self.session_id, text[:50])

        ai_start_res = TurnManager.ai_start(self.session_id)
        if not ai_start_res.success:
            logger.warning("[TTS_MESSAGE][AI_START_FAILED] session=%s error=%s", self.session_id, ai_start_res.error_code)
            return

        await self._mark_any_activity()
        await self._broadcast_events(ai_start_res.events)

        # Set AI as speaker in audio hub
        hub = get_hub(self.session_id)
        hub.init_ai_track()
        hub.set_speaker(AI_MODERATOR_ID)

        try:
            # TTS streaming
            logger.info("[TTS_MESSAGE][TTS_START] session=%s", self.session_id)
            tts = TTSService()
            tts_result = await tts.synthesize_stream(
                text=text,
                on_audio_chunk=lambda pcm, samples, sr: self._inject_ai_audio(hub, pcm, samples, sr)
            )
            logger.info("[TTS_MESSAGE][TTS_DONE] session=%s success=%s error=%s", self.session_id, tts_result.success, tts_result.error)

            if not tts_result.success:
                logger.warning("[TTS_MESSAGE][TTS_FAILED] session=%s error=%s fallback to text", self.session_id, tts_result.error)
                await self.channel_layer.group_send(
                    self.group_name,
                    {
                        "type": "turns.event",
                        "event_type": "STATIC_MESSAGE",
                        "payload": {"text": text, "use_tts": False},
                    },
                )

            # Append to transcript
            _append_to_session_transcript(self.session_id, {
                "type": "ai",
                "text": text,
                "trigger": "time_based",
                "timestamp": datetime.utcnow().isoformat()
            })

        except Exception as e:
            logger.error("[TTS_MESSAGE][ERROR] session=%s error=%s", self.session_id, e, exc_info=True)

        finally:
            # End AI turn
            hub.set_speaker(None)
            ai_end_res = TurnManager.ai_end(self.session_id)
            await self._mark_any_activity()
            await self._broadcast_events(ai_end_res.events)

            # Se ai_end ha aperto una finestra di prenotazione, schedula il timer
            for ev in ai_end_res.events:
                if ev.type == "RESERVATION_WINDOW_STARTED":
                    asyncio.create_task(
                        self._schedule_reservation_expiration(
                            session_id=self.session_id,
                            user_id=ev.payload["user_id"],
                        )
                    )

            logger.info("[TTS_MESSAGE][END] session=%s", self.session_id)

    async def _flush_pending_tts_messages(self) -> None:
        """
        Svuota la coda dei messaggi TTS pendenti se il turno è IDLE.
        Gestisce anche trigger_conclusion per transizionare a CONCLUSION dopo TTS.
        """
        from apps.turns.services import TurnManager
        from apps.moderation.pending_messages import dequeue_all_messages, has_pending_messages

        if not has_pending_messages(self.session_id):
            return

        state = TurnManager.get_state_only(self.session_id)
        if state and state.state != "IDLE":
            return

        pending = dequeue_all_messages(self.session_id)
        for msg in pending:
            await self._execute_tts_message(msg.text)

            # Se il messaggio aveva trigger_conclusion=True, transiziona a CONCLUSION
            if msg.trigger_conclusion:
                transitioned = await self._transition_session_to_conclusion()
                if transitioned:
                    await self.channel_layer.group_send(
                        f"sessions_{self.session_id}",
                        {
                            "type": "sessions.event",
                            "event_type": "STATE_CHANGED",
                            "new_state": "CONCLUSION",
                        },
                    )