"""
NasaMoonTask — plugin per la NASA Moon Survival Challenge.

I partecipanti sono astronauti il cui modulo lunare si e schiantato.
Devono classificare 15 oggetti in ordine di importanza per la sopravvivenza
e raggiungere un consenso di gruppo. Il ranking viene poi confrontato con
l'expert ranking NASA per calcolare un error score.

Il moderatore AI fa rispettare le 6 ground rules procedurali di
Hall & Watson (1970) per il consenso di gruppo.
"""

from __future__ import annotations

from typing import Any, Dict

from apps.tasks.base import TaskDefinition

from . import prompts as nasa_prompts
from . import report as nasa_report
from .config import NASA_ITEMS


class NasaMoonTask(TaskDefinition):
    @property
    def key(self) -> str:
        return "nasa_moon_survival"

    @property
    def display_name(self) -> str:
        return "NASA Moon Survival"

    @property
    def min_participants(self) -> int:
        return 3

    @property
    def max_participants(self) -> int:
        return 6

    @property
    def fixed_size(self) -> bool:
        return False

    # --- Prompt building ---

    def task_context_block(self, mode: str) -> str:
        return {
            "normal": nasa_prompts.SCENARIO_BLOCK_NORMAL,
            "forced_summary": nasa_prompts.SCENARIO_BLOCK_FORCED_SUMMARY,
            "forced_conclusion": nasa_prompts.SCENARIO_BLOCK_FORCED_CONCLUSION,
        }.get(mode, "")

    def llm_scenario_payload(self, mode: str = "normal") -> Dict[str, Any]:
        if mode == "forced_conclusion":
            return {
                "type": "nasa_moon_survival",
                "submission_action": "confermare il ranking finale dei 15 oggetti",
                "submission_outcome": "il ranking verra confrontato con quello degli esperti NASA",
            }
        if mode == "forced_summary":
            return {
                "type": "nasa_moon_survival",
                "objective": "Classificare 15 oggetti per la sopravvivenza sulla Luna",
            }
        # normal
        return {
            "type": "nasa_moon_survival",
            "objective": "Raggiungere un consenso di gruppo sul ranking dei 15 oggetti lunari",
            "items_count": len(NASA_ITEMS),
        }

    def intro_message_tail(self) -> str:
        rules_text = nasa_prompts.GROUND_RULES
        return (
            "In questa sessione affronterete la NASA Moon Survival Challenge: "
            "siete un equipaggio di astronauti il cui modulo lunare si e schiantato "
            "a circa 300 km dalla base. Dovete classificare 15 oggetti in ordine di "
            "importanza per la sopravvivenza e raggiungere un consenso di gruppo. "
            "L'host potra comporre il ranking durante la discussione e tutti potranno "
            "vederlo aggiornarsi in tempo reale.\n\n"
            "Per raggiungere un buon consenso, seguite queste regole:\n"
            f"{rules_text}\n\n"
            "Quando il gruppo sara d'accordo sul ranking, premete 'Pronto alla conclusione'."
        )

    def ready_to_conclude_messages(self) -> Dict[str, list[str]]:
        return {
            "normal": [
                "{nome} è pronto a concludere. Se anche tu pensi che il ranking finale sia condiviso, premi 'Pronto alla conclusione'.",
                "{nome} ha indicato di essere pronto alla conclusione. Quando anche tu sarai d'accordo sul ranking, premi il pulsante.",
                "{nome} si è dichiarato pronto a concludere. Se ritieni che il gruppo abbia raggiunto un consenso, premi 'Pronto alla conclusione'.",
            ],
            "last_one": [
                "{nome} è pronto a concludere. Manca solo un partecipante per chiudere il ranking.",
                "{nome} si è dichiarato pronto. Manca solo una persona: se sei d'accordo sul ranking, premi 'Pronto alla conclusione'.",
                "{nome} è pronto. Quasi tutti hanno deciso: manca solo un consenso per concludere.",
            ],
            "all_ready": [
                "Tutti i partecipanti sono pronti. Possiamo chiudere la discussione: l'host confermerà ora il ranking finale.",
                "Tutti hanno deciso. Avviamoci alla conferma del ranking finale.",
                "Siete tutti pronti. Possiamo passare alla conferma del ranking dei 15 oggetti.",
            ],
        }

    def fallback_forced_conclusion_body(
        self, summary: str, conclusion_reason: str
    ) -> str:
        if conclusion_reason == "timer_expired":
            intro = "Il tempo a disposizione e terminato."
        elif conclusion_reason == "all_participants_ready":
            intro = "Avete deciso di concludere la sessione."
        else:
            intro = "In conclusione:"
        return (
            f"{intro} "
            f"Ecco un breve riepilogo della vostra discussione: {summary}. "
            f"L'host deve ora confermare il ranking finale dei 15 oggetti. "
            f"Il ranking verra confrontato con quello degli esperti NASA. "
            f"Grazie per aver usato AIutami per la vostra sessione!"
        )

    # --- Report ---

    def build_report_llm_prompt(self) -> str:
        return nasa_report.REPORT_LLM_PROMPT

    def report_title(self) -> str:
        return "REPORT NASA MOON SURVIVAL"

    def collect_report_context(self, session) -> Dict[str, Any]:
        return nasa_report.collect_nasa_report_context(session)

    def build_report_pdf_sections(
        self, session, context: Dict[str, Any], styles: Dict[str, Any]
    ) -> list:
        return nasa_report.build_nasa_pdf_sections(session, context, styles)

    def build_report_fallback(self, data: Dict[str, Any]) -> list[str]:
        return nasa_report.build_nasa_report_fallback_lines(data)

    # --- Submission ---

    def all_submissions_received(self, session) -> bool:
        from .models import NasaRanking

        return NasaRanking.objects.filter(session=session, is_final=True).exists()

    def submission_summary(self, session):
        from .models import NasaRanking
        from .config import compute_error_score, EXPERT_RANKING

        try:
            ranking = NasaRanking.objects.get(session=session)
        except NasaRanking.DoesNotExist:
            return None

        error_score = compute_error_score(ranking.ranked_items)

        items_detail = []
        for i, item in enumerate(ranking.ranked_items):
            team_rank = i + 1
            expert_rank = EXPERT_RANKING[item]
            items_detail.append({
                "item": item,
                "team_rank": team_rank,
                "expert_rank": expert_rank,
                "diff": abs(team_rank - expert_rank),
            })

        return {
            "ranked_items": ranking.ranked_items,
            "error_score": error_score,
            "items_detail": items_detail,
        }
