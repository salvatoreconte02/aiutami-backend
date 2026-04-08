// src/pages/Login.jsx


import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import api from "../api/axiosConfig";

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const navigate = useNavigate();
  const location = useLocation();

  const { login } = useAuth();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      // Login (API token)
      await login(username, password);
      console.log("✅ Login riuscito");

      // Gestione del flusso di invito
      const inviteToken = location.state?.inviteToken;

      if (inviteToken) {
        try {
          const res = await api.post("/sessions/join_by_token/", {
            token: inviteToken,
          });

          const sessionId = res.data.session.id;

          // Vai direttamente in lobby
          navigate(`/session/${sessionId}/lobby`, { replace: true });
          return;
        } catch (err2) {
          console.error("Errore join_by_token:", err2);

          const msg =
            err2.response?.data?.non_field_errors?.[0] ||
            "Impossibile unirsi alla sessione. Link non valido o sessione piena.";

          alert(msg);
          navigate("/dashboard", { replace: true });
          return;
        }
      }

      // Nessun invito → comportamento normale
      navigate("/dashboard");
    } catch (err) {
      console.error("❌ Errore login:", err);

      if (err.response) {
        if (err.response.status === 401 || err.response.status === 400) {
          setError("Credenziali non valide. Riprova.");
        } else {
          setError(`Errore del server (${err.response.status}).`);
        }
      } else {
        setError("Errore di connessione al server.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        backgroundColor: "#54718C",
        minHeight: "calc(100vh - 160px)",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "Arial, sans-serif",
      }}
    >
      {/* LOGO */}
      <div style={{ textAlign: "center", marginBottom: "1rem" }}>
        <img
          src="/icons/logo.png"
          alt="AIutami logo"
          style={{ height: "250px", marginBottom: "0px" }}
        />
        <h1 style={{
          color: "black",
          fontWeight: "bold",
          fontSize: "4rem",
          marginTop: "0.2rem",
          marginBottom: "0"
        }}
        >
          AI<span style={{ fontWeight: "normal" }}>utami</span>
        </h1>
      </div>

      {/* CARD */}
      <div
        style={{
          backgroundColor: "#DCE2E9",
          borderRadius: "20px",
          padding: "2rem",
          width: "90%",
          maxWidth: "360px",
          textAlign: "center",
          boxShadow: "0 4px 10px rgba(0,0,0,0.2)",
        }}
      >
        <h2 style={{ color: "#000", marginBottom: "1.5rem" }}>LOG IN</h2>

        <form onSubmit={handleSubmit}>
          <input
            type="text"
            placeholder="Your username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            style={{
              width: "100%",
              padding: "0.8rem",
              marginBottom: "1rem",
              borderRadius: "8px",
              border: "1px solid #444",
              outline: "none",
              fontSize: "1rem",
              textAlign: "center",
            }}
          />

          <input
            type="password"
            placeholder="Your Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            style={{
              width: "100%",
              padding: "0.8rem",
              marginBottom: "0.5rem",
              borderRadius: "8px",
              border: "1px solid #444",
              outline: "none",
              fontSize: "1rem",
              textAlign: "center",
            }}
          />

          <p
            style={{
              fontSize: "0.8rem",
              color: "#3B4D65",
              textAlign: "right",
              marginBottom: "1rem",
              cursor: "pointer",
            }}
          >
            FORGOT YOUR PASSWORD?
          </p>

          <button
            type="submit"
            disabled={loading}
            style={{
              width: "100%",
              padding: "0.8rem",
              backgroundColor: "#3B8BDB",
              color: "white",
              border: "none",
              borderRadius: "8px",
              fontSize: "1rem",
              fontWeight: "bold",
              cursor: "pointer",
              boxShadow: "0 2px 4px rgba(0,0,0,0.2)",
            }}
          >
            {loading ? "Accesso in corso..." : "Log in"}
          </button>
        </form>

        {error && (
          <p style={{ color: "red", marginTop: "1rem", fontSize: "0.9rem" }}>
            {error}
          </p>
        )}

        <p
          style={{
            marginTop: "1.5rem",
            fontSize: "0.85rem",
            color: "#3B4D65",
          }}
        >
          NO ACCOUNT?{" "}
          <span
            style={{
              color: "#3B8BDB",
              fontWeight: "bold",
              cursor: "pointer",
            }}
            onClick={() => navigate("/signup")}
          >
            SIGN UP
          </span>
        </p>
      </div>
    </div>
  );
}
