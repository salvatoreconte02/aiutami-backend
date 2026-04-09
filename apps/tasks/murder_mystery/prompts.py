"""
Blocchi di testo task-specifici per Murder Mystery, iniettati dal core
moderation nello scheletro del system prompt LLM.

Step 3 del refactor task-pluggable: queste stringhe vivevano prima dentro
apps/moderation/service.py hardcoded nei 3 `_build_*_system_prompt()`. Ora
sono isolate qui e il core le ottiene tramite MurderMysteryTask.task_context_block(mode).

Vedi docs/plans/2026-04-08-task-pluggable-architecture.md §5 Step 3.
"""

# Usato dal prompt `normal` (decisione intervento durante la discussione).
SCENARIO_BLOCK_NORMAL = """## Scenario
I partecipanti stanno giocando a un murder mystery. Il loro obiettivo è discutere gli indizi e scoprire chi è l'assassino."""


# Usato dal prompt `forced_summary` (ricapitolazione intermedia periodica).
SCENARIO_BLOCK_FORCED_SUMMARY = """## Scenario
I partecipanti stanno giocando a un murder mystery. Devono discutere gli indizi e scoprire chi è l'assassino."""


# Usato dal prompt `forced_conclusion` (messaggio finale di chiusura).
# Istruisce l'LLM sull'azione finale richiesta ai partecipanti (voto colpevole).
SCENARIO_BLOCK_FORCED_CONCLUSION = """## Scenario
I partecipanti hanno giocato a un murder mystery. Al termine della sessione ciascun partecipante deve selezionare il colpevole nella propria interfaccia; dopo il voto scopriranno se hanno indovinato l'assassino."""
