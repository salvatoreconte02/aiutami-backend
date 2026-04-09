"""
MurderMysteryTask — plugin che incapsula la logica specifica di Murder Mystery.

In Step 1 questo plugin è un wrapper "invisibile": espone solo `key` e
`display_name`. Il core continua a gestire MM con l'enum hardcoded esistente,
quindi il comportamento non cambia. Negli step successivi del refactor
(vedi docs/plans/2026-04-08-task-pluggable-architecture.md) questo wrapper
assorbirà progressivamente:

  - Step 3: task_context_block() + llm_scenario_payload() +
            fallback_forced_conclusion_body()
  - Step 4: intro_message_tail()
  - Step 5: build_report_llm_prompt() + build_report_pdf_sections()
  - Step 6: submission_urls() + all_submissions_received() + il modello
            SessionVote che oggi sta in apps/sessions/models.py

Tutte le aggiunte saranno fatte rispettando la regola d'oro: il core non
importa mai direttamente da apps.tasks.murder_mystery, solo via
apps.tasks.registry.get_task("murder_mystery").
"""

from __future__ import annotations

from typing import Any, Dict

from apps.tasks.base import TaskDefinition

from . import prompts as mm_prompts


class MurderMysteryTask(TaskDefinition):
    @property
    def key(self) -> str:
        return "murder_mystery"

    @property
    def display_name(self) -> str:
        return "Murder Mystery"

    # Murder Mystery è sempre 3 partecipanti esatti (vincolo del task).
    @property
    def min_participants(self) -> int:
        return 3

    @property
    def max_participants(self) -> int:
        return 3

    @property
    def fixed_size(self) -> bool:
        return True

    # --- Step 3: prompt building ---

    def task_context_block(self, mode: str) -> str:
        return {
            "normal": mm_prompts.SCENARIO_BLOCK_NORMAL,
            "forced_summary": mm_prompts.SCENARIO_BLOCK_FORCED_SUMMARY,
            "forced_conclusion": mm_prompts.SCENARIO_BLOCK_FORCED_CONCLUSION,
        }.get(mode, "")

    def llm_scenario_payload(self, mode: str = "normal") -> Dict[str, Any]:
        if mode == "forced_conclusion":
            return {
                "type": "murder_mystery",
                "vote_action": "selezionare il colpevole",
                "vote_outcome": "scoprirete se avete indovinato l'assassino",
            }
        if mode == "forced_summary":
            return {
                "type": "murder_mystery",
                "objective": "Scoprire chi è l'assassino tra i sospettati",
            }
        # normal
        return {
            "type": "murder_mystery",
            "objective": "Discutere gli indizi e scoprire chi è l'assassino",
        }

    def fallback_forced_conclusion_body(
        self, summary: str, conclusion_reason: str
    ) -> str:
        # Preserva il testo esatto del fallback MM pre-refactor
        # (apps/moderation/service.py:_fallback_forced_conclusion)
        if conclusion_reason == "timer_expired":
            intro = "Il tempo a disposizione è terminato."
        elif conclusion_reason == "all_participants_ready":
            intro = "Avete deciso di procedere alla votazione."
        else:
            intro = "In conclusione:"
        return (
            f"{intro} "
            f"Ecco un breve riepilogo della vostra discussione: {summary}. "
            f"Ora è il momento di selezionare chi pensate sia il colpevole. "
            f"Quando tutti avranno votato, scoprirete se avete indovinato. "
            f"Grazie per aver usato AIutami per la vostra sessione!"
        )
