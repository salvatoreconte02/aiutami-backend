"""
Probe LLM bilingue: verifica che con MODERATOR_OUTPUT_LANGUAGE=Italian
l'output esca in italiano e con =English in inglese, senza code-switching.

Lancio (dentro container web):
    docker compose exec -e OPENAI_API_KEY=... \\
        -e MODERATOR_OUTPUT_LANGUAGE=Italian \\
        web python scripts/probe_language.py

    docker compose exec -e OPENAI_API_KEY=... \\
        -e MODERATOR_OUTPUT_LANGUAGE=English \\
        web python scripts/probe_language.py

Esegue 3 invocazioni LLM reali per scenario (off_topic, conflict,
monopolization), stampa message_to_say e una euristica "language guess"
basata su stop-word italiani vs inglesi.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import django  # noqa: E402

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "aiutami.settings")
django.setup()

from django.conf import settings  # noqa: E402

from apps.moderation.service import ModerationService  # noqa: E402


# Marker forti, parole funzione che l'LLM userà per forza nella sua lingua.
# Il count è approssimativo, non statisticamente robusto, ma sufficiente per
# detectare un code-switching grave su 1-2 frasi di output.
IT_MARKERS = (" il ", " la ", " che ", " di ", " un ", " una ", " sono ",
              " questo ", " stai ", " forse ", " mi ", " gli ", " ho ",
              " e' ", " è ", " perché ", " quando ")
EN_MARKERS = (" the ", " is ", " are ", " that ", " let's ", " we ",
              " you ", " your ", " can ", " do ", " what ", " maybe ",
              " hold ", " on ", " sounds ", " think ")


def language_guess(text: str | None) -> str:
    if not text:
        return "(empty)"
    s = " " + text.lower() + " "
    it_hits = sum(s.count(m) for m in IT_MARKERS)
    en_hits = sum(s.count(m) for m in EN_MARKERS)
    if it_hits == 0 and en_hits == 0:
        return f"unknown (it=0 en=0)"
    if it_hits >= en_hits * 2:
        return f"Italian (it={it_hits} en={en_hits})"
    if en_hits >= it_hits * 2:
        return f"English (it={it_hits} en={en_hits})"
    return f"MIXED (it={it_hits} en={en_hits})"


# Scenari: ogni "case" forza un comportamento specifico dell'LLM.
# I turni utente sono nella lingua "naturale dei partecipanti" (italiano)
# in entrambi i probe — questo è il caso reale: per il pilot inglese, gli
# utenti parleranno inglese, ma vogliamo verificare che anche con input
# italiano il modello rispetti MODERATOR_OUTPUT_LANGUAGE.

CASES_IT_INPUT = [
    {
        "id": "off_topic",
        "summary": "Marco e Anna stanno discutendo se l'ossigeno o l'acqua siano la priorità nel ranking lunare.",
        "last_turn": "Marco: ragazzi avete visto la partita ieri sera? Che gol!",
        "expected_reason_hint": "off_topic",
    },
    {
        "id": "conflict",
        "summary": "Il gruppo sta valutando l'ordine dei primi 3 oggetti.",
        "last_turn": "Marco: Anna, sei una stupida se pensi che il kit medico sia inutile, taci.",
        "expected_reason_hint": "conflict",
    },
    {
        "id": "user_request",
        "summary": "Il gruppo discute se la corda di nylon sia utile.",
        "last_turn": "Anna: moderatore, puoi aiutarci a capire come decidere quando non siamo d'accordo?",
        "expected_reason_hint": "user_request",
    },
]

CASES_EN_INPUT = [
    {
        "id": "off_topic",
        "summary": "Marco and Anna are debating whether oxygen or water comes first in the lunar ranking.",
        "last_turn": "Marco: did you guys watch the game last night? Amazing goal!",
        "expected_reason_hint": "off_topic",
    },
    {
        "id": "conflict",
        "summary": "The group is evaluating the order of the first 3 items.",
        "last_turn": "Marco: Anna, you're stupid if you think the medical kit is useless, just shut up.",
        "expected_reason_hint": "conflict",
    },
    {
        "id": "user_request",
        "summary": "The group is debating whether the nylon rope is useful.",
        "last_turn": "Anna: moderator, can you help us figure out how to decide when we disagree?",
        "expected_reason_hint": "user_request",
    },
]


def run_probe(runs_per_case: int = 1) -> int:
    language = getattr(settings, "MODERATOR_OUTPUT_LANGUAGE", "Italian")
    print(f"\n=== probe_language.py — MODERATOR_OUTPUT_LANGUAGE={language} ===\n")

    # Sceglie il pool di casi: input nella stessa lingua dell'output desiderato.
    # È il setup naturale del pilot (utenti italiani → IT, utenti inglesi → EN).
    cases = CASES_EN_INPUT if language == "English" else CASES_IT_INPUT

    leaks = 0
    total = 0
    for case in cases:
        for run in range(1, runs_per_case + 1):
            total += 1
            print(f"--- {case['id']} — run {run}/{runs_per_case} ---")
            print(f"  last_turn: {case['last_turn'][:80]}...")
            try:
                out = ModerationService._call_llm(
                    summary_in=case["summary"],
                    last_turn=case["last_turn"],
                    mode="normal",
                    session_phase="ACTIVE",
                    speaker_name="Marco",
                    speaking_time_per_participant={
                        "Marco": 60.0, "Anna": 60.0, "Lucia": 60.0,
                    },
                    elapsed_seconds=300.0,
                    interventions_log=[],
                    task_key="nasa_moon_survival",
                )
            except Exception as e:
                print(f"  ERROR: {e}")
                continue

            msg = out.get("message_to_say")
            summary = out.get("updated_summary")
            reason = out.get("reason")
            score = out.get("intervention_score")

            print(f"  reason: {reason}  score: {score}")
            print(f"  message_to_say: {msg!r}")
            print(f"  summary lang guess: {language_guess(summary)}")
            print(f"  message lang guess: {language_guess(msg)}")

            # Detect code-switching: lingua attesa diversa da quella detectata.
            expected_lang = language  # "Italian" o "English"
            for label, text in (("summary", summary), ("message", msg)):
                guess = language_guess(text)
                if guess.startswith("MIXED"):
                    print(f"  ⚠️  MIXED LANGUAGE in {label}")
                    leaks += 1
                elif expected_lang == "Italian" and guess.startswith("English"):
                    print(f"  ❌ LEAK: expected Italian, got English in {label}")
                    leaks += 1
                elif expected_lang == "English" and guess.startswith("Italian"):
                    print(f"  ❌ LEAK: expected English, got Italian in {label}")
                    leaks += 1
            print()

    print(f"=== Done: {total} runs, {leaks} language leaks/mixes detected ===")
    return 1 if leaks > 0 else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1,
                        help="invocations per case (default 1)")
    args = parser.parse_args()
    sys.exit(run_probe(runs_per_case=args.runs))
