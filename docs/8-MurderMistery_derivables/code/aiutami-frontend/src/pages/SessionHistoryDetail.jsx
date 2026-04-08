// src/pages/SessionHistoryDetail.jsx

import { useEffect, useMemo, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api from "../api/axiosConfig";

function minutesBetween(start, end) {
  if (!start || !end) return null;
  const ms = new Date(end) - new Date(start);
  if (Number.isNaN(ms)) return null;
  return Math.max(0, Math.round(ms / 60000));
}

function formatDateTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("it-IT", {
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
}

function safeTitle(s) {
  const t = s?.title?.trim();
  return t ? t : "Sessione senza titolo";
}

function pickBestDateIso(s) {
  return s?.ended_at || s?.conclusion_at || s?.started_at || s?.created_at || null;
}

export default function SessionHistoryDetail() {
  const { sessionId } = useParams();
  const navigate = useNavigate();

  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState(null);
  const [downloading, setDownloading] = useState(false);

  const durationMin = useMemo(() => {
    const end = session?.ended_at || session?.conclusion_at || null;
    return minutesBetween(session?.started_at, end);
  }, [session]);

  const dateIso = useMemo(() => pickBestDateIso(session), [session]);

  const contextLabel = useMemo(() => {
    if (!session) return "—";
    if (session?.context_label) return session.context_label;
    if (session?.context) return String(session.context).replaceAll("_", " ").toLowerCase();
    return "—";
  }, [session]);

  useEffect(() => {
    let mounted = true;

    async function load() {
      setLoading(true);
      setErrorMsg(null);

      try {
        const s = await api.get(`/sessions/${sessionId}/`);
        if (!mounted) return;
        setSession(s.data);
      } catch (e) {
        console.error("Errore dettaglio storico:", e);
        if (!mounted) return;
        setErrorMsg("Impossibile caricare i dettagli della sessione. Riprova tra poco.");
        setSession(null);
      } finally {
        if (mounted) setLoading(false);
      }
    }

    load();
    return () => {
      mounted = false;
    };
  }, [sessionId]);

  async function downloadPdf() {
    try {
      setDownloading(true);

      const res = await api.get(`/sessions/${sessionId}/report/`, {
        responseType: "blob",
      });

      const blob = new Blob([res.data], { type: "application/pdf" });
      const url = window.URL.createObjectURL(blob);

      const a = document.createElement("a");
      a.href = url;
      a.download = `report-${sessionId}.pdf`;
      document.body.appendChild(a);
      a.click();

      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      if (err?.response?.status === 409) {
        alert("Il report è disponibile solo per sessioni concluse.");
        return;
      }
      if (err?.response?.status === 403) {
        alert("Non sei autorizzato a scaricare questo report.");
        return;
      }
      console.error("Errore download PDF:", err);
      alert("Errore durante il download del PDF.");
    } finally {
      setDownloading(false);
    }
  }

  if (loading) {
    return (
      <div
        style={{
          minHeight: "100vh",
          background: "#E7EEF5",
          padding: "46px 18px",
          fontFamily: "'Inter', system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif",
          color: "#0f172a",
        }}
      >
        <div style={{ maxWidth: 980, margin: "0 auto" }}>
          <div
            style={{
              background: "white",
              borderRadius: 18,
              padding: "18px 18px",
              boxShadow: "0 6px 22px rgba(0,0,0,0.12)",
              border: "1px solid #D7E0EA",
            }}
          >
            Caricamento…
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#E7EEF5",
        padding: "46px 18px",
        fontFamily: "'Inter', system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif",
        color: "#0f172a",
      }}
    >
      <div style={{ maxWidth: 980, margin: "0 auto" }}>
        <button
          onClick={() => navigate("/history")}
          style={{
            marginBottom: 18,
            cursor: "pointer",
            border: "none",
            background: "transparent",
            fontWeight: 900,
            color: "#1E3A8A",
          }}
        >
          ← Indietro
        </button>

        <div style={{ marginBottom: 18 }}>
          <h1 style={{ margin: 0, fontSize: "2.0rem", fontWeight: 900, color: "#2D4B71" }}>
            Dettagli sessione
          </h1>
          <p style={{ margin: "8px 0 0 0", color: "#475569", fontWeight: 600 }}>
            Visualizza informazioni e scarica il riepilogo PDF
          </p>
        </div>

        {errorMsg && (
          <div
            style={{
              background: "#FEE2E2",
              border: "1px solid #FCA5A5",
              color: "#7F1D1D",
              padding: "12px 14px",
              borderRadius: 14,
              fontWeight: 800,
              boxShadow: "0 4px 14px rgba(0,0,0,0.10)",
              marginBottom: 16,
            }}
          >
            {errorMsg}
          </div>
        )}

        {!errorMsg && !session && (
          <div
            style={{
              background: "white",
              borderRadius: 18,
              padding: "22px 18px",
              boxShadow: "0 6px 22px rgba(0,0,0,0.12)",
              border: "1px solid #D7E0EA",
              color: "#334155",
              fontWeight: 700,
            }}
          >
            Sessione non trovata.
          </div>
        )}

        {!errorMsg && session && (
          <div
            style={{
              background: "white",
              borderRadius: 18,
              padding: 18,
              border: "1px solid #D7E0EA",
              boxShadow: "0 8px 26px rgba(0,0,0,0.10)",
            }}
          >
            <div style={{ fontWeight: 950, fontSize: "1.25rem", color: "#0f172a" }}>
              {safeTitle(session)}
            </div>

            <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "6px 10px",
                  borderRadius: 999,
                  background: "#EAF2FF",
                  border: "1px solid #BFD6FF",
                  color: "#1E3A8A",
                  fontWeight: 900,
                  fontSize: "0.9rem",
                  textTransform: "capitalize",
                }}
              >
                {contextLabel}
              </span>

              <span style={{ color: "#475569", fontWeight: 800 }}>
                {formatDateTime(dateIso)}
              </span>

            
            </div>

            <div
              style={{
                marginTop: 18,
                lineHeight: 1.8,
                color: "#0f172a",
                fontWeight: 750,
              }}
            >
              <div>Inizio – {formatDateTime(session?.started_at)}</div>
              <div>Fine – {formatDateTime(session?.ended_at || session?.conclusion_at)}</div>
              <div>Durata – {durationMin != null ? `${durationMin} minuti` : "—"}</div>
              <div>
                Partecipanti –{" "}
                {typeof session?.participants_count === "number"
                  ? session.participants_count
                  : "—"}
              </div>
            </div>

            <div style={{ marginTop: 18, display: "flex", justifyContent: "center" }}>
              <button
                onClick={downloadPdf}
                disabled={downloading}
                style={{
                  padding: "12px 18px",
                  borderRadius: 12,
                  border: "2px solid #2D6CDF",
                  background: downloading ? "#EAF2FF" : "white",
                  cursor: downloading ? "not-allowed" : "pointer",
                  fontWeight: 900,
                  color: "#1E3A8A",
                  boxShadow: "0 4px 14px rgba(45,108,223,0.10)",
                  display: "flex",
                  gap: 10,
                  alignItems: "center",
                }}
                onMouseEnter={(e) => {
                  if (downloading) return;
                  e.currentTarget.style.background = "#2D6CDF";
                  e.currentTarget.style.color = "white";
                }}
                onMouseLeave={(e) => {
                  if (downloading) return;
                  e.currentTarget.style.background = "white";
                  e.currentTarget.style.color = "#1E3A8A";
                }}
              >
                📄 {downloading ? "Scaricamento…" : "Scarica riepilogo (PDF)"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
