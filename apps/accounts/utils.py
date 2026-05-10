"""Helper riusabili sull'oggetto User di Django."""

from __future__ import annotations


def display_name_for_user(user) -> str:
    """Nome con cui il moderatore AI (e altri sistemi user-facing) chiama
    il partecipante.

    Priorità:
    - `first_name` se non vuoto (post-strip)
    - altrimenti `username`

    Pattern centralizzato: tutti i punti del codice che producevano
    `getattr(user, "display_name", None) or user.get_username()` ora
    devono importare da qui.

    `display_name` non esiste come attributo standard sul User di Django,
    quindi il vecchio pattern cadeva sempre su username. Risultato:
    il moderatore TTS pronunciava username corrotti tipo "Tschoe",
    "Salvcon" (vedi pilot log 2026-05-04).
    """
    if user is None:
        return "?"

    first = (getattr(user, "first_name", "") or "").strip()
    if first:
        return first

    return user.get_username()
