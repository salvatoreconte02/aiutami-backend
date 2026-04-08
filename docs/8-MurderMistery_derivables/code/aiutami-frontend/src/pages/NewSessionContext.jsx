// src/pages/NewSessionContext.jsx


import { useState } from "react";
import { useNavigate } from "react-router-dom";

export default function NewSessionContext() {
  const navigate = useNavigate();
  const [error, setError] = useState(null);
  const [loadingContext, setLoadingContext] = useState(null);

  // -------------------------------------------------------------
  // CONTEXT + ICON IMAGES
  // -------------------------------------------------------------
  const contexts = [
    {
      id: "WORKPLACE",
      label: "Riunione di lavoro",
      icon: "/icons/work.png",
      min: 2,
      max: 8,
    },
    {
      id: "ACADEMIC",
      label: "Sessione di studio",
      icon: "/icons/study.png",
      min: 2,
      max: 8,
    },
    {
      id: "MURDER_MYSTERY",
      label: "Murder Mystery",
      icon: "/icons/murder.png",
      min: 3,
      max: 3,
    },
    {
      id: "THERAPEUTIC",
      label: "Supporto terapeutico",
      icon: "/icons/therapy.png",
      min: 2,
      max: 8,
    },
    {
      id: "OTHER",
      label: "Altro",
      icon: "/icons/other.png",
      min: 2,
      max: 8,
    },
  ];

  function handleSelectContext(ctx) {
    setError(null);
    setLoadingContext(ctx.id);

    navigate("/new-session/details", {
      state: {
        context: ctx.id,
        min: ctx.min,
        max: ctx.max,
      },
    });

    setLoadingContext(null);
  }

  return (
    <div
      style={{
        maxWidth: "2000px",
        margin: "0 auto",
        padding: "3rem",
        textAlign: "center",
        fontFamily: "Arial, sans-serif",
      }}
    >
      <h1 style={{ fontSize: "2.4rem", marginBottom: "0.5rem" }}>
        Crea una nuova sessione
      </h1>
      <p style={{ fontSize: "1.2rem" }}>Scegli il contesto della sessione</p>

      {error && <p style={{ color: "red" }}>{error}</p>}

      {/* ------------------------------------
         LAYOUT A 3 CARD SOPRA E 2 CARD SOTTO
      ----------------------------------------- */}
      <div
        style={{
          marginTop: "4rem",
          display: "flex",
          flexDirection: "column",
          gap: "7rem",
          justifyContent: "center",
          alignItems: "center",
          minHeight: "55vh",
        }}
      >
        {/* RIGA 1: 3 card */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, 300px)",
            gap: "7rem",
            justifyContent: "center",
          }}
        >
          {contexts.slice(0, 3).map((ctx) => (
            <ContextCard
              key={ctx.id}
              icon={ctx.icon}
              label={ctx.label}
              loading={loadingContext === ctx.id}
              onClick={() => handleSelectContext(ctx)}
            />
          ))}
        </div>

        {/* RIGA 2: 2 card */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(2, 300px)", 
            gap: "7rem",
            justifyContent: "center",
            marginTop: "1rem",
          }}
        >
          {contexts.slice(3).map((ctx) => (
            <ContextCard
              key={ctx.id}
              icon={ctx.icon}
              label={ctx.label}
              loading={loadingContext === ctx.id}
              onClick={() => handleSelectContext(ctx)}
            />
          ))}
        </div>

      </div>
    </div>
  );
}

// ---------------
// CARD COMPONENT
// ---------------
function ContextCard({ icon, label, onClick, loading }) {
  return (
    <div
      onClick={loading ? null : onClick}
      style={{
        width: "300px",           
        height: "220px",           
        backgroundColor: "white",
        border: "1px solid #ccc",
        borderRadius: "16px",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        cursor: loading ? "not-allowed" : "pointer",
        opacity: loading ? 0.6 : 1,
        boxShadow: "0 3px 10px rgba(0,0,0,0.1)",
        transition: "0.15s",
        padding: "1rem",
      }}
      onMouseEnter={(e) => {
        if (!loading) e.currentTarget.style.transform = "scale(1.08)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = "scale(1)";
      }}
    >
      <img
        src={icon}
        alt={label}
        style={{ width: "80px", height: "80px", marginBottom: "0.8rem" }}
      />

      <h3 style={{ margin: 0, fontSize: "1.2rem" }}>
        {loading ? "Caricamento..." : label}
      </h3>
    </div>
  );
}