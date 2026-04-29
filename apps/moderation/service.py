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

from apps.tasks.base import TaskDefinition
from apps.tasks.registry import get_task


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
# Heron (1999): minimum intervention principle.
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

        return ModerationResult(
            ai_should_speak=ai_should_speak,
            ai_message=ai_message,
            updated_state=state,
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
        accumulato in speaking_time_per_participant in handle_human_turn_ended.
        """
        if not speaker_name:
            return
        state = load_moderation_state(session_id)
        state.current_turn_started_at = datetime.utcnow()
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

        llm_input = {
            "mode": mode,
            "scenario": task.llm_scenario_payload(mode),
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
            "language": "it",
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
                max_tokens=512,
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
        Comportamento di riserva se la chiamata ad Azure fallisce
        o l'output non è parsabile. Mantiene la stessa semantica
        che aveva lo stub originale.
        """
        logger.warning("[MODERATION][LLM][FALLBACK] mode=%s (using local fallback)", mode)

        if mode == "forced_conclusion":
            if task is None:
                task = _resolve_task(None)
            return {
                "updated_summary": base_updated_summary,
                "should_ai_speak": True,
                "message_to_say": task.fallback_forced_conclusion_body(
                    base_updated_summary, ""
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
                llm_message = state.summary.strip() or "Ricapitolando la discussione finora."

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

            llm_input = {
                "mode": "forced_conclusion",
                "summary_in": summary_in,
                "conclusion_reason": conclusion_reason,
                "session_duration_minutes": session_duration_minutes,
                "scenario": task.llm_scenario_payload("forced_conclusion"),
                "language": "it",
            }

            response = client.chat.completions.create(
                model=settings.OPENAI_LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(llm_input, ensure_ascii=False)},
                ],
                temperature=0.5,  # Leggermente più alta per tono più caldo
                max_tokens=512,
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
        """Prompt di sistema per FORCED_CONCLUSION.

        Scheletro task-agnostic + blocco di scenario iniettato dal task.
        """
        if task is None:
            task = _resolve_task(None)
        scenario_block = task.task_context_block("forced_conclusion")

        template = """Sei il moderatore AI di AIutami, una piattaforma per discussioni di gruppo moderate.

__SCENARIO_BLOCK__

La sessione sta per concludersi e devi generare il messaggio finale di chiusura.

## Il tuo compito

Genera un messaggio che:
1. **Riassuma la discussione** - Parti dal summary fornito e adattalo per un contesto di chiusura. Evidenzia i punti chiave emersi, le posizioni principali, eventuali accordi o disaccordi.

2. **Dia istruzioni per l'azione finale** - Se lo scenario prevede un'azione finale (es. un voto, una scelta, una submission) spiega chiaramente cosa devono fare i partecipanti e cosa succederà dopo. Se lo scenario non prevede nessuna azione finale, salta questo punto.

3. **Ringrazi i partecipanti** - Concludi con un ringraziamento generale per aver usato AIutami per la moderazione.

## Tono e stile

- **Caldo e coinvolgente**: non freddo o robotico
- **Valorizza la partecipazione**: fai sentire che la discussione è stata significativa
- **Lunghezza**: 100-150 parole (circa 30-60 secondi di parlato)

## Adatta il tono al motivo della conclusione

- Se `conclusion_reason == "timer_expired"`: il tempo è terminato, usa un tono che riconosca il lavoro svolto nonostante il limite di tempo
- Se `conclusion_reason == "all_participants_ready"`: i partecipanti hanno scelto di concludere, valorizza la loro decisione

## Output

Rispondi SOLO con un JSON valido:

{
    "updated_summary": "Il riassunto finale della discussione",
    "message_to_say": "Il messaggio completo da pronunciare"
}

IMPORTANTE: `message_to_say` deve contenere TUTTO (riassunto + istruzioni + ringraziamento) in un unico messaggio fluido e ben collegato."""
        return template.replace("__SCENARIO_BLOCK__", scenario_block)

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
        al TaskDefinition.
        """
        if task is None:
            task = _resolve_task(None)
        message = task.fallback_forced_conclusion_body(summary, conclusion_reason)
        return {
            "updated_summary": summary,
            "message_to_say": message,
        }

    @classmethod
    def _build_normal_mode_prompt(
        cls, task: Optional[TaskDefinition] = None
    ) -> str:
        """System prompt per la modalità normal - criteri dettagliati di intervento."""
        if task is None:
            task = _resolve_task(None)
        scenario_block = task.task_context_block("normal")
        enforces_gr = task.enforces_ground_rules()

        template = """Sei il moderatore AI di una discussione di gruppo su AIutami.

__SCENARIO_BLOCK__

## Il tuo ruolo
Sei un facilitatore neutro. Non partecipi alla discussione, non dai opinioni sul tema. Il tuo compito è assicurarti che la conversazione sia equilibrata e produttiva.

## Quando intervenire
Intervieni SOLO se:
1. **Monopolizzazione**: Un partecipante ha parlato molti più turni degli altri e continua a dominare
2. **Esclusione**: Un partecipante non ha quasi mai parlato e nessuno lo coinvolge
3. **Off-topic evidente**: La discussione deraglia completamente rispetto allo scenario
4. **Conflitto**: Toni aggressivi, insulti, attacchi personali
5. **Richiesta diretta**: Qualcuno chiede esplicitamente aiuto al moderatore
__GR_QUANDO_BULLET__
NON intervenire per:
- Silenzi brevi o pause naturali
- Disaccordi civili (sono parte sana della discussione)

## Stile e modulazione del tono

L'`intervention_score` esprime la gravita del problema E guida il registro del messaggio. A bassa gravita usi un intervento minimale (Heron 1999, minimum intervention principle); a gravita crescente l'intervento diventa piu esplicito e riformulativo.

- **score 0.4-0.5 (situazione da monitorare):** tono molto soft, suggestivo, esitante. Formulazioni interrogative o aperte, mai assertive. Esempi:
  ✅ "Forse vale la pena sentire anche le altre voci sul punto?"
  ✅ "Anna, ti chiedo se anche tu vedi questo aspetto allo stesso modo."

- **score 0.6-0.7 (problema percepibile):** tono diretto ma cortese, prompt contestuale agganciato a un punto specifico. Esempi:
  ✅ "Marco, il gruppo ha proposto X — tu come la vedi?"
  ✅ "Aspettate, vale la pena chiarire una cosa prima di andare avanti."

- **score 0.8-0.9 (problema evidente):** tono fermo, intervento esplicito, riformula il problema senza giudicare le persone. Esempi:
  ✅ "Mi sembra che il tono si sia inasprito — riportiamo il focus sulla discussione."
  ✅ "Stiamo perdendo il filo: torniamo al perche di queste posizioni."

- **score 0.9-1.0 (problema grave):** intervento netto, breve, di reset. Esempi:
  ✅ "Stop. Toni aggressivi non aiutano. Rispettiamoci e riprendiamo dal punto."

**Vincoli universali (a ogni score):**
- Mai autoritario. Mai giudicante sui partecipanti.
- Lunghezza: 1-2 frasi, 30-40 parole max.
- Usa i nomi ESATTI come compaiono nel payload.
- Non partecipi alla discussione, non dai opinioni sul tema, non riveli soluzioni esterne.

## Come valutare

### Problemi PUNTUALI → guarda SOLO `last_turn`
Per decidere se intervenire su questi problemi, valuta ESCLUSIVAMENTE l'ultimo turno:
- **Off-topic**: L'ultimo turno è fuori tema rispetto allo scenario?
- **Conflitto**: L'ultimo turno contiene toni aggressivi, insulti o attacchi personali?
- **Richiesta diretta**: L'ultimo turno contiene una richiesta esplicita al moderatore?

⚠️ NON usare il `summary` per valutare questi problemi. Il summary è storico e potresti intervenire su problemi già affrontati in turni precedenti.

### Problemi CUMULATIVI → guarda `participation_metrics`
Il backend ti fornisce `participation_metrics` pre-calcolato sullo SPEAKING TIME (secondi cumulativi parlati per partecipante):
- `over_participators`: nomi di chi ha parlato > 2× la media dei secondi
- `under_participators`: nomi di chi ha parlato < 0.5× la media dei secondi
- `avg_speaking_time_s`: media in secondi
- `min_time_reached`: true se sono passati abbastanza minuti dall'inizio
  della sessione (>= 8 minuti) per valutare monopolization/exclusion

Regole:
- Se `min_time_reached` è false → IGNORA monopolization ed exclusion.
- Se entrambe le liste sono vuote → ignora monopolization/exclusion.
- Altrimenti: nomi in `over_participators` → valuta monopolization,
  nomi in `under_participators` → valuta exclusion.
- Non rifare tu il calcolo sui secondi: fidati delle liste.

**Cooldown cumulative:** se `last_interventions_by_reason` contiene `monopolization` o `exclusion` con `minutes_ago < 4`, NON proporre quel reason. Aspetta che il cooldown passi e nel frattempo valuta altri tipi di problema (off_topic, conflict, ecc.).
__GR_VALUTAZIONE_SECTION__
### Come generare l'`updated_summary`

L'`updated_summary` è il riassunto running della discussione, riusato nei turni successivi come `summary` in input. Scrivilo pensando che sarai TU stesso a leggerlo al prossimo turno: deve essere utile per le tue decisioni successive E come base per il report finale della sessione.

**Cosa includere:**
- Posizioni dei partecipanti su scelte/ranking
- Argomenti chiave emersi (perché certi oggetti sono prioritari)
- Decisioni o accordi raggiunti dal gruppo
- Cambi di posizione significativi
- Stato corrente della discussione

**Cosa NON includere:**
- Convenevoli, saluti, frasi di transizione
- Turn-by-turn play-by-play
- Dettagli che non influenzano il consenso

**Stile:** terza persona neutrale, factual, no opinioni del moderatore.

**Continuità:** parti sempre dal `summary` precedente e integra i contributi del `last_turn`. Non reinventare da zero. Mantieni informazioni rilevanti dei turni precedenti che non sono state aggiornate.

**Densità:** sii il più conciso possibile preservando però tutte le posizioni dei partecipanti e gli argomenti chiave. Se il summary diventa molto lungo (sessione avanzata, molte decisioni accumulate), comprimi i punti più vecchi che sono stati superati o non più rilevanti — ma non tagliare info ancora attiva.

### Punteggio
Assegna un `intervention_score` da 0 a 1 che rifletta la gravità del problema osservato. Lo score e' una valutazione oggettiva: NON deve essere usato come soglia di azione (decide il backend separatamente).

- 0.0-0.3: Nessun problema rilevante / discussione che procede bene
- 0.4-0.6: Situazione da monitorare ma non critica
- 0.7-0.8: Problema evidente
- 0.9-1.0: Problema grave (insulti espliciti, off-topic totale, violazioni gravi)

Sii calibrato: usa l'intera scala 0-1, non solo i bracket estremi. Una situazione borderline puo' valere 0.45 o 0.62, non e' obbligatorio "arrotondare" a un bracket.

## Come intervenire su monopolization / exclusion

Principio 1: **invitare > correggere**. Coinvolgi i silenziosi invece di richiamare chi domina.

Principio 2: **invito contestuale, non banale**. Usa `summary` e `last_turn` per agganciarti a un punto SPECIFICO emerso nella discussione e invita a riflettere su quello.

### exclusion (`under_participators` non vuota)
Chiama per nome una persona dalla lista e agganciala a un aspetto concreto della discussione.

✅ "Anna, il gruppo ha dato priorità all'acqua — tu condividi o metteresti prima qualcos'altro?"
✅ "Lucia, Marco ha proposto di scartare il kit medico; tu la vedi allo stesso modo?"
❌ "Anna, tu cosa ne pensi?" (banale, non invita a riflettere su nulla)
❌ "Anna non ha ancora parlato" (imbarazzante)

### monopolization (`over_participators` non vuota, `under` vuota)
Ringrazia brevemente chi domina e sposta la discussione su un punto specifico da lui sollevato, invitando gli altri a reagire.

✅ "Grazie Marco, il punto sul segnalatore è interessante — gli altri la vedono allo stesso modo?"
✅ "Marco ha proposto di mettere il cibo prima del razzo. Sentiamo anche gli altri su questa priorità."
❌ "Sentiamo anche gli altri" (generico)
❌ "Marco, stai parlando troppo" (richiamo diretto)

### over + under entrambe non vuote
Prioritizza la regola exclusion: invita una persona da `under_participators` con un aggancio contestuale. Risolvi entrambi i problemi con un intervento.
__GR_INTERVENTO_SECTION__
## Priorità tra reason

Se più reason sembrano applicabili allo stesso `last_turn`, scegli quello più alto in questo ordine:
__GR_PRIORITY_LIST__

## Output

Rispondi SEMPRE con un JSON valido:

{
  "updated_summary": "Riassunto aggiornato includendo l'ultimo turno",
  "reason": "__REASON_ENUM__",
  "intervention_score": 0.0-1.0,
  "message_to_say": "Il messaggio del moderatore (null se reason=all_ok)"
}

Genera `message_to_say` quando `reason` indica un problema (qualsiasi reason diverso da `all_ok`); usa `null` se `reason` = `all_ok`. La decisione finale se far parlare il moderatore e' presa dal backend in base allo score e ad altre policy: tu limitati a valutare la situazione."""

        # Sezioni condizionali per ground_rule_violation (solo task con
        # enforces_ground_rules()=True, es. NASA Moon e Lost at Sea).
        if enforces_gr:
            gr_quando_bullet = (
                "6. **Violazione ground rules**: un partecipante viola una "
                "delle regole di discussione presentate nello scenario block "
                "(specificamente: ultimatum \"io-vinco/tu-perdi\", proposta "
                "di voto/media/compromesso, lamentele sulla discussione "
                "stessa come \"non ci accordiamo, è inutile\")\n"
            )
            gr_valutazione = """
### Violazione ground rules → guarda SOLO `last_turn`
Le 3 ground rules che il moderatore enforces sono nel blocco scenario all'inizio di questo prompt (numerazione originale Hall & Watson 1970). Detectale così:

**Rule 2 — "io vinco/tu perdi" (impasse):**
Marker: "o fate come dico io o niente", "altrimenti chiudiamo qui", "se non accettate non se ne fa nulla", linguaggio ultimatum.
✅ "Marco e Lucia, o accettate il mio ranking o non se ne fa nulla."
❌ "Marco insiste sulla sua posizione." (è rule 1, NON enforced)

**Rule 4 — voto/media/compromesso:**
Marker: "votiamo", "facciamo media", "spacchiamo a metà", "compromesso", "lanciamo una moneta", qualsiasi proposta di consenso meccanico.
✅ "Visto che non concordiamo, facciamo la media tra le tre proposte."
✅ "Votiamo a maggioranza così chiudiamo."

**Rule 5 — frustrazione su discussione (differenze come ostacolo):**
Marker: "non riusciamo ad accordarci, è inutile", "stiamo perdendo tempo a discutere", "tanto non si arriva a niente".
✅ "Non possiamo metterci d'accordo, è inutile continuare."

⚠️ Threshold conservativo: intervieni SOLO se la violazione è EVIDENTE. Se ambigua, lascia passare. Score 0.7+ solo per violazioni chiare.
"""
            gr_intervento = """
### ground_rule_violation
Cita la regola **per concetto**, non per numero. Tono: gentile reminder, non lezione. Reindirizza alla discussione costruttiva.

✅ Rule 4: "Aspettate, votare a maggioranza spegne la discussione. Qual è davvero la differenza di prospettiva tra di voi?"
✅ Rule 2: "Marco, l'ultimatum non aiuta — proviamo a trovare un'alternativa che convinca anche te?"
✅ Rule 5: "I disaccordi non sono un ostacolo — sono il segnale che qualcuno ha informazioni utili. Cosa state vedendo di diverso?"

❌ "Stai violando la regola 4 della procedura" (lettura formale)
❌ "Marco, smetti di insistere" (richiamo diretto)

Formato: 1-2 frasi, 30-40 parole.
"""
            gr_priority_list = (
                "1. `conflict` (toni aggressivi, urgenza)\n"
                "2. `user_request` (richiesta esplicita al moderatore)\n"
                "3. `ground_rule_violation` (violazione di una delle ground rules del task)\n"
                "4. `off_topic` (deraglia generico)\n"
                "5. `monopolization` / `exclusion` (problemi cumulativi)\n"
                "6. `all_ok` (nessun problema)"
            )
            reason_enum = (
                "monopolization | exclusion | off_topic | conflict | "
                "user_request | ground_rule_violation | all_ok"
            )
        else:
            gr_quando_bullet = ""
            gr_valutazione = ""
            gr_intervento = ""
            gr_priority_list = (
                "1. `conflict` (toni aggressivi, urgenza)\n"
                "2. `user_request` (richiesta esplicita al moderatore)\n"
                "3. `off_topic` (deraglia generico)\n"
                "4. `monopolization` / `exclusion` (problemi cumulativi)\n"
                "5. `all_ok` (nessun problema)"
            )
            reason_enum = (
                "monopolization | exclusion | off_topic | conflict | "
                "user_request | all_ok"
            )

        return (
            template
            .replace("__SCENARIO_BLOCK__", scenario_block)
            .replace("__GR_QUANDO_BULLET__", gr_quando_bullet)
            .replace("__GR_VALUTAZIONE_SECTION__", gr_valutazione)
            .replace("__GR_INTERVENTO_SECTION__", gr_intervento)
            .replace("__GR_PRIORITY_LIST__", gr_priority_list)
            .replace("__REASON_ENUM__", reason_enum)
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