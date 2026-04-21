"""
Task plugin Lost at Sea.

L'import di questo pacchetto registra LostAtSeaTask nel registry globale.
"""

from apps.tasks.registry import register

from .task import LostAtSeaTask
from . import models as _lost_at_sea_models  # noqa: F401 — Django deve scoprire LostAtSeaRanking

register(LostAtSeaTask())
