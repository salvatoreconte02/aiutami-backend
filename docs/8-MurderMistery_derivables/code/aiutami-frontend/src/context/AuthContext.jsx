// src/context/AuthContext.jsx
import React, { createContext, useContext, useState, useEffect } from "react";
import { login as apiLogin } from "../api/auth";
import api from "../api/axiosConfig";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  // token caricati inizialmente da localStorage
  const [authTokens, setAuthTokens] = useState(() => {
    const access = localStorage.getItem("accessToken");
    const refresh = localStorage.getItem("refreshToken");
    return access && refresh ? { access, refresh } : null;
  });

  const [user, setUser] = useState(null);
  const isAuthenticated = !!authTokens?.access;

  // login: chiama l'API, salva token in stato + localStorage
  const login = async (username, password) => {
    const data = await apiLogin(username, password); // { access, refresh }

    setAuthTokens(data);
    localStorage.setItem("accessToken", data.access);
    localStorage.setItem("refreshToken", data.refresh);

    return data;
  };

  // logout: pulisce tutto
  const logout = () => {
    setAuthTokens(null);
    setUser(null);
    localStorage.removeItem("accessToken");
    localStorage.removeItem("refreshToken");
  };

  // carica i dati utente se abbiamo un token valido
  useEffect(() => {
    if (!authTokens?.access) {
      setUser(null);
      return;
    }

    (async () => {
      try {
        // impostiamo il token nell'header Authorization
        // per tutte le future richieste
        const res = await api.get("/accounts/me/");
        setUser(res.data);
      } catch (err) {
        console.error("Errore nel recupero dell'utente:", err);
        // se il token non è più valido, effettuiamo logout
        logout();
      }
    })();
  }, [authTokens?.access]);

  const value = {
    authTokens,
    user,
    isAuthenticated,
    login,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// comodo hook per usare il contesto
export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
