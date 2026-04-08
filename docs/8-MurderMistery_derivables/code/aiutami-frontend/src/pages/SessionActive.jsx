// src/pages/SessionActive.jsx


import { useParams, useNavigate } from "react-router-dom";
import api from "../api/axiosConfig";
import { useAuth } from "../context/AuthContext";
import { useTurns } from "../turns/useTurns";
import { useEffect, useState, useRef } from "react";
import useSessionWS from "../sessions/useSessionWS";
import useWebRTC from "../webrtc/useWebRTC";
import { notifyOnce, sessionKey } from "../utils/notifyOnce";


// Avatar disponibili
const AVAILABLE_AVATARS = [
  "/avatars/avatar1.png",
  "/avatars/avatar2.png",
  "/avatars/avatar3.png",
  "/avatars/avatar4.png",
  "/avatars/avatar5.png",
  "/avatars/avatar6.png",
  "/avatars/avatar7.png",
  "/avatars/avatar8.png",
  "/avatars/avatar9.png",
  "/avatars/avatar10.png",
];

const ERROR_MESSAGES = {
  MIC_BUSY: "Qualcuno sta già parlando!",
  AI_SPEAKING: "Il moderatore AI sta parlando in questo momento.",
  PRIORITY_FOR_OTHER_USER: "Un'altra persona ha priorità per questo turno.",
  NOT_ALLOWED: "Non puoi prenotarti perché nessuno sta parlando.",
  ALREADY_RESERVED: "Qualcuno ha già prenotato il turno successivo.",
  CANNOT_RESERVE_WHILE_SPEAKING: "Stai già parlando, non puoi prenotarti!",
  SESSION_NOT_ACTIVE: "La sessione non è attiva.",
  SESSION_NOT_FOUND: "Sessione non trovata.",
  UNAUTHENTICATED: "Problema di autenticazione.",
};

const SUSPECTS = [
  { id: "Eddie", name: "Eddie", img: "/suspects/eddie.png" },
  { id: "Mickey", name: "Mickey", img: "/suspects/mickey.png" },
  { id: "Billy", name: "Billy", img: "/suspects/billy.png" },
];

// Hash deterministico del nome
function hashString(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) {
    h = (h * 31 + str.charCodeAt(i)) % 1000000007;
  }
  return h;
}

function getAvatar(username) {
  const index = hashString(username) % AVAILABLE_AVATARS.length;
  return AVAILABLE_AVATARS[index];
}

