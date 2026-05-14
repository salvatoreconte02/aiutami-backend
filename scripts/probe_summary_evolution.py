"""
Probe dell'evoluzione del summary attraverso una sequenza di turni
simulati, senza aprire una sessione reale (no WebSocket / ASR / Redis).

Chiama direttamente ModerationService._call_llm con il summary di output del
turno precedente come summary_in del successivo, esattamente come fa il
codice live. Stampa per ciascun turno:
    - summary IN (lunghezza + preview)
    - testo del turno
    - reason, score, eventuale messaggio del moderatore
    - summary OUT (lunghezza + preview)

Lancio (dentro container web, ha env e deps):
    docker compose run --rm \\
        -e OPENAI_API_KEY="$(grep '^OPENAI_API_KEY=' .env | cut -d= -f2-)" \\
        web python scripts/probe_summary_evolution.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import django  # noqa: E402

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "aiutami.settings")
django.setup()

from apps.moderation.service import ModerationService  # noqa: E402


TASK_KEY = "lost_at_sea"
PARTICIPANTS = ["salvatore", "Simo", "simona"]

# Sequenza che copre le due domande:
#   1) primo turno senza sostanza + richiesta recap subito dopo
#      → atteso: LLM dice "appena iniziato"
#   2) sei turni con contenuti sostanziali misti
#      → atteso: summary cresce a partire dal primo turno con posizione
TURNS = [
    ("salvatore", "Ciao a tutti, mi sentite?",
     "T1 pleasantry — summary atteso: vuoto"),
    ("salvatore", "Moderatore, mi puoi fare un recap di cosa abbiamo detto finora?",
     "T2 recap request, summary IN ancora vuoto — atteso: 'appena iniziato'"),
    ("salvatore", "Per me la zanzariera dovrebbe stare in basso nel ranking, non serve a molto.",
     "T3 posizione esplicita su item — atteso: summary popolato"),
    ("Simo", "Anche per me, sono d'accordo con Salvatore.",
     "T4 accordo — atteso: summary integra l'accordo"),
    ("simona", "Io invece penso che lo specchio da barba sia molto utile, possiamo usarlo per segnalare.",
     "T5 nuova posizione + argomento — atteso: summary cresce"),
    ("salvatore", "Però anche la corda di nylon serve, possiamo costruirci una vela.",
     "T6 altra posizione + argomento — atteso: summary cresce"),
    ("simona", "Moderatore, ci fai un recap completo della discussione?",
     "T7 recap request, summary IN pieno — atteso: recap dettagliato"),
]

SEPARATOR = "=" * 88


def fmt_preview(text: str, width: int = 200) -> str:
    if not text:
        return "<EMPTY>"
    if len(text) <= width:
        return text
    return text[:width] + "…"


def main() -> None:
    rolling_summary = ""
    speaking_time = {p: 0.0 for p in PARTICIPANTS}
    interventions_log: list[dict] = []
    elapsed = 0.0

    print(SEPARATOR)
    print("PROBE SUMMARY EVOLUTION")
    print(f"Task: {TASK_KEY}  |  Participants: {PARTICIPANTS}")
    print(f"DEFAULT_SUMMARY at start = {rolling_summary!r}")
    print(SEPARATOR)

    for idx, (speaker, transcript, hypothesis) in enumerate(TURNS, start=1):
        # Tempi simulati realistici
        elapsed += 30.0
        speaking_time[speaker] += 8.0

        try:
            out = ModerationService._call_llm(
                summary_in=rolling_summary,
                last_turn=transcript,
                mode="normal",
                session_phase="ACTIVE",
                speaker_name=speaker,
                speaking_time_per_participant=speaking_time,
                elapsed_seconds=elapsed,
                interventions_log=interventions_log,
                task_key=TASK_KEY,
            )
        except Exception as e:
            print(f"\n[TURN {idx}] LLM CALL FAILED: {e!r}")
            break

        new_summary = (out.get("updated_summary") or "").strip()
        reason = out.get("reason")
        score = out.get("intervention_score")
        message = out.get("message_to_say")

        print(f"\nTURN {idx}  [{speaker}]  (elapsed={elapsed:.0f}s)")
        print(f"  hypothesis : {hypothesis}")
        print(f"  said       : {transcript}")
        print(f"  summary IN : ({len(rolling_summary):>3} chars) {fmt_preview(rolling_summary, 200)}")
        print(f"  LLM reason : {reason}  score={score}")
        if message:
            print(f"  LLM says   : {fmt_preview(message, 240)}")
        print(f"  summary OUT: ({len(new_summary):>3} chars) {fmt_preview(new_summary, 240)}")

        # Avanza lo stato — proprio come fa il backend live
        rolling_summary = new_summary
        # Se il LLM ha proposto un intervento, lo logghiamo come fa il
        # backend live (per dare contesto sui cooldown). In questo probe
        # non applichiamo i filtri di backend, quindi assumiamo che sia
        # stato "parlato".
        if reason and reason != "all_ok" and message:
            from datetime import datetime
            interventions_log.append({
                "ts": datetime.utcnow().isoformat(),
                "reason": reason,
                "score": score or 0.0,
                "speaker": speaker,
                "message": message,
            })

    print()
    print(SEPARATOR)
    print(f"FINAL summary ({len(rolling_summary)} chars):")
    print(rolling_summary or "<EMPTY>")
    print(SEPARATOR)


if __name__ == "__main__":
    main()
