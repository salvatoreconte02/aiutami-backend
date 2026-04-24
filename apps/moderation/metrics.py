"""
Metriche di partecipazione per la moderazione AI.

Helper puro: dato un dict {nome: conteggio_turni} e parametri di soglia,
ritorna le liste over/under-participator, la media dei turni e il flag
min_turns_reached. Nessuno state, nessun I/O, testabile in isolamento.

Soglie di default (2×/0.5× media, min turns = 2×N) giustificate in
docs/plans/2026-04-20-moderation-logic-analysis-and-improvements.md
(Feature 2.5, rif. Srinivasan et al. CHI 2025, arXiv:2501.10553).
"""

from typing import TypedDict


DEFAULT_OVER_THRESHOLD = 2.0
DEFAULT_UNDER_THRESHOLD = 0.5
DEFAULT_MIN_TURNS_FACTOR = 2


class ParticipationMetrics(TypedDict):
    over_participators: list[str]
    under_participators: list[str]
    avg_turns: float
    min_turns_reached: bool


def compute_participation_metrics(
    turns_per_participant: dict[str, int],
    *,
    over_threshold: float = DEFAULT_OVER_THRESHOLD,
    under_threshold: float = DEFAULT_UNDER_THRESHOLD,
    min_turns_factor: int = DEFAULT_MIN_TURNS_FACTOR,
) -> ParticipationMetrics:
    n_participants = len(turns_per_participant)
    total_turns = sum(turns_per_participant.values())

    if n_participants == 0:
        return ParticipationMetrics(
            over_participators=[],
            under_participators=[],
            avg_turns=0.0,
            min_turns_reached=False,
        )

    avg_turns = total_turns / n_participants
    min_turns_reached = total_turns >= min_turns_factor * n_participants

    over_cutoff = over_threshold * avg_turns
    under_cutoff = under_threshold * avg_turns

    over = [(name, count) for name, count in turns_per_participant.items() if count > over_cutoff]
    under = [(name, count) for name, count in turns_per_participant.items() if count < under_cutoff]

    over_sorted = [name for name, _ in sorted(over, key=lambda item: (-item[1], item[0]))]
    under_sorted = [name for name, _ in sorted(under, key=lambda item: (item[1], item[0]))]

    return ParticipationMetrics(
        over_participators=over_sorted,
        under_participators=under_sorted,
        avg_turns=avg_turns,
        min_turns_reached=min_turns_reached,
    )
