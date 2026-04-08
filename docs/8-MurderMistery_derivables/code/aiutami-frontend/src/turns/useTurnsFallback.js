//  FALLBACK
// ---------------------------------------------------
// Usa IL SERVER REMOTO come SORGENTE UNICA DI VERITÀ.
// React vede sempre cambiamenti → UI si aggiorna sempre.
// ---------------------------------------------------

import { useState, useEffect, useCallback } from "react";
import {
  TURN_STATE_IDLE,
  TURN_STATE_HUMAN_SPEAKING,
  TURN_STATE_AI_SPEAKING,
  createInitialTurnState,
} from "./schema";

const SERVER_URL = "http://localhost:6060";

export function useTurnsFallback(sessionId, user) {
  const [state, setState] = useState(createInitialTurnState());

  // -----------------------------------------
  // LOADING REMOTO
  // -----------------------------------------
  async function loadRemote() {
    try {
      const res = await fetch(`${SERVER_URL}/${sessionId}`);
      const json = await res.json();
      return json || null;
    } catch {
      return null;
    }
  }

  // -----------------------------------------
  // SAVE REMOTO
  // -----------------------------------------
  async function saveRemote(newState) {
    try {
      await fetch(`${SERVER_URL}/${sessionId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newState),
      });
    } catch (e) {
      console.warn("errore POST remoto:", e);
    }
  }

  // -----------------------------------------
  // UPDATE: incrementa version SEMPRE
  // -----------------------------------------
  const updateState = useCallback(
    (updaterFn) => {
      setState((prev) => {
        let next = { ...prev };
        next = updaterFn(next) || next;

        next.version = (prev.version || 0) + 1;

        saveRemote(next);
        return { ...next }; 
      });
    },
    [sessionId]
  );

  // -----------------------------------------
  // POLLING: ogni 500ms carico il REMOTE e sovrascrivo
  // -----------------------------------------
  useEffect(() => {
    const int = setInterval(async () => {
      const remote = await loadRemote();
      if (!remote) return;

      // forza sempre un nuovo oggetto → React rerender
      setState((prev) => {
        if (remote.version !== prev.version) {
          return { ...remote };
        }
        return prev;
      });
    }, 500);

    return () => clearInterval(int);
  }, [sessionId]);

  // -----------------------------------------
  // LOGICA TURNI (come backend)
  // -----------------------------------------
  const requestSpeak = useCallback(() => {
    if (!user) return;

    updateState((s) => {
      if (s.state === TURN_STATE_HUMAN_SPEAKING) return s;
      if (s.state === TURN_STATE_AI_SPEAKING) return s;

      s.state = TURN_STATE_HUMAN_SPEAKING;
      s.current_speaker_user_id = user.id;
      s.reservation_user_id = null;

      return s;
    });
  }, [updateState, user]);

  const endSpeak = useCallback(() => {
    if (!user) return;

    updateState((s) => {
      if (s.current_speaker_user_id === user.id) {
        s.state = TURN_STATE_IDLE;
        s.current_speaker_user_id = null;
      }
      return s;
    });
  }, [updateState, user]);

  const requestReserve = useCallback(() => {
    if (!user) return;

    updateState((s) => {
      if (
        s.state === TURN_STATE_HUMAN_SPEAKING &&
        s.current_speaker_user_id !== user.id
      ) {
        s.reservation_user_id = user.id;
      }
      return s;
    });
  }, [updateState, user]);

  const clearReserve = useCallback(() => {
    if (!user) return;

    updateState((s) => {
      if (s.reservation_user_id === user.id) {
        s.reservation_user_id = null;
      }
      return s;
    });
  }, [updateState, user]);

  return {
    state,
    requestSpeak,
    endSpeak,
    requestReserve,
    clearReserve,
  };
}
