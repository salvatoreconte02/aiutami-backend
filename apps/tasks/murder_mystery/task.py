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
from . import report as mm_report


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

    def task_context_block(self, mode: str, language: str = "Italian") -> str:
        if language == "English":
            blocks = {
                "normal": mm_prompts.SCENARIO_BLOCK_NORMAL_EN,
                "forced_conclusion": mm_prompts.SCENARIO_BLOCK_FORCED_CONCLUSION_EN,
            }
        else:
            blocks = {
                "normal": mm_prompts.SCENARIO_BLOCK_NORMAL_IT,
                "forced_conclusion": mm_prompts.SCENARIO_BLOCK_FORCED_CONCLUSION_IT,
            }
        return blocks.get(mode, "")

    def llm_scenario_payload(
        self, mode: str = "normal", language: str = "Italian"
    ) -> Dict[str, Any]:
        if mode == "forced_conclusion":
            if language == "English":
                return {
                    "type": "murder_mystery",
                    "vote_action": "select the murderer",
                    "vote_outcome": "you'll find out whether you guessed the murderer correctly",
                }
            return {
                "type": "murder_mystery",
                "vote_action": "selezionare il colpevole",
                "vote_outcome": "scoprirete se avete indovinato l'assassino",
            }
        # normal
        if language == "English":
            return {
                "type": "murder_mystery",
                "objective": "Discuss the clues and figure out who the murderer is",
            }
        return {
            "type": "murder_mystery",
            "objective": "Discutere gli indizi e scoprire chi è l'assassino",
        }

    def intro_message_tail(self) -> str:
        # Testo MM verbatim pre-refactor (apps/moderation/intro.py)
        return "Quando avrete capito chi è il colpevole, premete 'Pronto alla conclusione'."

    def ready_to_conclude_messages(self) -> Dict[str, list[str]]:
        return {
            "normal": [
                "{nome} è pronto a concludere. Se hai capito con certezza di chi si tratta, premi anche tu 'Pronto alla conclusione' per terminare la sessione.",
                "{nome} ha indicato di essere pronto alla conclusione. Quando anche tu avrai raggiunto una certezza, premi il pulsante per concludere.",
                "{nome} si è dichiarato pronto a concludere. Se hai già individuato il colpevole, puoi premere 'Pronto alla conclusione'.",
                "{nome} è pronto. Ricorda: quando sei sicuro di chi si tratta, premi 'Pronto alla conclusione' per avviare la fase finale.",
            ],
            "last_one": [
                "{nome} è pronto a concludere. Ora manca solo un partecipante per avviare la fase finale.",
                "{nome} si è dichiarato pronto. Manca solo una persona: se hai raggiunto una certezza, premi 'Pronto alla conclusione'.",
                "{nome} è pronto. Quasi tutti hanno deciso: manca solo un voto per concludere la sessione.",
            ],
            "all_ready": [
                "Tutti i partecipanti sono pronti. Possiamo avviarci alla fase finale: è il momento di indicare chi pensate sia il colpevole.",
                "Tutti hanno deciso. Possiamo avviarci alla fase finale per votare il colpevole.",
                "Siete tutti pronti. Avviamoci alla votazione del colpevole.",
            ],
        }

    # --- Step 5: report ---

    def build_report_llm_prompt(self, language: str = "Italian") -> str:
        return mm_report.build_mm_report_llm_prompt(language)

    def report_title(self) -> str:
        return "REPORT SESSIONE MURDER MYSTERY"

    def collect_report_context(self, session) -> Dict[str, Any]:
        return mm_report.collect_mm_report_context(session)

    def build_report_pdf_sections(self, session, context: Dict[str, Any], styles: Dict[str, Any]) -> list:
        return mm_report.build_mm_pdf_sections(session, context, styles)

    def build_report_fallback(self, data: Dict[str, Any]) -> list[str]:
        return mm_report.build_mm_report_fallback_lines(data)

    # --- Step 6: submission (voto colpevole) ---

    def all_submissions_received(self, session) -> bool:
        from .models import SessionVote
        from apps.sessions.models import SessionParticipant
        total = SessionParticipant.objects.filter(session=session).count()
        votes = SessionVote.objects.filter(session=session).count()
        return votes >= total

    def submission_summary(self, session):
        from .models import SessionVote, MURDER_MYSTERY_GUILTY
        votes = SessionVote.objects.filter(session=session).select_related("participant__user")
        results = []
        correct_count = 0
        for vote in votes:
            username = getattr(vote.participant.user, "display_name", None) or vote.participant.user.get_username()
            is_correct = vote.suspect_chosen == MURDER_MYSTERY_GUILTY
            if is_correct:
                correct_count += 1
            results.append({
                "user_id": vote.participant.user_id,
                "username": username,
                "chose": vote.suspect_chosen,
                "correct": is_correct,
            })
        total = len(results)
        success_rate = int((correct_count / total) * 100) if total > 0 else 0
        return {
            "results": results,
            "guilty": MURDER_MYSTERY_GUILTY,
            "success_rate": success_rate,
        }

    def fallback_forced_conclusion_body(
        self,
        summary: str,
        conclusion_reason: str,
        language: str = "Italian",
    ) -> str:
        # Preserva il testo esatto del fallback MM pre-refactor
        # (apps/moderation/service.py:_fallback_forced_conclusion)
        if language == "English":
            if conclusion_reason == "timer_expired":
                intro = "Time is up."
            elif conclusion_reason == "all_participants_ready":
                intro = "You've decided to move on to the vote."
            else:
                intro = "In conclusion:"
            return (
                f"{intro} "
                f"Here is a brief recap of your discussion: {summary}. "
                f"It's now time to select who you think is the murderer. "
                f"Once everyone has voted, you'll find out if you guessed correctly. "
                f"Thank you for using AIutami for your session!"
            )
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
