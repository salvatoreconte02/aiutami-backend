// src/sessions/useSessionWS.js
// WebSocket per lo stato delle sessioni (ACTIVE/CONCLUSION)

import { useEffect, useState, useRef } from "react";

const WS_BASE =
  (import.meta.env.VITE_WS_BASE || "ws://localhost:8000/ws") + "/sessions";

export default function useSessionWS(sessionId, accessToken) {
  const wsRef = useRef(null);

  const [sessionEvent, setSessionEvent] = useState(null);
  const [voteEvent, setVoteEvent] = useState(null);

  const [connected, setConnected] = useState(false);

  const canOpen =
    Boolean(sessionId) && Boolean(accessToken) && accessToken.length > 10;

  useEffect(() => {
    if (!canOpen) return;

    const url = `${WS_BASE}/${sessionId}/?token=${accessToken}`;
    console.log("[SESSION_WS] APERTURA:", url);

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log("[SESSION_WS] ✔ APERTO");
      setConnected(true);
    };

    ws.onerror = (e) => {
      console.error("[SESSION_WS] ❌ ERRORE:", e);
    };

    ws.onclose = () => {
      console.log("[SESSION_WS] ✘ CHIUSO");
      setConnected(false);
      wsRef.current = null;
    };

    ws.onmessage = (event) => {
      console.log("[SESSION_WS] RAW:", event.data);

      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        console.warn("[SESSION_WS] Messaggio non JSON");
        return;
      }

      // ---------------------------
      // 0) SESSIONE CHIUSA (CLOSED)
      // ---------------------------
      const isSessionClosed =
        msg?.type === "sessions.session_closed" ||
        msg?.type === "session.session_closed" ||
        msg?.type === "SESSION_CLOSED";

      if (isSessionClosed) {
        // payload: SessionDetailSerializer completo con state:"CLOSED"
        if (msg.payload && typeof msg.payload === "object") {
          console.log("[SESSION_WS] 🔒 SESSION_CLOSED:", msg.payload);
          setSessionEvent(msg.payload);
          return;
        }

        // fallback minimo: almeno lo stato
        console.log("[SESSION_WS] 🔒 SESSION_CLOSED (senza payload) → fallback HTTP");
        setSessionEvent({ state: "CLOSED", __partial: true });
        return;
      }

      // ---------------------------
      // 1) EVENTI "STATE CHANGED"
      // ---------------------------
      const isStateChanged =
        msg?.type === "sessions.state_changed" ||
        msg?.type === "session.state_changed";

      if (isStateChanged) {
        // Caso normale: payload completo (SessionDetailSerializer)
        if (msg.payload && typeof msg.payload === "object" && msg.payload.state) {
          console.log("[SESSION_WS] 🔄 Stato sessione aggiornato:", msg.payload);
          setSessionEvent(msg.payload);
          return;
        }

        // Caso "payload vuoto" ma backend manda solo new_state
        if (msg.new_state) {
          console.log(
            "[SESSION_WS] 🔄 Stato sessione aggiornato (new_state):",
            msg.new_state
          );
          setSessionEvent({ state: msg.new_state, __partial: true });
          return;
        }

        // Caso estremo: evento senza info → segnalo "partial" e farà fallback HTTP
        console.log(
          "[SESSION_WS] 🔄 Stato sessione aggiornato (senza dettagli) → fallback HTTP"
        );
        setSessionEvent({ __partial: true });
        return;
      }

      // ---------------------------
      // 2) EVENTI VOTO (CONCLUSION)
      // ---------------------------
      const isVoteCast =
        msg?.type === "sessions.vote_cast" ||
        msg?.type === "session.vote_cast" ||
        msg?.type === "VOTE_CAST";

      const isAllVoted =
        msg?.type === "sessions.all_voted" ||
        msg?.type === "session.all_voted" ||
        msg?.type === "ALL_VOTED";

      if (isVoteCast) {
        const payload =
          (msg.payload && typeof msg.payload === "object" && msg.payload) || {
            user_id: msg.user_id,
          };

        console.log("[SESSION_WS] ✅ VOTE_CAST:", payload);
        setVoteEvent({ type: "VOTE_CAST", payload });
        return;
      }

      if (isAllVoted) {
        const payload =
          (msg.payload && typeof msg.payload === "object" && msg.payload) || {
            results: msg.results,
            success_rate: msg.success_rate,
            guilty: msg.guilty,
            closing_in_seconds: msg.closing_in_seconds,
          };

        console.log("[SESSION_WS] 🏁 ALL_VOTED:", payload);
        setVoteEvent({ type: "ALL_VOTED", payload });
        return;
      }

      console.log("[SESSION_WS] (ignoro type):", msg?.type);
    };

    return () => {
      if (wsRef.current) {
        console.log("[SESSION_WS] Cleanup → chiudo");
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [canOpen, sessionId, accessToken]);

  return { sessionEvent, voteEvent, connected };
}
