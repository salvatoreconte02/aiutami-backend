# apps/asr/worker.py

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
from django.conf import settings
from django.contrib.auth import get_user_model

from .azure_client import AzureStreamingClient
from .models import ASRTranscript

logger = logging.getLogger(__name__)
User = get_user_model()


class ASRStreamWorker:
    """
    Rappresenta lo stream ASR per una coppia (session_id, user_id).

    Responsabilità:
    - ricevere frame audio (aiortc / PyAV)
    - convertire i frame in PCM int16 mono
    - inviare i chunk PCM al client Azure streaming (se configurato)
    - loggare dimensioni e metadati del chunk PCM
    - salvare nel DB le trascrizioni finali restituite da Azure

    Il worker viene gestito dal WebRTCConsumer tramite ASRStreamManager:
    - ASRStreamManager.start_stream(...) chiama .start()
    - ASRStreamManager.ingest_frame(...) chiama .ingest_frame(...)
    - ASRStreamManager.stop_stream(...) chiama .stop()
    """

    def __init__(self, session_id: str, user_id: int) -> None:
        self.session_id = str(session_id)
        self.user_id = int(user_id)

        # Metadati utili per debug / integrazione ASR
        self.sample_rate: Optional[int] = None
        self.channels: Optional[int] = None
        self.total_samples: int = 0
        self.total_bytes: int = 0
        self.started: bool = False

        # Client Azure streaming (creato in start se configurato)
        self._azure_client: Optional[AzureStreamingClient] = None

    # ------------------------------------------------------------------ #
    # Ciclo di vita dello stream
    # ------------------------------------------------------------------ #

    def _init_azure_client(self) -> None:
        """
        Inizializza AzureStreamingClient se le variabili di configurazione
        sono presenti. In caso contrario, lascia il worker in modalità
        "solo logging" (nessuna chiamata esterna).
        """
        key = getattr(settings, "AZURE_SPEECH_KEY", None)
        region = getattr(settings, "AZURE_SPEECH_REGION", None)
        language = getattr(settings, "AZURE_SPEECH_LANGUAGE", "it-IT")

        if not key or not region:
            logger.warning(
                "[ASR] AzureSpeech non configurato "
                "(manca AZURE_SPEECH_KEY o AZURE_SPEECH_REGION). "
                "Lo stream funzionerà in sola modalità logging."
            )
            return

        def _on_partial(text: str) -> None:
            if not text:
                return
            logger.info(
                "[ASR][AZURE][partial] session=%s user=%s text=%r",
                self.session_id,
                self.user_id,
                text,
            )

        def _on_final(text: str) -> None:
            """
            Callback invocato da Azure quando viene restituito
            un segmento di trascrizione finale.
            - logga il testo,
            - lo salva nel modello ASRTranscript.
            """
            if not text:
                return

            logger.info(
                "[ASR][AZURE][final] session=%s user=%s text=%r",
                self.session_id,
                self.user_id,
                text,
            )

            # Persistenza nel DB (best-effort, gli errori non bloccano il flusso)
            try:
                user = User.objects.filter(pk=self.user_id).first()
                ASRTranscript.objects.create(
                    session_id=self.session_id,
                    user=user,
                    text=text,
                    is_final=True,
                    source="azure",
                )
            except Exception:
                logger.exception(
                    "[ASR] Errore nel salvataggio ASRTranscript "
                    "session=%s user=%s",
                    self.session_id,
                    self.user_id,
                )

        self._azure_client = AzureStreamingClient(
            key=key,
            region=region,
            language=language,
            on_partial=_on_partial,
            on_final=_on_final,
        )

    def start(self) -> None:
        """
        Chiamato da ASRStreamManager quando lo stream viene creato.
        Inizializza (eventualmente) il client Azure e avvia lo streaming.
        """
        if self.started:
            return

        self.started = True
        logger.info(
            "[ASR] Worker avviato session=%s user=%s",
            self.session_id,
            self.user_id,
        )

        # Inizializzazione client Azure (se configurato)
        self._init_azure_client()
        if self._azure_client is not None:
            try:
                self._azure_client.start()
                logger.info(
                    "[ASR] AzureStreamingClient avviato session=%s user=%s",
                    self.session_id,
                    self.user_id,
                )
            except Exception:
                logger.exception(
                    "[ASR] Errore nell'avvio di AzureStreamingClient "
                    "session=%s user=%s",
                    self.session_id,
                    self.user_id,
                )
                # In caso di errore si lavora comunque in sola modalità logging
                self._azure_client = None

    def stop(self) -> None:
        """
        Chiamato da ASRStreamManager quando lo stream viene chiuso.
        Chiude il client Azure (se presente) e logga un riepilogo.
        """
        if not self.started:
            return

        # Stop Azure
        if self._azure_client is not None:
            try:
                self._azure_client.stop()
            except Exception:
                logger.exception(
                    "[ASR] Errore nello stop di AzureStreamingClient "
                    "session=%s user=%s",
                    self.session_id,
                    self.user_id,
                )

        logger.info(
            "[ASR] Worker terminato session=%s user=%s "
            "total_samples=%d total_bytes=%d",
            self.session_id,
            self.user_id,
            self.total_samples,
            self.total_bytes,
        )

        self.started = False
        self._azure_client = None

    # ------------------------------------------------------------------ #
    # Ingestione frame audio
    # ------------------------------------------------------------------ #

    def ingest_frame(self, frame) -> None:
        """
        Riceve un frame audio da aiortc (tipicamente av.AudioFrame),
        lo converte in PCM int16 mono, lo logga, e se disponibile
        lo invia al client Azure in streaming.
        """

        # Estrazione metadati dal frame
        try:
            frame_sample_rate = getattr(frame, "sample_rate", None)
            frame_layout = getattr(frame, "layout", None)
        except Exception:
            frame_sample_rate = None
            frame_layout = None

        if self.sample_rate is None and frame_sample_rate is not None:
            self.sample_rate = int(frame_sample_rate)

        # Conversione in ndarray int16
        try:
            pcm = frame.to_ndarray(format="s16")
        except Exception:
            logger.exception(
                "[ASR] Errore in to_ndarray session=%s user=%s",
                self.session_id,
                self.user_id,
            )
            return

        # Gestione mono / multi-canale
        if pcm.ndim == 1:
            # Già mono: shape (samples,)
            pcm_mono = pcm.astype(np.int16, copy=False)
            channels = 1
        else:
            # shape (channels, samples) -> media sui canali
            channels = pcm.shape[0]
            pcm_mono = pcm.mean(axis=0).astype(np.int16)

        self.channels = channels

        # Conversione in bytes (PCM 16-bit little endian)
        pcm_bytes = pcm_mono.tobytes()
        num_samples = pcm_mono.shape[-1]
        num_bytes = len(pcm_bytes)

        self.total_samples += num_samples
        self.total_bytes += num_bytes

        # Logging del chunk corrente
        logger.info(
            "[ASR] PCM chunk session=%s user=%s samples=%d bytes=%d "
            "sr=%s layout=%s ch=%s",
            self.session_id,
            self.user_id,
            num_samples,
            num_bytes,
            self.sample_rate,
            frame_layout,
            self.channels,
        )

        # Invio al servizio ASR streaming (se attivo)
        if self._azure_client is not None:
            try:
                self._azure_client.push_audio(pcm_bytes)
            except Exception:
                logger.exception(
                    "[ASR] Errore nell'invio chunk a Azure session=%s user=%s",
                    self.session_id,
                    self.user_id,
                )