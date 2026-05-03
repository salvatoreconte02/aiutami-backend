"""
Blocchi di testo task-specifici per Murder Mystery, iniettati dal core
moderation nello scheletro del system prompt LLM.

Versioni IT/EN parallele: il sistema seleziona la lingua via
settings.MODERATOR_OUTPUT_LANGUAGE (default Italian).
"""

# --- Italian ---

SCENARIO_BLOCK_NORMAL_IT = """## Scenario
I partecipanti stanno giocando a un murder mystery. Il loro obiettivo è discutere gli indizi e scoprire chi è l'assassino."""

SCENARIO_BLOCK_FORCED_CONCLUSION_IT = """## Scenario
I partecipanti hanno giocato a un murder mystery. Al termine della sessione ciascun partecipante deve selezionare il colpevole nella propria interfaccia; dopo il voto scopriranno se hanno indovinato l'assassino."""


# --- English ---

SCENARIO_BLOCK_NORMAL_EN = """## Scenario
The participants are playing a murder mystery game. Their goal is to discuss the clues and figure out who the murderer is."""

SCENARIO_BLOCK_FORCED_CONCLUSION_EN = """## Scenario
The participants have been playing a murder mystery. At the end of the session each participant must select the suspect in their own interface; after voting they'll find out if they guessed the murderer correctly."""


# --- Backward-compat aliases (default Italian) ---

SCENARIO_BLOCK_NORMAL = SCENARIO_BLOCK_NORMAL_IT
SCENARIO_BLOCK_FORCED_CONCLUSION = SCENARIO_BLOCK_FORCED_CONCLUSION_IT
