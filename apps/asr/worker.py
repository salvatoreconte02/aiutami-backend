from __future__ import annotations

import logging
import time
from typing import Optional

import numpy as np
from django.conf import settings

from .azure_client import AzureStreamingClient

logger = logging.getLogger(__name__)


class ASRStreamWorker:
    AZURE_TARGET_SR = 16000

    # invio verso Azure ogni ~200ms @16kHz mono int16
    AZURE_PUSH_MS = 200
    AZURE_PUSH_BYTES = int(AZURE_TARGET_SR * (AZURE_PUSH_MS / 1000.0) * 2)  # 16k * 0.2 * 2 = 6400 bytes

    # warm-up (scarta i primissimi frame “sporchi”)
    WARMUP_MS = 500

    # gate anti-silenzio (riduce costi e final vuoti)
    SILENCE_RMS_GATE = 30.0
    SILENCE_PEAK_GATE = 200

    # log diagnostico 1Hz
    DIAG_HZ = 1.0

    def __init__(self, session_id: str, user_id: int) -> None:
        self.session_id = str(session_id)
        self.user_id = int(user_id)

        self.sample_rate: Optional[int] = None
        self.channels: Optional[int] = None
        self.total_samples: int = 0
        self.total_bytes: int = 0
        self.started: bool = False

        self._azure_client: Optional[AzureStreamingClient] = None
        self._push_buf = bytearray()
        self._logged_audio_stats = False  # log “diagnostico” una volta per sessione

        # runtime gating/diagnostics
        self._t0 = time.time()
        self._warmup_until = self._t0 + (self.WARMUP_MS / 1000.0)
        self._diag_next = self._t0 + (1.0 / self.DIAG_HZ)

        self._rms_acc = 0.0
        self._rms_n = 0
        self._zero_n = 0
        self._tot_n = 0

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def _init_azure_client(self) -> None:
        key = getattr(settings, "AZURE_SPEECH_KEY", None)
        region = getattr(settings, "AZURE_SPEECH_REGION", None)
        language = getattr(settings, "AZURE_SPEECH_LANGUAGE", "it-IT")

        if not key or not region:
            logger.warning("[ASR] Azure Speech non configurato (key/region mancanti)")
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
        self._push_buf.clear()
        self._logged_audio_stats = False

        now = time.time()
        self._t0 = now
        self._warmup_until = now + (self.WARMUP_MS / 1000.0)
        self._diag_next = now + (1.0 / self.DIAG_HZ)

        self._rms_acc = 0.0
        self._rms_n = 0
        self._zero_n = 0
        self._tot_n = 0

        logger.info("[ASR] Worker avviato session=%s user=%s", self.session_id, self.user_id)

        self._init_azure_client()
        if self._azure_client:
            self._azure_client.start()
            logger.info("[ASR] AzureStreamingClient avviato session=%s user=%s", self.session_id, self.user_id)

    def stop(self) -> None:
        if not self.started:
            return

        # flush buffer residuo verso Azure
        if self._azure_client and self._push_buf:
            try:
                self._azure_client.push_audio(bytes(self._push_buf))
            except Exception:
                logger.exception("[ASR] Errore flush buffer a Azure session=%s user=%s", self.session_id, self.user_id)
            self._push_buf.clear()

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
    # Conversione PCM robusta
    # ------------------------------------------------------------------ #

    @staticmethod
    def _to_mono(pcm: np.ndarray) -> tuple[np.ndarray, int]:
        if pcm.ndim == 1:
            return pcm, 1
        channels = int(pcm.shape[0])
        return pcm.mean(axis=0), channels

    @staticmethod
    def _mono_to_int16_robust(mono: np.ndarray) -> np.ndarray:
        """
        Conversione robusta:
        - int16: ritorna
        - float:
            * se max_abs <= 1.2 -> scala [-1,1] => int16
            * se 1.2 < max_abs <= 40000 -> assume già in scala “int16-like”, clip/cast
            * altrimenti -> normalizza su max_abs
        - altri int: clip/cast
        """
        if mono.dtype == np.int16:
            return mono

        if mono.dtype.kind == "f":
            x = mono.astype(np.float32, copy=False)
            max_abs = float(np.max(np.abs(x))) if x.size else 0.0

            if max_abs <= 1.2:
                y = x * 32767.0
            elif max_abs <= 40000.0:
                y = x
            else:
                if max_abs > 0:
                    y = (x / max_abs) * 32767.0
                else:
                    y = x

            return np.clip(y, -32768, 32767).astype(np.int16)

        x = mono.astype(np.int32, copy=False)
        return np.clip(x, -32768, 32767).astype(np.int16)

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

        mono, ch = self._to_mono(pcm)
        self.channels = ch

        # log diagnostico “una tantum” per capire davvero cosa arriva da PyAV
        if not self._logged_audio_stats:
            try:
                m_dtype = str(mono.dtype)
                m_kind = mono.dtype.kind
                m_max = float(np.max(mono)) if mono.size else 0.0
                m_min = float(np.min(mono)) if mono.size else 0.0
                m_abs = float(np.max(np.abs(mono))) if mono.size else 0.0
                logger.info(
                    "[ASR][DIAG] incoming mono dtype=%s kind=%s min=%.6f max=%.6f max_abs=%.6f layout=%s sr_in=%s",
                    m_dtype,
                    m_kind,
                    m_min,
                    m_max,
                    m_abs,
                    frame_layout,
                    src_sr,
                )
            except Exception:
                logger.exception("[ASR][DIAG] errore nel calcolo stats input")
            self._logged_audio_stats = True

        mono_i16 = self._mono_to_int16_robust(mono)
        pcm_16k, out_sr = self._resample_to_16k(mono_i16, src_sr)

        if not pcm_16k.size:
            return

        peak = int(np.max(np.abs(pcm_16k)))
        rms = float(np.sqrt(np.mean(pcm_16k.astype(np.float32) ** 2)))

        # warm-up: scarta primissimi frame (spesso “sporchi”/clippati)
        now = time.time()
        if now < self._warmup_until:
            return

        # diagnostica su 1 secondo (per capire se è silenzio reale / attenuato)
        x = pcm_16k.astype(np.float32)
        self._rms_acc += float(np.mean(x * x))
        self._rms_n += 1
        self._zero_n += int(np.sum(pcm_16k == 0))
        self._tot_n += int(pcm_16k.size)

        if now >= self._diag_next and self._rms_n > 0:
            rms_1s = (self._rms_acc / self._rms_n) ** 0.5
            zero_pct = (self._zero_n / max(self._tot_n, 1)) * 100.0
            logger.info(
                "[ASR][1s] session=%s user=%s rms_1s=%.1f zero_pct=%.1f%% sr_in=%s sr_out=%s ch=%s",
                self.session_id,
                self.user_id,
                rms_1s,
                zero_pct,
                src_sr,
                out_sr,
                self.channels,
            )
            self._rms_acc = 0.0
            self._rms_n = 0
            self._zero_n = 0
            self._tot_n = 0
            self._diag_next = now + (1.0 / self.DIAG_HZ)

        # gate anti-silenzio: non accumulare né inviare “quasi muto”
        if rms < self.SILENCE_RMS_GATE and peak < self.SILENCE_PEAK_GATE:
            return

        pcm_bytes = pcm_16k.tobytes()
        num_samples = int(pcm_16k.shape[0])
        num_bytes = int(len(pcm_bytes))

        self.total_samples += num_samples
        self.total_bytes += num_bytes

        # bufferizza sempre (dopo gate)
        self._push_buf.extend(pcm_bytes)

        # log meno “spam”: solo su flush o se clipping evidente
        clipping = (peak >= 32767)
        if clipping or len(self._push_buf) >= self.AZURE_PUSH_BYTES:
            logger.info(
                "[ASR] PCM buf session=%s user=%s add_samples=%d add_bytes=%d sr_in=%s sr_out=%s peak=%d rms=%.1f buf_bytes=%d total_bytes=%d",
                self.session_id,
                self.user_id,
                num_samples,
                num_bytes,
                src_sr,
                out_sr,
                peak,
                rms,
                len(self._push_buf),
                self.total_bytes,
            )

        # invio a blocchi verso Azure
        if self._azure_client and len(self._push_buf) >= self.AZURE_PUSH_BYTES:
            try:
                self._azure_client.push_audio(bytes(self._push_buf))
            except Exception:
                logger.exception("[ASR] Errore invio buffer a Azure session=%s user=%s", self.session_id, self.user_id)
            self._push_buf.clear()