"""
Costanti del task NASA Moon Survival.

I 15 oggetti e l'expert ranking provengono dal materiale MTa Learning
(docs/nasa_moon_survival/) basato sul paper originale di Hall (1962) e
ripreso da Hall & Watson (1970).

Gli oggetti sono tradotti in italiano e le unita di misura convertite
al sistema metrico (piedi -> metri, libbre -> kg).
"""

# I 15 oggetti in italiano, nell'ordine in cui vengono presentati
# ai partecipanti (ordine casuale, non significativo).
NASA_ITEMS = [
    "Scatola di fiammiferi",
    "Concentrato alimentare",
    "15 metri di corda di nylon",
    "Tela di paracadute",
    "Riscaldatore portatile",
    "Due pistole calibro .45",
    "Una cassa di latte in polvere",
    "Due bombole di ossigeno (5 kg ciascuna)",
    "Mappa stellare",
    "Canotto autogonfiabile",
    "Bussola magnetica",
    "20 litri d'acqua",
    "Razzi segnalatori",
    "Kit di pronto soccorso con ago per iniezioni",
    "Ricetrasmettitore FM a energia solare",
]

# Expert ranking: posizione 1 = piu importante, 15 = meno importante.
# Fonte: Mr. Radnofsky, Chief of the Crew Equipment Research Department,
# NASA Manned Spacecraft Center (via MTa Learning briefing slides).
EXPERT_RANKING = {
    "Due bombole di ossigeno (5 kg ciascuna)": 1,
    "20 litri d'acqua": 2,
    "Mappa stellare": 3,
    "Concentrato alimentare": 4,
    "Ricetrasmettitore FM a energia solare": 5,
    "15 metri di corda di nylon": 6,
    "Kit di pronto soccorso con ago per iniezioni": 7,
    "Tela di paracadute": 8,
    "Canotto autogonfiabile": 9,
    "Razzi segnalatori": 10,
    "Due pistole calibro .45": 11,
    "Una cassa di latte in polvere": 12,
    "Riscaldatore portatile": 13,
    "Bussola magnetica": 14,
    "Scatola di fiammiferi": 15,
}

# Range errore possibile: 0 (ranking perfetto) - 112 (massimo errore).
MAX_ERROR_SCORE = 112


def compute_error_score(ranked_items: list[str]) -> int:
    """
    Calcola l'error score del ranking di gruppo rispetto all'expert ranking.
    Error = somma |rank_team - rank_expert| per ogni item.
    """
    total = 0
    for team_rank_0based, item in enumerate(ranked_items):
        team_rank = team_rank_0based + 1  # 1-indexed
        expert_rank = EXPERT_RANKING[item]
        total += abs(team_rank - expert_rank)
    return total
