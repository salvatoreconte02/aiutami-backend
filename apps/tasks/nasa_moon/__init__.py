"""
Task plugin NASA Moon Survival.

L'import di questo pacchetto registra NasaMoonTask nel registry globale.
"""

from apps.tasks.registry import register

from .task import NasaMoonTask
from . import models as _nasa_models  # noqa: F401 — Django deve scoprire NasaRanking

register(NasaMoonTask())
