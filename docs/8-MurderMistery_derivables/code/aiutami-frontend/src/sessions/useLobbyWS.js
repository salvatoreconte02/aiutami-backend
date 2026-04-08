//  src/sessions/useLobbyWS.js
//  WebSocket per la lobby delle sessioni (con LOG)

import { useEffect, useState, useRef } from "react";

function buildLobbyWsBase() {
  // Se VITE_WS_BASE è definito (es: "wss://dominio/ws") lo usiamo come base per i WS
  const env = import.meta.env.VITE_WS_BASE;
  if (env) {
    return env.replace(/\/+$/, "") + "/sessions";
  }

  // Altrimenti usa protocollo + host corrente
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/ws/sessions`;
}

const WS_BASE = buildLobbyWsBase();

export default function useLobbyWS(sessionId, accessToken) {
  const wsRef = useRef(null);

  const [session, setSession] = useState(null);
  const [connected, setConnected] = useState(false);

  const canOpen =
    Boolean(sessionId) && Boolean(accessToken) && accessToken.length > 10;

  useEffect(() => {
    if (!canOpen) {
      console.log("[LOBBY_WS] Non apro WS: condizioni insufficienti");
      return;
    }

    const url = `${WS_BASE}/${sessionId}/?token=${encodeURIComponent(accessToken)}`;
    console.log("[LOBBY_WS] APERTURA:", url);

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log("[LOBBY_WS] ✔ APERTO");
      setConnected(true);
    };

    ws.onerror = (e) => {
      console.error("[LOBBY_WS] ❌ ERRORE:", e);
    };

    ws.onclose = (e) => {
      console.log("[LOBBY_WS] ✘ CHIUSO", {
        code: e.code,
        reason: e.reason,
        wasClean: e.wasClean,
      });
      setConnected(false);
      wsRef.current = null;
    };

    ws.onmessage = (event) => {
      console.log("[LOBBY_WS] RAW MESSAGE:", event.data);

      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        console.warn("[LOBBY_WS] Messaggio NON JSON");
        return;
      }

      console.log("[LOBBY_WS] Parsed:", msg);

      if (msg.type === "sessions.state_changed") {
        console.log("[LOBBY_WS] 🔄 Stato aggiornato ricevuto:", msg.payload);
        setSession(msg.payload);
      }
    };

    return () => {
      if (wsRef.current) {
        console.log("[LOBBY_WS] Cleanup → chiudo la connessione");
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [canOpen, sessionId, accessToken]);

  return {
    session,
    connected
  };
}
