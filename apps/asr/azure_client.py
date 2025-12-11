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
    Adapter minimale per Azure Speech-To-Text in modalità streaming continua.
    - riceve chunk PCM 16kHz mono (bytes)
    - li invia ad Azure tramite PushAudioInputStream
    - espone callback per partial / final
    """

    def __init__(
        self,
        key: str,
        region: str,
        language: str = "it-IT",
        on_partial: Optional[Callable[[str], None]] = None,
        on_final: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.key = key
        self.region = region
        self.language = language

        self.on_partial = on_partial
        self.on_final = on_final

        self._audio_queue: "queue.Queue[bytes]" = queue.Queue()
        self._stop_flag = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

        self._stream: Optional[speechsdk.audio.PushAudioInputStream] = None
        self._recognizer: Optional[speechsdk.SpeechRecognizer] = None

    # ----------------------------------------------------------
    # PUBLIC API
    # ----------------------------------------------------------

    def start(self) -> None:
        """
        Avvia la sessione Azure + thread che invia i chunk dalla coda.
        Blocca finché la continuous recognition non è effettivamente partita.
        """
        logger.info(
            "[AZURE-ASR] Avvio client streaming (region=%s, language=%s)",
            self.region,
            self.language,
        )

        # Configurazione di base
        speech_config = speechsdk.SpeechConfig(
            subscription=self.key,
            region=self.region,
        )
        speech_config.speech_recognition_language = self.language

        # Formato audio: 16kHz, 16bit, mono
        audio_format = speechsdk.audio.AudioStreamFormat(
            samples_per_second=16000,
            bits_per_sample=16,
            channels=1,
        )
        self._stream = speechsdk.audio.PushAudioInputStream(audio_format)
        audio_config = speechsdk.audio.AudioConfig(stream=self._stream)

        self._recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config,
        )

        # EVENTI ------------------------------------------------

        def _on_recognizing(evt: speechsdk.SpeechRecognitionEventArgs) -> None:
            try:
                text = evt.result.text
            except Exception:
                text = ""
            if self.on_partial and text:
                self.on_partial(text)

        def _on_recognized(evt: speechsdk.SpeechRecognitionEventArgs) -> None:
            try:
                text = evt.result.text
            except Exception:
                text = ""
            if self.on_final and text:
                self.on_final(text)

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
            # blocca finché la chiamata non è completata
            start_future.get()
            logger.info("[AZURE-ASR] Continuous recognition avviata correttamente")
        except Exception as e:
            logger.exception(
                "[AZURE-ASR] Errore in start_continuous_recognition_async: %s", e
            )
            return

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
        logger.info("[AZURE-ASR] Stop client streaming")
        self._stop_flag.set()

        if self._recognizer is not None:
            try:
                stop_future = self._recognizer.stop_continuous_recognition_async()
                # la .get() della ResultFuture non accetta timeout nella versione attuale
                stop_future.get()
            except Exception:
                logger.exception(
                    "[AZURE-ASR] Errore in stop_continuous_recognition_async"
                )

        if self._stream is not None:
            try:
                self._stream.close()
            except Exception:
                logger.exception(
                    "[AZURE-ASR] Errore chiudendo PushAudioInputStream"
                )

    def push_audio(self, pcm_bytes: bytes) -> None:
        """
        Chiamata dal tuo ASRStreamWorker per accodare audio PCM 16kHz mono.
        """
        if self._stop_flag.is_set():
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
                self._stream.write(chunk)
            except Exception as e:
                logger.error("[AZURE-ASR] Errore scrittura stream: %s", e)

        logger.info("[AZURE-ASR] Audio loop terminato")