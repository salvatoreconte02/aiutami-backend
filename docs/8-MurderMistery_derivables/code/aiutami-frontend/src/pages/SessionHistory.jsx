// src/pages/SessionHistory.jsx

import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../api/axiosConfig";

const MAX_ITEMS = 25;

const CONTEXT_LABELS = {
};

function getContextLabel(s) {
  if (s?.context_label) return s.context_label;
  if (s?.context && CONTEXT_LABELS[s.context]) return CONTEXT_LABELS[s.context];
  if (s?.context) return String(s.context).replaceAll("_", " ").toLowerCase();
  return "—";
}

function pickBestDateIso(s) {
  return s?.ended_at || s?.conclusion_at || s?.started_at || s?.created_at || null;
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

export default function SessionHistory() {
  const navigate = useNavigate();

  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState(null);

  // progress per il caricamento dei dettagli
  const [progress, setProgress] = useState({ done: 0, total: 0 });

  useEffect(() => {
    let mounted = true;

    async function load() {
      setLoading(true);
      setErrorMsg(null);
      setProgress({ done: 0, total: 0 });

      try {
        const res = await api.get("/sessions/mine/");
        const list = Array.isArray(res.data) ? res.data : [];

        // chiuse + ordina per data desc
        const closed = list
          .filter((s) => s?.state === "CLOSED")
          .sort((a, b) => {
            const da = new Date(pickBestDateIso(a) || 0).getTime();
            const db = new Date(pickBestDateIso(b) || 0).getTime();
            return db - da;
          })
          .slice(0, MAX_ITEMS);

        if (!mounted) return;

        setProgress({ done: 0, total: closed.length });

        // Arricchisco ogni sessione usando lo stesso endpoint del dettaglio:
        // /sessions/:id/ -> contiene context/context_label ecc.
        const enriched = await Promise.all(
          closed.map(async (s, idx) => {
            try {
              const detail = await api.get(`/sessions/${s.id}/`);
              const merged = { ...s, ...detail.data };
              return merged;
            } catch (e) {
              console.warn("[HISTORY] dettaglio non disponibile per", s?.id, e);
              return s; // fallback ai dati base
            } finally {
              if (mounted) {
                setProgress((p) => ({ ...p, done: Math.min(p.total, idx + 1) }));
              }
            }
          })
        );

        // riordina dopo enrich usando best date reale
        enriched.sort((a, b) => {
          const da = new Date(pickBestDateIso(a) || 0).getTime();
          const db = new Date(pickBestDateIso(b) || 0).getTime();
          return db - da;
        });

        if (mounted) setItems(enriched);
      } catch (e) {
        console.error("Errore storico:", e);
        if (mounted) setErrorMsg("Impossibile caricare lo storico. Riprova tra poco.");
      } finally {
        if (mounted) setLoading(false);
      }
    }

    load();
    return () => {
      mounted = false;
    };
  }, []);

  const empty = !loading && !errorMsg && items.length === 0;

  const subtitle = useMemo(() => {
    if (loading) {
      if (progress.total > 0) return `Caricamento in corso… (${progress.done}/${progress.total})`;
      return "Caricamento in corso…";
    }
    if (errorMsg) return "Si è verificato un errore.";
    return "Visualizza un elenco delle tue sessioni concluse";
  }, [loading, errorMsg, progress.done, progress.total]);

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
        <div style={{ marginBottom: 18 }}>
          <h1 style={{ margin: 0, fontSize: "2.2rem", fontWeight: 900, color: "#2D4B71" }}>
            Storico delle sessioni
          </h1>
          <p style={{ margin: "8px 0 0 0", color: "#475569", fontWeight: 600 }}>
            {subtitle}
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

        {loading && (
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
        )}

        {empty && (
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
            Nessuna sessione conclusa trovata.
          </div>
        )}

        {!loading && !errorMsg && items.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 14 }}>
            {items.map((s) => {
              const dateIso = pickBestDateIso(s);
              const context = getContextLabel(s);

              return (
                <div
                  key={s.id}
                  style={{
                    background: "white",
                    borderRadius: 18,
                    padding: 16,
                    border: "1px solid #D7E0EA",
                    boxShadow: "0 8px 26px rgba(0,0,0,0.10)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 16,
                  }}
                >
                  <div style={{ minWidth: 0 }}>
                    <div
                      style={{
                        fontWeight: 950,
                        fontSize: "1.1rem",
                        color: "#0f172a",
                        marginBottom: 6,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                        maxWidth: 640,
                      }}
                      title={safeTitle(s)}
                    >
                      {safeTitle(s)}
                    </div>

                    <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
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
                        {context}
                      </span>

                      <span style={{ color: "#475569", fontWeight: 800 }}>
                        {formatDateTime(dateIso)}
                      </span>
                    </div>
                  </div>

                  <button
                    onClick={() => navigate(`/history/${s.id}`)}
                    style={{
                      padding: "10px 16px",
                      borderRadius: 12,
                      border: "2px solid #2D6CDF",
                      background: "white",
                      cursor: "pointer",
                      fontWeight: 900,
                      color: "#1E3A8A",
                      boxShadow: "0 4px 14px rgba(45,108,223,0.10)",
                      flexShrink: 0,
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = "#2D6CDF";
                      e.currentTarget.style.color = "white";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = "white";
                      e.currentTarget.style.color = "#1E3A8A";
                    }}
                  >
                    Dettagli
                  </button>
                </div>
              );
            })}
          </div>
        )}

        {!loading && !errorMsg && items.length >= MAX_ITEMS && (
          <div style={{ marginTop: 14, color: "#475569", fontWeight: 700 }}>
            Stai visualizzando le ultime {MAX_ITEMS} sessioni concluse.
          </div>
        )}
      </div>
    </div>
  );
}
