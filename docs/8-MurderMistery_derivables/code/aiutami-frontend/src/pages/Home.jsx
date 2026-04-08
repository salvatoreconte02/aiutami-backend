// src/pages/Home.jsx

// Import base React
import { useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import api from "../api/axiosConfig";
import { useAuth } from "../context/AuthContext";

export default function Home() {
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated } = useAuth();
  const enterMode = isAuthenticated && location.state?.mode === "enter";

  // Gestione invito da query ?invite=TOKEN
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const inviteToken = params.get("invite");

    // se non c'è parametro ?invite=... → normale homepage
    if (!inviteToken) return;

    // se NON sono autenticata → vai a login, portandoti dietro il token
    if (!isAuthenticated) {
      navigate("/login", { state: { inviteToken } });
      return;
    }

    // se sono autenticata → prova a unirti subito alla sessione
    const join = async () => {
      try {
        const res = await api.post("/sessions/join_by_token/", {
          token: inviteToken,
        });

        const sessionId = res.data.session.id;
        navigate(`/session/${sessionId}/lobby`);
      } catch (err) {
        console.error("Errore join_by_token da Home:", err);
        const msg =
          err.response?.data?.non_field_errors?.[0] ||
          "Impossibile unirti alla sessione. Il link potrebbe non essere più valido.";
        alert(msg);
        navigate("/dashboard");
      }
    };

    join();
  }, [location.search, isAuthenticated, navigate]);

  // ---- UI DELLA HOME ----
  return (
    <div
      style={{
        fontFamily: "Arial, sans-serif",
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        height: "100vh",
        backgroundColor: "#54718C",
        color: "white",
        padding: "2rem",
      }}
    >
      {/* CONTENITORE PRINCIPALE */}
      <div
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
          width: "100%",
          maxWidth: "1600px",
          gap: "3rem",
        }}
      >
        {/* SEZIONE TESTO */}
        <div style={{ flex: 1 }}>
          <h1
            style={{
              fontSize: "3.5rem",
              fontWeight: "bold",
              marginBottom: "1rem",
              lineHeight: "1.3",
            }}
          >
            Parla, collabora e lascia che<br />
            il{" "}
            <span style={{
              color: "#ffffff", fontWeight: "bold"
            }}>
              Moderatore AI
            </span>{" "}
            gestisca il dialogo.
          </h1>

          <p
            style={{
              fontSize: "2rem",
              lineHeight: "1.5",
              marginBottom: "2rem",
            }}
          >
            Crea sessioni vocali di gruppo con un moderatore AI che regola i
            turni di parola e adatta la conversazione al contesto scelto.
          </p>

          {/* BOTTONI */}
          {!isAuthenticated ? (
            // NON LOGGATO: Login + Signup
            <div style={{ display: "flex", gap: "1rem" }}>
              <button
                onClick={() => navigate("/login")}
                style={{
                  backgroundColor: "transparent",
                  color: "white",
                  border: "none",
                  fontSize: "2rem",
                  cursor: "pointer",
                  textDecoration: "underline",
                }}
              >
                Log in
              </button>

              <button
                onClick={() => navigate("/signup")}
                style={{
                  backgroundColor: "#3B8BDB",
                  color: "white",
                  border: "none",
                  borderRadius: "100px",
                  padding: "2rem 2rem",
                  fontSize: "2rem",
                  fontWeight: "bold",
                  cursor: "pointer",
                }}
              >
                Sign up
              </button>
            </div>
          ) : enterMode ? (
            // LOGGATO + arrivato dal logo: SOLO "Entra"
            <div style={{
              display: "flex",
              gap: "1rem",
              marginLeft: "30%",
            }}
            >
              <button
                onClick={() => navigate("/dashboard")}
                style={{
                  backgroundColor: "#3B8BDB",
                  color: "white",
                  border: "none",
                  borderRadius: "100px",
                  padding: "2rem 2rem",
                  fontSize: "2rem",
                  fontWeight: "bold",
                  cursor: "pointer",
                }}
              >
                Entra
              </button>
            </div>
          ) : null /* LOGGATO ma non in enterMode: nessun bottone */}
        </div>

        {/* SEZIONE IMMAGINE */}
        <div
          style={{
            flex: 1,
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
          }}
        >
          <img
            src="/icons/landing.png"
            alt="AI Moderatore e partecipanti"
            style={{
              maxWidth: "90%",
              height: "auto",
              borderRadius: "50%",
              boxShadow: "0 0 10px rgba(0,0,0,0.3)",
            }}
          />
        </div>
      </div>
    </div>
  );
}
