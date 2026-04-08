// Importiamo strumenti da React Router:
// - Link → per creare link che NON ricaricano la pagina
// - useNavigate → per fare redirect tramite codice (es: navigate("/login"))
import { Link, useNavigate } from "react-router-dom";

// Importiamo il nostro AuthContext.
// useAuth ci dà accesso a:
// - isAuthenticated → dice se l'utente è loggato
// - logout → funzione che cancella i token e resetta l'utente
import { useAuth } from "../context/AuthContext";

export default function Header() {
  // Hook che ci permette di navigare tra le pagine
  const navigate = useNavigate();

  // Recuperiamo dal contesto:
  // - isAuthenticated → true se abbiamo accessToken valido
  // - logout → funzione per fare logout globale
  const { isAuthenticated, logout, user } = useAuth();

  const initial =
    (user?.first_name?.trim()?.[0] ||
      user?.username?.trim()?.[0] ||
      user?.email?.trim()?.[0] ||
      "U"
    ).toUpperCase();


  function handleLogoClick(e) {
    e.preventDefault();

    if (isAuthenticated) {
      // Torna alla Home ma in modalità "Entra"
      navigate("/", { state: { mode: "enter" } });
    } else {
      // Home normale
      navigate("/");
    }
  }

  return (
    <header
      style={{
        position: "sticky", // chiave
        top: 0,              // resta in alto
        zIndex: 1000,        // sopra al contenuto
        height: "90px",                 // spessore header
        backgroundColor: "#f2f2f2",
        borderBottom: "1px solid rgba(0,0,0,0.08)",
        display: "flex",
        alignItems: "center",
        padding: "0 48px",
      }}
    >
      <nav
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "16px",
        }}
      >
        {/* SINISTRA: Logo + Dashboard */}
        <div style={{ display: "flex", alignItems: "center", gap: "14px" }}>
          {/* Logo cliccabile */}
          <a
            href="/"
            onClick={handleLogoClick}
            style={{
              display: "flex",
              alignItems: "center",
              textDecoration: "none",
            }}
          >
            <img
              src="/icons/logo.png"
              alt="AIutami"
              style={{
                height: "80px",
                width: "80px",
                objectFit: "contain",
              }}
            />
          </a>

          {/* Label Dashboard accanto al logo (solo se loggato) */}
          {isAuthenticated && (
            <Link
              to="/dashboard"
              style={{
                textDecoration: "none",
                color: "#1E2833",
                fontWeight: "800",
                fontSize: "1.25rem",
                padding: "8px 10px",
                borderRadius: "10px",
              }}
            >
              Dashboard
            </Link>
          )}
        </div>

        {/* DESTRA: Profilo (icona)*/}
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          {isAuthenticated ? (
            <>
              {/* Icona profilo */}
              <div
                onClick={() => navigate("/me")}
                title="Profilo"
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = "#e6e6e6";
                  e.currentTarget.style.transform = "scale(1.05)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = "#f2f2f2";
                  e.currentTarget.style.transform = "scale(1)";
                }}
                style={{
                  width: "54px",
                  height: "54px",
                  borderRadius: "50%",
                  backgroundColor: "#ffffff",
                  border: "2px solid #858585",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  cursor: "pointer",
                  userSelect: "none",

                  // ANIMAZIONI
                  transition: "background-color 0.15s ease, transform 0.1s ease",
                }}
              >
                <span
                  style={{
                    fontSize: "1.75rem",
                    fontWeight: "700",
                    color: "#000000",
                    lineHeight: 1,
                  }}
                >
                  {initial}
                </span>
              </div>
            </>
          ) : (
            <>
              {/* Se non loggato: Login/Signup */}
              <Link
                to="/login"
                style={{
                  textDecoration: "none",
                  color: "#1E2833",
                  fontWeight: "700",
                  padding: "8px 10px",
                  borderRadius: "10px",
                }}
              >
                Login
              </Link>
              <Link
                to="/signup"
                style={{
                  textDecoration: "none",
                  color: "white",
                  backgroundColor: "#3B8BDB",
                  fontWeight: "800",
                  padding: "10px 14px",
                  borderRadius: "12px",
                }}
              >
                Signup
              </Link>
            </>
          )}
        </div>
      </nav>
    </header>
  );
}
