# apps/asr/service.py

from __future__ import annotations

import logging
from typing import Dict, Tuple

from django.core.cache import cache

from .worker import ASRStreamWorker

logger = logging.getLogger(__name__)


class ASRStreamManager:
    """
    Gestore in-process dei flussi ASR, indicizzati per (session_id, user_id).

    - start_stream: crea un worker per la coppia (session_id, user_id)
    - ingest_frame: inoltra il frame al worker
    - stop_stream: chiude il worker e lo rimuove
    """

    def __init__(self) -> None:
        self._streams: Dict[Tuple[str, int], ASRStreamWorker] = {}

    def _key(self, session_id, user_id) -> Tuple[str, int]:
        return str(session_id), int(user_id)

    def _transcript_cache_key(self, session_id, user_id) -> str:
        return f"asr:final_segments:{str(session_id)}:{int(user_id)}"

    # ------------------------------------------------------------------ #
    # API pubblica usata dal WebRTCConsumer
    # ------------------------------------------------------------------ #

    def start_stream(self, session_id, user_id) -> None:
        key = self._key(session_id, user_id)

        if key in self._streams:
            logger.info(
                "[ASR] start_stream: worker già esistente session=%s user=%s",
                session_id,
                user_id,
            )
            return

        # Reset transcript cache per questo turno (pulizia forte)
        try:
            cache.delete(self._transcript_cache_key(session_id, user_id))
            logger.info("[ASR][CACHE] cleared session=%s user=%s", session_id, user_id)
        except Exception:
            logger.exception("[ASR][CACHE] failed clear session=%s user=%s", session_id, user_id)

        worker = ASRStreamWorker(session_id=session_id, user_id=user_id)
        self._streams[key] = worker

        logger.info("[ASR] START worker session=%s user=%s", session_id, user_id)
        worker.start()
        logger.info("[ASR] Stream creato session=%s user=%s", session_id, user_id)

    def ingest_frame(self, session_id, user_id, frame) -> None:
        """
        Chiamata dal WebRTCConsumer per ogni frame audio ricevuto.
        """
        key = self._key(session_id, user_id)
        worker = self._streams.get(key)

        if not worker:
            logger.warning(
                "[ASR] ingest_frame senza worker session=%s user=%s (frame ignorato)",
                session_id,
                user_id,
            )
            return

        worker.ingest_frame(frame)

    def stop_stream(self, session_id, user_id) -> None:
        key = self._key(session_id, user_id)
        worker = self._streams.pop(key, None)

        if not worker:
            logger.info(
                "[ASR] stop_stream: nessun worker da chiudere session=%s user=%s",
                session_id,
                user_id,
            )
            return

        worker.stop()


# Istanza globale usata da WebRTCConsumer
asr_stream_manager = ASRStreamManager()