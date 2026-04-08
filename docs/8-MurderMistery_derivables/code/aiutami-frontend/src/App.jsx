// src/App.jsx

import { BrowserRouter, Routes, Route } from "react-router-dom";

import Header from "./components/Header";
import Footer from "./components/Footer";
import RequireAuth from "./components/RequireAuth";

// PAGINE PUBBLICHE
import Home from "./pages/Home";
import Login from "./pages/Login";
import Signup from "./pages/Signup";

// PAGINE PROTETTE
import Dashboard from "./pages/Dashboard";
import Me from "./pages/Me";

// CREAZIONE SESSIONE
import NewSessionContext from "./pages/NewSessionContext";
import NewSessionDetails from "./pages/NewSessionDetails";
import JoinSessionByLink from "./pages/JoinSessionByLink";

// LOBBY
import SessionLobby from "./pages/SessionLobby";

// SESSIONE ATTIVA
import SessionActive from "./pages/SessionActive";

// SESSIONE — FASE DI CONCLUSIONE (Murder Mystery)
// import SessionConclusion from "./pages/SessionConclusion";

// STORICO
import SessionHistory from "./pages/SessionHistory";
import SessionHistoryDetail from "./pages/SessionHistoryDetail";

export default function App() {
  return (
    <BrowserRouter>

      {/* HEADER — sempre visibile */}
      <Header />

      {/* CONTENITORE PRINCIPALE DELLE PAGINE */}
      <div style={{ padding: "20px", minHeight: "calc(100vh - 150px)" }}>
        <Routes>

          {/* ---------------------------- */}
          {/*           PUBBLICHE          */}
          {/* ---------------------------- */}
          <Route path="/" element={<Home />} />
          <Route path="/home" element={<Home />} />
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />

          {/* ---------------------------- */}
          {/*           PROTETTE           */}
          {/* ---------------------------- */}

          {/* Dashboard utente */}
          <Route
            path="/dashboard"
            element={
              <RequireAuth>
                <Dashboard />
              </RequireAuth>
            }
          />

          {/* Profilo utente */}
          <Route
            path="/me"
            element={
              <RequireAuth>
                <Me />
              </RequireAuth>
            }
          />

          {/* ---------------------------- */}
          {/*     CREAZIONE SESSIONE       */}
          {/* ---------------------------- */}

          {/* Step 1: scelta contesto */}
          <Route
            path="/new-session/context"
            element={
              <RequireAuth>
                <NewSessionContext />
              </RequireAuth>
            }
          />

          {/* Step 2: dettagli sessione */}
          <Route
            path="/new-session/details"
            element={
              <RequireAuth>
                <NewSessionDetails />
              </RequireAuth>
            }
          />

          {/* Unirsi tramite link (?invite=) */}
          <Route
            path="/join-session"
            element={
              <RequireAuth>
                <JoinSessionByLink />
              </RequireAuth>
            }
          />

          {/* ---------------------------- */}
          {/*             LOBBY            */}
          {/* ---------------------------- */}
          <Route
            path="/session/:sessionId/lobby"
            element={
              <RequireAuth>
                <SessionLobby />
              </RequireAuth>
            }
          />

          {/* ---------------------------- */}
          {/*         SESSIONE ATTIVA      */}
          {/* ---------------------------- */}
          <Route
            path="/session/:sessionId/active"
            element={
              <RequireAuth>
                <SessionActive />
              </RequireAuth>
            }
          />

          <Route
            path="/history"
            element={
              <RequireAuth>
                <SessionHistory />
              </RequireAuth>
            }
          />
          <Route
            path="/history/:sessionId"
            element={
              <RequireAuth>
                <SessionHistoryDetail />
              </RequireAuth>
            }
          />

        </Routes>
      </div>

      {/* FOOTER */}
      <Footer />

    </BrowserRouter>
  );
}
