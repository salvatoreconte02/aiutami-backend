// src/pages/Dashboard.jsx
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../api/axiosConfig";

export default function Dashboard() {
  const navigate = useNavigate();
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const res = await api.get("/sessions/mine/");
        setSessions(res.data);
      } catch (err) {
        console.error("Errore caricamento sessioni:", err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) return <h2>Caricamento dashboard...</h2>;

  const lobby = sessions.filter((s) => s.state === "LOBBY");
  const active = sessions.filter((s) => s.state === "ACTIVE");

  return (
    <div
      style={{
        width: "100%",
        minHeight: "100vh",
        padding: "4rem 3rem",
        fontFamily: "Inter, sans-serif",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
      }}
    >
      {/* TITOLO */}
      <h1 style={{ fontSize: "2.8rem", fontWeight: "700", marginBottom: "0.5rem" }}>
        Le tue sessioni
      </h1>

      <p style={{ fontSize: "1.2rem", color: "#555", marginBottom: "4rem" }}>
        Crea una nuova sessione, unisciti con un link o rivedi lo storico.
      </p>

      {/* -------------------------------------- */}
      {/* SEZIONE: card azioni principali */}
      {/* -------------------------------------- */}
      <div
        style={{
          display: "flex",
          justifyContent: "center",
          gap: "3rem",
          marginBottom: "5rem",
          marginTop: "2rem",
        }}
      >
        <ActionCard
          icon="/icons/add.png"
          title="Crea una nuova sessione"
          desc="Scegli un contesto, assegna un nome e condividi il link."
          onClick={() => navigate("/new-session/context")}
        />

        <ActionCard
          icon="/icons/link.png"
          title="Unisciti con un link"
          desc="Accedi rapidamente tramite link d’invito."
          onClick={() => navigate("/join-session")}
        />

        <ActionCard
          icon="/icons/archivio.png"
          title="Storico sessioni"
          desc="Rivedi i riepiloghi delle sessioni concluse."
          onClick={() => navigate("/history")}
        />
      </div>


      {/* DUE COLONNE */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(2, 1fr)",
          gap: "4rem",
          width: "100%",
          maxWidth: "1100px",
        }}
      >

        <Column
          dotColor="#F2A100"
          title="Sessioni in lobby"
          subtitle="Sessioni pronte per iniziare"
          empty="Nessuna sessione in lobby."
          sessions={lobby}
          onEnter={(id) => navigate(`/session/${id}/lobby`)}
          showReenter
        />

        <Column
          dotColor="#EB5757"
          title="Sessioni attive"
          subtitle="Sessioni attualmente in corso"
          empty="Nessuna sessione attiva al momento."
          sessions={active}
          onEnter={(id) => navigate(`/session/${id}/active`)}
          showReenter
        />
      </div>
    </div>
  );
}

/* ===========================================================
   COMPONENTI UI DELLA DASHBOARD
   =========================================================== */

// Card azione (uniforme)
function ActionCard({ icon, title, desc, onClick }) {
  return (
    <div
      onClick={onClick}
      style={{
        width: "300px",
        height: "240px",
        padding: "1.5rem",
        borderRadius: "12px",
        border: "1px solid #e6e6e6",
        boxShadow: "0 2px 8px rgba(0,0,0,0.08)",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "flex-start",
        cursor: "pointer",
        transition: "0.15s ease",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.transform = "translateY(-3px)";
        e.currentTarget.style.boxShadow = "0 4px 12px rgba(0,0,0,0.12)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = "translateY(0)";
        e.currentTarget.style.boxShadow = "0 2px 8px rgba(0,0,0,0.08)";
      }}
    >
      <img
        src={icon}
        alt=""
        style={{
          width: "75px",
          height: "70px",
          marginBottom: "1rem",
          opacity: 0.85,
        }}
      />

      <h3 style={{ margin: "0 0 0.5rem", fontSize: "1.15rem", textAlign: "center" }}>
        {title}
      </h3>

      <p
        style={{
          color: "#666",
          fontSize: "0.9rem",
          textAlign: "center",
          lineHeight: "1.3rem",
        }}
      >
        {desc}
      </p>
    </div>
  );
}


function Column({ dotColor, title, subtitle, empty, sessions, onEnter, showReenter }) {
  return (
    <div>
      <h2
        style={{
          fontSize: "1.3rem",
          fontWeight: "600",
          marginBottom: "0.3rem",
          display: "flex",
          alignItems: "center",
          gap: "0.4rem",
        }}
      >
        <span
          style={{
            width: "10px",
            height: "10px",
            background: dotColor,
            borderRadius: "50%",
          }}
        ></span>
        {title}
      </h2>

      <p style={{ color: "#666", marginBottom: "1.2rem", fontSize: "1rem" }}>
        {subtitle}
      </p>

      {sessions.length === 0 && (
        <p style={{ color: "#999", fontSize: "1rem" }}>{empty}</p>
      )}

      {sessions.map((s) => (
        <SessionCard
          key={s.id}
          title={s.title}
          users={s.participants_count}
          onEnter={() => onEnter(s.id)}
          showReenter={showReenter}
        />
      ))}
    </div>
  );
}

function SessionCard({ title, users, onEnter, showReenter }) {
  return (
    <div
      style={{
        border: "1px solid #ddd",
        background: "white",
        borderRadius: "14px",
        padding: "3rem",
        marginTop: "1rem",
        height: "180px",
      }}
    >
      <h4 style={{ fontSize: "1.2rem", fontWeight: "600", marginBottom: "0.4rem" }}>
        {title}
      </h4>

      <p style={{ color: "#555", fontSize: "1rem", marginBottom: "1rem" }}>
        Utenti collegati: {users}
      </p>

      <div style={{ display: "flex", gap: "0.6rem" }}>
        {showReenter && (
          <button
            onClick={onEnter}
            style={{
              background: "#3B82F6",
              color: "white",
              border: "none",
              padding: "0.5rem 1rem",
              borderRadius: "8px",
              cursor: "pointer",
              fontSize: "1rem",
            }}
          >
            Rientra
          </button>
        )}
      </div>
    </div>
  );
}
