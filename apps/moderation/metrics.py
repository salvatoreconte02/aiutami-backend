"""
Metriche di partecipazione per la moderazione AI.

Helper puro: dato un dict {nome: numero} (speaking time in secondi o turn
count), un elapsed_seconds e i parametri di soglia, ritorna le liste
over/under-participator, la media e il flag min_time_reached.
Nessuno state, nessun I/O.

Soglie di default:
- over: > 2× media (Srinivasan et al., CHI 2025, arXiv:2501.10553)
- under: < 0.5× media (deviazione conservativa rispetto al paper, che usa
  < media: noi favoriamo precision over recall in moderazione continua,
  vs. paper che fa intervento one-shot).
- min_elapsed_seconds: 480.0 (8 minuti, allineato al paper su sessioni
  da 30 minuti).
"""

from typing import TypedDict, Mapping, Union


DEFAULT_OVER_THRESHOLD = 2.0
DEFAULT_UNDER_THRESHOLD = 0.5
DEFAULT_MIN_ELAPSED_SECONDS = 480.0  # 8 minutes (paper)


Number = Union[int, float]


class ParticipationMetrics(TypedDict):
    over_participators: list[str]
    under_participators: list[str]
    avg_speaking_time_s: float
    min_time_reached: bool


def compute_participation_metrics(
    speaking_time_per_participant: Mapping[str, Number],
    *,
    elapsed_seconds: float,
    over_threshold: float = DEFAULT_OVER_THRESHOLD,
    under_threshold: float = DEFAULT_UNDER_THRESHOLD,
    min_elapsed_seconds: float = DEFAULT_MIN_ELAPSED_SECONDS,
) -> ParticipationMetrics:
    n = len(speaking_time_per_participant)
    total = sum(speaking_time_per_participant.values())

    if n == 0:
        return ParticipationMetrics(
            over_participators=[],
            under_participators=[],
            avg_speaking_time_s=0.0,
            min_time_reached=False,
        )

    avg = total / n
    min_time_reached = elapsed_seconds >= min_elapsed_seconds

    over_cutoff = over_threshold * avg
    under_cutoff = under_threshold * avg

    over = [
        (name, value)
        for name, value in speaking_time_per_participant.items()
        if value > over_cutoff
    ]
    under = [
        (name, value)
        for name, value in speaking_time_per_participant.items()
        if value < under_cutoff
    ]

    over_sorted = [n for n, _ in sorted(over, key=lambda kv: (-kv[1], kv[0]))]
    under_sorted = [n for n, _ in sorted(under, key=lambda kv: (kv[1], kv[0]))]

    return ParticipationMetrics(
        over_participators=over_sorted,
        under_participators=under_sorted,
        avg_speaking_time_s=float(avg),
        min_time_reached=min_time_reached,
    )
