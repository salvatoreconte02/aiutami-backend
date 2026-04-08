// src/api/axiosConfig.js

/*
====================================================================
   AXIOS CONFIG – GESTIONE TOKEN, REFRESH E RETRY DELLE RICHIESTE
====================================================================

Questo file gestisce l’autenticazione lato client.
Qui avvengono automaticamente tre cose fondamentali:

1. Viene aggiunto l'accessToken (JWT) a ogni richiesta
2. Se il token è scaduto, viene richiesto un nuovo accessToken usando il refreshToken
3. La richiesta originale viene ripetuta automaticamente dopo il refresh

*/

import axios from "axios";

// URL base del backend
const BASE_URL =
  import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000/api";

// Istanza principale di Axios
const api = axios.create({
  baseURL: BASE_URL,
  withCredentials: false, // Usando JWT, non servono cookie HTTPOnly
});

/* ====================================================================
   1. REQUEST INTERCEPTOR
   --------------------------------------------------------------------
   Ogni volta che il frontend fa una richiesta (GET/POST/PUT/DELETE...),
   questo intercettore viene eseguito PRIMA dell’invio della richiesta.

   In questo modo possiamo:
   - Aggiungere il token JWT al header Authorization
   - Evitare di doverlo fare manualmente in ogni chiamata API
==================================================================== */

api.interceptors.request.use(
  (config) => {
    // Leggiamo l'accessToken salvato nel localStorage dal login
    const accessToken = localStorage.getItem("accessToken");

    // Se esiste, lo aggiungiamo all’header
    if (accessToken) {
      config.headers.Authorization = `Bearer ${accessToken}`;
    }

    return config; // Continuiamo con la richiesta originale
  },
  (error) => Promise.reject(error)
);

/* ====================================================================
   2. RESPONSE INTERCEPTOR
   --------------------------------------------------------------------
   Questo intercettore gestisce tutte le RISPOSTE del backend.

   - Se il backend risponde 401 (Unauthorized),
     significa che l'accessToken è scaduto.

   Allora:
   ➜ proviamo a richiedere un nuovo accessToken tramite refreshToken
   ➜ aggiorniamo il localStorage
   ➜ ripetiamo automaticamente la richiesta che era fallita
==================================================================== */

api.interceptors.response.use(
  (response) => response, // Risposta OK → passiamo oltre

  // Gestione errori dal backend
  async (error) => {
    const originalRequest = error.config;

    /* ---------------------------------------------------------------
       Caso 401 (Unauthorized) → Token scaduto
       - Non vogliamo fare refresh più volte → controlliamo _retry
    ---------------------------------------------------------------- */
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true; // Flag per evitare loop infiniti

      // Recuperiamo il refreshToken dal browser
      const refreshToken = localStorage.getItem("refreshToken");

      // Se NON c’è refreshToken → logout immediato
      if (!refreshToken) {
        localStorage.removeItem("accessToken");
        return Promise.reject(error);
      }

      try {
        /* -------------------------------------------------------------
           2A. Richiediamo un nuovo accessToken
           -------------------------------------------------------------
           Endpoint Django Rest Framework SimpleJWT:
           POST /auth/token/refresh/
           body: { refresh: "<refresh_token>" }
        ------------------------------------------------------------- */
        const res = await axios.post(`${BASE_URL}/auth/token/refresh/`, {
          refresh: refreshToken,
        });

        const newAccess = res.data.access;

        // Salviamo il nuovo accessToken nel browser
        localStorage.setItem("accessToken", newAccess);

        /* -------------------------------------------------------------
           2B. Ripetiamo la richiesta originale:
           - aggiorniamo l'header Authorization
           - reinoltriamo la richiesta tramite api(originalRequest)
        ------------------------------------------------------------- */
        originalRequest.headers.Authorization = `Bearer ${newAccess}`;
        return api(originalRequest);
      } catch (refreshError) {
        /*
        ==================================================================
        2C. FALLIMENTO DEL REFRESH TOKEN
        ------------------------------------------------------------------
        Questo significa che il refreshToken è scaduto o non è più valido.
          Possibili cause:
        - l'utente ha cambiato password
        - il refresh token è scaduto
        - è stato invalidato lato server
        - qualcuno ha cancellato i token dal browser

        Azione corretta:
        ➜ rimuovere entrambi i token
        ➜ reindirizzare alla pagina di login
        ==================================================================
        */
        console.error("⚠️ Refresh token non valido o scaduto:", refreshError);

        localStorage.removeItem("accessToken");
        localStorage.removeItem("refreshToken");

        // Redirect forzato → l’app reindirizza al login
        window.location.href = "/login";
      }
    }

    // Altri errori → passiamo l'errore ai componenti React
    return Promise.reject(error);
  }
);

/*
====================================================================
   EXPORT
====================================================================
*/
export default api;