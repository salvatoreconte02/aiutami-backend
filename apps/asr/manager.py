# apps/asr/manager.py

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

# Stato in-process:
# asr_states[(session_id, user_id)] = {
#     "task": <asyncio.Task>,
#     "track": <MediaStreamTrack>
# }
asr_states: dict[tuple[str, int], dict] = {}


async def start_asr_for_track(session_id: str, user_id: int, track):
    """
    Avviata quando arriva una nuova traccia audio da WebRTC.
    Crea e avvia un task dedicato che legge i frame dalla track.
    """
    key = (session_id, user_id)

    # Se esiste un ASR attivo per questa coppia → stop e restart
    if key in asr_states:
        old = asr_states[key]
        old_task = old.get("task")
        if old_task and not old_task.done():
            old_task.cancel()
        del asr_states[key]

    # Crea il task asincrono che leggerà i frame audio
    task = asyncio.create_task(
        _run_asr_loop(session_id, user_id, track),
        name=f"ASR-{session_id}-{user_id}"
    )

    asr_states[key] = {
        "task": task,
        "track": track,
    }


async def stop_asr(session_id: str, user_id: int):
    """
    Ferma e rimuove un task ASR attivo.
    """
    key = (session_id, user_id)
    state = asr_states.pop(key, None)

    if state is None:
        return

    task = state.get("task")
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    logger.info(f"[ASR] Stopped ASR for session={session_id} user={user_id}")


# -------------------------------------------------------------------------
# LOOP DI LETTURA FRAME AUDIO (stub)
# -------------------------------------------------------------------------
async def _run_asr_loop(session_id: str, user_id: int, track):
    """
    Loop principale:
    - legge frame audio dalla track WebRTC
    - (in futuro) li manda all’ASR Azure
    - ora logga ogni X frame
    """
    frame_counter = 0

    logger.info(
        f"[ASR] START loop session={session_id} user={user_id}"
    )

    try:
        while True:
            frame = await track.recv()  # Frame PCM 16bit/Opus a seconda del browser
            frame_counter += 1

            # 🔹 LOG ogni 10 frame (basso impatto, utile debug)
            if frame_counter % 10 == 0:
                logger.info(
                    f"[ASR] session={session_id} user={user_id} frames={frame_counter} "
                    f"timestamp={frame.time}"
                )

            # TODO: futuro → mandare frame al servizio Azure ASR

    except asyncio.CancelledError:
        logger.info(
            f"[ASR] LOOP CANCELLED session={session_id} user={user_id}"
        )
        raise

    except Exception as e:
        logger.error(
            f"[ASR] ERROR in loop session={session_id} user={user_id}: {e}"
        )

    finally:
        logger.info(
            f"[ASR] END loop session={session_id} user={user_id}"
        )