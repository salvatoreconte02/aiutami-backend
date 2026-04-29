"""
Client OpenAI Realtime per trascrizione streaming (transcription-only mode).

Espone la stessa interfaccia di AzureStreamingClient — `start()`,
`push_audio()`, `stop()`, callback `on_partial` / `on_final`,
property `queue_size` — così il worker ASR non deve conoscere il
provider sottostante.

Architettura:
- `push_audio()` è sincrona: mette i bytes in una `queue.Queue`
  thread-safe.
- `start()` avvia un thread che ospita un event loop asyncio
  dedicato.
- Dentro il loop, due coroutine: writer (legge dalla queue e invia
  `input_audio_buffer.append`) e reader (ascolta gli eventi dal
  WebSocket e propaga partial / final alle callback).
- `stop()` mette una sentinella nella queue, attende lo svuotamento,
  invia `input_audio_buffer.commit`, chiude il WebSocket e fa join
  del thread.

Non c'è da fare polling o retry esplicito: la connessione WebSocket è
persistente per tutta la durata del turno; se crolla, un ciclo viene
propagato al chiamante via logging e lo stop procede normalmente.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import websockets
from websockets.asyncio.client import ClientConnection

logger = logging.getLogger(__name__)


REALTIME_URL = "wss://api.openai.com/v1/realtime?intent=transcription"
REALTIME_BETA_HEADER = "realtime=v1"


@dataclass
class _Stats:
    pushed_bytes_total: int = 0
    write_failures: int = 0


class OpenAIRealtimeTranscriptionClient:
    """
    OpenAI Realtime transcription-only streaming client.

    Interfaccia attesa dal worker:
      - start()
      - push_audio(pcm_bytes: bytes)
      - stop()
      - queue_size property
      - callback on_partial(text: str), on_final(text: str)
    """

    # Timeout grazia per attendere eventi finali dopo commit
    STOP_FINAL_GRACE_S = 1.5

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini-transcribe",
        language: str = "it",
        on_partial: Optional[Callable[[str], None]] = None,
        on_final: Optional[Callable[[str], None]] = None,
        sample_rate_hz: int = 24000,
        channels: int = 1,
        bits_per_sample: int = 16,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.language = language
        self.on_partial = on_partial
        self.on_final = on_final

        self.sample_rate_hz = int(sample_rate_hz)
        self.channels = int(channels)
        self.bits_per_sample = int(bits_per_sample)

        self._audio_q: "queue.Queue[Optional[bytes]]" = queue.Queue(maxsize=200)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._connected_event = threading.Event()
        self._stopped_event = threading.Event()
        self._running = False

        self._ws: Optional[ClientConnection] = None
        self._stats = _Stats()

        # Accumulatore partial: gli eventi `.delta` riportano singoli
        # incrementi di testo. L'API Azure vecchia esponeva invece il
        # partial cumulativo. Per preservare la semantica delle
        # callback del worker, accumulo qui il testo parziale corrente
        # e lo resetto quando arriva `.completed`.
        self._partial_buffer = ""
        self._lock = threading.Lock()

    @property
    def queue_size(self) -> int:
        try:
            return int(self._audio_q.qsize())
        except Exception:
            return 0

    # Lifecycle

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._connected_event.clear()
            self._stopped_event.clear()

        logger.debug(
            "[OPENAI-ASR] Avvio client streaming (model=%s language=%s sr=%s)",
            self.model,
            self.language,
            self.sample_rate_hz,
        )

        self._loop_thread = threading.Thread(
            target=self._thread_entry,
            name="openai-asr-loop",
            daemon=True,
        )
        self._loop_thread.start()

        # Attendo la conferma di connessione (timeout 10s) ma se non
        # arriva il client continua comunque (il writer scarterà i
        # frame finché il WS non è pronto).
        if not self._connected_event.wait(timeout=10.0):
            logger.warning("[OPENAI-ASR] Connessione WS non confermata entro 10s (proseguo)")

    def push_audio(self, pcm_bytes: bytes) -> None:
        if not pcm_bytes:
            return
        if not self._running:
            return
        try:
            self._audio_q.put(pcm_bytes, timeout=0.2)
            self._stats.pushed_bytes_total += len(pcm_bytes)
        except queue.Full:
            self._stats.write_failures += 1
            logger.warning("[OPENAI-ASR] Queue full: drop chunk bytes=%d", len(pcm_bytes))
        except Exception:
            self._stats.write_failures += 1
            logger.exception("[OPENAI-ASR] Errore enqueue audio")

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False

        # Sentinel al writer
        try:
            self._audio_q.put(None, timeout=0.2)
        except Exception:
            pass

        # Attende la fine del thread (con loop interno)
        if self._loop_thread is not None:
            self._loop_thread.join(timeout=self.STOP_FINAL_GRACE_S + 3.0)

        logger.debug(
            "[OPENAI-ASR] Stop client streaming (pushed_bytes_total=%d write_failures=%d queue_size=%d)",
            self._stats.pushed_bytes_total,
            self._stats.write_failures,
            self.queue_size,
        )

        self._loop_thread = None
        self._loop = None
        self._ws = None

    # Thread + loop

    def _thread_entry(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._main())
        except Exception:
            logger.exception("[OPENAI-ASR] Errore nel main loop")
        finally:
            try:
                loop.close()
            except Exception:
                pass
            self._stopped_event.set()

    async def _main(self) -> None:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "OpenAI-Beta": REALTIME_BETA_HEADER,
        }

        try:
            async with websockets.connect(
                REALTIME_URL,
                additional_headers=headers,
                max_size=2**24,  # 16MB per evento (audio grandi ok)
            ) as ws:
                self._ws = ws

                # Configurazione sessione transcription-only
                session_update = {
                    "type": "transcription_session.update",
                    "session": {
                        "input_audio_format": "pcm16",
                        "input_audio_transcription": {
                            "model": self.model,
                            "language": self.language,
                        },
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": 0.5,
                            "prefix_padding_ms": 300,
                            "silence_duration_ms": 500,
                        },
                    },
                }
                await ws.send(json.dumps(session_update))
                logger.debug("[OPENAI-ASR] transcription_session.update inviato")

                self._connected_event.set()

                writer_task = asyncio.create_task(self._writer_loop(ws), name="openai-asr-writer")
                reader_task = asyncio.create_task(self._reader_loop(ws), name="openai-asr-reader")

                # Attende il writer (uscirà sulla sentinella)
                await writer_task

                # Committa l'audio residuo e attende eventi finali
                try:
                    await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                    logger.debug("[OPENAI-ASR] input_audio_buffer.commit inviato")
                except Exception:
                    logger.exception("[OPENAI-ASR] Errore invio commit")

                # Grazia per ricevere gli ultimi `.completed`
                try:
                    await asyncio.wait_for(
                        self._wait_reader_quiet(reader_task),
                        timeout=self.STOP_FINAL_GRACE_S,
                    )
                except asyncio.TimeoutError:
                    pass

                reader_task.cancel()
                try:
                    await reader_task
                except (asyncio.CancelledError, Exception):
                    pass

        except Exception:
            logger.exception("[OPENAI-ASR] Errore connessione/sessione WS")
            self._connected_event.set()  # sblocca eventuali waiter

    async def _wait_reader_quiet(self, reader_task: asyncio.Task) -> None:
        """Attende finché il reader è ancora attivo (fino al timeout esterno)."""
        while not reader_task.done():
            await asyncio.sleep(0.05)

    async def _writer_loop(self, ws: ClientConnection) -> None:
        """
        Legge chunk PCM dalla queue sync e li invia come eventi
        `input_audio_buffer.append` (base64).
        """
        loop = asyncio.get_event_loop()
        try:
            while True:
                # Uso run_in_executor per bridge blocking get() → asyncio
                item = await loop.run_in_executor(None, self._audio_q.get)
                if item is None:
                    break
                if not item:
                    continue
                try:
                    b64 = base64.b64encode(item).decode("ascii")
                    await ws.send(json.dumps({
                        "type": "input_audio_buffer.append",
                        "audio": b64,
                    }))
                except Exception:
                    self._stats.write_failures += 1
                    logger.exception("[OPENAI-ASR] Errore invio audio chunk")
        finally:
            logger.debug("[OPENAI-ASR] Writer terminato")

    async def _reader_loop(self, ws: ClientConnection) -> None:
        """
        Consuma eventi dal WebSocket e propaga partial/final alle
        callback registrate.
        """
        try:
            async for raw in ws:
                try:
                    event = json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode("utf-8"))
                except Exception:
                    logger.exception("[OPENAI-ASR] Errore parsing evento WS")
                    continue
                self._handle_event(event)
        except Exception:
            # Chiusura WS o errore di rete: semplicemente usciamo
            logger.debug("[OPENAI-ASR] Reader terminato (connessione chiusa)")

    def _handle_event(self, event: dict) -> None:
        et = event.get("type") or ""

        if et == "conversation.item.input_audio_transcription.delta":
            delta = event.get("delta") or ""
            if not delta:
                return
            self._partial_buffer += delta
            if self.on_partial:
                try:
                    self.on_partial(self._partial_buffer)
                except Exception:
                    logger.exception("[OPENAI-ASR] Errore callback on_partial")
            logger.debug("[OPENAI-ASR][partial] delta=%r", delta)
            return

        if et == "conversation.item.input_audio_transcription.completed":
            text = (event.get("transcript") or "").strip()
            self._partial_buffer = ""
            if text:
                logger.info("[OPENAI-ASR][final] text=%r", text)
                if self.on_final:
                    try:
                        self.on_final(text)
                    except Exception:
                        logger.exception("[OPENAI-ASR] Errore callback on_final")
            else:
                logger.warning("[OPENAI-ASR][final-empty] evento completed con transcript vuoto")
            return

        if et == "conversation.item.input_audio_transcription.failed":
            logger.warning("[OPENAI-ASR][transcription_failed] event=%s", event)
            return

        if et in ("transcription_session.created", "transcription_session.updated"):
            logger.debug("[OPENAI-ASR][%s] id=%s", et, event.get("session", {}).get("id"))
            return

        if et == "input_audio_buffer.speech_started":
            logger.debug("[OPENAI-ASR][vad] speech_started")
            return

        if et == "input_audio_buffer.speech_stopped":
            logger.debug("[OPENAI-ASR][vad] speech_stopped")
            return

        if et == "input_audio_buffer.committed":
            logger.debug("[OPENAI-ASR][buffer] committed item_id=%s", event.get("item_id"))
            return

        if et == "error":
            err = event.get("error") or {}
            logger.error(
                "[OPENAI-ASR][error] type=%s message=%s",
                err.get("type"),
                err.get("message"),
            )
            return

        logger.debug("[OPENAI-ASR][event] %s", et)
