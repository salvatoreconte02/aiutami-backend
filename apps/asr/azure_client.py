# apps/asr/azure_client.py

from __future__ import annotations

import logging
import threading
import queue
from typing import Callable, Optional

import azure.cognitiveservices.speech as speechsdk

logger = logging.getLogger(__name__)


class AzureStreamingClient:
    """
    Adapter per Azure Speech-To-Text in modalità streaming continua.
    - riceve chunk PCM (bytes)
    - li invia ad Azure tramite PushAudioInputStream
    - espone callback per partial / final

    IMPORTANTE:
    - Il formato dichiarato qui (sample rate / channels) deve combaciare con quello dei bytes inviati.
    - Se dichiari 16kHz ma mandi 48kHz, Azure interpreterà male il segnale.
    """

    def __init__(
        self,
        key: str,
        region: str,
        language: str = "it-IT",
        on_partial: Optional[Callable[[str], None]] = None,
        on_final: Optional[Callable[[str], None]] = None,
        *,
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

        self._audio_queue: "queue.Queue[bytes]" = queue.Queue()
        self._stop_flag = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

        self._stream: Optional[speechsdk.audio.PushAudioInputStream] = None
        self._recognizer: Optional[speechsdk.SpeechRecognizer] = None

        # stats / debug
        self._pushed_bytes_total: int = 0
        self._write_failures: int = 0
        self._started: bool = False

    # ----------------------------------------------------------
    # PUBLIC API
    # ----------------------------------------------------------

    def start(self) -> None:
        """
        Avvia la sessione Azure + thread che invia i chunk dalla coda.
        Blocca finché la continuous recognition non è effettivamente partita.
        """
        if self._started:
            return

        logger.info(
            "[AZURE-ASR] Avvio client streaming (region=%s, language=%s, sr=%s, ch=%s, bps=%s)",
            self.region,
            self.language,
            self.sample_rate_hz,
            self.channels,
            self.bits_per_sample,
        )

        # Configurazione di base
        speech_config = speechsdk.SpeechConfig(
            subscription=self.key,
            region=self.region,
        )
        speech_config.speech_recognition_language = self.language

        # Formato audio dichiarato allo stream (DEVE combaciare con i bytes inviati)
        audio_format = speechsdk.audio.AudioStreamFormat(
            samples_per_second=self.sample_rate_hz,
            bits_per_sample=self.bits_per_sample,
            channels=self.channels,
        )
        self._stream = speechsdk.audio.PushAudioInputStream(audio_format)
        audio_config = speechsdk.audio.AudioConfig(stream=self._stream)

        self._recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config,
        )

        # EVENTI ------------------------------------------------

        def _on_recognizing(evt: speechsdk.SpeechRecognitionEventArgs) -> None:
            # partial
            try:
                res = evt.result
                text = res.text or ""
                reason = getattr(res, "reason", None)
                if text:
                    logger.info("[AZURE-ASR][partial] reason=%s text=%r", reason, text)
                else:
                    # utile per capire se sta “girando” ma senza testo
                    logger.debug("[AZURE-ASR][partial] reason=%s (empty text)", reason)
            except Exception:
                logger.exception("[AZURE-ASR][partial] handler error")

            if self.on_partial and text:
                try:
                    self.on_partial(text)
                except Exception:
                    logger.exception("[AZURE-ASR] on_partial callback error")

        def _on_recognized(evt: speechsdk.SpeechRecognitionEventArgs) -> None:
            # final / no-match
            try:
                res = evt.result
                text = res.text or ""
                reason = getattr(res, "reason", None)

                # Il reason è la cosa più importante da loggare per debug:
                # - RecognizedSpeech: testo valido
                # - NoMatch: niente riconosciuto
                logger.info("[AZURE-ASR][final] reason=%s text=%r", reason, text)

                # In caso di NoMatch, spesso è sample rate errato o audio troppo basso / silenzioso.
                if reason == speechsdk.ResultReason.NoMatch:
                    try:
                        nm = speechsdk.NoMatchDetails.from_result(res)
                        logger.warning("[AZURE-ASR][final] NoMatchDetails=%r", nm)
                    except Exception:
                        logger.warning("[AZURE-ASR][final] NoMatchDetails non disponibili")
            except Exception:
                logger.exception("[AZURE-ASR][final] handler error")
                text = ""

            if self.on_final and text:
                try:
                    self.on_final(text)
                except Exception:
                    logger.exception("[AZURE-ASR] on_final callback error")

        def _on_canceled(evt: speechsdk.SpeechRecognitionCanceledEventArgs) -> None:
            try:
                details = evt.result.cancellation_details
                logger.error(
                    "[AZURE-ASR] CANCELED: reason=%s error_code=%s error_details=%r",
                    details.reason,
                    getattr(details, "error_code", None),
                    details.error_details,
                )
            except Exception:
                logger.error("[AZURE-ASR] CANCELED (raw evt=%r)", evt)

        def _on_session_started(evt: speechsdk.SessionEventArgs) -> None:
            logger.info("[AZURE-ASR] Session started: %r", evt)

        def _on_session_stopped(evt: speechsdk.SessionEventArgs) -> None:
            logger.info("[AZURE-ASR] Session stopped: %r", evt)

        self._recognizer.recognizing.connect(_on_recognizing)
        self._recognizer.recognized.connect(_on_recognized)
        self._recognizer.canceled.connect(_on_canceled)
        self._recognizer.session_started.connect(_on_session_started)
        self._recognizer.session_stopped.connect(_on_session_stopped)

        # Avvio effettivo della continuous recognition
        start_future = self._recognizer.start_continuous_recognition_async()
        try:
            start_future.get()
            logger.info("[AZURE-ASR] Continuous recognition avviata correttamente")
        except Exception:
            logger.exception("[AZURE-ASR] Errore in start_continuous_recognition_async")
            return

        self._started = True

        # Thread che consuma i chunk dalla coda e li scrive nello stream
        self._worker_thread = threading.Thread(
            target=self._audio_loop,
            name="azure-asr-audio-loop",
            daemon=True,
        )
        self._worker_thread.start()

    def stop(self) -> None:
        """
        Chiude stream + thread.
        """
        logger.info(
            "[AZURE-ASR] Stop client streaming (pushed_bytes_total=%d write_failures=%d queue_size=%d)",
            self._pushed_bytes_total,
            self._write_failures,
            self._audio_queue.qsize(),
        )

        self._stop_flag.set()

        if self._recognizer is not None:
            try:
                stop_future = self._recognizer.stop_continuous_recognition_async()
                stop_future.get()
            except Exception:
                logger.exception("[AZURE-ASR] Errore in stop_continuous_recognition_async")

        if self._stream is not None:
            try:
                self._stream.close()
            except Exception:
                logger.exception("[AZURE-ASR] Errore chiudendo PushAudioInputStream")

        self._started = False

    def push_audio(self, pcm_bytes: bytes) -> None:
        """
        Chiamata dal tuo ASRStreamWorker per accodare audio PCM.
        """
        if self._stop_flag.is_set() or not self._started:
            return
        if not pcm_bytes:
            return
        self._audio_queue.put(pcm_bytes)

    # ----------------------------------------------------------
    # PRIVATE LOOP — invio chunk
    # ----------------------------------------------------------

    def _audio_loop(self) -> None:
        """
        Invia allo stream Azure tutti i chunk PCM presenti in coda.
        """
        logger.info("[AZURE-ASR] Audio loop avviato")

        while not self._stop_flag.is_set():
            try:
                chunk = self._audio_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if not chunk:
                continue

            try:
                # self._stream può essere None solo se start() non è riuscito
                if self._stream is None:
                    continue

                self._stream.write(chunk)
                self._pushed_bytes_total += len(chunk)

                # Debug “leggero”: ogni ~1MB
                if self._pushed_bytes_total % (1024 * 1024) < len(chunk):
                    logger.debug(
                        "[AZURE-ASR] pushed_bytes_total=%d queue_size=%d",
                        self._pushed_bytes_total,
                        self._audio_queue.qsize(),
                    )

            except Exception:
                self._write_failures += 1
                logger.exception("[AZURE-ASR] Errore scrittura stream")

        logger.info("[AZURE-ASR] Audio loop terminato")