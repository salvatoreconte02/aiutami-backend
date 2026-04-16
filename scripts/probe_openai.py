"""
Probe script per verificare le capability della chiave OpenAI del lab.

Testa:
  1. LLM chat completion (gpt-4o-mini)
  2. STT batch (whisper-1)
  3. STT batch nuovo (gpt-4o-mini-transcribe, se disponibile)
  4. TTS (tts-1)
  5. TTS nuovo (gpt-4o-mini-tts, se disponibile)
  6. Realtime API (gpt-4o-mini-realtime-preview) — solo check modello visibile

Lancio:
    python scripts/probe_openai.py
"""
from __future__ import annotations

import io
import os
import sys
import wave
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from openai import OpenAI, APIError


ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

if load_dotenv is not None and ENV_PATH.exists():
    load_dotenv(ENV_PATH)

API_KEY = os.getenv("OPENAI_KEY_LAB_POLIMI")
if not API_KEY:
    print("ERRORE: variabile OPENAI_KEY_LAB_POLIMI non trovata nel .env")
    sys.exit(1)

client = OpenAI(api_key=API_KEY)


def ok(msg: str) -> None:
    print(f"  [OK]    {msg}")


def ko(msg: str) -> None:
    print(f"  [FAIL]  {msg}")


def info(msg: str) -> None:
    print(f"  [INFO]  {msg}")


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def build_silent_wav(seconds: float = 1.0, sample_rate: int = 16000) -> io.BytesIO:
    """Genera un WAV di silenzio valido per test STT."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00\x00" * int(seconds * sample_rate))
    buf.seek(0)
    buf.name = "probe.wav"
    return buf


def test_llm(model: str) -> None:
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Rispondi solo con OK."}],
            max_tokens=5,
        )
        ok(f"LLM {model} -> '{resp.choices[0].message.content.strip()}'")
    except APIError as e:
        ko(f"LLM {model} -> {e.status_code} {e.message}")
    except Exception as e:
        ko(f"LLM {model} -> {type(e).__name__}: {e}")


def test_stt(model: str) -> None:
    try:
        audio = build_silent_wav(1.0)
        resp = client.audio.transcriptions.create(model=model, file=audio)
        ok(f"STT {model} -> testo='{resp.text!r}' (silenzio, testo vuoto e' ok)")
    except APIError as e:
        ko(f"STT {model} -> {e.status_code} {e.message}")
    except Exception as e:
        ko(f"STT {model} -> {type(e).__name__}: {e}")


def test_tts(model: str, voice: str = "nova") -> None:
    try:
        resp = client.audio.speech.create(
            model=model,
            voice=voice,
            input="Ciao, test.",
            response_format="mp3",
        )
        data = resp.read() if hasattr(resp, "read") else resp.content
        ok(f"TTS {model} voce={voice} -> {len(data)} bytes mp3")
    except APIError as e:
        ko(f"TTS {model} -> {e.status_code} {e.message}")
    except Exception as e:
        ko(f"TTS {model} -> {type(e).__name__}: {e}")


def test_models_list() -> None:
    """Lista i modelli visibili, filtrando per quelli che ci interessano."""
    try:
        models = client.models.list()
        names = sorted(m.id for m in models.data)
        interesting_prefixes = (
            "gpt-4o",
            "gpt-4.1",
            "whisper",
            "tts",
            "o1",
            "o3",
        )
        filtered = [n for n in names if n.startswith(interesting_prefixes)]
        info(f"Totale modelli visibili: {len(names)}")
        for n in filtered:
            print(f"    - {n}")
    except APIError as e:
        ko(f"models.list -> {e.status_code} {e.message}")
    except Exception as e:
        ko(f"models.list -> {type(e).__name__}: {e}")


def main() -> None:
    print(f"Uso chiave OPENAI_KEY_LAB_POLIMI (prefisso: {API_KEY[:10]}...)")

    section("Modelli visibili (filtrati)")
    test_models_list()

    section("LLM")
    test_llm("gpt-4o-mini")
    test_llm("gpt-4o")

    section("STT (batch)")
    test_stt("whisper-1")
    test_stt("gpt-4o-mini-transcribe")
    test_stt("gpt-4o-transcribe")

    section("TTS")
    test_tts("tts-1", voice="nova")
    test_tts("tts-1-hd", voice="nova")
    test_tts("gpt-4o-mini-tts", voice="nova")

    section("Fine probe")
    print("Realtime API: non testata qui (richiede WebSocket).")
    print("Se 'gpt-4o-mini-realtime-preview' compare nella lista modelli,")
    print("probabilmente hai accesso — si testa con client separato.")


if __name__ == "__main__":
    main()
