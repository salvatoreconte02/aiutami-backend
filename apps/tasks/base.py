"""
Contratto astratto per un task plugin di AIutami.

Un TaskDefinition descrive tutto ciò che è specifico di un task (Murder Mystery,
NASA Moon Survival, discussione generica...). Il core del backend non conosce
i task specifici: interagisce con essi solo attraverso questa interfaccia.

In Step 0 il contratto è minimale (solo `key` e `display_name`) perché serve
unicamente a far girare il registry. I metodi veri (prompt building, intro,
submission, report, ...) verranno aggiunti negli step successivi del refactor,
uno per volta, man mano che il core smette di avere logica MM-specifica.

Vedi docs/plans/2026-04-08-task-pluggable-architecture.md per il piano completo.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class TaskDefinition(ABC):
    """
    Classe astratta che ogni task plugin deve estendere.

    Ogni sottoclasse concreta (es. MurderMysteryTask) fornisce:
      - `key`: stringa identificatrice univoca, usata come valore di
        Session.context e come chiave nel registry (es. "murder_mystery")
      - `display_name`: etichetta leggibile per UI e log (es. "Murder Mystery")
    """

    @property
    @abstractmethod
    def key(self) -> str:
        """Chiave univoca del task nel registry."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Nome leggibile del task."""

    # --- Capienza della sessione ---
    # Step 2: questi campi servono al core (Session.clean, serializer validate)
    # per validare min_size/max_size di una sessione senza hardcodare Murder
    # Mystery. Task a numero fisso di partecipanti (es. MM 3/3) dichiarano
    # `fixed_size=True` e usano min_participants == max_participants.

    @property
    @abstractmethod
    def min_participants(self) -> int:
        """Numero minimo di partecipanti ammesso dal task."""

    @property
    @abstractmethod
    def max_participants(self) -> int:
        """Numero massimo di partecipanti ammesso dal task."""

    @property
    @abstractmethod
    def fixed_size(self) -> bool:
        """
        True se il task richiede esattamente `min_participants` partecipanti
        (es. Murder Mystery: sempre 3). In quel caso min_size e max_size di
        una Session devono coincidere con min_participants/max_participants.
        False se il task accetta un range (es. discussione generica).
        """

    # --- Prompt building per il moderatore LLM ---
    # Step 3: il core moderation mantiene uno scheletro di system prompt
    # task-agnostic (tono, cooldown, output JSON, criteri generici) e delega
    # al task un blocco di testo con lo scenario e un dict `scenario` da
    # inserire nel payload LLM. I default sono pensati per GENERIC: blocco
    # vuoto + payload vuoto. I task concreti (MM, NASA) li sovrascrivono.

    def task_context_block(self, mode: str) -> str:
        """
        Ritorna il blocco di testo task-specifico da iniettare nello scheletro
        del system prompt del moderatore.

        `mode` è uno di: "normal", "forced_summary", "forced_conclusion".
        Stringa vuota = task completamente generico (nessuno scenario specifico).
        """
        return ""

    def llm_scenario_payload(self, mode: str = "normal") -> Dict[str, Any]:
        """
        Ritorna il dict da inserire come `scenario` nel payload JSON inviato
        all'LLM. I task concreti mettono qui tipo, obiettivo e info di contesto
        che l'LLM può consultare. Default vuoto = GENERIC.
        """
        return {}

    def fallback_forced_conclusion_body(
        self, summary: str, conclusion_reason: str
    ) -> str:
        """
        Testo pre-scritto usato se la chiamata LLM per forced_conclusion
        fallisce. I task concreti possono personalizzarlo con istruzioni
        specifiche (es. "selezionate il colpevole"). Il default è generico:
        riepilogo della discussione + ringraziamento.
        """
        if conclusion_reason == "timer_expired":
            intro = "Il tempo a disposizione è terminato."
        elif conclusion_reason == "all_participants_ready":
            intro = "Avete deciso di concludere la sessione."
        else:
            intro = "In conclusione:"
        return (
            f"{intro} "
            f"Ecco un breve riepilogo della vostra discussione: {summary}. "
            f"Grazie per aver usato AIutami per la vostra sessione!"
        )

    def __repr__(self) -> str:
        return f"<TaskDefinition key={self.key!r}>"
