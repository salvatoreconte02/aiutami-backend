// src/api/auth.js

// Questa funzione fa SOLO la chiamata al backend.
// Non salva token, non tocca lo stato globale.
// Viene usata dall'AuthContext per ottenere { access, refresh }.
import api from "./axiosConfig";

// Login → chiama il backend e restituisce i token
export async function login(username, password) {
  const res = await api.post("/auth/token/", { username, password });
  return res.data; // { access, refresh }
}

// Utility per pulire i token dal browser (se serve)
export function clearTokens() {
  localStorage.removeItem("accessToken");
  localStorage.removeItem("refreshToken");
}