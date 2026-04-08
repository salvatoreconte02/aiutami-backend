// src/pages/JoinSessionByLink.jsx

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../api/axiosConfig";

export default function JoinSessionByLink() {
  const [link, setLink] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  // Estrae il token "invite" da una stringa tipo:
  // - https://tuodominio.it/?invite=abc123
  // - http://127.0.0.1:8000/?invite=abc123
  // - ?invite=abc123
  // (opzionale: solo token nudo)
  function extractInviteToken(value) {
    const trimmed = value.trim();
    if (!trimmed) return null;

    // Caso 1: URL completo
    if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
      try {
        const url = new URL(trimmed);
        const params = new URLSearchParams(url.search);
        return params.get("invite");
      } catch {
        return null;
      }
    }

    // Caso 2: query tipo "?invite=abc123"
    if (trimmed.startsWith("?")) {
      const params = new URLSearchParams(trimmed);
      return params.get("invite");
    }

    // Caso 3: l’utente incolla solo il token
    return trimmed || null;
  }

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    const token = extractInviteToken(link);
    if (!token) {
      setError(
        "Link di invito non valido. Incolla l'URL completo che hai ricevuto dall'host."
      );
      setLoading(false);
      return;
    }

    try {
      const res = await api.post("/sessions/join_by_token/", { token });
      const sessionId = res.data.session.id;
      navigate(`/session/${sessionId}/lobby`);
    } catch (err) {
      console.error("Errore join_by_token:", err);
      const apiErrors = err.response?.data;
      const nonField = apiErrors?.non_field_errors?.[0];

      setError(
        nonField ||
          "Impossibile unirti alla sessione. Controlla che il link sia corretto o che la sessione non sia piena."
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: "600px", margin: "0 auto", fontFamily: "Arial" }}>
      <h1 style={{ textAlign: "center", marginBottom: "1rem" }}>
        Unisciti a una sessione tramite link
      </h1>

      <p style={{ textAlign: "center", marginBottom: "1.5rem" }}>
        Incolla il link di invito che hai ricevuto dall&apos;host. Puoi usare
        direttamente il link che hai copiato dal pulsante &quot;Copia
        invito&quot;.
      </p>

      <form onSubmit={handleSubmit}>
        <input
          type="text"
          placeholder="https://tuodominio.it/?invite=abc123"
          value={link}
          onChange={(e) => setLink(e.target.value)}
          style={{
            width: "100%",
            padding: "0.8rem",
            borderRadius: "8px",
            border: "1px solid #ccc",
            marginBottom: "0.8rem",
          }}
        />

        {error && (
          <p style={{ color: "red", marginBottom: "0.8rem" }}>{error}</p>
        )}

        <button
          type="submit"
          disabled={loading}
          style={{
            backgroundColor: "#3B6BA5",
            color: "white",
            border: "none",
            borderRadius: "8px",
            padding: "0.8rem 1.2rem",
            cursor: "pointer",
            width: "100%",
            fontSize: "1rem",
            fontWeight: "bold",
          }}
        >
          {loading ? "Connessione in corso..." : "Unisciti alla sessione"}
        </button>
      </form>
    </div>
  );
}
