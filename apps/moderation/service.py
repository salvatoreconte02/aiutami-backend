# apps/moderation/service.py

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Any
import json
import os

from openai import AzureOpenAI  # client ufficiale per Azure OpenAI

logger = logging.getLogger(__name__)

from .state import (
    ModerationState,
    load_moderation_state,
    save_moderation_state,
)

# Parametri configurabili (in seguito si possono spostare in settings)
MAX_AI_INTERVENTIONS_PER_SESSION = 10
AI_INTERVENTION_COOLDOWN = timedelta(seconds=30)
SUMMARY_TURNS_INTERVAL = 1  # DEBUG: forza un riassunto ad ogni turno umano

class HardModerationAction(str, Enum):
    """
    Azione di moderazione "hard" decisa dal motore trigger PRIMA della chiamata LLM.
    """
    NONE = "none"
    FORCED_SUMMARY = "forced_summary"
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
    ) -> ModerationResult:
        """
        Chiamato alla fine di ogni turno umano, DOPO che:
        - il turno è stato chiuso dal TurnManager;
        - i trigger sono stati valutati;
        - eventuali trigger con messaggi fissi sono già stati gestiti.

        `hard_action` indica se questo turno scatena:
        - nessun intervento LLM obbligatorio (NONE),
        - un riassunto intermedio obbligatorio (FORCED_SUMMARY),
        - una conclusione obbligatoria (FORCED_CONCLUSION).
        """
        state = load_moderation_state(session_id)

        # 1) Determinare la modalità di chiamata LLM in base a hard_action
        mode = cls._decide_llm_mode(hard_action, session_phase)

        # 2) Chiamare il LLM (ora collegato ad Azure)
        llm_output = cls._call_llm(
            summary_in=state.summary,
            last_turn=last_turn_text,
            mode=mode,
            session_phase=session_phase,
            speaker_name=speaker_name,
        )

        # 3) Aggiornare il riassunto in ogni caso
        state.summary = llm_output["updated_summary"]

        # Gestione contatore turni dall'ultimo riassunto intermedio
        if mode == "forced_summary":
            state.human_turns_since_last_summary = 0
        else:
            # Il motore trigger esterno userà questo contatore per decidere
            # quando impostare hard_action = FORCED_SUMMARY
            state.human_turns_since_last_summary += 1

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

        # 5) Se l'AI parlerà, aggiornare contatori
        if ai_should_speak:
            state.ai_interventions_count += 1
            state.last_ai_intervention_at = datetime.utcnow()

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

    # -------------------------------------------------------------------------
    # Metodi interni
    # -------------------------------------------------------------------------

    @classmethod
    def _decide_llm_mode(
        cls,
        hard_action: HardModerationAction,
        session_phase: str,
    ) -> str:
        """
        Traduce l'azione hard in una modalità per il prompt LLM.
        """
        if hard_action == HardModerationAction.FORCED_SUMMARY:
            return "forced_summary"
        if hard_action == HardModerationAction.FORCED_CONCLUSION:
            return "forced_conclusion"
        return "normal"

    @classmethod
    def _build_azure_client(cls) -> AzureOpenAI:
        """
        Crea un client AzureOpenAI usando le variabili d'ambiente del container.
        """
        endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
        api_key = os.environ["AZURE_OPENAI_API_KEY"]
        api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")

        return AzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=endpoint,
        )

    @classmethod
    def _call_llm(
        cls,
        *,
        summary_in: str,
        last_turn: str,
        mode: str,
        session_phase: str,
        speaker_name: Optional[str] = None,
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
        llm_input = {
            "mode": mode,
            "summary_in": summary_in,
            "last_turn": last_turn,
            "session_phase": session_phase,
            "language": "it",
            # TODO: recuperare il valore reale dal dominio sessione
            "participants_count": 3,
            "speaker_name": speaker_name,
            "extra_context": {
                # Per future estensioni (scenario, regole speciali, ecc.)
            },
        }

        # Log della request LLM
        logger.info(
            "[MODERATION][LLM][REQUEST] mode=%s speaker=%s phase=%s transcript=%r",
            mode,
            speaker_name,
            session_phase,
            last_turn,
        )

        # 2) Tentativo di chiamata reale verso Azure OpenAI
        try:
            client = cls._build_azure_client()
            deployment = os.environ.get("AZURE_OPENAI_MODEL", "gpt-4o-mini")

            system_prompt = (
                "Sei un moderatore AI di una discussione di gruppo in italiano. "
                "Ricevi in input un oggetto JSON con informazioni sulla sessione. "
                "Devi SEMPRE rispondere con un JSON valido (nessun testo extra), "
                "con la seguente struttura:\n\n"
                "{\n"
                '  "updated_summary": string,\n'
                '  "should_ai_speak": boolean,\n'
                '  "message_to_say": string o null,\n'
                '  "reason": string,\n'
                '  "intervention_score": number tra 0 e 1\n'
                "}\n\n"
                "Regole:\n"
                "- se mode == 'forced_summary': devi generare un breve riassunto neutro e chiaro "
                "  della discussione finora e impostare should_ai_speak=true.\n"
                "- se mode == 'forced_conclusion': devi produrre una conclusione finale, "
                "  invitando i partecipanti a votare/chiudere, e impostare should_ai_speak=true.\n"
                "- se mode == 'normal': decidi tu se intervenire. Se non serve, imposta "
                "  should_ai_speak=false e message_to_say=null.\n"
                "- Lo stile deve essere breve, neutro, rispettoso, adatto a un moderatore."
            )

            response = client.chat.completions.create(
                model=deployment,
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
            )

            # In AzureOpenAI, content è solitamente una stringa JSON
            raw_output = response.choices[0].message.content
            if isinstance(raw_output, list):
                # In caso di contenuto multi-parte (non comune qui), si concatena
                raw_output = "".join(part.get("text", "") for part in raw_output)

        except Exception as e:
            # In caso di errore di rete/API, si torna a un fallback locale
            logger.warning("[MODERATION][LLM][ERROR] mode=%s error=%s", mode, str(e))
            return cls._fallback_llm_output(mode, base_updated_summary)

        # 3) Parsing e normalizzazione dell'output del modello
        try:
            parsed: dict[str, Any] = json.loads(raw_output)
        except Exception as e:
            # Se il modello non restituisce JSON valido, si applica il fallback
            logger.warning(
                "[MODERATION][LLM][PARSE_ERROR] mode=%s raw_output=%r error=%s",
                mode, raw_output, str(e)
            )
            return cls._fallback_llm_output(mode, base_updated_summary)

        updated_summary = parsed.get("updated_summary", summary_in)
        should_ai_speak = bool(parsed.get("should_ai_speak", False))
        message_to_say = parsed.get("message_to_say")
        reason = parsed.get("reason", "unknown")
        intervention_score_raw = parsed.get("intervention_score", 0.0)

        try:
            intervention_score = float(intervention_score_raw)
        except (TypeError, ValueError):
            intervention_score = 0.0

        # Log della risposta LLM
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
    def _fallback_llm_output(cls, mode: str, base_updated_summary: str) -> dict:
        """
        Comportamento di riserva se la chiamata ad Azure fallisce
        o l'output non è parsabile. Mantiene la stessa semantica
        che aveva lo stub originale.
        """
        logger.warning("[MODERATION][LLM][FALLBACK] mode=%s (using local fallback)", mode)

        if mode == "forced_summary":
            return {
                "updated_summary": base_updated_summary,
                "should_ai_speak": True,
                "message_to_say": f"Ricapitolando finora: {base_updated_summary}",
                "reason": "summary_fallback",
                "intervention_score": 1.0,
            }

        if mode == "forced_conclusion":
            return {
                "updated_summary": base_updated_summary,
                "should_ai_speak": True,
                "message_to_say": (
                    "In conclusione: "
                    f"{base_updated_summary}. "
                    "Ora ciascun partecipante deve selezionare il colpevole nella propria interfaccia. "
                    "Quando tutti avranno votato, la sessione verrà chiusa."
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

        - mode == "forced_summary" / "forced_conclusion":
          intervento obbligatorio, si salta il filtro di cooldown/limiti.

        - mode == "normal":
          si usano cooldown, max interventi, eventuale soglia su llm_score.
        """

        if mode in ("forced_summary", "forced_conclusion"):
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

        # 3) Limite massimo interventi per sessione
        if state.ai_interventions_count >= MAX_AI_INTERVENTIONS_PER_SESSION:
            return False, None

        # 4) Cooldown minimo tra interventi
        if state.last_ai_intervention_at is not None:
            now = datetime.utcnow()
            if now - state.last_ai_intervention_at < AI_INTERVENTION_COOLDOWN:
                return False, None

        # 5) Regole legate alla fase della sessione
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
        conclusion_reason: str,  # "timer_expired" or "all_participants_ready"
        session_duration_minutes: int = 30,
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

        try:
            client = cls._build_azure_client()
            deployment = os.environ.get("AZURE_OPENAI_MODEL", "gpt-4o-mini")

            system_prompt = cls._build_forced_conclusion_system_prompt()

            llm_input = {
                "mode": "forced_conclusion",
                "summary_in": summary_in,
                "conclusion_reason": conclusion_reason,
                "session_duration_minutes": session_duration_minutes,
                "scenario": {
                    "type": "murder_mystery",
                    "vote_action": "selezionare il colpevole",
                    "vote_outcome": "scoprirete se avete indovinato l'assassino"
                },
                "language": "it",
            }

            response = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(llm_input, ensure_ascii=False)},
                ],
                temperature=0.5,  # Slightly higher for warmer tone
                max_tokens=512,
            )

            raw_output = response.choices[0].message.content
            if isinstance(raw_output, list):
                raw_output = "".join(part.get("text", "") for part in raw_output)

        except Exception as e:
            logger.warning("[MODERATION][LLM][CONCLUSION_ERROR] error=%s", str(e))
            return cls._fallback_forced_conclusion(summary_in, conclusion_reason)

        try:
            parsed = json.loads(raw_output)
        except Exception as e:
            logger.warning(
                "[MODERATION][LLM][CONCLUSION_PARSE_ERROR] raw=%r error=%s",
                raw_output, str(e)
            )
            return cls._fallback_forced_conclusion(summary_in, conclusion_reason)

        logger.info(
            "[MODERATION][LLM][CONCLUSION_RESPONSE] message=%r",
            parsed.get("message_to_say", "")[:50],
        )

        return {
            "updated_summary": parsed.get("updated_summary", summary_in),
            "message_to_say": parsed.get("message_to_say"),
        }

    @classmethod
    def _build_forced_conclusion_system_prompt(cls) -> str:
        """Prompt di sistema per FORCED_CONCLUSION."""
        return """Sei il moderatore AI di AIutami, una piattaforma per discussioni di gruppo moderate.

La sessione sta per concludersi e devi generare il messaggio finale di chiusura.

## Il tuo compito

Genera un messaggio che:
1. **Riassuma la discussione** - Parti dal summary fornito e adattalo per un contesto di chiusura. Evidenzia i punti chiave emersi, le posizioni principali, eventuali accordi o disaccordi.

2. **Dia istruzioni per il voto** - Spiega chiaramente cosa devono fare i partecipanti (es. selezionare il colpevole) e cosa succederà dopo (es. quando tutti avranno votato, vedranno i risultati).

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

    @classmethod
    def _fallback_forced_conclusion(cls, summary: str, conclusion_reason: str) -> dict:
        """
        Messaggio di fallback se la chiamata LLM per conclusion fallisce.
        """
        if conclusion_reason == "timer_expired":
            intro = "Il tempo a disposizione è terminato."
        else:
            intro = "Avete deciso di procedere alla votazione."

        message = (
            f"{intro} "
            f"Ecco un breve riepilogo della vostra discussione: {summary}. "
            f"Ora è il momento di selezionare chi pensate sia il colpevole. "
            f"Quando tutti avranno votato, scoprirete se avete indovinato. "
            f"Grazie per aver usato AIutami per la vostra sessione!"
        )

        return {
            "updated_summary": summary,
            "message_to_say": message,
        }