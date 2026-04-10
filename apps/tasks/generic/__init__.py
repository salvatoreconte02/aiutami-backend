from .task import GenericTask
from apps.tasks.registry import register

register(GenericTask())
