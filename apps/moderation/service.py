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
)

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

        # Incrementa contatore turni per lo speaker
        if speaker_name:
            state.turns_per_participant[speaker_name] = (
                state.turns_per_participant.get(speaker_name, 0) + 1
            )

        # 1) Determinare la modalità di chiamata LLM in base a hard_action
        mode = cls._decide_llm_mode(hard_action, session_phase)

        # 2) Chiamare il LLM (ora collegato ad Azure)
        llm_output = cls._call_llm(
            summary_in=state.summary,
            last_turn=last_turn_text,
            mode=mode,
            session_phase=session_phase,
            speaker_name=speaker_name,
            turns_per_participant=state.turns_per_participant,
            task_key=task_key,
        )

        # 3) Aggiornare il riassunto in ogni caso
        state.summary = llm_output["updated_summary"]

        # 4) Decidere se l'AI deve parlare davvero (regole backend + hard/soft)
        ai_should_speak, ai_message = cls._decide_ai_intervention(
            state=state,
            llm_should_speak=llm_output.get("should_ai_speak", False),
            llm_message=llm_output.get("message_to_say"),
            llm_reason=llm_output.get("reason"),
            llm_score=llm_output.get("intervention_score"),  # opzionale
            session_phase=session_phase,
            mode=mode,
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
        turns_per_participant: Optional[dict[str, int]] = None,
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
        if turns_per_participant is None:
            turns_per_participant = {}

        total_turns = sum(turns_per_participant.values()) if turns_per_participant else 0

        task = _resolve_task(task_key)

        llm_input = {
            "mode": mode,
            "scenario": task.llm_scenario_payload(mode),
            "discussion": {
                "summary": summary_in,
                "last_turn": last_turn,
                "last_speaker": speaker_name,
            },
            "participants": {
                "count": len(turns_per_participant) if turns_per_participant else 3,
                "turns": turns_per_participant,
            },
            "session": {
                "phase": session_phase,
                "total_turns": total_turns,
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
        should_ai_speak = bool(parsed.get("should_ai_speak", False))
        message_to_say = parsed.get("message_to_say")
        reason = parsed.get("reason", "unknown")
        intervention_score_raw = parsed.get("intervention_score", 0.0)

        try:
            intervention_score = float(intervention_score_raw)
        except (TypeError, ValueError):
            intervention_score = 0.0

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
    ) -> tuple[bool, Optional[str]]:
        """
        Applica le regole di backend sopra la proposta dell'LLM.

        Casi:

        - mode == "forced_conclusion":
          intervento obbligatorio, si salta il filtro di cooldown/limiti.

        - mode == "normal":
          si usano cooldown, max interventi, eventuale soglia su llm_score.
        """

        if mode == "forced_conclusion":
            # Se il modello non ha fornito un messaggio esplicito,
            # si usa come fallback il riassunto attuale dello stato.
            if not llm_message:
                llm_message = state.summary.strip() or "Ricapitolando la discussione finora."

            return True, llm_message

        # Modalità normale: il backend filtra la proposta dell'LLM.

        # 1) Se il modello non propone di parlare, non si interviene.
        if not llm_should_speak or not llm_message:
            return False, None

        # 2) Eventuale soglia su intervention_score (se valorizzato)
        if llm_score is not None and llm_score < 0.7:
            # soglia esemplificativa, da tarare
            return False, None

        # 3) Cooldown minimo tra interventi (bypass per conflict/user_request)
        if llm_reason not in COOLDOWN_BYPASS_REASONS:
            if state.last_ai_intervention_at is not None:
                now = datetime.utcnow()
                if now - state.last_ai_intervention_at < AI_INTERVENTION_COOLDOWN:
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

NON intervenire per:
- Off-topic parziali (aspetta che il gruppo si auto-corregga)
- Silenzi brevi o pause naturali
- Disaccordi civili (sono parte sana della discussione)

## Stile
- Tono: gentile, indiretto, mai autoritario
- Lunghezza: 1-2 frasi (20-30 parole max)
- Esempi: "Lucia, tu cosa ne pensi di questo?" / "Interessante, ma tornando al tema..."

## Come valutare

### Problemi PUNTUALI → guarda SOLO `last_turn`
Per decidere se intervenire su questi problemi, valuta ESCLUSIVAMENTE l'ultimo turno:
- **Off-topic**: L'ultimo turno è fuori tema rispetto allo scenario?
- **Conflitto**: L'ultimo turno contiene toni aggressivi, insulti o attacchi personali?
- **Richiesta diretta**: L'ultimo turno contiene una richiesta esplicita al moderatore?

⚠️ NON usare il `summary` per valutare questi problemi. Il summary è storico e potresti intervenire su problemi già affrontati in turni precedenti.

### Problemi CUMULATIVI → guarda `participants.turns`
Per questi problemi, valuta i contatori numerici dei turni:
- **Monopolizzazione**: Un partecipante ha molti più turni degli altri?
- **Esclusione**: Un partecipante ha zero o pochissimi turni?

⚠️ Valuta questi problemi SOLO se `session.total_turns` >= 6.
Nei primi turni della discussione è normale che la partecipazione sia sbilanciata.
Se total_turns < 6, ignora monopolizzazione ed esclusione.

### A cosa serve il `summary`
Usa il summary SOLO per:
- Capire il contesto generale della discussione
- Generare l'`updated_summary` includendo i nuovi punti emersi dall'ultimo turno

### Punteggio
Assegna un `intervention_score` da 0 a 1:
- 0.0-0.3: Tutto ok, nessun problema
- 0.4-0.6: Situazione da monitorare ma non critica
- 0.7-0.8: Problema evidente, intervento consigliato
- 0.9-1.0: Problema grave (insulti, off-topic totale), intervento necessario

Imposta `should_ai_speak: true` SOLO se `intervention_score >= 0.7`

## Output

Rispondi SEMPRE con un JSON valido:

{
  "updated_summary": "Riassunto aggiornato includendo l'ultimo turno",
  "should_ai_speak": true/false,
  "message_to_say": "Il messaggio da dire (null se should_ai_speak=false)",
  "reason": "monopolization | exclusion | off_topic | conflict | user_request | all_ok",
  "intervention_score": 0.0-1.0
}"""
        return template.replace("__SCENARIO_BLOCK__", scenario_block)

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