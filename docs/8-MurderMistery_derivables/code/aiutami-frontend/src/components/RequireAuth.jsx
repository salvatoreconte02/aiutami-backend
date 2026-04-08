// src/components/RequireAuth.jsx
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function RequireAuth({ children }) {
  const { isAuthenticated } = useAuth(); // <-- QUI LA DIFFERENZA VERA
  const location = useLocation();

  // Se NON sei autenticata, vai al login
  if (!isAuthenticated) {
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: location }}
      />
    );
  }

  // Se sei autenticata, mostra la pagina protetta
  return children;
}
