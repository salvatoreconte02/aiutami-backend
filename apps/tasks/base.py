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

    def __repr__(self) -> str:
        return f"<TaskDefinition key={self.key!r}>"
