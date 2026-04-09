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

from apps.tasks.base import TaskDefinition


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
