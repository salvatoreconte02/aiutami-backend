from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import azure.cognitiveservices.speech as speechsdk

logger = logging.getLogger(__name__)


@dataclass
class _Stats:
    pushed_bytes_total: int = 0
    write_failures: int = 0


class AzureStreamingClient:
    """
    Client Azure Speech-to-Text streaming via PushAudioInputStream.

    Interfaccia attesa dal worker:
      - start()
      - push_audio(pcm_bytes: bytes)
      - stop()
      - (opzionale) queue_size property
    """

    def __init__(
        self,
        key: str,
        region: str,
        language: str = "it-IT",
        on_partial: Optional[Callable[[str], None]] = None,
        on_final: Optional[Callable[[str], None]] = None,
        sample_rate_hz: int = 16000,
        channels: int = 1,
        bits_per_sample: int = 16,
    ) -> None:
        self.key = key
        self.region = region
        self.language = language
        self.on_partial = on_partial
        self.on_final = on_final

        self.sample_rate_hz = int(sample_rate_hz)
        self.channels = int(channels)
        self.bits_per_sample = int(bits_per_sample)

        self._audio_q: "queue.Queue[Optional[bytes]]" = queue.Queue(maxsize=200)
        self._writer_thread: Optional[threading.Thread] = None
        self._running = False

        self._stats = _Stats()

        self._speech_config: Optional[speechsdk.SpeechConfig] = None
        self._push_stream: Optional[speechsdk.audio.PushAudioInputStream] = None
        self._audio_cfg: Optional[speechsdk.audio.AudioConfig] = None
        self._recognizer: Optional[speechsdk.SpeechRecognizer] = None

        self._lock = threading.Lock()

    @property
    def queue_size(self) -> int:
        try:
            return int(self._audio_q.qsize())
        except Exception:
            return 0

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True

        logger.info(
            "[AZURE-ASR] Avvio client streaming (region=%s, language=%s, sr=%s, ch=%s, bps=%s)",
            self.region,
            self.language,
            self.sample_rate_hz,
            self.channels,
            self.bits_per_sample,
        )

        # Speech config
        self._speech_config = speechsdk.SpeechConfig(subscription=self.key, region=self.region)
        self._speech_config.speech_recognition_language = self.language
        # Output dettagliato aiuta diagnosi (non cambia la trascrizione)
        self._speech_config.output_format = speechsdk.OutputFormat.Detailed

        # Audio stream format (PCM raw)
        fmt = speechsdk.audio.AudioStreamFormat(
            samples_per_second=self.sample_rate_hz,
            bits_per_sample=self.bits_per_sample,
            channels=self.channels,
        )
        self._push_stream = speechsdk.audio.PushAudioInputStream(stream_format=fmt)
        self._audio_cfg = speechsdk.audio.AudioConfig(stream=self._push_stream)

        # Recognizer
        self._recognizer = speechsdk.SpeechRecognizer(speech_config=self._speech_config, audio_config=self._audio_cfg)

        # Handlers
        def _on_recognizing(evt: speechsdk.SpeechRecognitionEventArgs) -> None:
            try:
                txt = evt.result.text or ""
                if txt and self.on_partial:
                    self.on_partial(txt)
                logger.info("[AZURE-ASR][partial] reason=%s text=%r", evt.result.reason, txt)
            except Exception:
                logger.exception("[AZURE-ASR] Errore handler recognizing")

        def _on_recognized(evt: speechsdk.SpeechRecognitionEventArgs) -> None:
            try:
                res = evt.result
                txt = res.text or ""
                logger.info("[AZURE-ASR][final] reason=%s text=%r", res.reason, txt)

                # Se arriva vuoto, è cruciale capire se è NoMatch o altro
                if res.reason == speechsdk.ResultReason.NoMatch:
                    try:
                        details = speechsdk.NoMatchDetails.from_result(res)
                        logger.warning("[AZURE-ASR][nomatch] %s", details)
                    except Exception:
                        logger.exception("[AZURE-ASR] Errore nel leggere NoMatchDetails")

                if self.on_final:
                    self.on_final(txt)
            except Exception:
                logger.exception("[AZURE-ASR] Errore handler recognized")

        def _on_canceled(evt: speechsdk.SpeechRecognitionCanceledEventArgs) -> None:
            try:
                logger.error(
                    "[AZURE-ASR][canceled] reason=%s error_code=%s details=%r",
                    evt.reason,
                    getattr(evt, "error_code", None),
                    getattr(evt, "error_details", None),
                )
            except Exception:
                logger.exception("[AZURE-ASR] Errore handler canceled")

        def _on_session_started(evt: speechsdk.SessionEventArgs) -> None:
            logger.info("[AZURE-ASR] Session started: %s", evt)

        def _on_session_stopped(evt: speechsdk.SessionEventArgs) -> None:
            logger.info("[AZURE-ASR] Session stopped: %s", evt)

        self._recognizer.recognizing.connect(_on_recognizing)
        self._recognizer.recognized.connect(_on_recognized)
        self._recognizer.canceled.connect(_on_canceled)
        self._recognizer.session_started.connect(_on_session_started)
        self._recognizer.session_stopped.connect(_on_session_stopped)

        # Writer thread (scrive sul push stream)
        self._writer_thread = threading.Thread(target=self._audio_loop, name="azure-asr-audio-loop", daemon=True)
        self._writer_thread.start()
        logger.info("[AZURE-ASR] Audio loop avviato")

        # Start continuous recognition
        try:
            self._recognizer.start_continuous_recognition_async().get()
            logger.info("[AZURE-ASR] Continuous recognition avviata correttamente")
        except Exception:
            logger.exception("[AZURE-ASR] Errore avvio continuous recognition")
            self._running = False
            raise

    def push_audio(self, pcm_bytes: bytes) -> None:
        if not pcm_bytes:
            return
        if not self._running:
            return
        try:
            # Non bloccare indefinitamente: se la coda è piena, si scarta e si logga
            self._audio_q.put(pcm_bytes, timeout=0.2)
            self._stats.pushed_bytes_total += len(pcm_bytes)
        except queue.Full:
            self._stats.write_failures += 1
            logger.warning("[AZURE-ASR] Queue full: drop chunk bytes=%d", len(pcm_bytes))
        except Exception:
            self._stats.write_failures += 1
            logger.exception("[AZURE-ASR] Errore enqueue audio")

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False

        # chiusura: sentinel al writer
        try:
            self._audio_q.put(None, timeout=0.2)
        except Exception:
            pass

        # attende writer
        if self._writer_thread:
            self._writer_thread.join(timeout=2.0)

        # chiude stream (segnala EOF ad Azure)
        try:
            if self._push_stream:
                self._push_stream.close()
        except Exception:
            logger.exception("[AZURE-ASR] Errore chiusura push stream")

        # breve grace (consente finalizzazione)
        time.sleep(0.4)

        # stop recognition
        try:
            if self._recognizer:
                self._recognizer.stop_continuous_recognition_async().get()
        except Exception:
            logger.exception("[AZURE-ASR] Errore stop continuous recognition")

        logger.info(
            "[AZURE-ASR] Stop client streaming (pushed_bytes_total=%d write_failures=%d queue_size=%d)",
            self._stats.pushed_bytes_total,
            self._stats.write_failures,
            self.queue_size,
        )

        self._recognizer = None
        self._audio_cfg = None
        self._push_stream = None
        self._speech_config = None
        self._writer_thread = None

    def _audio_loop(self) -> None:
        """
        Consuma bytes PCM dalla queue e li scrive su PushAudioInputStream.
        """
        try:
            while True:
                item = self._audio_q.get()
                if item is None:
                    break
                if not item:
                    continue
                try:
                    if self._push_stream:
                        self._push_stream.write(item)
                except Exception:
                    self._stats.write_failures += 1
                    logger.exception("[AZURE-ASR] Errore write su push stream")
        finally:
            logger.info("[AZURE-ASR] Audio loop terminato")