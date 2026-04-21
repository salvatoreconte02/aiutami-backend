"""
Costanti del task Lost at Sea.

I 15 oggetti e l'expert ranking provengono dall'esercizio "Lost at Sea"
di Nemiroff & Pasmore (1975), con ranking esperto della US Coast Guard.

Gli oggetti sono tradotti in italiano.
"""

# I 15 oggetti in italiano, nell'ordine in cui vengono presentati
# ai partecipanti (ordine casuale, non significativo).
LOST_AT_SEA_ITEMS = [
    "Specchio da barba",
    "Tanica di carburante (10 litri)",
    "Tanica d'acqua (25 litri)",
    "Cassa di razioni dell'esercito",
    "Telo di plastica opaco (2 mq)",
    "Barrette di cioccolato (2 confezioni)",
    "Kit da pesca oceanica con canna",
    "Corda di nylon (5 metri)",
    "Cuscino galleggiante",
    "Repellente per squali",
    "Bottiglia di rum 160 proof",
    "Radio a transistor",
    "Mappa dell'Oceano Atlantico",
    "Zanzariera",
    "Sestante (senza accessori)",
]

# Expert ranking: posizione 1 = piu importante, 15 = meno importante.
# Fonte: US Coast Guard (via Nemiroff & Pasmore, 1975).
EXPERT_RANKING = {
    "Specchio da barba": 1,
    "Tanica di carburante (10 litri)": 2,
    "Tanica d'acqua (25 litri)": 3,
    "Cassa di razioni dell'esercito": 4,
    "Telo di plastica opaco (2 mq)": 5,
    "Barrette di cioccolato (2 confezioni)": 6,
    "Kit da pesca oceanica con canna": 7,
    "Corda di nylon (5 metri)": 8,
    "Cuscino galleggiante": 9,
    "Repellente per squali": 10,
    "Bottiglia di rum 160 proof": 11,
    "Radio a transistor": 12,
    "Mappa dell'Oceano Atlantico": 13,
    "Zanzariera": 14,
    "Sestante (senza accessori)": 15,
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
