from __future__ import annotations

import logging
from typing import Optional

import numpy as np
from django.conf import settings

from .azure_client import AzureStreamingClient

logger = logging.getLogger(__name__)


class ASRStreamWorker:
    """
    Stream ASR per (session_id, user_id).

    - riceve frame audio WebRTC (PyAV)
    - converte correttamente in PCM int16 mono
    - resampla a 16kHz per Azure
    - invia chunk ad Azure Speech
    """

    AZURE_TARGET_SR = 16000

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
    # Lifecycle
    # ------------------------------------------------------------------ #

    def _init_azure_client(self) -> None:
        key = getattr(settings, "AZURE_SPEECH_KEY", None)
        region = getattr(settings, "AZURE_SPEECH_REGION", None)
        language = getattr(settings, "AZURE_SPEECH_LANGUAGE", "it-IT")

        if not key or not region:
            logger.warning(
                "[ASR] Azure Speech non configurato (key/region mancanti)"
            )
            return

        def _on_partial(text: str) -> None:
            if text:
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
                if session_obj:
                    ASRTranscript.objects.create(
                        session=session_obj,
                        user_id=self.user_id,
                        text=text,
                        created_at=timezone.now(),
                    )
            except Exception:
                logger.exception(
                    "[ASR] Errore salvataggio transcript session=%s user=%s",
                    self.session_id,
                    self.user_id,
                )

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
        logger.info("[ASR] Worker avviato session=%s user=%s", self.session_id, self.user_id)

        self._init_azure_client()
        if self._azure_client:
            self._azure_client.start()

    def stop(self) -> None:
        if not self.started:
            return

        if self._azure_client:
            self._azure_client.stop()

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
    # Conversione PCM
    # ------------------------------------------------------------------ #

    @staticmethod
    def _to_mono_int16(pcm: np.ndarray) -> tuple[np.ndarray, int]:
        """
        Converte PCM float/int in mono int16 CORRETTO.
        """
        if pcm.ndim == 1:
            mono = pcm
            channels = 1
        else:
            channels = int(pcm.shape[0])
            mono = pcm.mean(axis=0)

        # FLOAT -> INT16 (CASO CRITICO FIXATO)
        if mono.dtype.kind == "f":
            mono_f = mono.astype(np.float32, copy=False)
            mono_i16 = np.clip(mono_f * 32767.0, -32768, 32767).astype(np.int16)
            return mono_i16, channels

        # INT16 diretto
        if mono.dtype == np.int16:
            return mono, channels

        # altri interi
        mono_i16 = mono.astype(np.int16, copy=False)
        return mono_i16, channels

    def _resample_to_16k(self, pcm_int16: np.ndarray, src_sr: int) -> tuple[np.ndarray, int]:
        if src_sr == self.AZURE_TARGET_SR:
            return pcm_int16, src_sr

        if src_sr == 48000:
            n = (len(pcm_int16) // 3) * 3
            if n <= 0:
                return pcm_int16, src_sr
            x = pcm_int16[:n].astype(np.float32)
            y = x.reshape(-1, 3).mean(axis=1)
            return y.astype(np.int16), self.AZURE_TARGET_SR

        if src_sr <= 0:
            return pcm_int16, src_sr

        x = pcm_int16.astype(np.float32)
        src_len = len(x)
        if src_len < 2:
            return pcm_int16, src_sr

        dst_len = int(round(src_len * (self.AZURE_TARGET_SR / float(src_sr))))
        dst_len = max(dst_len, 1)

        src_idx = np.linspace(0, src_len - 1, src_len)
        dst_idx = np.linspace(0, src_len - 1, dst_len)
        y = np.interp(dst_idx, src_idx, x)
        return y.astype(np.int16), self.AZURE_TARGET_SR

    # ------------------------------------------------------------------ #
    # Ingestione frame
    # ------------------------------------------------------------------ #

    def ingest_frame(self, frame) -> None:
        try:
            frame_sample_rate = frame.sample_rate
            frame_layout = frame.layout
        except Exception:
            frame_sample_rate = None
            frame_layout = None

        if self.sample_rate is None and frame_sample_rate:
            self.sample_rate = int(frame_sample_rate)

        src_sr = int(frame_sample_rate) if frame_sample_rate else (self.sample_rate or 0)

        try:
            pcm = frame.to_ndarray()
        except Exception:
            logger.exception("[ASR] Errore to_ndarray session=%s user=%s", self.session_id, self.user_id)
            return

        pcm_mono, channels = self._to_mono_int16(pcm)
        self.channels = channels

        pcm_16k, out_sr = self._resample_to_16k(pcm_mono, src_sr)

        # ---- LIVELLO AUDIO (DEBUG CHIAVE) ----
        peak = int(np.max(np.abs(pcm_16k))) if pcm_16k.size else 0
        rms = float(np.sqrt(np.mean(pcm_16k.astype(np.float32) ** 2))) if pcm_16k.size else 0.0

        pcm_bytes = pcm_16k.tobytes()
        num_samples = pcm_16k.shape[0]
        num_bytes = len(pcm_bytes)

        self.total_samples += num_samples
        self.total_bytes += num_bytes

        logger.info(
            "[ASR] PCM chunk session=%s user=%s samples=%d bytes=%d sr_in=%s sr_out=%s "
            "peak=%d rms=%.1f total_bytes=%d",
            self.session_id,
            self.user_id,
            num_samples,
            num_bytes,
            src_sr,
            out_sr,
            peak,
            rms,
            self.total_bytes,
        )

        if self._azure_client:
            self._azure_client.push_audio(pcm_bytes)