// src/pages/SessionLobby.jsx

import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api from "../api/axiosConfig";
import { useAuth } from "../context/AuthContext";
import useLobbyWS from "../sessions/useLobbyWS";
import { notifyOnce, sessionKey } from "../utils/notifyOnce";

// Avatar disponibili
const AVAILABLE_LOBBY_AVATARS = [
  "/avatars/avatar1.png",
  "/avatars/avatar2.png",
  "/avatars/avatar3.png",
  "/avatars/avatar4.png",
  "/avatars/avatar5.png",
  "/avatars/avatar6.png",
  "/avatars/avatar7.png",
  "/avatars/avatar8.png",
  "/avatars/avatar9.png",
  "/avatars/avatar10.png",
];

function hashString(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) {
    h = (h * 31 + str.charCodeAt(i)) % 1000000007;
  }
  return h;
}

function getAvatarForUser(username) {
  const index = hashString(username) % AVAILABLE_LOBBY_AVATARS.length;
  return AVAILABLE_LOBBY_AVATARS[index];
}

export default function SessionLobby() {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const { user, authTokens } = useAuth();

  const [session, setSession] = useState(null);
  const [participants, setParticipants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [copyDone, setCopyDone] = useState(false);

  // WS
  const { session: wsSession } = useLobbyWS(sessionId, authTokens?.access);

  // ---------------- LOAD iniziale ----------------
  async function fetchSession() {
    const res = await api.get(`/sessions/${sessionId}/`);
    setSession(res.data);
    console.log("[LOBBY] HTTP session:", res.data);
  }

  async function fetchParticipants() {
    const res = await api.get(`/sessions/${sessionId}/participants/`);
    setParticipants(res.data);
    console.log("[LOBBY] HTTP participants:", res.data);
  }

  useEffect(() => {
    async function load() {
      try {
        const res = await api.get(`/sessions/${sessionId}/`);
        const s = res.data;

        // Se la sessione non è più in LOBBY → redirect immediato
        if (s.state === "ACTIVE") {
          navigate(`/session/${sessionId}/active`, { replace: true });
          return;
        }
        if (s.state === "CONCLUSION") {
          navigate(`/session/${sessionId}/conclusion`, { replace: true });
          return;
        }
        if (s.state === "CLOSED") {
          navigate("/dashboard", { replace: true });
          return;
        }
        if (s.state !== "LOBBY") {
          navigate("/dashboard", { replace: true });
          return;
        }

        setSession(s);

        const p = await api.get(`/sessions/${sessionId}/participants/`);
        setParticipants(p.data);

      } catch (err) {
        console.error("Errore caricamento lobby:", err);
      } finally {
        setLoading(false);
      }
    }

    load();
  }, [sessionId, navigate]);


  // ---------------- WS reaction ----------------
  useEffect(() => {
    if (!wsSession) return;

    console.log("[LOBBY] ⚡ WS UPDATE ricevuto:", wsSession);

    // Aggiorna sessione
    setSession((prev) => ({
      ...wsSession,
      me: prev?.me ?? wsSession.me,
    }));

    // Aggiorna lista
    (async () => {
      try {
        await fetchParticipants();
      } catch (err) {
        console.error("[LOBBY] errore refreshing participants:", err);
      }
    })();

    // REDIRECTS
    console.log("[LOBBY] Controllo redirect per stato:", wsSession.state);

    if (wsSession.state === "ACTIVE") {
      console.log("[LOBBY] 🔁 Redirect a SESSION ACTIVE");
      navigate(`/session/${sessionId}/active`);
    }

    if (wsSession.state === "CLOSED") {
      console.log("[LOBBY] 🔁 Redirect a DASHBOARD (session closed)");
      // Se questa tab ha appena fatto debug_force_close, non mostrare il secondo popup
      const wasDebug = sessionStorage.getItem(sessionKey(sessionId, "debug_forced_close")) === "1";

      if (!wasDebug) {
        notifyOnce(sessionKey(sessionId, "closed_alert"), () => {
          alert("La sessione è stata chiusa.");
        });
      }

      // pulizia flag
      sessionStorage.removeItem(sessionKey(sessionId, "debug_forced_close"));

      navigate("/dashboard", { replace: true });
    }

  }, [wsSession, sessionId, navigate]);

  // ---------------- DEBUG FORCE CLOSE ----------------
  async function handleForceClose() {
    try {
      await api.post(`/sessions/${sessionId}/debug_force_close/`);

      // Segno che questa tab ha chiuso in modalità debug
      sessionStorage.setItem(sessionKey(sessionId, "debug_forced_close"), "1");

      // Mostro UNA sola volta il popup "forzata"
      notifyOnce(sessionKey(sessionId, "debug_force_close_alert"), () => {
        alert("Sessione chiusa forzatamente");
      });

      navigate("/dashboard", { replace: true });
    } catch (err) {
      console.error("[LOBBY] force close errore:", err);
    }
  }

  // ---------------- COPY INVITE ----------------
  const handleCopyLink = async () => {
    if (!session?.invite_url) return;

    try {
      const urlObj = new URL(session.invite_url, window.location.origin);
      const inviteToken = urlObj.searchParams.get("invite");

      const link = `${window.location.origin}/?invite=${inviteToken}`;
      await navigator.clipboard.writeText(link);

      setCopyDone(true);
      setTimeout(() => setCopyDone(false), 2000);
    } catch (err) {
      console.error("[LOBBY] errore copia:", err);
    }
  };

  // ---------------- LOADING ----------------
  if (loading) return <h2>Caricamento lobby…</h2>;
  if (!session) return <h2>Sessione non trovata</h2>;

  const isHost = session?.host?.id === user?.id;

  const count = session.participants_count;
  const max = session.max_size;
  const canStart = isHost && count === max;

  // ---------------- UI ----------------
  return (
    <div style={{ maxWidth: "900px", margin: "0 auto", fontFamily: "Arial" }}>
      <h1 style={{ textAlign: "center" }}>Lobby della sessione</h1>

      <h2 style={{ textAlign: "center", color: "#2d4b71" }}>
        {session.title}
      </h2>

      <p style={{ textAlign: "center", marginTop: "-5px" }}>
        Partecipanti: {count}/{max}
      </p>

      {/* LISTA PARTECIPANTI */}
      <div
        style={{
          marginTop: "2rem",
          padding: "1.5rem",
          background: "#f7f9fc",
          borderRadius: "12px",
          border: "1px solid #d9e2ef",
        }}
      >
        <h3 style={{ marginBottom: "1rem", color: "#2d4b71" }}>
          Utenti nella lobby
        </h3>

        {participants.map((p) => (
          <ParticipantRow key={p.user.id} user={p.user} role={p.role} />
        ))}
      </div>

      {/* LINK INVITO */}
      <div style={{ marginTop: "2rem", textAlign: "center" }}>
        <button
          onClick={handleCopyLink}
          disabled={!session?.invite_url}
          style={{
            background: "#3B8BDB",
            color: "white",
            border: "none",
            padding: "0.8rem 1.2rem",
            borderRadius: "8px",
            cursor: session?.invite_url ? "pointer" : "not-allowed",
          }}
        >
          {copyDone ? "Link copiato!" : "Copia link invito"}
        </button>
      </div>

      {/* HOST CONTROLS */}
      {isHost && (
        <div style={{ marginTop: "2rem", textAlign: "center" }}>
          <button
            onClick={async () => {
              try {
                console.log("[LOBBY] Host avvia sessione…");
                await api.post(`/sessions/${sessionId}/start/`);
                navigate(`/session/${sessionId}/active`);
              } catch (err) {
                console.error("[LOBBY] start ERRORE:", err);
                alert("Errore nell'avvio della sessione");
              }
            }}
            disabled={!canStart}
            style={{
              background: canStart ? "#2ecc71" : "#a5d6b5",
              color: "white",
              border: "none",
              padding: "1rem 2rem",
              borderRadius: "8px",
              cursor: canStart ? "pointer" : "not-allowed",
            }}
          >
            Avvia sessione
          </button>

          {/* DEBUG */}
          <button
            onClick={handleForceClose}
            style={{
              background: "#b30000",
              color: "white",
              border: "none",
              padding: "0.9rem 1.6rem",
              borderRadius: "8px",
              cursor: "pointer",
              fontSize: "0.95rem",
              marginTop: "1.5rem",
            }}
          >
            🔧 Chiudi sessione (DEBUG)
          </button>
        </div>
      )}
    </div>
  );
}

function ParticipantRow({ user, role }) {
  const avatar = getAvatarForUser(user.username);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0.5rem 1rem",
        background: "white",
        borderRadius: "8px",
        border: "1px solid #ddd",
        marginBottom: "0.5rem",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.7rem" }}>
        <img
          src={avatar}
          alt=""
          style={{
            width: "36px",
            height: "36px",
            borderRadius: "50%",
            border: "2px solid #e1e8f0",
          }}
        />
        <span style={{ fontWeight: "bold" }}>{user.username}</span>
      </div>

      <span style={{ color: "#555" }}>
        {role === "HOST" ? "👑 Host" : "Partecipante"}
      </span>
    </div>
  );
}
