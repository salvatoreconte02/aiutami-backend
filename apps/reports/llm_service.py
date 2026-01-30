"""
Report LLM Service - genera il testo del report via Azure OpenAI.
"""

import logging
import os
import json
from typing import Any

from openai import AzureOpenAI

logger = logging.getLogger(__name__)


REPORT_SYSTEM_PROMPT = """Sei un analista di sessioni di discussione moderate su AIutami.

Genera un report testuale completo in italiano per una sessione di Murder Mystery.

Il report deve includere queste sezioni (usa esattamente questi titoli):

RISULTATO FINALE
- Chi era il colpevole
- Quanti partecipanti hanno indovinato (es. "2 su 3")
- Percentuale di successo

VOTI DEI PARTECIPANTI
- Lista dei partecipanti con chi hanno scelto e se era corretto (usa ✓ o ✗)

STATISTICHE PARTECIPAZIONE
- Interventi per partecipante con percentuali
- Interventi del moderatore AI con percentuale

RIASSUNTO DELLA DISCUSSIONE
- Basato sul final_summary fornito, rielaboralo in modo discorsivo

ANALISI FINALE
- Un breve paragrafo (3-5 frasi) che analizza come è andata la sessione
- Commenta la partecipazione, eventuali dinamiche interessanti, e il risultato finale

Formato:
- Usa testo semplice, NO markdown
- Separa le sezioni con una riga vuota
- Tono informativo ma accessibile (il pubblico sono ragazzi)
- Lunghezza totale: 300-500 parole
"""


class ReportLLMService:
    """
    Servizio per generare il testo del report via LLM.
    """

    @classmethod
    def generate_report_text(cls, data: dict[str, Any]) -> str:
        """
        Genera il testo del report dalla data della sessione.

        Args:
            data: dizionario con:
                - session_title
                - duration_minutes
                - participants: list of {name, turns, percentage}
                - ai_interventions
                - ai_intervention_percentage
                - votes: list of {name, chose, correct}
                - guilty
                - success_rate
                - final_summary

        Returns:
            Il testo del report generato
        """
        logger.info("[REPORT][LLM][REQUEST] Generating report for session: %s", data.get("session_title"))

        try:
            client = cls._build_azure_client()
            deployment = os.environ.get("AZURE_OPENAI_MODEL", "gpt-4o-mini")

            response = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": REPORT_SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
                ],
                temperature=0.6,
                max_tokens=1024,
            )

            content = response.choices[0].message.content
            logger.info("[REPORT][LLM][RESPONSE] Generated report length: %d", len(content))
            return content

        except Exception as e:
            logger.warning("[REPORT][LLM][ERROR] %s - using fallback", str(e))
            return cls._fallback_report(data)

    @classmethod
    def _build_azure_client(cls) -> AzureOpenAI:
        """Crea client Azure OpenAI."""
        endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
        api_key = os.environ["AZURE_OPENAI_API_KEY"]
        api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")

        return AzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=endpoint,
        )

    @classmethod
    def _fallback_report(cls, data: dict[str, Any]) -> str:
        """Genera un report di fallback se LLM non disponibile."""
        lines = [
            f"REPORT SESSIONE: {data.get('session_title', 'Sessione senza titolo')}",
            f"Durata: {data.get('duration_minutes', 0)} minuti",
            "",
            "RISULTATO FINALE",
            f"Il colpevole era: {data.get('guilty', 'Sconosciuto')}",
            f"Percentuale di successo: {data.get('success_rate', 0)}%",
            "",
            "VOTI DEI PARTECIPANTI",
        ]

        for vote in data.get("votes", []):
            symbol = "✓" if vote.get("correct") else "✗"
            lines.append(f"- {vote.get('name')}: {vote.get('chose')} {symbol}")

        lines.extend([
            "",
            "STATISTICHE PARTECIPAZIONE",
        ])

        for p in data.get("participants", []):
            lines.append(f"- {p.get('name')}: {p.get('turns')} interventi ({p.get('percentage')}%)")

        lines.extend([
            f"- Moderatore AI: {data.get('ai_interventions', 0)} interventi ({data.get('ai_intervention_percentage', 0)}%)",
            "",
            "RIASSUNTO",
            data.get("final_summary", "Nessun riassunto disponibile."),
            "",
            "Generato da AIutami",
        ])

        return "\n".join(lines)