export default function SessionActive() {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const { user, authTokens } = useAuth();
  const accessToken = authTokens?.access || null;
  const webrtc = useWebRTC(sessionId, accessToken);


  // WS sessione: ACTIVE / CONCLUSION / CLOSED
  const { sessionEvent, voteEvent, connected } = useSessionWS(sessionId, accessToken);

  const [session, setSession] = useState(null);
  const [participants, setParticipants] = useState([]);

  const [timeLeft, setTimeLeft] = useState(null); // null = timer nascosto (parte al TIMER 25)
  const [loading, setLoading] = useState(true);

  const [showReadyConfirm, setShowReadyConfirm] = useState(false);

  // Error bubble (destra)
  const [errorBubbleMessage, setErrorBubbleMessage] = useState(null);
  const [errorBubbleKey, setErrorBubbleKey] = useState(0);
  const errorBubbleTimerRef = useRef(null);

  // System bubble (sinistra)
  const [systemBubbleMessage, setSystemBubbleMessage] = useState(null);
  const [systemBubbleKey, setSystemBubbleKey] = useState(0);
  const systemBubbleTimerRef = useRef(null);

  const moderatorRef = useRef(null);

  // Votazioni finali (CONCLUSION)
  const [myVote, setMyVote] = useState(null);
  const [voteSending, setVoteSending] = useState(false);
  const [voteError, setVoteError] = useState(null);

  const [votesCastUserIds, setVotesCastUserIds] = useState(new Set());
  const [finalResults, setFinalResults] = useState(null); // payload ALL_VOTED

  const [closingSeconds, setClosingSeconds] = useState(null);

  const didAutoCloseRef = useRef(false);
  const closeRequestedRef = useRef(false);

  // In CONCLUSION: il voto è consentito solo dopo il recap AI
  const [canVote, setCanVote] = useState(false);

  // In CONCLUSION sblocchiamo solo dopo aver visto partire il recap AI
  const [conclusionRecapStarted, setConclusionRecapStarted] = useState(false);

  // Fallback (join tardivo / evento perso) ma solo per il recap AI in CONCLUSION, non per gli altri eventi di sessione
  const recapFallbackTimerRef = useRef(null);

  // Anti-race: contatore eventi TURN e "checkpoint" quando entriamo in CONCLUSION
  const turnSeqRef = useRef(0);
  const conclusionTurnSeqRef = useRef(null);



  // Turni WS
  const {
    state: turnState,
    lastEvent,
    requestSpeak,
    endSpeak,
    requestReserve,
    clearReserve,
  } = useTurns(sessionId, user, accessToken);

  const [aiTurnActive, setAiTurnActive] = useState(false);

  const aiSpeaking =
    turnState?.state === "AI_SPEAKING" ||
    turnState?.state === "AI_INTRODUCING" ||
    aiTurnActive;

  const isMeSpeaker =
    !aiSpeaking &&
    turnState?.state === "HUMAN_SPEAKING" &&
    turnState?.current_speaker_user_id === user?.id;

  const myReservation = turnState.reservation_user_id === user?.id;

  // Host detection robusta: in CONCLUSION a volte session.me non c'è
  const isHost =
    session?.me?.role === "HOST" ||
    String(session?.host?.id) === String(user?.id);


  useEffect(() => {
    if (!lastEvent) return;

    // Ogni evento TURN aumenta di 1
    turnSeqRef.current += 1;
    const seq = turnSeqRef.current;

    if (lastEvent.type === "turns.ai_started") {
      setAiTurnActive(true);

      // Valido solo se l'evento è successivo all'ingresso in CONCLUSION
      if (
        session?.state === "CONCLUSION" &&
        conclusionTurnSeqRef.current != null &&
        seq > conclusionTurnSeqRef.current
      ) {
        setConclusionRecapStarted(true);
        setCanVote(false); // riblocca sicuro
      }
    }

    if (lastEvent.type === "turns.ai_ended") {
      setAiTurnActive(false);

      // Sblocca SOLO se:
      // - siamo in CONCLUSION
      // - recap partito in CONCLUSION
      // - evento successivo all'ingresso in CONCLUSION
      if (
        session?.state === "CONCLUSION" &&
        conclusionRecapStarted &&
        conclusionTurnSeqRef.current != null &&
        seq > conclusionTurnSeqRef.current
      ) {
        setCanVote(true);
      }
    }
  }, [lastEvent, session?.state, conclusionRecapStarted]);





  // Per rilevare scadenza prenotazione
  const prevReservationUserIdRef = useRef(null);
  const reservationUsedRef = useRef(false);

  // Per mostrare l'intro bubble una sola volta
  const didShowIntroBubbleRef = useRef(false);

  // ----------------------------------------------------
  // LOAD iniziale
  // ----------------------------------------------------
  useEffect(() => {
    async function load() {
      try {
        const s = await api.get(`/sessions/${sessionId}/`);
        const p = await api.get(`/sessions/${sessionId}/participants/`);

        const serverState = s.data.state;

        if (serverState === "LOBBY") {
          navigate(`/session/${sessionId}/lobby`, { replace: true });
          return;
        }

        if (serverState === "CONCLUSION") {
          // nel caso in cui lo stato è CONCLUSION non fare niente (evito redirect pagina)
          //navigate(`/session/${sessionId}/conclusion`, { replace: true });
          //return;
        }

        if (serverState === "CLOSED") {
          navigate("/dashboard", { replace: true });
          return;
        }

        if (serverState !== "ACTIVE") {
          navigate("/dashboard", { replace: true });
          return;
        }

        setSession(s.data);
        setParticipants(p.data);
      } catch (err) {
        console.error("Errore caricamento iniziale:", err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [sessionId, navigate]);



  const formatTime = (sec) => {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  };

  // ----------------------------------------------------
  // Countdown timer UI (solo quando timeLeft è attivo)
  // ----------------------------------------------------
  useEffect(() => {
    if (timeLeft == null) return;

    const t = setInterval(() => {
      setTimeLeft((x) => (x > 0 ? x - 1 : 0));
    }, 1000);

    return () => clearInterval(t);
  }, [timeLeft]);

  // ----------------------------------------------------
  // WS Sessione
  // ----------------------------------------------------
  useEffect(() => {
    if (!sessionEvent) return;

    async function handleSessionEvent() {
      let ev = sessionEvent;

      // NORMALIZZA new_state → state (subito, senza HTTP)
      if (!ev.state && ev.new_state) {
        ev = { ...ev, state: ev.new_state };
      }

      // Fallback HTTP SOLO se ancora non abbiamo state
      if (ev.__partial && !ev.state) {
        try {
          const s = await api.get(`/sessions/${sessionId}/`);
          ev = s.data;
        } catch (err) {
          console.error("[ACTIVE] Fallback HTTP session failed:", err);
          return;
        }
      }
      // Aggiorna sessione in UI
      setSession((prev) => {
        const prevState = prev?.state;
        const nextState = ev?.state || prevState;

        // Anti-regressione: non tornare mai indietro
        if (
          (prevState === "CONCLUSION" || prevState === "CLOSED") &&
          nextState === "ACTIVE"
        ) {
          console.log("[ACTIVE] Ignoro regressione di stato", {
            prevState,
            nextState,
          });
          return prev;
        }

        return {
          ...prev,
          ...ev,
          state: nextState,
        };
      });

      // Appena entriamo in CONCLUSION, blocchiamo le card del voto
      if (ev.state === "CONCLUSION") {
        setCanVote(false);
        setConclusionRecapStarted(false);

        // checkpoint: da qui in poi considero validi solo i TURN successivi
        conclusionTurnSeqRef.current = turnSeqRef.current;
      }



      // Refresh partecipanti (utile per UI “ready”)
      try {
        const p = await api.get(`/sessions/${sessionId}/participants/`);
        setParticipants(p.data);
      } catch (err) {
        console.error("[ACTIVE] Errore refresh partecipanti (WS):", err);
      }

      // Redirect unico basato su stato server
      if (ev.state === "CONCLUSION") {
        //elimino anche in questo caso il redirect a conclusion
        //navigate(`/session/${sessionId}/conclusion`, { replace: true });
        //return;
      }

      if (ev.state === "CLOSED") {
        notifyOnce(sessionKey(sessionId, "closed_alert"), () => {
          alert("La sessione è stata chiusa.");
        });

        notifyOnce(sessionKey(sessionId, "closed_nav"), () => {
          const iAmHost = String(ev?.host?.id) === String(user?.id);

          if (iAmHost) {
            navigate("/history", { replace: true });
          } else {
            navigate("/dashboard", { replace: true });
          }

        });

        return;

      }

      if (ev.state === "LOBBY") {
        navigate(`/session/${sessionId}/lobby`, { replace: true });
        return;
      }
    }

    handleSessionEvent();
  }, [sessionEvent, sessionId, navigate, user?.id]);




  useEffect(() => {
    if (!voteEvent) return;

    if (voteEvent.type === "VOTE_CAST") {
      const uid = voteEvent.payload?.user_id;
      if (!uid) return;

      setVotesCastUserIds((prev) => new Set([...prev, uid]));
    }

    if (voteEvent.type === "ALL_VOTED") {
      setFinalResults(voteEvent.payload);
      setClosingSeconds(voteEvent.payload?.closing_in_seconds ?? 15);
    }
  }, [voteEvent]);

  // ----------------------------------------------------
  // ERROR bubble (destra) dai messaggi di errore turni
  // ----------------------------------------------------
  useEffect(() => {
    if (!lastEvent) return;
    if (lastEvent.type !== "turns.error") return;

    const err = lastEvent.payload?.error_code;
    const msg = ERROR_MESSAGES[err] || "Azione non consentita.";

    setErrorBubbleKey((k) => k + 1);
    setErrorBubbleMessage(msg);

    if (errorBubbleTimerRef.current) {
      clearTimeout(errorBubbleTimerRef.current);
    }
    errorBubbleTimerRef.current = setTimeout(() => {
      setErrorBubbleMessage(null);
    }, 3000);
  }, [lastEvent]);

  // ----------------------------------------------------
  // TRACK: la prenotazione viene effettivamente usata per parlare?
  // ----------------------------------------------------
  useEffect(() => {
    if (!lastEvent) return;

    // Quando uno inizia a parlare
    if (lastEvent.type === "turns.human_started") {
      const uid = lastEvent.payload?.user_id;
      const currentReservationUser = prevReservationUserIdRef.current;
      if (uid && currentReservationUser && uid === currentReservationUser) {
        reservationUsedRef.current = true;
      }
    }

    // Quando impostiamo una nuova prenotazione, resettiamo il flag
    if (lastEvent.type === "turns.reservation_set") {
      reservationUsedRef.current = false;
    }
  }, [lastEvent]);

  // ----------------------------------------------------
  // SYSTEM bubble (sinistra): prenotazione scaduta
  // ----------------------------------------------------

  useEffect(() => {
    if (!lastEvent) return;
    if (lastEvent.type !== "turns.reservation_expired") return;

    const expiredUserId = lastEvent.payload?.user_id;
    const expiredUser = participants.find((p) => p.user.id === expiredUserId);
    const name = expiredUser?.user?.username || "Un partecipante";

    const text = `${name} ha atteso troppo tempo e non può più sfruttare la prenotazione.\nOra tutti possono parlare.`;

    setSystemBubbleKey((k) => k + 1);
    setSystemBubbleMessage(text);

    if (systemBubbleTimerRef.current) clearTimeout(systemBubbleTimerRef.current);
    systemBubbleTimerRef.current = setTimeout(() => {
      setSystemBubbleMessage(null);
    }, 4500);
  }, [lastEvent, participants]);

  useEffect(() => {
    if (!lastEvent) return;
    if (lastEvent.type !== "turns.reservation_window_started") return;

    const uid = lastEvent.payload?.user_id;
    const seconds = lastEvent.payload?.window_seconds;

    const reservedUser = participants.find((p) => p.user.id === uid);
    const name = reservedUser?.user?.username || "Un partecipante";

    // testo bubble prenotazie
    const text =
      seconds
        ? `${name} ha prenotato il prossimo intervento.\nHa priorità per parlare per ${seconds} secondi.`
        : `${name} ha prenotato il prossimo intervento.\nHa priorità per parlare ora.`;

    setSystemBubbleKey((k) => k + 1);
    setSystemBubbleMessage(text);

    if (systemBubbleTimerRef.current) clearTimeout(systemBubbleTimerRef.current);
    systemBubbleTimerRef.current = setTimeout(() => {
      setSystemBubbleMessage(null);
    }, 4500);
  }, [lastEvent, participants]);


  // ----------------------------------------------------
  // SYSTEM bubble: mostra STATIC_MESSAGE
  // ----------------------------------------------------
  useEffect(() => {
    if (!lastEvent) return;

    if (lastEvent.type === "turns.static_message") {
      const { text, trigger_type, target_user_id } = lastEvent.payload || {};
      if (!text) return;
      // se è un messaggio privato e non è per me, ignoralo
      if (
        target_user_id != null &&
        String(target_user_id) !== String(user?.id)
      ) {
        return;
      }

      setSystemBubbleKey((k) => k + 1);
      setSystemBubbleMessage(text);

      if (systemBubbleTimerRef.current) clearTimeout(systemBubbleTimerRef.current);
      systemBubbleTimerRef.current = setTimeout(() => {
        setSystemBubbleMessage(null);
      }, 6000);

      // TIMER 25: avvia timer visivo 5 minuti
      if (trigger_type === "TIMER_25") {
        setTimeLeft(5 * 60);
      }
    }
  }, [lastEvent]);

  // ----------------------------------------------------
  // SYSTEM bubble: fase introduttiva AI (AI_INTRODUCING)
  // ----------------------------------------------------
  useEffect(() => {
    const st = turnState?.state;

    if (st === "AI_INTRODUCING") {
      if (didShowIntroBubbleRef.current) return;
      didShowIntroBubbleRef.current = true;

      const text =
        "📢 Fase introduttiva\n" +
        "Il moderatore AI sta spiegando regole e contesto della sessione.\n" +
        "Per favore ascolta: tra poco inizierà la sessione vera e propria.";

      setSystemBubbleKey((k) => k + 1);
      setSystemBubbleMessage(text);

      if (systemBubbleTimerRef.current) clearTimeout(systemBubbleTimerRef.current);
      systemBubbleTimerRef.current = setTimeout(() => {
        setSystemBubbleMessage(null);
      }, 14000);
      return;
    }

    // quando finisce l'introduzione, permetti di mostrarla di nuovo in una sessione successiva
    if (st && st !== "AI_INTRODUCING") {
      didShowIntroBubbleRef.current = false;
    }
  }, [turnState?.state]);


  // ----------------------------------------------------
  // CONNECT WebRTC quando sessione ACTIVE
  // ----------------------------------------------------
  useEffect(() => {
    if (!session) return;

    const shouldBeConnected =
      session.state === "ACTIVE" || session.state === "CONCLUSION";

    if (shouldBeConnected) {
      webrtc.connect();
    }
  }, [session?.state]);


  // ----------------------------------------------------
  // ABILITA/DISABILITA local audio in base a isMeSpeaker
  // ----------------------------------------------------

  useEffect(() => {
    // mic locale ON solo se sei effettivamente lo speaker umano
    // e l'AI non sta parlando.
    webrtc.setLocalEnabled(isMeSpeaker && !aiSpeaking);
  }, [isMeSpeaker, aiSpeaking]);

  // ----------------------------------------------------
  // COUNTDOWN DOPO LA RICEZIONE DI TUTTE LE VOTAZIONI AL TERMINE DEL QUALE
  // LA SESSIONE PASSA A CLOSED
  // ----------------------------------------------------
  useEffect(() => {
    if (closingSeconds == null) return;
    if (closingSeconds <= 0) return;

    const t = setInterval(() => {
      setClosingSeconds((s) => (s == null ? s : Math.max(0, s - 1)));
    }, 1000);

    return () => clearInterval(t);
  }, [closingSeconds]);

  // Quando il countdown arriva a 0: l'host chiude la sessione con POST /close/
  useEffect(() => {
    if (!finalResults) return;
    if (closingSeconds !== 0) return;

    // se è già CLOSED, nessuno deve chiamare /close/
    if (session?.state === "CLOSED") return;

    // chiusura automatica solo in CONCLUSION
    if (session?.state !== "CONCLUSION") return;

    // solo host
    if (!isHost) return;

    if (didAutoCloseRef.current) return;
    didAutoCloseRef.current = true;

    closeSession();
  }, [closingSeconds, finalResults, isHost, session?.state]);


  // ----------------------------------------------------
  // Handler turni
  // ----------------------------------------------------
  function handleMicClick() {
    if (aiSpeaking) return;
    isMeSpeaker ? endSpeak() : requestSpeak();
  }

  function handleHandClick() {
    if (aiSpeaking) return;
    myReservation ? clearReserve() : requestReserve();
  }

  // ----------------------------------------------------
  // READY-TO-CONCLUDE
  // ----------------------------------------------------
  function handleReadyToggle() {
    if (iAmReady) return;
    setShowReadyConfirm(true);
  }

  async function confirmReady() {
    setShowReadyConfirm(false);

    try {
      await api.post(`/sessions/${sessionId}/ready_to_conclude/`, { ready: true });

      const p = await api.get(`/sessions/${sessionId}/participants/`);
      setParticipants(p.data);
    } catch (err) {
      alert("Errore aggiornamento stato 'pronto alla conclusione'.");
    }
  }

  function cancelReady() {
    setShowReadyConfirm(false);
  }

  // ----------------------------------------------------
  // VOTAZIONI
  // ----------------------------------------------------

  async function castVote(suspectName) {
    setVoteError(null);

    //  in CONCLUSION si vota solo quando canVote è true
    if (session?.state === "CONCLUSION" && !canVote) {
      setVoteError("Attendi che il moderatore finisca di parlare.");
      return;
    }


    if (aiSpeaking) {
      setVoteError("Attendi che il moderatore finisca di parlare.");
      return;
    }

    setVoteSending(true);
    try {
      await api.post(`/sessions/${sessionId}/vote/`, { suspect: suspectName });
      setMyVote(suspectName);
    } catch (err) {
      const msg = err?.response?.data?.detail || "Errore durante il voto.";
      setVoteError(msg);
    } finally {
      setVoteSending(false);
    }
  }

  // ----------------------------------------------------
  // Chiusura sessione
  // ----------------------------------------------------

  async function closeSession() {
    // Solo host deve chiamare /close/
    if (!isHost) return;

    // evita doppie chiamate (bottone + timer + re-render)
    if (closeRequestedRef.current) return;
    closeRequestedRef.current = true;

    try {
      await api.post(`/sessions/${sessionId}/close/`);
      // OK: ora aspetti WS sessions.session_closed oppure state=CLOSED
    } catch (err) {
      // 409 = la sessione non è in CONCLUSION o è già chiusa → non fare nulla
      if (err?.response?.status === 409) {
        console.info("[closeSession] Sessione già chiusa o non in CONCLUSION (409), continuo.");
        return;
      }

      console.error("[closeSession] Errore:", err);

      // Se proprio fallisce, permetto eventuale retry
      closeRequestedRef.current = false;

      notifyOnce(sessionKey(sessionId, "close_error"), () => {
        alert("Errore nella chiusura della sessione.");
      });
    }
  }



  // ----------------------------------------------------
  // Guardie
  // ----------------------------------------------------
  if (loading) return <h2 style={{ color: "white" }}>Caricamento...</h2>;
  if (!session) return <h2>Sessione non trovata</h2>;

  const meParticipant = participants.find((p) => p.user.id === user.id);
  const others = participants.filter((p) => p.user.id !== user.id);

  const readyParticipants = participants.filter((p) => p.ready_to_conclude);
  const readyCount = readyParticipants.length;
  const totalCount = participants.length;
  const iAmReady = !!meParticipant?.ready_to_conclude;

  const circleSize = 620;
  const radius = circleSize / 2;
  const step = 360 / (others.length || 1);
  const orbit = radius * 0.99;  // prima era radius - 70 circa, li portiamo più fuori


  // ----------------------------------------------------
  // ----------------------------------------------------
  // UI
  // ----------------------------------------------------
  return (
    <>
      <audio
        ref={webrtc.remoteAudioRef}
        autoPlay
        playsInline
      />
      {session?.state === "ACTIVE" && (

        <div
          style={{
            background: "#5B7793",
            minHeight: "100vh",
            color: "white",
            fontFamily: "'Inter', sans-serif",
            position: "relative",
            overflow: "hidden",
          }}
        >

          {/* TIMER IN ALTO A SINISTRA */}
          {timeLeft != null && (
            <div
              style={{
                position: "absolute",
                top: "50px",
                left: "50px",
                zIndex: 200,
              }}
            >
              <div style={{ fontSize: "1.1rem", opacity: 0.85 }}>Tempo rimanente:</div>
              <div
                style={{
                  fontSize: "2.1rem",
                  fontWeight: 800,
                  letterSpacing: "0.03em",
                }}
              >
                {formatTime(timeLeft)}
              </div>
            </div>
          )}
          {/* WRAPPER GENERALE */}
          <div
            style={{
              width: "100%",
              minHeight: "100vh",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              paddingTop: "140px",   // Spazio dall’header AL CERCHIO
              position: "relative",
            }}
          >

            {/* ANIMAZIONI GLOBALI */}
            <style>
              {`
              @keyframes circleAmbient {
                0% { transform: scale(1); box-shadow: 0 0 25px rgba(0,0,0,0.25); }
                50% { transform: scale(1.02); box-shadow: 0 0 35px rgba(0,0,0,0.35); }
                100% { transform: scale(1); box-shadow: 0 0 25px rgba(0,0,0,0.25); }
              }

              @keyframes speakerPulse {
                0% { transform: scale(1); }
                50% { transform: scale(1.08); }
                100% { transform: scale(1); }
              }

              @keyframes speakerWave {
                0% { opacity: 0; transform: scale(1); }
                50% { opacity: 0.6; transform: scale(1.25); }
                100% { opacity: 0; transform: scale(1.5); }
              }

              @keyframes bubbleIn {
                0% { opacity: 0; transform: translateY(10px); }
                100% { opacity: 1; transform: translateY(0); }
              }
              `}
            </style>


            {/* CERCHIO CENTRATO */}
            <div
              style={{
                position: "relative",
                width: `${circleSize}px`,
                height: `${circleSize}px`,
              }}
            >

              {/* SYSTEM BUBBLE SINISTRA */}
              {systemBubbleMessage && (
                <div
                  key={systemBubbleKey}
                  style={{
                    position: "absolute",
                    top: "78%",
                    right: "125%",
                    width: "420px",
                    maxWidth: "44vw",
                    background: "#E7EEF5",
                    color: "#1F2D3D",
                    padding: "1.6rem 1.8rem",
                    borderRadius: "26px",
                    boxShadow: "0 10px 28px rgba(0,0,0,0.28)",
                    fontSize: "1.15rem",
                    fontWeight: 700,
                    lineHeight: 1.35,
                    whiteSpace: "pre-line",
                    animation: "bubbleIn 0.25s ease-out",
                    zIndex: 20,
                  }}
                >
                  {systemBubbleMessage}
                </div>
              )}

              {/* ERROR BUBBLE DESTRA */}
              {errorBubbleMessage && (
                <div
                  key={errorBubbleKey}
                  style={{
                    position: "absolute",
                    top: "78%",
                    right: "-95%",
                    width: "440px",
                    maxWidth: "46vw",
                    background: "#FEE2E2",
                    color: "#7F1D1D",
                    padding: "1.6rem 1.8rem",
                    borderRadius: "26px",
                    boxShadow: "0 10px 28px rgba(0,0,0,0.28)",
                    fontSize: "1.18rem",
                    fontWeight: 750,
                    lineHeight: 1.35,
                    whiteSpace: "pre-line",
                    animation: "bubbleIn 0.25s ease-out",
                    zIndex: 20,
                  }}
                >
                  {errorBubbleMessage}
                </div>
              )}


              {/* CERCHIO E PARTECIPANTI */}
              <div
                style={{
                  width: `${circleSize}px`,
                  height: `${circleSize}px`,
                  borderRadius: "50%",
                  background:
                    "radial-gradient(circle at 30% 20%, #E7EEF5 0%, #6D90B0 70%)",
                  border: "8px solid rgba(255,255,255,0.7)",
                  animation: "circleAmbient 6s ease-in-out infinite",
                  position: "relative",
                }}
              >

                {/* MODERATORE AL CENTRO */}
                <div
                  style={{
                    position: "absolute",
                    left: radius - 55,
                    top: radius - 55,
                    textAlign: "center",
                    width: "110px",
                  }}
                >
                  <div
                    style={{
                      width: "110px",
                      height: "110px",
                      margin: "0 auto",
                      position: "relative",
                    }}
                  >
                    {aiSpeaking && (
                      <div
                        style={{
                          position: "absolute",
                          top: 0,
                          left: 0,
                          width: "110px",
                          height: "110px",
                          borderRadius: "50%",
                          border: "4px solid rgba(255,255,255,0.95)",
                          animation: "speakerWave 1.4s infinite",
                        }}
                      />
                    )}

                    <img
                      src="/icons/logo.png"
                      style={{
                        width: "110px",
                        height: "110px",
                        borderRadius: "50%",
                        background: "white",
                        border: `6px solid ${aiSpeaking ? "#4CAF50" : "white"}`,
                        boxShadow: aiSpeaking
                          ? "0 0 22px rgba(76,175,80,0.95)"
                          : "0 0 22px rgba(0,0,0,0.25)",
                        animation: aiSpeaking ? "speakerPulse 1.2s infinite" : "none",
                      }}
                    />
                  </div>

                  <div
                    style={{
                      marginTop: "6px",
                      color: "#0f172a",
                      fontWeight: 700,
                      fontSize: "0.95rem",
                    }}
                  >
                    ModeratoreAI
                  </div>
                </div>

                {/* ALTRI PARTECIPANTI */}
                {others.map((p, i) => {
                  const angle = (i * step * Math.PI) / 180;
                  const x = radius + orbit * Math.cos(angle);
                  const y = radius + orbit * Math.sin(angle);

                  const isSpeaker =
                    !aiSpeaking &&
                    turnState?.state === "HUMAN_SPEAKING" &&
                    turnState?.current_speaker_user_id === p.user.id;
                  const isReserved =
                    turnState.reservation_user_id === p.user.id;

                  const avatar = getAvatar(p.user.username);

                  const borderColor = isSpeaker
                    ? "#4CAF50"
                    : isReserved
                      ? "#F2A74A"
                      : "#FFFFFF";

                  const boxShadow = isSpeaker
                    ? "0 0 22px rgba(76,175,80,0.95)"
                    : isReserved
                      ? "0 0 16px rgba(242,167,74,0.95)"
                      : "0 0 10px rgba(255,255,255,0.7)";

                  return (
                    <div
                      key={p.user.id}
                      style={{
                        position: "absolute",
                        left: x - 55,
                        top: y - 55,
                        textAlign: "center",
                        width: "110px",
                      }}
                    >
                      <div
                        style={{
                          width: "110px",
                          height: "110px",
                          margin: "0 auto",
                          position: "relative",
                        }}
                      >
                        {isSpeaker && (
                          <div
                            style={{
                              position: "absolute",
                              top: 0,
                              left: 0,
                              width: "110px",
                              height: "110px",
                              borderRadius: "50%",
                              border: "4px solid rgba(255,255,255,0.95)",
                              animation: "speakerWave 1.4s infinite",
                            }}
                          />
                        )}

                        <img
                          src={avatar}
                          style={{
                            width: "110px",
                            height: "110px",
                            borderRadius: "50%",
                            border: `6px solid ${borderColor}`,
                            boxShadow,
                            animation: isSpeaker ? "speakerPulse 1.2s infinite" : "none",
                            background: "#e5e7eb",
                            position: "relative",
                          }}
                        />
                      </div>

                      {/* User label */}
                      <div
                        style={{
                          marginTop: "8px",
                          padding: "4px 12px",
                          background: "rgba(255,255,255,0.96)",
                          borderRadius: "999px",
                          fontSize: "0.9rem",
                          color: "#1F2933",
                          fontWeight: 600,
                          display: "inline-block",
                        }}
                      >
                        {p.user.username}
                      </div>
                    </div>
                  );
                })}

                {/* IO (sempre sud) */}
                {meParticipant && (() => {
                  const angle = (90 * Math.PI) / 180;
                  const x = radius + orbit * Math.cos(angle);
                  const y = radius + orbit * Math.sin(angle);

                  const isSpeaker =
                    !aiSpeaking &&
                    turnState?.state === "HUMAN_SPEAKING" &&
                    turnState?.current_speaker_user_id === meParticipant.user.id;
                  const isReserved =
                    turnState.reservation_user_id === meParticipant.user.id;

                  const avatar = getAvatar(meParticipant.user.username);

                  const borderColor = isSpeaker
                    ? "#4CAF50"
                    : isReserved
                      ? "#F2A74A"
                      : "#FFFFFF";

                  const boxShadow = isSpeaker
                    ? "0 0 22px rgba(76,175,80,0.95)"
                    : isReserved
                      ? "0 0 16px rgba(242,167,74,0.95)"
                      : "0 0 10px rgba(255,255,255,0.7)";

                  return (
                    <div
                      style={{
                        position: "absolute",
                        left: x - 55,
                        top: y - 55,
                        width: "110px",
                        textAlign: "center",
                      }}
                    >
                      <div
                        style={{
                          width: "110px",
                          height: "110px",
                          margin: "0 auto",
                          position: "relative",
                        }}
                      >
                        {isSpeaker && (
                          <div
                            style={{
                              position: "absolute",
                              top: 0,
                              left: 0,
                              width: "110px",
                              height: "110px",
                              borderRadius: "50%",
                              border: "4px solid rgba(255,255,255,0.95)",
                              animation: "speakerWave 1.4s infinite",
                            }}
                          />
                        )}

                        <img
                          src={avatar}
                          style={{
                            width: "110px",
                            height: "110px",
                            borderRadius: "50%",
                            border: `6px solid ${borderColor}`,
                            boxShadow,
                            animation: isSpeaker ? "speakerPulse 1.2s infinite" : "none",
                            background: "#e5e7eb",
                            position: "relative",
                          }}
                        />
                      </div>

                      {/* Label */}
                      <div
                        style={{
                          marginTop: "8px",
                          padding: "4px 12px",
                          background: "rgba(255,255,255,0.96)",
                          borderRadius: "999px",
                          fontSize: "0.9rem",
                          color: "#1F2933",
                          fontWeight: 600,
                          display: "inline-block",
                        }}
                      >
                        {meParticipant.user.username}
                      </div>
                    </div>
                  );
                })()}
              </div>
            </div>
          </div>

          {/* PANEL RIGHT */}
          <div
            style={{
              position: "absolute",
              right: "15%",
              top: "15%",
              width: "300px",
              background: "#E7EEF5",
              borderRadius: "22px",
              padding: "1.5rem",
              boxShadow: "0 4px 16px rgba(0,0,0,0.28)",
              color: "#1F2D3D",
              maxHeight: "520px",
              overflowY: "auto",
              zIndex: 999,
            }}
          >
            <h3
              style={{
                marginTop: 0,
                marginBottom: "0.4rem",
                color: "#2D4B71",
                fontSize: "1.2rem",
                fontWeight: 800,
              }}
            >
              Pronti alla conclusione
            </h3>

            <p
              style={{
                fontSize: "0.9rem",
                marginTop: 0,
                marginBottom: "0.9rem",
                color: "#4B5563",
              }}
            >
              <strong>{readyCount}/{totalCount}</strong> partecipanti hanno cliccato{" "}
              <strong>"Pronto alla conclusione"</strong>.
            </p>

            {readyParticipants.length === 0 && (
              <p style={{ color: "#6b7280", fontStyle: "italic" }}>
                Nessuno è ancora pronto.
              </p>
            )}

            {readyParticipants.map((p) => (
              <div
                key={p.user.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "0.7rem",
                  background: "white",
                  borderRadius: "16px",
                  padding: "0.65rem 0.8rem",
                  marginBottom: "0.55rem",
                  border: "1px solid #CBD5E1",
                  boxShadow: "0 2px 6px rgba(15,23,42,0.15)",
                }}
              >
                <img
                  src={getAvatar(p.user.username)}
                  style={{
                    width: "34px",
                    height: "34px",
                    borderRadius: "50%",
                    border: "2px solid #F2A74A",
                  }}
                />
                <span
                  style={{
                    fontWeight: 700,
                    fontSize: "0.95rem",
                    color: "#111827",
                  }}
                >
                  {p.user.username}
                </span>
              </div>
            ))}
          </div>

          {/* CONTROLLI SOTTO */}
          <div
            style={{
              position: "absolute",
              top: `${circleSize + 280}px`,   // 620 + tot = circa 800px sotto l'inizio wrapper
              left: "50%",
              transform: "translateX(-50%)",
              display: "flex",
              justifyContent: "center",
              alignItems: "center",
              gap: "4rem",
              zIndex: 10,
            }}
          >
            {/* PRENOTA */}
            <button
              onClick={handleHandClick}
              disabled={aiSpeaking}
              style={{
                width: "140px",
                height: "140px",
                borderRadius: "50%",
                background: myReservation ? "#F2A74A" : "#FFE69B",
                border: "none",
                cursor: aiSpeaking ? "not-allowed" : "pointer",
                opacity: aiSpeaking ? 0.6 : 1,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: "3rem",
                boxShadow: "0 6px 16px rgba(0,0,0,0.28)",
              }}
            >
              ✋
            </button>

            {/* MIC */}
            <button
              onClick={handleMicClick}
              disabled={aiSpeaking}
              style={{
                width: "140px",
                height: "140px",
                borderRadius: "50%",
                background: (isMeSpeaker && !aiSpeaking) ? "#4CAF50" : "#D6DDE6",
                border: "none",
                cursor: aiSpeaking ? "not-allowed" : "pointer",
                opacity: aiSpeaking ? 0.6 : 1,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: "3rem",
                boxShadow: "0 6px 16px rgba(0,0,0,0.28)",
              }}
            >
              🎙️
            </button>

            {/* READY */}
            <button
              onClick={handleReadyToggle}
              disabled={iAmReady}
              style={{
                width: "150px",
                height: "150px",
                borderRadius: "50%",
                border: "4px solid rgba(6, 116, 185, 0.85)",
                background: iAmReady ? "#E5E7EB" : "white",
                cursor: iAmReady ? "not-allowed" : "pointer",
                opacity: iAmReady ? 0.65 : 1,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                fontWeight: 900,
                color: iAmReady ? "#6B7280" : "rgba(6, 116, 185, 0.85)",
                boxShadow: iAmReady
                  ? "none"
                  : "0 6px 16px rgba(0,0,0,0.28)",
              }}
            >
              I&apos;M<br />READY
            </button>
          </div>

          {/* DEBUG CLOSE */}
          {isHost && (
            <div style={{ marginTop: "3rem", textAlign: "center" }}>
              <button
                onClick={async () => {
                  try {
                    await api.post(`/sessions/${sessionId}/debug_force_close/`);
                    navigate("/dashboard");
                  } catch {
                    alert("Errore chiusura sessione.");
                  }
                }}
                style={{
                  padding: "10px 20px",
                  background: "#ff4444",
                  border: "none",
                  borderRadius: "6px",
                  color: "white",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                🔥 Chiudi sessione (DEBUG)
              </button>
            </div>
          )}
          {showReadyConfirm && (
            <div
              style={{
                position: "fixed",
                inset: 0,
                background: "rgba(15, 23, 42, 0.65)",
                zIndex: 9999,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <div
                style={{
                  background: "#E7EEF5",
                  borderRadius: "24px",
                  padding: "2rem 2.2rem",
                  width: "420px",
                  maxWidth: "90%",
                  boxShadow: "0 10px 40px rgba(0,0,0,0.35)",
                  textAlign: "center",
                  color: "#1F2D3D",
                }}
              >
                <h3
                  style={{
                    marginTop: 0,
                    marginBottom: "0.8rem",
                    fontSize: "1.4rem",
                    fontWeight: 800,
                    color: "#2D4B71",
                  }}
                >
                  Sei sicuro?
                </h3>

                <p
                  style={{
                    fontSize: "1rem",
                    lineHeight: 1.45,
                    marginBottom: "1.6rem",
                  }}
                >
                  Stai per dichiararti <strong>pronto alla conclusione</strong>.
                  <br />
                  Dopo la conferma non potrai più tornare indietro.
                </p>

                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    gap: "1rem",
                  }}
                >
                  <button
                    onClick={cancelReady}
                    style={{
                      flex: 1,
                      padding: "0.8rem 0",
                      borderRadius: "999px",
                      border: "2px solid #CBD5E1",
                      background: "white",
                      color: "#475569",
                      fontWeight: 700,
                      cursor: "pointer",
                    }}
                  >
                    No, continuo a discutere
                  </button>

                  <button
                    onClick={confirmReady}
                    style={{
                      flex: 1,
                      padding: "0.8rem 0",
                      borderRadius: "999px",
                      border: "none",
                      background: "#0674B9",
                      color: "white",
                      fontWeight: 800,
                      cursor: "pointer",
                      boxShadow: "0 4px 12px rgba(6,116,185,0.45)",
                    }}
                  >
                    Sì, sono pronto
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
      {session?.state === "CONCLUSION" && (
        <div
          style={{
            minHeight: "100vh",
            background: "#E7EEF5",
            padding: "60px 20px",
            fontFamily: "'Inter', sans-serif",
          }}
        >
          <style>
            {`
              @keyframes fadeIn {
                from { opacity: 0; transform: translateY(10px); }
                to   { opacity: 1; transform: translateY(0); }
              }

              @keyframes pulseAI {
                0% { transform: scale(1); opacity: 0.9; }
                50% { transform: scale(1.08); opacity: 1; }
                100% { transform: scale(1); opacity: 0.9; }
              }

              @keyframes wave {
                0% { opacity: 0.25; transform: scale(1); }
                50% { opacity: 0.55; transform: scale(1.45); }
                100% { opacity: 0; transform: scale(1.9); }
              }

              .suspect-card:hover {
                border-color: #2D4B71 !important;
                transform: translateY(-6px) !important;
                box-shadow: 0 6px 20px rgba(45,75,113,0.35) !important;
              }

              .suspect-card.selected:hover {
                border-color: #4CAF50 !important;
                box-shadow: 0 0 20px rgba(76,175,80,0.45) !important;
                transform: translateY(-6px);
              }

              .primary-btn:hover {
                transform: translateY(-3px);
                filter: brightness(0.98);
              }
            `}
          </style>

          {/* INDICATORE MODERATORE */}
          <div
            style={{
              display: "flex",
              justifyContent: "center",
              alignItems: "center",
              gap: "14px",
              marginBottom: "40px",
              animation: "fadeIn 0.35s ease-out",
            }}
          >
            <div style={{ position: "relative", width: "60px", height: "60px" }}>
              <img
                src="/icons/logo.png"
                style={{
                  width: "60px",
                  height: "60px",
                  borderRadius: "50%",
                  background: "white",
                  border: "3px solid #CBD5E1",
                  animation: aiSpeaking ? "pulseAI 1.4s infinite" : "none",
                }}
              />
              {aiSpeaking && (
                <div
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "60px",
                    height: "60px",
                    borderRadius: "50%",
                    border: "3px solid rgba(88,124,163,0.45)",
                    animation: "wave 1.6s infinite",
                  }}
                />
              )}
            </div>

            <span style={{ fontSize: "1.15rem", color: "#475569", fontWeight: 600 }}>
              {aiSpeaking
                ? "Il moderatore sta parlando... (voto bloccato)"
                : myVote
                  ? `Hai votato: ${myVote}`
                  : "Ora puoi votare il colpevole."}
            </span>
          </div>

          {/* TITOLO */}
          <h1
            style={{
              textAlign: "center",
              fontSize: "3rem",
              fontWeight: 800,
              color: "#2D4B71",
              marginBottom: "12px",
            }}
          >
            Chi pensi sia il colpevole?
          </h1>

          {/* SOTTOTITOLO */}
          <p
            style={{
              textAlign: "center",
              fontSize: "1.2rem",
              color: "#374151",
              maxWidth: "860px",
              margin: "0 auto 34px auto",
              lineHeight: 1.4,
            }}
          >
            Ascolta il riepilogo finale del moderatore. <br />
            Quando finisce, scegli il sospettato e invia il tuo voto.
          </p>

          {/* PROGRESS VOTI */}
          <div
            style={{
              textAlign: "center",
              marginBottom: "26px",
              fontSize: "1.05rem",
              color: "#1F2D3D",
              fontWeight: 700,
            }}
          >
            Voti: {votesCastUserIds.size}/3
            {finalResults && (
              <span style={{ marginLeft: 10, fontWeight: 600, color: "#475569" }}>
                • success rate: {finalResults.success_rate}%
              </span>
            )}
          </div>

          {/* CARDS SOSPETTATI */}
          <div
            style={{
              display: "flex",
              justifyContent: "center",
              gap: "2.6rem",
              flexWrap: "wrap",
            }}
          >
            {SUSPECTS.map((s) => {
              const isSelected = myVote === s.name || myVote === s.id;

              const disabled = !canVote || aiSpeaking || voteSending || !!myVote;

              return (
                <div
                  key={s.id}
                  className={`suspect-card ${isSelected ? "selected" : ""}`}
                  onClick={() => {
                    if (disabled) return;
                    castVote(s.id);
                  }}
                  style={{
                    width: "280px",
                    padding: "1.3rem",
                    borderRadius: "24px",
                    background: "white",
                    cursor: disabled ? "not-allowed" : "pointer",
                    border: isSelected ? "4px solid #4CAF50" : "3px solid #D2D8E0",
                    boxShadow: isSelected
                      ? "0 0 20px rgba(76,175,80,0.45)"
                      : "0 5px 14px rgba(0,0,0,0.14)",
                    opacity: disabled ? 0.6 : 1,
                    transition: "0.28s",
                    textAlign: "center",
                  }}
                >
                  <img
                    src={s.img}
                    alt={s.name}
                    style={{
                      width: "100%",
                      borderRadius: "18px",
                      marginBottom: "1rem",
                      display: "block",
                    }}
                  />
                  <div style={{ fontSize: "1.35rem", fontWeight: 800, color: "#1F2D3D" }}>
                    {isSelected ? `✅ ${s.name}` : s.name}
                  </div>

                  {finalResults && (
                    <div style={{ marginTop: 8, fontSize: "0.95rem", color: "#475569", fontWeight: 600 }}>
                      {finalResults.guilty === s.name || finalResults.guilty === s.id
                        ? "👑 Colpevole"
                        : " "}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* ERROR VOTO */}
          {voteError && (
            <div
              style={{
                maxWidth: 740,
                margin: "26px auto 0 auto",
                background: "#FEE2E2",
                color: "#7F1D1D",
                padding: "14px 16px",
                borderRadius: 14,
                fontWeight: 700,
                textAlign: "center",
                boxShadow: "0 4px 14px rgba(0,0,0,0.12)",
              }}
            >
              {voteError}
            </div>
          )}

          {finalResults && (
            <div
              style={{
                maxWidth: 980,
                margin: "44px auto 0 auto",
                background: "white",
                borderRadius: 26,
                padding: "22px 22px",
                boxShadow: "0 14px 44px rgba(15,23,42,0.18)",
                border: "1px solid #D7E0EA",
                animation: "fadeIn 0.35s ease-out",
              }}
            >
              {/* Header */}
              <div
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  justifyContent: "space-between",
                  gap: 14,
                  marginBottom: 14,
                }}
              >
                <div>
                  <h3
                    style={{
                      margin: 0,
                      color: "#2D4B71",
                      fontSize: "1.65rem",
                      fontWeight: 950,
                      letterSpacing: "-0.02em",
                    }}
                  >
                    Risultati finali
                  </h3>
                  <div style={{ marginTop: 6, color: "#475569", fontWeight: 650 }}>
                    Tutti hanno votato. Riepilogo della sessione.
                  </div>
                </div>

                <div
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 10,
                    padding: "10px 12px",
                    borderRadius: 999,
                    background: "#EAF2FF",
                    border: "1px solid #BFD6FF",
                    color: "#1E3A8A",
                    fontWeight: 900,
                    whiteSpace: "nowrap",
                  }}
                >
                  Success rate: {finalResults.success_rate}%
                </div>
              </div>

              {/* Guilty highlight */}
              <div
                style={{
                  marginTop: 14,
                  padding: "16px 16px",
                  borderRadius: 18,
                  background:
                    "linear-gradient(135deg, rgba(76,175,80,0.14), rgba(76,175,80,0.06))",
                  border: "1px solid rgba(76,175,80,0.35)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 12,
                }}
              >
                <div
                  style={{
                    color: "#0f172a",
                    fontWeight: 900,
                    fontSize: "1.05rem",
                  }}
                >
                  Colpevole
                </div>

                <div
                  style={{
                    padding: "8px 14px",
                    borderRadius: 999,
                    background: "#4CAF50",
                    color: "white",
                    fontWeight: 950,
                    fontSize: "1.05rem",
                    letterSpacing: "0.01em",
                  }}
                >
                  {finalResults.guilty}
                </div>
              </div>

              {/* Divider */}
              <div
                style={{
                  height: 1,
                  background: "#E2E8F0",
                  margin: "18px 0",
                }}
              />

              {/* Results list */}
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {finalResults.results.map((r) => {
                  const correct = !!r.correct;

                  return (
                    <div
                      key={r.user_id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        gap: 12,
                        background: "#F8FAFC",
                        border: "1px solid #E2E8F0",
                        borderRadius: 18,
                        padding: "12px 12px",
                        boxShadow: "0 2px 10px rgba(15,23,42,0.06)",
                      }}
                    >
                      {/* Left */}
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 12,
                          minWidth: 0,
                        }}
                      >
                        <img
                          src={getAvatar(r.username || "user")}
                          alt={r.username}
                          style={{
                            width: 44,
                            height: 44,
                            borderRadius: "50%",
                            border: "2px solid #CBD5E1",
                            background: "white",
                            flexShrink: 0,
                          }}
                        />

                        <div style={{ minWidth: 0 }}>
                          <div
                            style={{
                              fontWeight: 950,
                              color: "#0f172a",
                              fontSize: "1.05rem",
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                              maxWidth: 360,
                            }}
                            title={r.username}
                          >
                            {r.username}
                          </div>

                          <div
                            style={{
                              marginTop: 2,
                              color: "#475569",
                              fontWeight: 750,
                            }}
                          >
                            Ha scelto:{" "}
                            <span style={{ color: "#0f172a", fontWeight: 950 }}>
                              {r.chose}
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* Right */}
                      <div
                        style={{
                          padding: "8px 12px",
                          borderRadius: 999,
                          fontWeight: 950,
                          border: `2px solid ${correct
                            ? "rgba(76,175,80,0.45)"
                            : "rgba(239,68,68,0.45)"
                            }`,
                          background: correct
                            ? "rgba(76,175,80,0.10)"
                            : "rgba(239,68,68,0.10)",
                          color: correct ? "#166534" : "#7F1D1D",
                          flexShrink: 0,
                          whiteSpace: "nowrap",
                        }}
                      >
                        {correct ? "Corretto" : "Errato"}
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Footer */}
              <div
                style={{
                  marginTop: 18,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 14,
                  flexWrap: "wrap",
                }}
              >
                <div
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 10,
                    padding: "10px 12px",
                    borderRadius: 999,
                    background: "#F1F5F9",
                    border: "1px solid #CBD5E1",
                    color: "#0f172a",
                    fontWeight: 900,
                  }}
                >
                  Chiusura automatica tra{" "}
                  <span style={{ fontWeight: 950 }}>
                    {closingSeconds ?? finalResults.closing_in_seconds ?? 15}s
                  </span>
                </div>

                {isHost && (
                  <button
                    className="primary-btn"
                    onClick={closeSession}
                    style={{
                      padding: "14px 22px",
                      borderRadius: 16,
                      border: "none",
                      background: "#2D4B71",
                      color: "white",
                      fontSize: "1.05rem",
                      fontWeight: 950,
                      cursor: "pointer",
                      boxShadow: "0 8px 22px rgba(45,75,113,0.28)",
                      transition: "0.25s",
                    }}
                  >
                    Chiudi sessione
                  </button>
                )}
              </div>
            </div>
          )}


        </div>
      )}
    </>
  );

}