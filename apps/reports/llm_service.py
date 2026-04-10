"""
Report LLM Service - genera il testo del report via Azure OpenAI.
"""

import logging
import os
import json
from typing import Any, Optional

from openai import AzureOpenAI

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
            from apps.tasks.registry import get_task
            task = get_task("murder_mystery")

        system_prompt = task.build_report_llm_prompt()

        logger.info("[REPORT][LLM][REQUEST] Generating report for session: %s", data.get("session_title"))

        try:
            client = cls._build_azure_client()
            deployment = os.environ.get("AZURE_OPENAI_MODEL", "gpt-4o-mini")

            response = client.chat.completions.create(
                model=deployment,
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
    def _fallback_report(cls, data: dict[str, Any], task: Optional[TaskDefinition] = None) -> str:
        """Genera un report di fallback se LLM non disponibile."""
        if task is None:
            from apps.tasks.registry import get_task
            task = get_task("murder_mystery")

        lines = [
            f"REPORT SESSIONE: {data.get('session_title', 'Sessione senza titolo')}",
            f"Durata: {data.get('duration_minutes', 0)} minuti",
            "",
            "RISULTATO FINALE",
        ]

        # Sezione task-specifica (per MM: colpevole + voti)
        lines.extend(task.build_report_fallback(data))

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
