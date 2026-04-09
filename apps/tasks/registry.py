"""
Registry dei task plugin di AIutami.

Il registry è un semplice dizionario in memoria che mappa la chiave del task
(stringa, es. "murder_mystery") alla sua istanza TaskDefinition concreta.

Come si usa:

    from apps.tasks.registry import register, get_task, all_keys
    from apps.tasks.base import TaskDefinition

    class MyTask(TaskDefinition):
        @property
        def key(self): return "my_task"
        @property
        def display_name(self): return "My Task"

    register(MyTask())
    get_task("my_task")  # -> istanza MyTask
    all_keys()           # -> ["my_task"]

La registrazione avviene al boot di Django: ogni sottopacchetto in apps/tasks/
(murder_mystery, nasa_moon, generic) importa la propria classe e chiama
register() al momento dell'import. apps/tasks/apps.py:TasksConfig.ready() si
occupa di forzare gli import al boot.

Il core del backend chiama SOLO get_task(session.context) — non importa mai
direttamente le classi concrete dai sottopacchetti.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from .base import TaskDefinition


class TaskAlreadyRegistered(Exception):
    """Sollevata quando si tenta di registrare due task con la stessa chiave."""


class TaskNotFound(KeyError):
    """Sollevata quando si richiede un task con chiave non registrata."""


_REGISTRY: Dict[str, TaskDefinition] = {}


def register(task: TaskDefinition) -> None:
    """
    Registra un task nel registry globale.

    Solleva TaskAlreadyRegistered se la stessa chiave è già presente.
    """
    key = task.key
    if key in _REGISTRY:
        raise TaskAlreadyRegistered(
            f"Task con chiave {key!r} è già registrato "
            f"(esistente: {_REGISTRY[key]!r}, nuovo: {task!r})"
        )
    _REGISTRY[key] = task


def get_task(key: str) -> TaskDefinition:
    """
    Ritorna il TaskDefinition registrato per la chiave data.

    Solleva TaskNotFound se la chiave non esiste.
    """
    try:
        return _REGISTRY[key]
    except KeyError as exc:
        raise TaskNotFound(
            f"Nessun task registrato con chiave {key!r}. "
            f"Registrati: {sorted(_REGISTRY.keys())}"
        ) from exc


def all_keys() -> List[str]:
    """Ritorna l'elenco ordinato delle chiavi dei task registrati."""
    return sorted(_REGISTRY.keys())


def task_choices() -> List[Tuple[str, str]]:
    """
    Ritorna l'elenco (key, display_name) dei task registrati, utilizzabile
    come `choices=` per un Django CharField o come validazione di serializer.
    """
    return [(t.key, t.display_name) for t in sorted(_REGISTRY.values(), key=lambda t: t.key)]


def _reset_for_tests() -> None:
    """
    Svuota il registry. USO ESCLUSIVO PER TEST.

    Non chiamare in codice di produzione: il registry è costruito una sola
    volta al boot Django e deve restare stabile per tutta la vita del processo.
    """
    _REGISTRY.clear()
