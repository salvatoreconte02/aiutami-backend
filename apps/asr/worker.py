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

    # invio verso Azure a chunk fissi (meno overhead, più regolare)
    AZURE_PUSH_MS = 300
    AZURE_PUSH_BYTES = int(AZURE_TARGET_SR * (AZURE_PUSH_MS / 1000.0) * 2)  # 9600 bytes

    # --- IMPORTANTISSIMO PER DEBUG: disattivati per togliere variabili ---
    WARMUP_MS = 0  # prima era 500: ora 0
    SILENCE_RMS_GATE = 0.0  # prima 40.0: ora 0 (disattiva gate)
    SILENCE_PEAK_GATE = 0   # prima 250: ora 0 (disattiva gate)

    # stop “gentile”
    DRAIN_TIMEOUT_S = 2.0
    STOP_GRACE_SLEEP_S = 0.6

    # diagnostica aggregata 1Hz
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
        self._logged_audio_stats = False

        self._warmup_until = 0.0
        self._diag_next = 0.0

        self._rms_acc = 0.0
        self._rms_n = 0
        self._zero_n = 0
        self._tot_n = 0

        self._sent_bytes = 0

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
            # qui logghiamo anche gli empty, perché è il problema che stiamo inseguendo
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

        now = time.time()
        self.started = True

        self._push_buf.clear()
        self._logged_audio_stats = False

        self._warmup_until = now + (self.WARMUP_MS / 1000.0)
        self._diag_next = now + (1.0 / self.DIAG_HZ)

        self._rms_acc = 0.0
        self._rms_n = 0
        self._zero_n = 0
        self._tot_n = 0

        self._sent_bytes = 0
        self.total_samples = 0
        self.total_bytes = 0

        logger.info("[ASR] Worker avviato session=%s user=%s", self.session_id, self.user_id)

        self._init_azure_client()
        if self._azure_client:
            self._azure_client.start()
            logger.info("[ASR] AzureStreamingClient avviato session=%s user=%s", self.session_id, self.user_id)

    def _try_signal_end_of_stream(self) -> None:
        """
        Best-effort: se AzureStreamingClient espone un metodo per “chiudere” lo stream,
        lo invoca. In caso contrario non fa nulla.
        """
        c = self._azure_client
        if c is None:
            return

        for name in ("end_stream", "end_of_stream", "close_stream", "close", "finish", "complete"):
            fn = getattr(c, name, None)
            if callable(fn):
                try:
                    fn()
                    logger.info("[ASR] Segnalato end-of-stream a Azure via %s()", name)
                except Exception:
                    logger.exception("[ASR] Errore durante end-of-stream via %s()", name)
                return

    def _drain_queue_best_effort(self, timeout_s: float) -> None:
        c = self._azure_client
        if c is None:
            return

        def _get_qsize() -> Optional[int]:
            for name in ("queue_size", "qsize", "get_queue_size"):
                v = getattr(c, name, None)
                try:
                    if callable(v):
                        return int(v())
                    if v is not None:
                        return int(v)
                except Exception:
                    return None
            return None

        end = time.time() + max(0.0, timeout_s)
        last_q = None
        while time.time() < end:
            q = _get_qsize()
            if q is None:
                return
            last_q = q
            if q <= 0:
                return
            time.sleep(0.02)

        if last_q is not None:
            logger.info("[ASR] Drain timeout: queue_size=%s session=%s user=%s", last_q, self.session_id, self.user_id)

    def stop(self) -> None:
        if not self.started:
            return

        # flush residuo (tutto)
        if self._azure_client and self._push_buf:
            try:
                self._azure_client.push_audio(bytes(self._push_buf))
                self._sent_bytes += len(self._push_buf)
            except Exception:
                logger.exception("[ASR] Errore flush buffer a Azure session=%s user=%s", self.session_id, self.user_id)
            self._push_buf.clear()

        # segnala fine stream (se supportato dal client)
        self._try_signal_end_of_stream()

        # attesa “grace” per dare tempo al recognizer di finalizzare
        time.sleep(self.STOP_GRACE_SLEEP_S)

        # prova a far svuotare la coda prima di chiudere
        self._drain_queue_best_effort(timeout_s=self.DRAIN_TIMEOUT_S)

        if self._azure_client:
            self._azure_client.stop()

        logger.info(
            "[ASR] Worker terminato session=%s user=%s total_samples=%d total_bytes=%d sent_bytes=%d",
            self.session_id,
            self.user_id,
            self.total_samples,
            self.total_bytes,
            self._sent_bytes,
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
                y = (x / max_abs) * 32767.0 if max_abs > 0 else x
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

        if not self._logged_audio_stats:
            try:
                m_dtype = str(mono.dtype)
                m_kind = mono.dtype.kind
                m_max = float(np.max(mono)) if mono.size else 0.0
                m_min = float(np.min(mono)) if mono.size else 0.0
                m_abs = float(np.max(np.abs(mono))) if mono.size else 0.0
                logger.info(
                    "[ASR][DIAG] incoming mono dtype=%s kind=%s min=%.6f max=%.6f max_abs=%.6f layout=%s sr_in=%s",
                    m_dtype, m_kind, m_min, m_max, m_abs, frame_layout, src_sr
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

        now = time.time()
        if now < self._warmup_until:
            return

        # diagnostica aggregata 1Hz
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
                self.session_id, self.user_id, rms_1s, zero_pct, src_sr, out_sr, self.channels
            )
            self._rms_acc = 0.0
            self._rms_n = 0
            self._zero_n = 0
            self._tot_n = 0
            self._diag_next = now + (1.0 / self.DIAG_HZ)

        pcm_bytes = pcm_16k.tobytes()
        num_bytes = int(len(pcm_bytes))

        # gate silenzio (disattivato se soglie a 0)
        if self.SILENCE_RMS_GATE > 0.0 or self.SILENCE_PEAK_GATE > 0:
            if rms < self.SILENCE_RMS_GATE and peak < self.SILENCE_PEAK_GATE:
                return

        self.total_bytes += num_bytes
        self.total_samples += int(pcm_16k.shape[0])

        self._push_buf.extend(pcm_bytes)

        if self._azure_client and len(self._push_buf) >= self.AZURE_PUSH_BYTES:
            try:
                while len(self._push_buf) >= self.AZURE_PUSH_BYTES:
                    chunk = bytes(self._push_buf[: self.AZURE_PUSH_BYTES])
                    del self._push_buf[: self.AZURE_PUSH_BYTES]
                    self._azure_client.push_audio(chunk)
                    self._sent_bytes += len(chunk)
            except Exception:
                logger.exception("[ASR] Errore invio buffer a Azure session=%s user=%s", self.session_id, self.user_id)
                self._push_buf.clear()

            logger.info(
                "[ASR] PUSH session=%s user=%s sr_in=%s sr_out=%s peak=%d rms=%.1f sent_bytes=%d buf_rem=%d total_bytes=%d",
                self.session_id, self.user_id, src_sr, out_sr, peak, rms, self._sent_bytes, len(self._push_buf), self.total_bytes
            )