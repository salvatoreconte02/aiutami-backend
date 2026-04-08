// src/turns/useTurnsWS.js
// WebSocket per il sistema di turni (speaking/reservation)

import { useEffect, useRef, useState, useCallback } from "react";
import { createInitialTurnState } from "./schema";

// Log utili
const log = (...args) => console.log("[WS]", ...args);
const turnLog = (...args) => console.log("[TURN]", ...args);

const WS_BASE = (import.meta.env.VITE_WS_BASE || "ws://localhost:8000/ws") + "/turns";

export function useTurnsWS(sessionId, user, accessToken) {
  const wsRef = useRef(null);
  const pingTimerRef = useRef(null);

  const [state, setState] = useState(createInitialTurnState());
  const [lastEvent, setLastEvent] = useState(null);

  // Override AI: quando true, qualunque turns.state “stale” non può spegnere AI_SPEAKING
  const aiOverrideRef = useRef(false);

  const canOpen =
    Boolean(sessionId) &&
    Boolean(user?.id) &&
    Boolean(accessToken && accessToken.length > 10);

  const openWebSocket = useCallback(() => {
    if (!canOpen) {
      log("WS skipped: condizioni insufficienti");
      return;
    }

    if (wsRef.current && wsRef.current.readyState !== WebSocket.CLOSED) {
      log("🔁 Chiudo WS precedente prima di riaprire");
      try {
        wsRef.current.close();
      } catch {}
      wsRef.current = null;
    }

    const url = `${WS_BASE}/${sessionId}/?token=${accessToken}`;
    log("🔌 Apertura WebSocket →", url);

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      log("✅ WS aperto");
      ws.send(JSON.stringify({ type: "turns.get_state" }));

      if (pingTimerRef.current) clearInterval(pingTimerRef.current);
      pingTimerRef.current = setInterval(() => {
        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: "turns.ping" }));
        }
      }, 5000);
    };

    ws.onerror = (e) => {
      console.error("[WS] Errore WebSocket:", e);
    };

    ws.onclose = (e) => {
      log("❌ WS chiuso", { code: e.code, reason: e.reason, wasClean: e.wasClean });
      wsRef.current = null;

      if (pingTimerRef.current) {
        clearInterval(pingTimerRef.current);
        pingTimerRef.current = null;
      }
    };

    ws.onmessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        console.warn("[WS] Messaggio non JSON, ignorato");
        return;
      }

      const t = msg.type;
      const p = msg.payload;

      if (t === "turns.ping_ok") return;

      if (t === "turns.state") {
        turnLog("📡 RX state:", {
          state: p?.state,
          speaker: p?.current_speaker_user_id,
          reservation: p?.reservation_user_id,
          error: p?.error_code,
          aiOverride: aiOverrideRef.current,
        });
      } else if (t === "turns.static_message") {
        turnLog("📢 RX static:", {
          trigger_type: p?.trigger_type,
          target_user_id: p?.target_user_id,
          use_tts: p?.use_tts,
          text: p?.text,
        });
      } else {
        turnLog("📩 RX:", t, p);
      }

      if (t === "turns.state") {
        let next = p;

        if (aiOverrideRef.current) {
          next = {
            ...next,
            state: "AI_SPEAKING",
            current_speaker_user_id: null,
          };
        }

        setState(next);

        if (next?.error_code) {
          setLastEvent({ type: "turns.error", payload: next });
        }
        return;
      }

      switch (t) {
        case "turns.ai_started": {
          turnLog("🤖 event:", t, p);
          aiOverrideRef.current = true;

          setState((prev) => ({
            ...prev,
            state: "AI_SPEAKING",
            current_speaker_user_id: null,
          }));

          setLastEvent({ type: t, payload: p });
          ws.send(JSON.stringify({ type: "turns.get_state" }));
          return;
        }

        case "turns.ai_ended": {
          turnLog("🛑 event:", t, p);
          aiOverrideRef.current = false;

          setState((prev) => ({
            ...prev,
            state: "IDLE",
            current_speaker_user_id: null,
          }));

          setLastEvent({ type: t, payload: p });
          ws.send(JSON.stringify({ type: "turns.get_state" }));
          return;
        }

        case "turns.human_started":
        case "turns.human_ended":
        case "turns.reservation_set":
        case "turns.reservation_window_started":
        case "turns.reservation_expired": {
          turnLog("👤 event:", t, p);
          setLastEvent({ type: t, payload: p });
          ws.send(JSON.stringify({ type: "turns.get_state" }));
          return;
        }

        case "turns.static_message": {
          setLastEvent({ type: "turns.static_message", payload: p });
          return;
        }

        case "turns.event": {
          if (msg.event_type === "STATIC_MESSAGE") {
            turnLog("📢 RX static (via turns.event):", {
              trigger_type: p?.trigger_type,
              target_user_id: p?.target_user_id,
              use_tts: p?.use_tts,
              text: p?.text,
            });

            setLastEvent({ type: "turns.static_message", payload: p });
          }
          return;
        }

        case "turns.ai_message": {
          const text = typeof p === "string" ? p : p?.text;
          setLastEvent({ type: "turns.ai_message", payload: { text } });
          return;
        }

        case "moderation.ai_message": {
          const text = typeof p === "string" ? p : p?.text;
          setLastEvent({ type: "turns.ai_message", payload: { text } });
          return;
        }

        default:
          return;
      }
    };
  }, [canOpen, sessionId, accessToken]);

  useEffect(() => {
    if (!canOpen) return;

    openWebSocket();

    return () => {
      if (wsRef.current) {
        log("🧹 Cleanup: chiudo WS");
        try {
          wsRef.current.close();
        } catch {}
        wsRef.current = null;

        if (pingTimerRef.current) {
          clearInterval(pingTimerRef.current);
          pingTimerRef.current = null;
        }
      }
      aiOverrideRef.current = false;
    };
  }, [canOpen, openWebSocket]);

  function sendWS(msg) {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      log("⚠️ Invio fallito (WS non aperto):", msg);
      return;
    }
    ws.send(JSON.stringify(msg));
  }

  const requestSpeak = useCallback(() => {
    turnLog("🎤 requestSpeak()");
    sendWS({ type: "turns.request_speak" });
  }, []);

  const endSpeak = useCallback(() => {
    turnLog("🔇 endSpeak()");
    sendWS({ type: "turns.end_speak" });
  }, []);

  const requestReserve = useCallback(() => {
    turnLog("📌 requestReserve()");
    sendWS({ type: "turns.request_reserve" });
  }, []);

  const clearReserve = useCallback(() => {
    turnLog("🧹 clearReserve() — non implementato");
  }, []);

  return {
    state,
    lastEvent,
    requestSpeak,
    endSpeak,
    requestReserve,
    clearReserve,
  };
}
