// src/pages/Signup.jsx

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../api/axiosConfig";

export default function Signup() {
  // Campi del form — devono corrispondere al serializer Django
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [password, setPassword] = useState("");

  // Messaggi per feedback all'utente
  const [errorMsg, setErrorMsg] = useState("");
  const [successMsg, setSuccessMsg] = useState("");

  const navigate = useNavigate();

  const labelStyle = {
    display: "block",
    marginBottom: "0.35rem",
    color: "#2C3A4B",
    fontWeight: "700",
    fontSize: "0.95rem",
  };

  const inputStyle = {
    width: "100%",
    padding: "0.85rem 0.9rem",
    borderRadius: "12px",
    border: "1px solid rgba(0,0,0,0.18)",
    outline: "none",
    fontSize: "1rem",
    backgroundColor: "white",
  };

  // Funzione principale — invia i dati al backend
  const handleSignup = async (e) => {
    e.preventDefault(); // evita refresh della pagina
    setErrorMsg("");
    setSuccessMsg("");

    try {
      // Inviamo i dati al nostro endpoint Django
      const res = await api.post("/accounts/signup/", {
        username,
        email,
        first_name: firstName,
        last_name: lastName,
        password,
      });

      console.log("✅ Registrazione riuscita:", res.data);

      // Mostriamo conferma e redirezioniamo al login
      setSuccessMsg("Registrazione completata! Ora puoi accedere.");
      setTimeout(() => navigate("/login"), 1500);
    } catch (err) {
      console.error("❌ Errore di signup:", err);

      // Gestione errori specifici del backend Django
      if (err.response?.data?.detail) {
        // Es. "Email già in uso", "Username già in uso"
        setErrorMsg(err.response.data.detail);
      } else if (err.response?.data?.password) {
        // Errore della password non valida dal serializer
        setErrorMsg("La password deve contenere almeno 8 caratteri.");
      } else if (err.response?.status === 400) {
        // Errori generici di validazione lato backend
        setErrorMsg("Username o email già in uso.");
      } else {
        // Fallback: errore sconosciuto
        setErrorMsg("Errore durante la registrazione. Riprova.");
      }
    }
  };

  return (
    <div
      style={{
        minHeight: "calc(100vh - 72px)",
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        padding: "3rem 1rem",
        background: "linear-gradient(180deg, #F7F8FA 0%, #FFFFFF 70%)",
        fontFamily: "Arial, sans-serif",
      }}
    >
      <div style={{ width: "100%", maxWidth: "520px" }}>
        <div style={{ marginBottom: "1.25rem" }}>
          <h1 style={{ margin: 0, fontSize: "2.2rem", letterSpacing: "-0.02em" }}>
            Registrazione
          </h1>
          <p style={{ margin: "0.5rem 0 0", color: "#5B6573", fontSize: "1rem" }}>
            Crea il tuo account per accedere ad AIutami.
          </p>
        </div>

        <div
          style={{
            backgroundColor: "white",
            borderRadius: "18px",
            padding: "1.6rem",
            border: "1px solid rgba(0,0,0,0.08)",
            boxShadow: "0 14px 30px rgba(0,0,0,0.08)",
          }}
        >
          {/* 🔹 Form di signup */}
          <form onSubmit={handleSignup}>
            {/* Nome + Cognome */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                gap: "0.9rem",
                marginBottom: "1rem",
              }}
            >
              <div>
                <label style={labelStyle}>Nome</label>
                <input
                  type="text"
                  value={firstName}
                  onChange={(e) => setFirstName(e.target.value)}
                  required
                  placeholder="Mario"
                  style={inputStyle}
                />
              </div>

              <div>
                <label style={labelStyle}>Cognome</label>
                <input
                  type="text"
                  value={lastName}
                  onChange={(e) => setLastName(e.target.value)}
                  required
                  placeholder="Rossi"
                  style={inputStyle}
                />
              </div>
            </div>

            {/* Username */}
            <div style={{ marginBottom: "1rem" }}>
              <label style={labelStyle}>Username</label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                placeholder="mrossi"
                style={inputStyle}
              />
            </div>

            {/* Email */}
            <div style={{ marginBottom: "1rem" }}>
              <label style={labelStyle}>Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                placeholder="mario.rossi@email.com"
                style={inputStyle}
              />
            </div>

            {/* Password */}
            <div style={{ marginBottom: "1.25rem" }}>
              <label style={labelStyle}>Password (min. 8 caratteri)</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
                placeholder="••••••••"
                style={inputStyle}
              />
            </div>

            {/* Bottone invio */}
            <button
              type="submit"
              style={{
                width: "100%",
                backgroundColor: "#3B8BDB",
                color: "white",
                border: "none",
                borderRadius: "12px",
                padding: "0.9rem 1rem",
                cursor: "pointer",
                fontWeight: "800",
                fontSize: "1rem",
                boxShadow: "0 6px 14px rgba(59,139,219,0.25)",
                transition: "transform 0.1s ease, background-color 0.15s ease",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = "#3277BE";
                e.currentTarget.style.transform = "scale(1.01)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = "#3B8BDB";
                e.currentTarget.style.transform = "scale(1)";
              }}
            >
              Registrati
            </button>
          </form>

          {/* Messaggi di stato */}
          {successMsg && (
            <div
              style={{
                marginTop: "1rem",
                padding: "0.85rem 1rem",
                borderRadius: "12px",
                backgroundColor: "rgba(46, 204, 113, 0.14)",
                border: "1px solid rgba(46, 204, 113, 0.30)",
                color: "#1E6B3B",
                fontWeight: "700",
                textAlign: "center",
              }}
            >
              {successMsg}
            </div>
          )}

          {errorMsg && (
            <div
              style={{
                marginTop: "1rem",
                padding: "0.85rem 1rem",
                borderRadius: "12px",
                backgroundColor: "rgba(217, 83, 79, 0.14)",
                border: "1px solid rgba(217, 83, 79, 0.30)",
                color: "#7A1F1D",
                fontWeight: "700",
                textAlign: "center",
              }}
            >
              {errorMsg}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
