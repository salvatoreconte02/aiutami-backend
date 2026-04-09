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

    def __repr__(self) -> str:
        return f"<TaskDefinition key={self.key!r}>"
