// src/pages/NewSessionDetails.jsx


import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import api from "../api/axiosConfig";

export default function NewSessionDetails() {
  const navigate = useNavigate();
  const location = useLocation();

  // Arriva direttamente da STEP 1 (ossia NewSessionContext) con questi dati...
  const context = location.state?.context;
  const min = location.state?.min;
  const max = location.state?.max;

  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  // -------------------------------------------------------------
  // CREAZIONE SESSIONE (unica vera parte logica dello step 2)
  // -------------------------------------------------------------
  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      // 1️. CREA SESSIONE IN LOBBY
      const createRes = await api.post("/sessions/", {
        context: context, 
        title: title,
        notes: notes || null,

        // Altri contesti → min/max passati dallo step precedente
        // Murder Mystery → backend li ignora e forza 3/3
        min_size: min,
        max_size: max,
      });

      const id = createRes.data.id;

      // 2️. CREA INVITO (solo host)
      const inviteRes = await api.post(`/sessions/${id}/invitations/`);
      const token = inviteRes.data.token;

      // 3️. REDIRECT ALLA LOBBY
      navigate(`/session/${id}/lobby`, {
        state: { inviteToken: token },
      });

    } catch (err) {
      console.error(err);
      const msg = err?.response?.data?.detail || "Errore nella creazione della sessione.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  // Arrivo scorretto senza Step1
  if (!context) {
    return <h2>Errore: contesto mancante. Torna indietro.</h2>;
  }

  return (
    <div style={{ maxWidth: "700px", margin: "0 auto", padding: "2rem" }}>
      <h1
        style={{
          textAlign: "center",
          fontSize: "2rem",
          fontWeight: "bold",
        }}
      >
        Dettagli della sessione
      </h1>

      <p style={{ textAlign: "center" }}>
        Contesto scelto: <b>{context}</b>
      </p>

      <form onSubmit={handleSubmit} style={{ marginTop: "2rem" }}>
        {/* Nome sessione */}
        <label style={{ display: "block", marginBottom: "0.5rem" }}>
          Nome della sessione
        </label>
        <input
          type="text"
          placeholder="Inserisci un nome"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
          style={{
            width: "100%",
            padding: "0.8rem",
            borderRadius: "8px",
            border: "1px solid #ccc",
            marginBottom: "1.5rem",
          }}
        />

        {/* Note */}
        <label style={{ display: "block", marginBottom: "0.5rem" }}>
          Note per il moderatore (opzionale)
        </label>
        <textarea
          placeholder="Aggiungi qualche indicazione o regola (opzionale)"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={5}
          style={{
            width: "100%",
            padding: "0.8rem",
            borderRadius: "8px",
            border: "1px solid #ccc",
            marginBottom: "2rem",
          }}
        />

        {error && (
          <p style={{ color: "red", marginBottom: "1rem" }}>{error}</p>
        )}

        <button
          type="submit"
          disabled={loading}
          style={{
            width: "100%",
            backgroundColor: "#3B6BA5",
            color: "white",
            fontSize: "1rem",
            padding: "0.9rem",
            border: "none",
            borderRadius: "8px",
            cursor: "pointer",
          }}
        >
          {loading ? "Creazione..." : "Crea sessione"}
        </button>
      </form>
    </div>
  );
}
