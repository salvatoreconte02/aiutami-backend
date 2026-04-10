"""
Task plugin Murder Mystery.

L'import di questo pacchetto registra MurderMysteryTask nel registry globale.
apps/tasks/apps.py:TasksConfig.ready() si occupa di forzare l'import al boot
Django, così il task è disponibile via registry.get_task("murder_mystery")
senza che il core debba conoscerlo direttamente.
"""

from apps.tasks.registry import register

from .task import MurderMysteryTask
from . import models as _mm_models  # noqa: F401 — Django deve scoprire SessionVote

register(MurderMysteryTask())
