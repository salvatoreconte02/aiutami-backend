from __future__ import annotations

import logging
import os
import time
import wave
import threading
from typing import Optional

import numpy as np
from django.conf import settings
from django.core.cache import cache

from .openai_realtime_client import OpenAIRealtimeTranscriptionClient as ASRStreamingClient

logger = logging.getLogger(__name__)


class ASRStreamWorker:
    # OpenAI Realtime pcm16 richiede 24kHz mono 16-bit little-endian
    ASR_TARGET_SR = 24000

    # chunk regolari verso il client ASR
    ASR_PUSH_MS = 300
    ASR_PUSH_BYTES = int(ASR_TARGET_SR * (ASR_PUSH_MS / 1000.0) * 2)  # 14400 bytes

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

    # GAIN: spento finché non è “pulito”
    GAIN = 1.0
    SOFTCLIP_LEVEL = 0.98

    # Transcript cache (final chunks)
    TRANSCRIPT_TTL_S = 60 * 30  # 30 minuti
    TRANSCRIPT_MAX_SEGMENTS = 200
    TRANSCRIPT_MAX_CHARS = 12000

    def __init__(self, session_id: str, user_id: int) -> None:
        self.session_id = str(session_id)
        self.user_id = int(user_id)

        self.sample_rate: Optional[int] = None
        self.channels: Optional[int] = None

        self.total_samples: int = 0
        self.total_bytes: int = 0
        self.started: bool = False

        self._asr_client: Optional[ASRStreamingClient] = None

        self._push_buf = bytearray()
        self._logged_audio_stats = False
        self._logged_shape = False

        self._warmup_until = 0.0
        self._diag_next = 0.0

        self._rms_acc = 0.0
        self._rms_n = 0
        self._zero_n = 0
        self._tot_n = 0

        self._sent_bytes = 0

        # debug wav
        self._debug_wav_enabled = False
        self._debug_wav_raw_path: Optional[str] = None
        self._debug_wav_target_path: Optional[str] = None
        self._debug_wav_raw_buf = bytearray()
        self._debug_wav_target_buf = bytearray()
        self._debug_wav_max_bytes_target = int(self.ASR_TARGET_SR * self.DEBUG_WAV_SECONDS * 2)
        self._debug_wav_max_bytes_raw = int(48000 * self.DEBUG_WAV_SECONDS * 2)  # cap “alto”, poi si riduce
        self._debug_wav_raw_sr: Optional[int] = None

        # lock per append transcript (callback ASR arriva da thread)
        self._transcript_lock = threading.Lock()

    # Transcript cache helpers

    def _transcript_cache_key(self) -> str:
        return f"asr:final_segments:{self.session_id}:{self.user_id}"

    def _reset_transcript_cache(self) -> None:
        """
        Reset della cache a inizio stream: evita residue di turni precedenti
        in caso di crash o mancato delete lato consumer.
        """
        key = self._transcript_cache_key()
        try:
            cache.delete(key)
            cache.set(key, [], timeout=self.TRANSCRIPT_TTL_S)
            logger.info("[ASR][CACHE] reset session=%s user=%s", self.session_id, self.user_id)
        except Exception:
            logger.exception("[ASR][CACHE] failed reset session=%s user=%s", self.session_id, self.user_id)

    def _append_final_segment_to_cache(self, text: str) -> None:
        """
        Accoda un segmento "final" in cache (lista di stringhe).
        Chiamato da callback ASR (thread), quindi deve essere robusto.
        """
        t = (text or "").strip()
        if not t:
            return

        key = self._transcript_cache_key()
        try:
            with self._transcript_lock:
                segments = cache.get(key) or []
                if not isinstance(segments, list):
                    segments = []

                # deduplica soft: se il provider ripete l'ultimo final, non duplicare
                if segments:
                    last = str(segments[-1]).strip()
                    if last and (t == last or t in last or last in t):
                        cache.set(key, segments, timeout=self.TRANSCRIPT_TTL_S)
                        return

                segments.append(t)

                # cap segmenti
                if len(segments) > self.TRANSCRIPT_MAX_SEGMENTS:
                    segments = segments[-self.TRANSCRIPT_MAX_SEGMENTS :]

                # cap caratteri totali (mantiene i più recenti)
                total_chars = 0
                trimmed = []
                for s in reversed(segments):
                    ss = str(s).strip()
                    if not ss:
                        continue
                    total_chars += len(ss) + 1
                    if total_chars > self.TRANSCRIPT_MAX_CHARS:
                        break
                    trimmed.append(ss)

                segments = list(reversed(trimmed)) if trimmed else [t]

                cache.set(key, segments, timeout=self.TRANSCRIPT_TTL_S)

            logger.info(
                "[ASR][CACHE] appended_final session=%s user=%s segments=%d last=%r",
                self.session_id,
                self.user_id,
                len(segments),
                t[:120],
            )
        except Exception:
            logger.exception("[ASR][CACHE] failed append_final session=%s user=%s", self.session_id, self.user_id)

    # Lifecycle

    def _init_asr_client(self) -> None:
        api_key = getattr(settings, "OPENAI_API_KEY", None)
        model = getattr(settings, "OPENAI_STT_MODEL", "gpt-4o-mini-transcribe")
        language = getattr(settings, "OPENAI_STT_LANGUAGE", "it")

        if not api_key:
            logger.warning("[ASR] OpenAI non configurato (OPENAI_API_KEY mancante)")
            return

        def _on_partial(text: str) -> None:
            if text:
                logger.debug("[ASR][OPENAI][partial] session=%s user=%s text=%r", self.session_id, self.user_id, text)

        def _on_final(text: str) -> None:
            # Log + persistenza in cache per consumo da TurnsConsumer (fine turno)
            if text:
                logger.info("[ASR][OPENAI][final] session=%s user=%s text=%r", self.session_id, self.user_id, text)
                self._append_final_segment_to_cache(text)

        self._asr_client = ASRStreamingClient(
            api_key=api_key,
            model=model,
            language=language,
            on_partial=_on_partial,
            on_final=_on_final,
            sample_rate_hz=self.ASR_TARGET_SR,
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
        self._logged_shape = False

        self._warmup_until = now + (self.WARMUP_MS / 1000.0)
        self._diag_next = now + (1.0 / self.DIAG_HZ)

        self._rms_acc = 0.0
        self._rms_n = 0
        self._zero_n = 0
        self._tot_n = 0

        self._sent_bytes = 0
        self.total_samples = 0
        self.total_bytes = 0

        # transcript cache: reset per-turno
        self._reset_transcript_cache()

        # debug wav
        self._debug_wav_enabled = os.getenv(self.DEBUG_WAV_ENV, "0") == "1"
        self._debug_wav_raw_buf.clear()
        self._debug_wav_target_buf.clear()
        self._debug_wav_raw_sr = None
        if self._debug_wav_enabled:
            self._debug_wav_raw_path = f"/tmp/asr_debug_raw_{self.session_id}.wav"
            self._debug_wav_target_path = f"/tmp/asr_debug_{self.ASR_TARGET_SR}_{self.session_id}.wav"
        else:
            self._debug_wav_raw_path = None
            self._debug_wav_target_path = None

        logger.info("[ASR] Worker avviato session=%s user=%s", self.session_id, self.user_id)

        self._init_asr_client()
        if self._asr_client:
            self._asr_client.start()
            logger.info("[ASR] client streaming avviato session=%s user=%s", self.session_id, self.user_id)

    def _try_signal_end_of_stream(self) -> None:
        c = self._asr_client
        if c is None:
            return
        for name in ("end_stream", "end_of_stream", "close_stream", "close", "finish", "complete"):
            fn = getattr(c, name, None)
            if callable(fn):
                try:
                    fn()
                    logger.info("[ASR] Segnalato end-of-stream al client via %s()", name)
                except Exception:
                    logger.exception("[ASR] Errore durante end-of-stream via %s()", name)
                return

    def _drain_queue_best_effort(self, timeout_s: float) -> None:
        c = self._asr_client
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

    def _write_wav(self, path: str, sr: int, pcm_bytes: bytes) -> None:
        try:
            with wave.open(path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(int(sr))
                wf.writeframes(pcm_bytes)
            logger.info("[ASR][DEBUG] Salvato WAV: %s sr=%s bytes=%d", path, sr, len(pcm_bytes))
        except Exception:
            logger.exception("[ASR][DEBUG] Errore salvataggio WAV: %s", path)

    def _write_debug_wavs(self) -> None:
        if not self._debug_wav_enabled:
            return
        if self._debug_wav_raw_path and self._debug_wav_raw_sr and self._debug_wav_raw_buf:
            self._write_wav(self._debug_wav_raw_path, self._debug_wav_raw_sr, bytes(self._debug_wav_raw_buf))
        if self._debug_wav_target_path and self._debug_wav_target_buf:
            self._write_wav(self._debug_wav_target_path, self.ASR_TARGET_SR, bytes(self._debug_wav_target_buf))

    def stop(self) -> None:
        if not self.started:
            return

        # flush residuo
        if self._asr_client and self._push_buf:
            try:
                self._asr_client.push_audio(bytes(self._push_buf))
                self._sent_bytes += len(self._push_buf)
            except Exception:
                logger.exception("[ASR] Errore flush buffer al client session=%s user=%s", self.session_id, self.user_id)
            self._push_buf.clear()

        self._try_signal_end_of_stream()
        time.sleep(self.STOP_GRACE_SLEEP_S)
        self._drain_queue_best_effort(timeout_s=self.DRAIN_TIMEOUT_S)

        if self._asr_client:
            self._asr_client.stop()

        self._write_debug_wavs()

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
        self._asr_client = None

    # Audio helpers

    @staticmethod
    def _guess_channels(frame_layout) -> Optional[int]:
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
        Supporta:
        - (N,)        mono
        - (C, N)      channels-first
        - (N, C)      channels-last
        """
        if pcm.ndim == 1:
            return pcm, 1

        if pcm.ndim != 2:
            raise ValueError(f"PCM shape non supportato: {pcm.shape}")

        # channels-first
        if pcm.shape[0] in (1, 2) and pcm.shape[1] > 2:
            return pcm.mean(axis=0), int(pcm.shape[0])

        # channels-last
        if pcm.shape[1] in (1, 2) and pcm.shape[0] > 2:
            return pcm.mean(axis=1), int(pcm.shape[1])

        # fallback
        return pcm.mean(axis=0), int(pcm.shape[0])

    @staticmethod
    def _to_mono_robust(pcm: np.ndarray, expected_ch: int) -> tuple[np.ndarray, int]:
        mono, ch = ASRStreamWorker._to_mono(pcm)
        return mono, ch

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

    def _resample_to_target(self, pcm_int16: np.ndarray, src_sr: int) -> tuple[np.ndarray, int]:
        """Resample PCM mono int16 alla frequenza target ASR_TARGET_SR."""
        if src_sr == self.ASR_TARGET_SR or src_sr <= 0:
            return pcm_int16, src_sr

        # Fast path 48kHz → 24kHz: decimate 2x con media coppia
        if src_sr == 48000 and self.ASR_TARGET_SR == 24000:
            n = (len(pcm_int16) // 2) * 2
            if n <= 0:
                return pcm_int16, src_sr
            x = pcm_int16[:n].astype(np.float32)
            y = x.reshape(-1, 2).mean(axis=1)
            return y.astype(np.int16), self.ASR_TARGET_SR

        # Path generico: interpolazione lineare
        x = pcm_int16.astype(np.float32)
        src_len = len(x)
        if src_len < 2:
            return pcm_int16, src_sr

        dst_len = int(round(src_len * (self.ASR_TARGET_SR / float(src_sr))))
        dst_len = max(dst_len, 1)

        src_idx = np.linspace(0, src_len - 1, src_len)
        dst_idx = np.linspace(0, src_len - 1, dst_len)
        y = np.interp(dst_idx, src_idx, x)
        return y.astype(np.int16), self.ASR_TARGET_SR

    @staticmethod
    def _rms_i16(x_i16: np.ndarray) -> float:
        if x_i16.size == 0:
            return 0.0
        xf = x_i16.astype(np.float32)
        return float(np.sqrt(np.mean(xf * xf)))

    def _apply_gain_softclip(self, pcm_target_i16: np.ndarray) -> np.ndarray:
        if self.GAIN <= 1.0001:
            return pcm_target_i16
        x = pcm_target_i16.astype(np.float32) * float(self.GAIN)
        limit = float(self.SOFTCLIP_LEVEL) * 32767.0
        limit = 32767.0 if limit <= 0 else limit
        y = np.tanh(x / limit) * limit
        return np.clip(y, -32768.0, 32767.0).astype(np.int16)

    # Ingestione frame

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

        if not self._logged_shape:
            try:
                logger.debug(
                    "[ASR][SHAPE] session=%s user=%s pcm_shape=%s expected_ch=%s dtype=%s sr_in=%s layout=%s",
                    self.session_id,
                    self.user_id,
                    getattr(pcm, "shape", None),
                    expected_ch,
                    getattr(pcm, "dtype", None),
                    src_sr,
                    frame_layout,
                )
            except Exception:
                logger.exception("[ASR][SHAPE] errore log shape")
            self._logged_shape = True

        mono, ch = self._to_mono_robust(pcm, expected_ch)
        self.channels = ch

        if not self._logged_audio_stats:
            try:
                m_dtype = str(mono.dtype)
                m_kind = mono.dtype.kind
                m_max = float(np.max(mono)) if mono.size else 0.0
                m_min = float(np.min(mono)) if mono.size else 0.0
                m_abs = float(np.max(np.abs(mono))) if mono.size else 0.0
                logger.debug(
                    "[ASR][DIAG] mono dtype=%s kind=%s min=%.6f max=%.6f max_abs=%.6f sr_in=%s ch=%s expected_ch=%s",
                    m_dtype, m_kind, m_min, m_max, m_abs, src_sr, ch, expected_ch
                )
            except Exception:
                logger.exception("[ASR][DIAG] errore nel calcolo stats input")
            self._logged_audio_stats = True

        mono_i16 = self._mono_to_int16_robust(mono)

        # --- DEBUG RAW (prima del resample) ---
        if self._debug_wav_enabled:
            if self._debug_wav_raw_sr is None and src_sr > 0:
                self._debug_wav_raw_sr = src_sr
                self._debug_wav_max_bytes_raw = int(src_sr * self.DEBUG_WAV_SECONDS * 2)
            if self._debug_wav_raw_sr and len(self._debug_wav_raw_buf) < self._debug_wav_max_bytes_raw:
                raw_bytes = mono_i16.tobytes()
                remaining = self._debug_wav_max_bytes_raw - len(self._debug_wav_raw_buf)
                self._debug_wav_raw_buf.extend(raw_bytes[:remaining])

        # resample -> 16k
        pcm_target, out_sr = self._resample_to_target(mono_i16, src_sr)
        if not pcm_target.size:
            return

        # gain (di default no-op)
        pcm_target_g = self._apply_gain_softclip(pcm_target)

        peak = int(np.max(np.abs(pcm_target_g)))
        rms = self._rms_i16(pcm_target_g)

        now = time.time()
        if now < self._warmup_until:
            return

        # --- DEBUG target-rate (dopo warmup, come lo mandi al client ASR) ---
        if self._debug_wav_enabled and len(self._debug_wav_target_buf) < self._debug_wav_max_bytes_target:
            b = pcm_target_g.tobytes()
            remaining = self._debug_wav_max_bytes_target - len(self._debug_wav_target_buf)
            self._debug_wav_target_buf.extend(b[:remaining])

        # diagnostica 1Hz (post-processing)
        x = pcm_target_g.astype(np.float32)
        self._rms_acc += float(np.mean(x * x))
        self._rms_n += 1
        self._zero_n += int(np.sum(pcm_target_g == 0))
        self._tot_n += int(pcm_target_g.size)

        if now >= self._diag_next and self._rms_n > 0:
            rms_1s = (self._rms_acc / self._rms_n) ** 0.5
            zero_pct = (self._zero_n / max(self._tot_n, 1)) * 100.0
            logger.debug(
                "[ASR][1s] session=%s user=%s rms_1s=%.1f zero_pct=%.1f%% sr_in=%s sr_out=%s ch=%s",
                self.session_id, self.user_id, rms_1s, zero_pct, src_sr, out_sr, self.channels
            )
            self._rms_acc = 0.0
            self._rms_n = 0
            self._zero_n = 0
            self._tot_n = 0
            self._diag_next = now + (1.0 / self.DIAG_HZ)

        pcm_bytes = pcm_target_g.tobytes()
        num_bytes = int(len(pcm_bytes))

        self.total_bytes += num_bytes
        self.total_samples += int(pcm_target_g.shape[0])

        self._push_buf.extend(pcm_bytes)

        if self._asr_client and len(self._push_buf) >= self.ASR_PUSH_BYTES:
            try:
                while len(self._push_buf) >= self.ASR_PUSH_BYTES:
                    chunk = bytes(self._push_buf[: self.ASR_PUSH_BYTES])
                    del self._push_buf[: self.ASR_PUSH_BYTES]
                    self._asr_client.push_audio(chunk)
                    self._sent_bytes += len(chunk)
            except Exception:
                logger.exception("[ASR] Errore invio buffer al client session=%s user=%s", self.session_id, self.user_id)
                self._push_buf.clear()

            logger.debug(
                "[ASR] PUSH session=%s user=%s sr_in=%s sr_out=%s peak=%d rms=%.1f sent_bytes=%d buf_rem=%d total_bytes=%d",
                self.session_id, self.user_id, src_sr, out_sr, peak, rms, self._sent_bytes, len(self._push_buf), self.total_bytes
            )