// src/pages/Me.jsx

import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function Me() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();

  const displayName = user
    ? `${user.first_name || ""} ${user.last_name || ""}`.trim() || user.username
    : "";

  const initial = user?.username?.[0]?.toUpperCase() || "U";

  function handleLogout() {
    logout();
    navigate("/login", { replace: true });
  }

  return (
    <div
      style={{
        minHeight: "calc(100vh - 60px)",
        padding: "2.5rem 1.5rem",
        background:
          "linear-gradient(180deg, #EEF4FF 0%, #F7F8FA 60%, #FFFFFF 100%)",
        fontFamily: "Arial, sans-serif",
      }}
    >
      <div style={{ maxWidth: "900px", margin: "0 auto" }}>
        {/* Header pagina */}
        <div style={{ marginBottom: "1.5rem" }}>
          <h1 style={{ margin: 0, fontSize: "2.2rem", letterSpacing: "-0.02em" }}>
            Profilo utente
          </h1>
          <p style={{ margin: "0.4rem 0 0", color: "#5B6573", fontSize: "1.05rem" }}>
            Gestisci e visualizza le tue informazioni principali.
          </p>
        </div>

        {/* Stato loading */}
        {!user ? (
          <div
            style={{
              padding: "1.25rem",
              borderRadius: "14px",
              backgroundColor: "rgba(255,255,255,0.9)",
              border: "1px solid rgba(0,0,0,0.08)",
              boxShadow: "0 10px 24px rgba(0,0,0,0.08)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "0.9rem" }}>
              <div
                style={{
                  width: "48px",
                  height: "48px",
                  borderRadius: "12px",
                  backgroundColor: "#DCE8FF",
                }}
              />
              <div style={{ flex: 1 }}>
                <div
                  style={{
                    height: "14px",
                    width: "220px",
                    backgroundColor: "#E8ECF2",
                    borderRadius: "999px",
                    marginBottom: "10px",
                  }}
                />
                <div
                  style={{
                    height: "12px",
                    width: "140px",
                    backgroundColor: "#EEF1F6",
                    borderRadius: "999px",
                  }}
                />
              </div>
            </div>
            <p style={{ margin: "1rem 0 0", color: "#6B7380" }}>
              Caricamento dati utente…
            </p>
          </div>
        ) : (
          <>
            {/* Card principale */}
            <div
              style={{
                borderRadius: "18px",
                backgroundColor: "rgba(255,255,255,0.95)",
                border: "1px solid rgba(0,0,0,0.08)",
                boxShadow: "0 14px 30px rgba(0,0,0,0.10)",
                overflow: "hidden",
              }}
            >
              {/* Top bar */}
              <div
                style={{
                  padding: "1.25rem 1.25rem",
                  background:
                    "linear-gradient(90deg, rgba(59,139,219,0.14), rgba(84,113,140,0.10))",
                  borderBottom: "1px solid rgba(0,0,0,0.06)",
                  display: "flex",
                  alignItems: "center",
                  gap: "1rem",
                }}
              >
                {/* Avatar */}
                <div
                  style={{
                    width: "56px",
                    height: "56px",
                    borderRadius: "16px",
                    backgroundColor: "#3B8BDB",
                    color: "white",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontWeight: "800",
                    fontSize: "1.4rem",
                    boxShadow: "0 10px 18px rgba(59,139,219,0.35)",
                    flexShrink: 0,
                  }}
                >
                  {initial}
                </div>

                {/* Info principali */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "baseline",
                      gap: "0.6rem",
                      flexWrap: "wrap",
                    }}
                  >
                    <h2 style={{ margin: 0, fontSize: "1.35rem" }}>{displayName}</h2>
                    <span
                      style={{
                        padding: "0.25rem 0.6rem",
                        borderRadius: "999px",
                        backgroundColor: "rgba(59,139,219,0.12)",
                        color: "#1D5FA7",
                        fontSize: "0.9rem",
                        fontWeight: "700",
                      }}
                    >
                      @{user.username}
                    </span>
                  </div>

                  <div style={{ marginTop: "0.35rem", color: "#51606F" }}>
                    {user.email}
                  </div>
                </div>

                {/* ID pill */}
                <div
                  style={{
                    padding: "0.45rem 0.7rem",
                    borderRadius: "12px",
                    border: "1px solid rgba(0,0,0,0.10)",
                    backgroundColor: "rgba(255,255,255,0.65)",
                    fontSize: "0.9rem",
                    color: "#3C4653",
                    fontWeight: "700",
                  }}
                  title="ID utente"
                >
                  ID: {user.id}
                </div>
              </div>

              {/* Contenuto */}
              <div style={{ padding: "1.25rem" }}>
                <h3 style={{ margin: "0 0 1rem", fontSize: "1.1rem" }}>
                  Informazioni account
                </h3>

                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                    gap: "0.9rem",
                  }}
                >
                  <InfoField label="Username" value={user.username} />
                  <InfoField label="Email" value={user.email} />
                  <InfoField label="Nome" value={user.first_name || "—"} />
                  <InfoField label="Cognome" value={user.last_name || "—"} />
                </div>

                {/* AZIONI */}
                <div
                  style={{
                    marginTop: "1.25rem",
                    paddingTop: "1rem",
                    borderTop: "1px solid rgba(0,0,0,0.08)",
                    display: "flex",
                    justifyContent: "center",
                  }}
                >
                  <button
                    onClick={handleLogout}
                    style={{
                      backgroundColor: "#d9534f",
                      color: "white",
                      border: "none",
                      padding: "12px 16px",
                      cursor: "pointer",
                      borderRadius: "12px",
                      fontWeight: "800",
                      transition: "transform 0.1s ease, background-color 0.15s ease",
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.backgroundColor = "#c64541";
                      e.currentTarget.style.transform = "scale(1.03)";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.backgroundColor = "#d9534f";
                      e.currentTarget.style.transform = "scale(1)";
                    }}
                  >
                    Logout
                  </button>
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function InfoField({ label, value }) {
  return (
    <div
      style={{
        padding: "0.9rem 1rem",
        borderRadius: "14px",
        border: "1px solid rgba(0,0,0,0.08)",
        backgroundColor: "white",
      }}
    >
      <div style={{ fontSize: "0.85rem", color: "#6B7380", marginBottom: "0.35rem" }}>
        {label}
      </div>
      <div style={{ fontSize: "1.05rem", fontWeight: "700", color: "#1E2833" }}>
        {value}
      </div>
    </div>
  );
}