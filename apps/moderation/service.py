import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Any
import json

from django.conf import settings
from openai import OpenAI  # client ufficiale OpenAI

logger = logging.getLogger(__name__)

from .state import (
    ModerationState,
    load_moderation_state,
    save_moderation_state,
    last_intervention_for_reason,
)
from .metrics import compute_participation_metrics, DEFAULT_MIN_ELAPSED_SECONDS
from . import prompts as moderation_prompts

from apps.sessions.event_log import persist_event_async
from apps.tasks.base import TaskDefinition
from apps.tasks.registry import get_task


def _output_language() -> str:
    """Lingua di output del moderatore, da env. Default Italian."""
    return getattr(settings, "MODERATOR_OUTPUT_LANGUAGE", "Italian")


def _resolve_task(task_key: Optional[str], session_id: Optional[str | int] = None) -> TaskDefinition:
    """
    Risolve il TaskDefinition da usare per costruire i prompt.

    Se `task_key` è fornito, lo usa direttamente. Altrimenti lo ricava
    dal `session.context` tramite `session_id`. Se nessuno dei due è
    disponibile, usa il primo task registrato come fallback (solo per
    test che chiamano direttamente i metodi privati senza contesto).
    """
    if task_key:
        return get_task(task_key)
    if session_id is not None:
        from apps.sessions.models import Session
        context = Session.objects.values_list("context", flat=True).get(id=session_id)
        return get_task(context)
    # Fallback per test che chiamano direttamente i metodi privati senza
    # contesto. In produzione l'orchestrator passa sempre task_key.
    logger.warning("[MODERATION] _resolve_task senza task_key né session_id")
    return get_task("murder_mystery")

# Parametri configurabili (in seguito si possono spostare in settings)
AI_INTERVENTION_COOLDOWN = timedelta(seconds=60)
COOLDOWN_BYPASS_REASONS = {"conflict", "user_request"}

# Reason "responsivi" che bypassano il filtro score: una volta classificato
# il turno come conflict (insulto) o user_request (richiesta esplicita al
# moderatore), l'intervento e' dovuto a prescindere dalla gravita percepita.
# Lo score in questi casi guida solo la modulazione del tono del messaggio,
# non la decisione di parlare. Simmetrico a COOLDOWN_BYPASS_REASONS.
SCORE_BYPASS_REASONS = {"conflict", "user_request"}

# Soglia minima di intervention_score per parlare nei reason "discrezionali"
# (off_topic, monopolization, exclusion, ground_rule_violation). Allineata
# alla scala di gravita nel prompt: 0.4 corrisponde a "situazione da
# monitorare ma non critica" — il minimo della fascia di intervento.
# Reason in SCORE_BYPASS_REASONS bypassano questa soglia.
MIN_INTERVENTION_SCORE = 0.4

# Cooldown per-reason: i reason cumulativi richiedono attese più lunghe
# perché il fenomeno (turn count / speaking time) decade lentamente.
# Heron (1999): minimum intervention principle (upper bound conceptual).
# Valore 4min scelto per analogia con il 4-minute visualization refresh
# interval di Houtti et al. (2025) "Observe, Ask, Intervene" — analogia,
# non adozione diretta (il paper non definisce un cooldown tra interventi).
COOLDOWN_OVERRIDES = {
    "monopolization": timedelta(minutes=4),
    "exclusion": timedelta(minutes=4),
}

class HardModerationAction(str, Enum):
    """
    Azione di moderazione "hard" decisa dal motore trigger PRIMA della chiamata LLM.
    """
    NONE = "none"
    FORCED_CONCLUSION = "forced_conclusion"


@dataclass
class ModerationResult:
    """
    Risultato della moderazione alla fine di un turno umano.
    """
    ai_should_speak: bool
    ai_message: Optional[str]
    updated_state: ModerationState


