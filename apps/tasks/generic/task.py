"""
GenericTask — task "discussione libera" senza scenario specifico.

Non ha submission (voto, ranking), non ha blocchi scenario per l'LLM,
e in CONCLUSION chiude subito senza attendere input dai partecipanti.
Tutti i metodi ereditano i default di TaskDefinition, che sono già
pensati per questo caso.
"""

from apps.tasks.base import TaskDefinition


class GenericTask(TaskDefinition):
    @property
    def key(self) -> str:
        return "generic"

    @property
    def display_name(self) -> str:
        return "Discussione generica"

    @property
    def min_participants(self) -> int:
        return 2

    @property
    def max_participants(self) -> int:
        return 8

    @property
    def fixed_size(self) -> bool:
        return False
