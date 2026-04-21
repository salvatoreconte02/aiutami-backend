"""
Report LLM Service - genera il testo del report via OpenAI.
"""

import logging
import json
from typing import Any, Optional

from django.conf import settings
from openai import OpenAI

from apps.tasks.base import TaskDefinition

logger = logging.getLogger(__name__)


class ReportLLMService:
    """
    Servizio per generare il testo del report via LLM.
    """

    @classmethod
    def generate_report_text(cls, data: dict[str, Any], task: Optional[TaskDefinition] = None) -> str:
        """
        Genera il testo del report dalla data della sessione.

        Args:
            data: dizionario con dati generici (session_title, duration_minutes,
                  participants, ai_interventions, final_summary) + dati
                  task-specifici mergiati da collect_report_context().
            task: TaskDefinition da cui ottenere il system prompt.
                  Se None, usa il default di TaskDefinition.

        Returns:
            Il testo del report generato
        """
        if task is None:
            logger.warning("[REPORT][LLM] task=None — il caller dovrebbe sempre passare il task")

        system_prompt = task.build_report_llm_prompt() if task else (
            "Genera un report testuale in italiano per una sessione di discussione. "
            "Includi statistiche partecipazione, commenta il Gini index, e riassunto. "
            "Formato: testo semplice, 200-400 parole."
        )

        logger.info("[REPORT][LLM][REQUEST] Generating report for session: %s", data.get("session_title"))

        try:
            client = cls._build_openai_client()

            response = client.chat.completions.create(
                model=settings.OPENAI_LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
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
            return cls._fallback_report(data, task=task)

    @classmethod
    def _build_openai_client(cls) -> OpenAI:
        """Crea client OpenAI."""
        return OpenAI(api_key=settings.OPENAI_API_KEY)

    @classmethod
    def _fallback_report(cls, data: dict[str, Any], task: Optional[TaskDefinition] = None) -> str:
        """Genera un report di fallback se LLM non disponibile."""
        lines = [
            f"REPORT SESSIONE: {data.get('session_title', 'Sessione senza titolo')}",
            f"Durata: {data.get('duration_minutes', 0)} minuti",
            "",
            "RISULTATO FINALE",
        ]

        # Sezione task-specifica
        if task is not None:
            lines.extend(task.build_report_fallback(data))

        lines.extend([
            "",
            "STATISTICHE PARTECIPAZIONE",
        ])

        for p in data.get("participants", []):
            lines.append(f"- {p.get('name')}: {p.get('turns')} interventi ({p.get('percentage')}%)")

        gini = data.get("gini_index", 0)
        lines.extend([
            f"- Moderatore AI: {data.get('ai_interventions', 0)} interventi ({data.get('ai_intervention_percentage', 0)}%)",
            f"Indice di Gini: {gini:.2f}",
            "",
            "RIASSUNTO",
            data.get("final_summary", "Nessun riassunto disponibile."),
            "",
            "Generato da AIutami",
        ])

        return "\n".join(lines)