class ModerationService:
    """
    Servizio che incapsula:
    - chiamata LLM (hard/soft);
    - aggiornamento del riassunto;
    - decisione finale se il moderatore deve parlare.
    """

    @classmethod
    def handle_human_turn_ended(
        cls,
        *,
        session_id: int | str,
        user_id: int | str,
        last_turn_text: str,
        session_phase: str,            # es. "ACTIVE", "CONCLUSION"
        hard_action: HardModerationAction,
        speaker_name: Optional[str] = None,
        task_key: Optional[str] = None,
    ) -> ModerationResult:
        """
        Chiamato alla fine di ogni turno umano, DOPO che:
        - il turno è stato chiuso dal TurnManager;
        - i trigger sono stati valutati;
        - eventuali trigger con messaggi fissi sono già stati gestiti.

        `hard_action` indica se questo turno scatena:
        - nessun intervento LLM obbligatorio (NONE),
        - una conclusione obbligatoria (FORCED_CONCLUSION).
        """
        state = load_moderation_state(session_id)

        # Cattura snapshot prima della mutazione: serviranno per l'event log
        # (DiscussionEvent.metadata.summary_at_decision e duration_s)
        summary_in_for_event = state.summary
        turn_started_at_for_event = state.current_turn_started_at
        turn_duration_s_for_event = 0.0

        # Accumula speaking time del turno appena chiuso, se abbiamo un
        # timestamp di inizio (settato da record_human_turn_start).
        # Se manca (es. reconnection mid-turn, test che chiamano direttamente),
        # il delta è 0 e non aggiorniamo lo state.
        if speaker_name and state.current_turn_started_at is not None:
            delta_seconds = (
                datetime.utcnow() - state.current_turn_started_at
            ).total_seconds()
            if delta_seconds > 0:
                state.speaking_time_per_participant[speaker_name] = (
                    state.speaking_time_per_participant.get(speaker_name, 0.0)
                    + delta_seconds
                )
                turn_duration_s_for_event = delta_seconds
            state.current_turn_started_at = None

        # Elapsed seconds dalla sessione (per min_time_reached). Default a 0
        # se session_started_at non è ancora stato settato (sessione inattiva
        # o test diretti). Difensivo contro state Redis pre-esistente
        # con tz-aware datetime: strippa la tz prima della sottrazione.
        elapsed_seconds = 0.0
        if state.session_started_at is not None:
            started_at = state.session_started_at
            if started_at.tzinfo is not None:
                started_at = started_at.replace(tzinfo=None)
            elapsed_seconds = (datetime.utcnow() - started_at).total_seconds()

        # 1) Determinare la modalità di chiamata LLM in base a hard_action
        mode = cls._decide_llm_mode(hard_action, session_phase)

        # 2) Chiamare il LLM (ora collegato ad Azure)
        llm_output = cls._call_llm(
            summary_in=state.summary,
            last_turn=last_turn_text,
            mode=mode,
            session_phase=session_phase,
            speaker_name=speaker_name,
            speaking_time_per_participant=state.speaking_time_per_participant,
            elapsed_seconds=elapsed_seconds,
            interventions_log=state.interventions_log,
            task_key=task_key,
        )

        # 3) Aggiornare il riassunto in ogni caso
        state.summary = llm_output["updated_summary"]

        # 4) Decidere se l'AI deve parlare davvero (regole backend + hard/soft)
        min_time_reached = elapsed_seconds >= DEFAULT_MIN_ELAPSED_SECONDS
        ai_should_speak, ai_message = cls._decide_ai_intervention(
            state=state,
            llm_should_speak=llm_output.get("should_ai_speak", False),
            llm_message=llm_output.get("message_to_say"),
            llm_reason=llm_output.get("reason"),
            llm_score=llm_output.get("intervention_score"),  # opzionale
            session_phase=session_phase,
            mode=mode,
            min_time_reached=min_time_reached,
        )

        # 5) Se l'AI parlerà in normal mode, aggiornare contatori e log
        # (forced_conclusion non consuma il budget interventi)
        if ai_should_speak and mode == "normal":
            state.ai_interventions_count += 1
            state.last_ai_intervention_at = datetime.utcnow()
            state.interventions_log.append({
                "ts": datetime.utcnow().isoformat(),
                "reason": llm_output.get("reason", "unknown"),
                "score": llm_output.get("intervention_score", 0.0),
                "speaker": speaker_name,
                "message": ai_message,
            })

        # 6) Se forced_conclusion e AI ha parlato, setta il flag
        if mode == "forced_conclusion" and ai_should_speak:
            state.forced_conclusion_done = True

        # 7) Salvare lo stato aggiornato
        save_moderation_state(session_id, state)

        # 8) Persistenza event log (DiscussionEvent) — fire-and-forget,
        # non blocca il caller. Se fallisce, log e proseguiamo.
        cls._fire_persist_events(
            session_id=session_id,
            speaker_name=speaker_name,
            last_turn_text=last_turn_text,
            turn_duration_s=turn_duration_s_for_event,
            turn_started_at=turn_started_at_for_event,
            summary_after_turn=state.summary,
            summary_at_decision=summary_in_for_event,
            llm_output=llm_output,
            ai_should_speak=ai_should_speak,
            ai_message=ai_message,
            min_time_reached=min_time_reached,
            mode=mode,
            session_phase=session_phase,
        )

        return ModerationResult(
            ai_should_speak=ai_should_speak,
            ai_message=ai_message,
            updated_state=state,
        )

    @staticmethod
    def _diagnose_block_reason(
        *,
        llm_should_speak: bool,
        llm_reason: Optional[str],
        llm_score: Optional[float],
        ai_should_speak: bool,
        min_time_reached: bool,
        session_phase: str,
        state: ModerationState,
    ) -> Optional[str]:
        """Replica la logica di _decide_ai_intervention per attribuire la
        ragione del block, quando ai_should_speak=False ma il LLM voleva
        parlare. Solo a fini di telemetry/event log: NON modifica nulla.
        """
        if ai_should_speak:
            return None
        if not llm_should_speak:
            # Il LLM stesso non voleva parlare (reason=all_ok o no message).
            return None
        if llm_reason in {"monopolization", "exclusion"} and not min_time_reached:
            return "min_time_not_reached"
        if llm_reason not in SCORE_BYPASS_REASONS:
            if llm_score is not None and llm_score < MIN_INTERVENTION_SCORE:
                return "min_score"
        if llm_reason not in COOLDOWN_BYPASS_REASONS:
            last_for_reason = last_intervention_for_reason(state, llm_reason)
            if last_for_reason is not None:
                last_ts = datetime.fromisoformat(last_for_reason["ts"])
                cooldown = COOLDOWN_OVERRIDES.get(
                    llm_reason, AI_INTERVENTION_COOLDOWN
                )
                if datetime.utcnow() - last_ts < cooldown:
                    return "cooldown"
        if session_phase != "ACTIVE":
            return "not_active_phase"
        return "unknown"

    @classmethod
    def _fire_persist_events(
        cls,
        *,
        session_id,
        speaker_name: Optional[str],
        last_turn_text: str,
        turn_duration_s: float,
        turn_started_at: Optional[datetime],
        summary_after_turn: str,
        summary_at_decision: str,
        llm_output: dict,
        ai_should_speak: bool,
        ai_message: Optional[str],
        min_time_reached: bool,
        mode: str,
        session_phase: str,
    ) -> None:
        """Fire-and-forget di 2 eventi: human_turn + ai_intervention.

        Usa asyncio.create_task se siamo in event loop async (production
        Daphne), altrimenti fa write sincrono via persist_event_sync (test).
        """
        # Costruisce metadata
        human_meta = {
            "duration_s": round(turn_duration_s, 3),
            "turn_started_at": (
                turn_started_at.isoformat() if turn_started_at else None
            ),
            "summary_after_this_turn": summary_after_turn,
            "empty_transcription": not (last_turn_text or "").strip(),
        }

        llm_reason = llm_output.get("reason", "unknown")
        llm_score = llm_output.get("intervention_score", 0.0)
        llm_should_speak = llm_output.get("should_ai_speak", False)
        block_reason = cls._diagnose_block_reason(
            llm_should_speak=llm_should_speak,
            llm_reason=llm_reason,
            llm_score=llm_score,
            ai_should_speak=ai_should_speak,
            min_time_reached=min_time_reached,
            session_phase=session_phase,
            # Usiamo state caricato fresh per avere interventions_log corrente
            state=load_moderation_state(session_id),
        )

        ai_meta = {
            "reason": llm_reason,
            "score": float(llm_score) if llm_score is not None else None,
            "was_played": ai_should_speak,
            "block_reason": block_reason,
            "summary_at_decision": summary_at_decision,
            "mode": mode,
        }
        # Per ai_intervention il messaggio "intended" del LLM va in content
        # (utile per debug anche se bloccato)
        ai_content = (
            ai_message
            if ai_should_speak
            else (llm_output.get("message_to_say") or "")
        )

        # Determina se siamo in event loop async (Daphne) o sync (test/CLI)
        try:
            asyncio.get_running_loop()
            running_async = True
        except RuntimeError:
            running_async = False

        if running_async:
            asyncio.create_task(persist_event_async(
                session_id=session_id,
                event_type="human_turn",
                speaker_name=speaker_name,
                content=last_turn_text or "",
                metadata=human_meta,
            ))
            asyncio.create_task(persist_event_async(
                session_id=session_id,
                event_type="ai_intervention",
                speaker_name=speaker_name,  # speaker che ha innescato
                content=ai_content,
                metadata=ai_meta,
            ))
        else:
            from apps.sessions.event_log import persist_event_sync
            persist_event_sync(
                session_id=session_id,
                event_type="human_turn",
                speaker_name=speaker_name,
                content=last_turn_text or "",
                metadata=human_meta,
            )
            persist_event_sync(
                session_id=session_id,
                event_type="ai_intervention",
                speaker_name=speaker_name,
                content=ai_content,
                metadata=ai_meta,
            )

    @classmethod
    def record_human_turn_start(
        cls,
        *,
        session_id: int | str,
        speaker_name: Optional[str],
    ) -> None:
        """
        Registra l'istante di inizio di un turno umano. Chiamato dal turn
        consumer quando state transita a HUMAN_SPEAKING. Il delta verrà
        accumulato in speaking_time_per_participant via
        record_human_turn_end (o handle_human_turn_ended, idempotente).
        """
        if not speaker_name:
            return
        state = load_moderation_state(session_id)
        state.current_turn_started_at = datetime.utcnow()
        save_moderation_state(session_id, state)

    @classmethod
    def record_human_turn_end(
        cls,
        *,
        session_id: int | str,
        speaker_name: Optional[str],
    ) -> None:
        """
        Accumula lo speaking_time del turno appena terminato e resetta
        current_turn_started_at.

        Chiamato dal turn consumer in `_handle_end_speak` **prima** del
        guard mod-OFF: garantisce che lo speaking_time venga accumulato
        anche quando la pipeline LLM viene saltata (no-moderator mode).

        Idempotente: se chiamata di nuovo dopo che current_turn_started_at
        è già None (es. da handle_human_turn_ended in mod ON), no-op.
        Coerente con lo stesso blocco in handle_human_turn_ended che ora
        risulta no-op se questa funzione è stata chiamata prima.
        """
        if not speaker_name:
            return
        state = load_moderation_state(session_id)
        if state.current_turn_started_at is None:
            return
        delta_seconds = (
            datetime.utcnow() - state.current_turn_started_at
        ).total_seconds()
        if delta_seconds > 0:
            state.speaking_time_per_participant[speaker_name] = (
                state.speaking_time_per_participant.get(speaker_name, 0.0)
                + delta_seconds
            )
        state.current_turn_started_at = None
        save_moderation_state(session_id, state)

    @classmethod
    def _decide_llm_mode(
        cls,
        hard_action: HardModerationAction,
        session_phase: str,
    ) -> str:
        """
        Traduce l'azione hard in una modalità per il prompt LLM.
        """
        if hard_action == HardModerationAction.FORCED_CONCLUSION:
            return "forced_conclusion"
        return "normal"

    @staticmethod
    def _extract_last_interventions_by_reason(
        interventions_log: list[dict],
    ) -> dict[str, dict]:
        """
        Per i reason cumulativi (monopolization, exclusion), estrae l'ultimo
        intervento dal log con `message` e `minutes_ago`. Ritorna {} se nessuno.
        Off_topic/conflict/user_request sono puntuali e non vanno in memoria.
        """
        cumulative_reasons = ("monopolization", "exclusion")
        result: dict[str, dict] = {}
        now = datetime.utcnow()
        for reason in cumulative_reasons:
            for entry in reversed(interventions_log):
                if entry.get("reason") == reason:
                    last_ts = datetime.fromisoformat(entry["ts"])
                    minutes_ago = (now - last_ts).total_seconds() / 60.0
                    result[reason] = {
                        "message": entry.get("message", ""),
                        "minutes_ago": round(minutes_ago, 1),
                    }
                    break
        return result

    @classmethod
    def _build_openai_client(cls) -> OpenAI:
        """
        Crea un client OpenAI usando la chiave configurata nelle settings.
        """
        return OpenAI(api_key=settings.OPENAI_API_KEY)

    @classmethod
    def _call_llm(
        cls,
        *,
        summary_in: str,
        last_turn: str,
        mode: str,
        session_phase: str,
        speaker_name: Optional[str] = None,
        speaking_time_per_participant: Optional[dict[str, float]] = None,
        elapsed_seconds: float = 0.0,
        interventions_log: Optional[list[dict]] = None,
        task_key: Optional[str] = None,
    ) -> dict:
        """
        Chiamata al LLM secondo il contratto stabilito.

        Deve SEMPRE restituire un dict con:
        - updated_summary (string)
        - should_ai_speak (bool)
        - message_to_say (string o None)
        - reason (string)
        - intervention_score (float 0-1)
        """

        # Summary "di sicurezza" in caso di fallback
        base_updated_summary = (summary_in + " " + last_turn).strip()

        # 1) Preparazione input strutturato per il modello
        if speaking_time_per_participant is None:
            speaking_time_per_participant = {}
        if interventions_log is None:
            interventions_log = []

        total_speaking_time_s = (
            sum(speaking_time_per_participant.values())
            if speaking_time_per_participant
            else 0.0
        )

        task = _resolve_task(task_key)

        participation_metrics = compute_participation_metrics(
            speaking_time_per_participant,
            elapsed_seconds=elapsed_seconds,
        )
        last_by_reason = cls._extract_last_interventions_by_reason(interventions_log)

        # Quando min_time_reached=False, il prompt dice di ignorare
        # monopolization/exclusion. gpt-4o-mini pero' tende a rispettare i
        # nomi nelle liste over/under_participators come segnale strutturato
        # forte, anche quando la regola condizionale lo proibisce. Quindi
        # nel payload inviato al modello azzeriamo le due liste finche' il
        # min_time non e' raggiunto: il modello vede liste vuote e applica
        # naturalmente la sua altra regola ("se entrambe vuote, ignora").
        # La metrica originale resta invariata per logging/uso interno.
        payload_metrics = dict(participation_metrics)
        if not payload_metrics.get("min_time_reached"):
            payload_metrics["over_participators"] = []
            payload_metrics["under_participators"] = []

        language = _output_language()

        llm_input = {
            "mode": mode,
            "scenario": task.llm_scenario_payload(mode, language=language),
            "discussion": {
                "summary": summary_in,
                "last_turn": last_turn,
                "last_speaker": speaker_name,
            },
            "participants": {
                "count": (
                    len(speaking_time_per_participant)
                    if speaking_time_per_participant
                    else 3
                ),
                "names": list(speaking_time_per_participant.keys()),
            },
            "participation_metrics": payload_metrics,
            "last_interventions_by_reason": last_by_reason,
            "session": {
                "phase": session_phase,
                "elapsed_seconds": round(elapsed_seconds, 1),
                "total_speaking_time_s": round(total_speaking_time_s, 1),
            },
            "language": language,
        }

        logger.info(
            "[MODERATION][LLM][REQUEST] mode=%s speaker=%s phase=%s transcript=%r",
            mode,
            speaker_name,
            session_phase,
            last_turn,
        )

        # 2) Tentativo di chiamata reale verso OpenAI
        try:
            client = cls._build_openai_client()

            system_prompt = cls._build_system_prompt(mode, task=task)

            response = client.chat.completions.create(
                model=settings.OPENAI_LLM_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": json.dumps(llm_input, ensure_ascii=False),
                    },
                ],
                temperature=0.4,
                max_tokens=2048,
                response_format={"type": "json_object"},
            )

            # content è una stringa JSON (JSON mode)
            raw_output = response.choices[0].message.content
            if isinstance(raw_output, list):
                # In caso di contenuto multi-parte (non comune qui), si concatena
                raw_output = "".join(part.get("text", "") for part in raw_output)

        except Exception as e:
            # In caso di errore di rete/API, si torna a un fallback locale
            logger.warning("[MODERATION][LLM][ERROR] mode=%s error=%s", mode, str(e))
            return cls._fallback_llm_output(mode, base_updated_summary, task=task)

        # 3) Parsing e normalizzazione dell'output del modello
        try:
            parsed: dict[str, Any] = json.loads(raw_output)
        except Exception as e:
            # Se il modello non restituisce JSON valido, si applica il fallback
            logger.warning(
                "[MODERATION][LLM][PARSE_ERROR] mode=%s raw_output=%r error=%s",
                mode, raw_output, str(e)
            )
            return cls._fallback_llm_output(mode, base_updated_summary, task=task)

        updated_summary = parsed.get("updated_summary", summary_in)
        message_to_say = parsed.get("message_to_say")
        reason = parsed.get("reason", "unknown")
        intervention_score_raw = parsed.get("intervention_score", 0.0)

        try:
            intervention_score = float(intervention_score_raw)
        except (TypeError, ValueError):
            intervention_score = 0.0

        # should_ai_speak non e' piu' un campo prodotto dal modello (Feature 2.6):
        # lo deriviamo da reason. Il modello valuta, il backend decide.
        should_ai_speak = bool(message_to_say) and reason != "all_ok"

        logger.info(
            "[MODERATION][LLM][RESPONSE] mode=%s should_speak=%s reason=%s score=%.2f message=%r",
            mode,
            should_ai_speak,
            reason,
            intervention_score,
            message_to_say,
        )

        return {
            "updated_summary": updated_summary,
            "should_ai_speak": should_ai_speak,
            "message_to_say": message_to_say,
            "reason": reason,
            "intervention_score": intervention_score,
        }

    @classmethod
    def _fallback_llm_output(
        cls,
        mode: str,
        base_updated_summary: str,
        task: Optional[TaskDefinition] = None,
    ) -> dict:
        """
        Comportamento di riserva se la chiamata LLM fallisce o l'output
        non e' parsabile. Localizzato via settings.MODERATOR_OUTPUT_LANGUAGE.
        """
        logger.warning("[MODERATION][LLM][FALLBACK] mode=%s (using local fallback)", mode)

        if mode == "forced_conclusion":
            if task is None:
                task = _resolve_task(None)
            language = _output_language()
            return {
                "updated_summary": base_updated_summary,
                "should_ai_speak": True,
                "message_to_say": task.fallback_forced_conclusion_body(
                    base_updated_summary, "", language=language
                ),
                "reason": "conclusion_fallback",
                "intervention_score": 1.0,
            }

        # Modalità normale: nessun intervento
        return {
            "updated_summary": base_updated_summary,
            "should_ai_speak": False,
            "message_to_say": None,
            "reason": "all_ok_fallback",
            "intervention_score": 0.0,
        }

    @classmethod
    def _decide_ai_intervention(
        cls,
        *,
        state: ModerationState,
        llm_should_speak: bool,
        llm_message: Optional[str],
        llm_reason: Optional[str],
        llm_score: Optional[float],
        session_phase: str,
        mode: str,
        min_time_reached: bool = False,
    ) -> tuple[bool, Optional[str]]:
        """
        Applica le regole di backend sopra la proposta dell'LLM.

        Casi:

        - mode == "forced_conclusion":
          intervento obbligatorio, si salta il filtro di cooldown/limiti.

        - mode == "normal":
          si usano cooldown, max interventi, eventuale soglia su llm_score.
          Inoltre: i reason cumulativi (monopolization/exclusion) sono
          bloccati finche' min_time_reached non e' True (safety net per
          il caso in cui il modello li classifichi a inizio sessione
          ignorando la regola del prompt).
        """

        if mode == "forced_conclusion":
            # Se il modello non ha fornito un messaggio esplicito,
            # si usa come fallback il riassunto attuale dello stato.
            if not llm_message:
                if state.summary.strip():
                    llm_message = state.summary.strip()
                elif _output_language() == "English":
                    llm_message = "Summing up the discussion so far."
                else:
                    llm_message = "Ricapitolando la discussione finora."

            return True, llm_message

        # Modalità normale: il backend filtra la proposta dell'LLM.

        # 1) Se il modello non propone di parlare (reason=all_ok o messaggio
        # vuoto), non si interviene. should_ai_speak e' derivato da reason
        # e message_to_say in _call_llm (Feature 2.6).
        if not llm_should_speak or not llm_message:
            return False, None

        # 2) Safety net: i reason cumulativi richiedono min_time_reached.
        # Anche se il prompt dice di ignorarli quando False, il modello
        # talvolta li propone basandosi sui nomi visti in over/under
        # (gpt-4o-mini disobbedisce alle regole condizionali). Blocchiamo
        # qui per coerenza con la policy del prompt.
        if llm_reason in {"monopolization", "exclusion"} and not min_time_reached:
            logger.info(
                "[MODERATION][BLOCK] reason=%s but min_time_reached=False",
                llm_reason,
            )
            return False, None

        # 3) Soglia minima di gravita su intervention_score per i reason
        # discrezionali (Feature 2.6). I reason responsivi (conflict,
        # user_request) bypassano: l'intervento e' dovuto a prescindere.
        if llm_reason not in SCORE_BYPASS_REASONS:
            if llm_score is not None and llm_score < MIN_INTERVENTION_SCORE:
                return False, None

        # 3) Cooldown per-reason: confronta col l'ultimo intervento dello
        # STESSO reason (tramite interventions_log). Bypass per conflict
        # e user_request. Reason cumulativi (mono/excl) hanno cooldown più
        # lungo da COOLDOWN_OVERRIDES.
        if llm_reason not in COOLDOWN_BYPASS_REASONS:
            last_for_reason = last_intervention_for_reason(state, llm_reason)
            if last_for_reason is not None:
                last_ts = datetime.fromisoformat(last_for_reason["ts"])
                cooldown = COOLDOWN_OVERRIDES.get(
                    llm_reason, AI_INTERVENTION_COOLDOWN
                )
                if datetime.utcnow() - last_ts < cooldown:
                    return False, None

        # 4) Regole legate alla fase della sessione
        if session_phase != "ACTIVE":
            # In prima battuta si evita che l'AI intervenga fuori da ACTIVE.
            return False, None

        # Se si arriva qui, l'intervento AI è consentito.
        return True, llm_message

    @classmethod
    def call_llm_for_conclusion(
        cls,
        *,
        summary_in: str,
        conclusion_reason: str,  # "timer_expired" o "all_participants_ready"
        session_duration_minutes: int = 30,
        task_key: Optional[str] = None,
    ) -> dict:
        """
        Chiamata LLM dedicata per FORCED_CONCLUSION.

        A differenza di _call_llm(), non richiede last_turn o speaker_name
        perché viene chiamata alla transizione, non dopo un turno.

        Returns dict with:
        - updated_summary
        - should_ai_speak (always True)
        - message_to_say
        - reason
        - intervention_score
        """
        logger.info(
            "[MODERATION][LLM][CONCLUSION_REQUEST] reason=%s duration=%d",
            conclusion_reason,
            session_duration_minutes,
        )

        task = _resolve_task(task_key)

        try:
            client = cls._build_openai_client()

            system_prompt = cls._build_forced_conclusion_system_prompt(task=task)

            language = _output_language()
            llm_input = {
                "mode": "forced_conclusion",
                "summary_in": summary_in,
                "conclusion_reason": conclusion_reason,
                "session_duration_minutes": session_duration_minutes,
                "scenario": task.llm_scenario_payload(
                    "forced_conclusion", language=language
                ),
                "language": language,
            }

            response = client.chat.completions.create(
                model=settings.OPENAI_LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(llm_input, ensure_ascii=False)},
                ],
                temperature=0.5,  # Leggermente più alta per tono più caldo
                max_tokens=2048,
                response_format={"type": "json_object"},
            )

            raw_output = response.choices[0].message.content
            if isinstance(raw_output, list):
                raw_output = "".join(part.get("text", "") for part in raw_output)

        except Exception as e:
            logger.warning("[MODERATION][LLM][CONCLUSION_ERROR] error=%s", str(e))
            return cls._fallback_forced_conclusion(summary_in, conclusion_reason, task=task)

        try:
            parsed = json.loads(raw_output)
        except Exception as e:
            logger.warning(
                "[MODERATION][LLM][CONCLUSION_PARSE_ERROR] raw=%r error=%s",
                raw_output, str(e)
            )
            return cls._fallback_forced_conclusion(summary_in, conclusion_reason, task=task)

        logger.info(
            "[MODERATION][LLM][CONCLUSION_RESPONSE] message=%r",
            parsed.get("message_to_say", "")[:50],
        )

        return {
            "updated_summary": parsed.get("updated_summary", summary_in),
            "message_to_say": parsed.get("message_to_say"),
        }

    @classmethod
    def _build_forced_conclusion_system_prompt(
        cls, task: Optional[TaskDefinition] = None
    ) -> str:
        """Thin dispatcher → apps.moderation.prompts.build_forced_conclusion_prompt.

        Lingua di output letta da settings.MODERATOR_OUTPUT_LANGUAGE.
        """
        if task is None:
            task = _resolve_task(None)
        return moderation_prompts.build_forced_conclusion_prompt(
            task, language=_output_language()
        )

    @classmethod
    def _fallback_forced_conclusion(
        cls,
        summary: str,
        conclusion_reason: str,
        task: Optional[TaskDefinition] = None,
    ) -> dict:
        """
        Messaggio di fallback se la chiamata LLM per conclusion fallisce.
        Il testo task-specifico (es. "selezionate il colpevole") è delegato
        al TaskDefinition. Localizzato via MODERATOR_OUTPUT_LANGUAGE.
        """
        if task is None:
            task = _resolve_task(None)
        message = task.fallback_forced_conclusion_body(
            summary, conclusion_reason, language=_output_language()
        )
        return {
            "updated_summary": summary,
            "message_to_say": message,
        }

    @classmethod
    def _build_normal_mode_prompt(
        cls, task: Optional[TaskDefinition] = None
    ) -> str:
        """Thin dispatcher → apps.moderation.prompts.build_normal_mode_prompt.

        Lingua di output letta da settings.MODERATOR_OUTPUT_LANGUAGE.
        """
        if task is None:
            task = _resolve_task(None)
        return moderation_prompts.build_normal_mode_prompt(
            task, language=_output_language()
        )

    @classmethod
    def _build_system_prompt(
        cls, mode: str, task: Optional[TaskDefinition] = None
    ) -> str:
        """
        Costruisce il system prompt appropriato in base alla modalità.

        Args:
            mode: "normal" o "forced_conclusion"
            task: TaskDefinition da cui estrarre il blocco scenario.

        Returns:
            System prompt string per il modello LLM
        """
        if mode == "forced_conclusion":
            return cls._build_forced_conclusion_system_prompt(task=task)
        # normal e qualsiasi modalità sconosciuta → normal mode
        return cls._build_normal_mode_prompt(task=task)