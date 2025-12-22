from __future__ import annotations

import logging
import os
import time
import wave
from typing import Optional

import numpy as np
from django.conf import settings

from .azure_client import AzureStreamingClient

logger = logging.getLogger(__name__)


class ASRStreamWorker:
    AZURE_TARGET_SR = 16000

    # chunk regolari verso Azure
    AZURE_PUSH_MS = 300
    AZURE_PUSH_BYTES = int(AZURE_TARGET_SR * (AZURE_PUSH_MS / 1000.0) * 2)  # 9600 bytes

    # taglia i primissimi frame “sporchi” (pop/rumore WebRTC)
    WARMUP_MS = 400

    # stop “gentile”
    DRAIN_TIMEOUT_S = 2.0
    STOP_GRACE_SLEEP_S = 0.6

    # diagnostica aggregata 1Hz
    DIAG_HZ = 1.0

    # DEBUG WAV: abilitare con ASR_DEBUG_WAV=1
    DEBUG_WAV_ENV = "ASR_DEBUG_WAV"
    DEBUG_WAV_SECONDS = 8.0  # max durata dump

    # GAIN: per ora spento (il segnale va prima reso “corretto”)
    GAIN = 1.0
    SOFTCLIP_LEVEL = 0.98

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

        # debug wav
        self._debug_wav_enabled = False
        self._debug_wav_path: Optional[str] = None
        self._debug_wav_buf = bytearray()
        self._debug_wav_max_bytes = int(self.AZURE_TARGET_SR * self.DEBUG_WAV_SECONDS * 2)

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
                logger.info("[ASR][AZURE][partial] session=%s user=%s text=%r", self.session_id, self.user_id, text)

        def _on_final(text: str) -> None:
            logger.info("[ASR][AZURE][final] session=%s user=%s text=%r", self.session_id, self.user_id, text)

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

        # debug wav
        self._debug_wav_enabled = os.getenv(self.DEBUG_WAV_ENV, "0") == "1"
        self._debug_wav_buf.clear()
        self._debug_wav_path = f"/tmp/asr_debug_{self.session_id}.wav" if self._debug_wav_enabled else None

        logger.info("[ASR] Worker avviato session=%s user=%s", self.session_id, self.user_id)

        self._init_azure_client()
        if self._azure_client:
            self._azure_client.start()
            logger.info("[ASR] AzureStreamingClient avviato session=%s user=%s", self.session_id, self.user_id)

    def _try_signal_end_of_stream(self) -> None:
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
        while time.time() < end:
            q = _get_qsize()
            if q is None:
                return
            if q <= 0:
                return
            time.sleep(0.02)

    def _write_debug_wav(self) -> None:
        if not self._debug_wav_enabled or not self._debug_wav_path:
            return
        try:
            with wave.open(self._debug_wav_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.AZURE_TARGET_SR)
                wf.writeframes(bytes(self._debug_wav_buf))
            logger.info("[ASR][DEBUG] Salvato WAV: %s bytes=%d", self._debug_wav_path, len(self._debug_wav_buf))
        except Exception:
            logger.exception("[ASR][DEBUG] Errore salvataggio WAV")

    def stop(self) -> None:
        if not self.started:
            return

        # flush residuo
        if self._azure_client and self._push_buf:
            try:
                self._azure_client.push_audio(bytes(self._push_buf))
                self._sent_bytes += len(self._push_buf)
            except Exception:
                logger.exception("[ASR] Errore flush buffer a Azure session=%s user=%s", self.session_id, self.user_id)
            self._push_buf.clear()

        self._try_signal_end_of_stream()
        time.sleep(self.STOP_GRACE_SLEEP_S)
        self._drain_queue_best_effort(timeout_s=self.DRAIN_TIMEOUT_S)

        if self._azure_client:
            self._azure_client.stop()

        self._write_debug_wav()

        logger.info(
            "[ASR] Worker terminato session=%s user=%s total_samples=%d total_bytes=%d sent_bytes=%d debug_wav=%s",
            self.session_id,
            self.user_id,
            self.total_samples,
            self.total_bytes,
            self._sent_bytes,
            "ON" if self._debug_wav_enabled else "OFF",
        )

        self.started = False
        self._azure_client = None

    # ------------------------------------------------------------------ #
    # Audio helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _guess_channels(frame_layout) -> Optional[int]:
        # PyAV: frame.layout può esporre .channels
        try:
            ch = getattr(frame_layout, "channels", None)
            if ch:
                return int(ch)
        except Exception:
            pass
        return None

    @staticmethod
    def _to_mono(pcm: np.ndarray) -> tuple[np.ndarray, int]:
        """
        Normalizza qualsiasi layout PCM in mono in modo deterministico.
        Supporta:
        - (N,)        mono
        - (2, N)      stereo channels-first
        - (N, 2)      stereo channels-last
        """
        if pcm.ndim == 1:
            return pcm, 1

        if pcm.ndim != 2:
            raise ValueError(f"PCM shape non supportato: {pcm.shape}")

        # stereo channels-first: (2, N)
        if pcm.shape[0] == 2 and pcm.shape[1] > 2:
            return pcm.mean(axis=0), 2

        # stereo channels-last: (N, 2)
        if pcm.shape[1] == 2 and pcm.shape[0] > 2:
            return pcm.mean(axis=1), 2

        # fallback difensivo
        return pcm.mean(axis=0), pcm.shape[0]
    
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
        if src_sr == self.AZURE_TARGET_SR or src_sr <= 0:
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

    @staticmethod
    def _rms_i16(x_i16: np.ndarray) -> float:
        if x_i16.size == 0:
            return 0.0
        xf = x_i16.astype(np.float32)
        return float(np.sqrt(np.mean(xf * xf)))

    def _apply_gain_softclip(self, pcm_16k_i16: np.ndarray) -> np.ndarray:
        if self.GAIN <= 1.0001:
            return pcm_16k_i16

        x = pcm_16k_i16.astype(np.float32) * float(self.GAIN)
        limit = float(self.SOFTCLIP_LEVEL) * 32767.0
        limit = 32767.0 if limit <= 0 else limit
        y = np.tanh(x / limit) * limit
        return np.clip(y, -32768.0, 32767.0).astype(np.int16)

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

        expected_ch = self._guess_channels(frame_layout) or 1
        mono, ch = self._to_mono_robust(pcm, expected_ch)
        self.channels = ch

        if not self._logged_audio_stats:
            try:
                m_dtype = str(mono.dtype)
                m_kind = mono.dtype.kind
                m_max = float(np.max(mono)) if mono.size else 0.0
                m_min = float(np.min(mono)) if mono.size else 0.0
                m_abs = float(np.max(np.abs(mono))) if mono.size else 0.0
                logger.info(
                    "[ASR][DIAG] incoming mono dtype=%s kind=%s min=%.6f max=%.6f max_abs=%.6f layout=%s sr_in=%s ch_inferred=%s",
                    m_dtype, m_kind, m_min, m_max, m_abs, frame_layout, src_sr, ch
                )
            except Exception:
                logger.exception("[ASR][DIAG] errore nel calcolo stats input")
            self._logged_audio_stats = True

        mono_i16 = self._mono_to_int16_robust(mono)
        pcm_16k, out_sr = self._resample_to_16k(mono_i16, src_sr)
        if not pcm_16k.size:
            return

        # gain (attualmente 1.0 quindi no-op)
        pcm_16k_g = self._apply_gain_softclip(pcm_16k)

        peak = int(np.max(np.abs(pcm_16k_g)))
        rms = self._rms_i16(pcm_16k_g)

        now = time.time()
        if now < self._warmup_until:
            return

        # diagnostica 1Hz (post-processing)
        x = pcm_16k_g.astype(np.float32)
        self._rms_acc += float(np.mean(x * x))
        self._rms_n += 1
        self._zero_n += int(np.sum(pcm_16k_g == 0))
        self._tot_n += int(pcm_16k_g.size)

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

        pcm_bytes = pcm_16k_g.tobytes()
        num_bytes = int(len(pcm_bytes))

        self.total_bytes += num_bytes
        self.total_samples += int(pcm_16k_g.shape[0])

        # accumula per debug wav (post warmup)
        if self._debug_wav_enabled and len(self._debug_wav_buf) < self._debug_wav_max_bytes:
            remaining = self._debug_wav_max_bytes - len(self._debug_wav_buf)
            self._debug_wav_buf.extend(pcm_bytes[:remaining])

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