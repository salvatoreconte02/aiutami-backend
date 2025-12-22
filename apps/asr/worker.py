# apps/asr/worker.py

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
from django.conf import settings

from .azure_client import AzureStreamingClient

logger = logging.getLogger(__name__)


class ASRStreamWorker:
    """
    Rappresenta lo stream ASR per una coppia (session_id, user_id).

    Responsabilità:
    - ricevere frame audio (aiortc / PyAV)
    - convertire i frame in PCM int16 mono
    - (FIX) resamplare a 16kHz mono per Azure STT
    - inviare i chunk PCM al client Azure streaming (se configurato)
    - loggare dimensioni e metadati del chunk PCM
    - salvare nel DB le trascrizioni finali restituite da Azure
    """

    AZURE_TARGET_SR = 16000  # Azure Speech STT tipico (e il tuo azure_client è impostato così)

    def __init__(self, session_id: str, user_id: int) -> None:
        self.session_id = str(session_id)
        self.user_id = int(user_id)

        self.sample_rate: Optional[int] = None
        self.channels: Optional[int] = None
        self.total_samples: int = 0
        self.total_bytes: int = 0
        self.started: bool = False

        self._azure_client: Optional[AzureStreamingClient] = None

    # ------------------------------------------------------------------ #
    # Ciclo di vita dello stream
    # ------------------------------------------------------------------ #

    def _init_azure_client(self) -> None:
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
            if not text:
                return

            logger.info(
                "[ASR][AZURE][final] session=%s user=%s text=%r",
                self.session_id,
                self.user_id,
                text,
            )

            try:
                from django.utils import timezone
                from django.apps import apps as django_apps

                ASRTranscript = django_apps.get_model("asr", "ASRTranscript")
                Session = django_apps.get_model("sessions", "Session")

                session_obj = Session.objects.filter(id=self.session_id).first()
                if session_obj is None:
                    logger.warning(
                        "[ASR][AZURE][final] Session non trovata, skip salvataggio transcript "
                        "session=%s user=%s",
                        self.session_id,
                        self.user_id,
                    )
                    return

                ASRTranscript.objects.create(
                    session=session_obj,
                    user_id=self.user_id,
                    text=text,
                    created_at=timezone.now(),
                )

                logger.info(
                    "[ASR][AZURE][final] Transcript salvato su DB session=%s user=%s",
                    self.session_id,
                    self.user_id,
                )
            except Exception:
                logger.exception(
                    "[ASR][AZURE][final] Errore nel salvataggio transcript su DB "
                    "session=%s user=%s",
                    self.session_id,
                    self.user_id,
                )

        # IMPORTANTE: AzureStreamingClient di default è 16kHz mono.
        self._azure_client = AzureStreamingClient(
            key=key,
            region=region,
            language=language,
            on_partial=_on_partial,
            on_final=_on_final,
            sample_rate_hz=self.AZURE_TARGET_SR,
            channels=1,
            bits_per_sample=16,
        )

    def start(self) -> None:
        if self.started:
            return

        self.started = True
        logger.info(
            "[ASR] Worker avviato session=%s user=%s",
            self.session_id,
            self.user_id,
        )

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
                self._azure_client = None

    def stop(self) -> None:
        if not self.started:
            return

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
            "[ASR] Worker terminato session=%s user=%s total_samples=%d total_bytes=%d",
            self.session_id,
            self.user_id,
            self.total_samples,
            self.total_bytes,
        )

        self.started = False
        self._azure_client = None

    # ------------------------------------------------------------------ #
    # Conversione / resampling
    # ------------------------------------------------------------------ #

    @staticmethod
    def _to_mono_int16(pcm: np.ndarray) -> tuple[np.ndarray, int]:
        """
        Converte l'array PCM in mono int16.
        Ritorna (pcm_mono_int16, channels_originali).
        """
        if pcm.ndim == 1:
            return pcm.astype(np.int16, copy=False), 1

        # shape tipico PyAV: (channels, samples)
        channels = int(pcm.shape[0])
        mono = pcm.mean(axis=0).astype(np.int16)
        return mono, channels

    def _resample_to_16k(self, pcm_int16: np.ndarray, src_sr: int) -> tuple[np.ndarray, int]:
        """
        Resample minimo e robusto:
        - Caso 48k -> 16k: decimazione fattore 3 (media su finestre di 3 campioni)
        - Caso 16k -> 16k: no-op
        - Altri sample rate: fallback con interpolazione lineare (sufficiente per test)
        """
        if src_sr == self.AZURE_TARGET_SR:
            return pcm_int16, src_sr

        if src_sr == 48000:
            # 48k -> 16k: fattore 3
            n = (len(pcm_int16) // 3) * 3
            if n <= 0:
                return pcm_int16, src_sr
            x = pcm_int16[:n].astype(np.float32)
            y = x.reshape(-1, 3).mean(axis=1)
            return y.astype(np.int16), self.AZURE_TARGET_SR

        # Fallback generico: interpolazione lineare su indice tempo
        if src_sr <= 0:
            return pcm_int16, src_sr

        x = pcm_int16.astype(np.float32)
        src_len = len(x)
        if src_len < 2:
            return pcm_int16, src_sr

        dst_len = int(round(src_len * (self.AZURE_TARGET_SR / float(src_sr))))
        dst_len = max(dst_len, 1)

        src_idx = np.linspace(0, src_len - 1, num=src_len, dtype=np.float32)
        dst_idx = np.linspace(0, src_len - 1, num=dst_len, dtype=np.float32)
        y = np.interp(dst_idx, src_idx, x)
        return y.astype(np.int16), self.AZURE_TARGET_SR

    # ------------------------------------------------------------------ #
    # Ingestione frame audio
    # ------------------------------------------------------------------ #

    def ingest_frame(self, frame) -> None:
        """
        Riceve un frame audio da aiortc (tipicamente av.AudioFrame),
        lo converte in PCM int16 mono, lo resampla a 16kHz, e lo invia ad Azure.
        """

        # Metadati frame
        try:
            frame_sample_rate = getattr(frame, "sample_rate", None)
            frame_layout = getattr(frame, "layout", None)
        except Exception:
            frame_sample_rate = None
            frame_layout = None

        if self.sample_rate is None and frame_sample_rate is not None:
            self.sample_rate = int(frame_sample_rate)

        src_sr = int(frame_sample_rate) if frame_sample_rate else (self.sample_rate or 0)

        # Estrazione PCM (PyAV)
        try:
            # senza format=... per compatibilità PyAV
            pcm = frame.to_ndarray()
        except Exception:
            logger.exception(
                "[ASR] Errore in to_ndarray session=%s user=%s",
                self.session_id,
                self.user_id,
            )
            return

        pcm_mono, channels = self._to_mono_int16(pcm)
        self.channels = channels

        # Resample a 16kHz per Azure
        pcm_16k, out_sr = self._resample_to_16k(pcm_mono, src_sr)

        # Bytes PCM 16-bit little-endian
        pcm_bytes = pcm_16k.tobytes()
        num_samples = int(pcm_16k.shape[-1])
        num_bytes = int(len(pcm_bytes))

        self.total_samples += num_samples
        self.total_bytes += num_bytes

        # Logging: ridotto ma informativo (include src_sr -> out_sr)
        logger.info(
            "[ASR] PCM chunk session=%s user=%s samples=%d bytes=%d sr_in=%s sr_out=%s layout=%s ch=%s total_bytes=%d",
            self.session_id,
            self.user_id,
            num_samples,
            num_bytes,
            src_sr,
            out_sr,
            frame_layout,
            self.channels,
            self.total_bytes,
        )

        if self._azure_client is not None:
            try:
                self._azure_client.push_audio(pcm_bytes)
            except Exception:
                logger.exception(
                    "[ASR] Errore nell'invio chunk a Azure session=%s user=%s",
                    self.session_id,
                    self.user_id,
                )