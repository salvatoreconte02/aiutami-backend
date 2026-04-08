// src/webrtc/useWebRTC.js

import { useCallback, useEffect, useRef, useState } from "react";

const WS_BASE = import.meta.env.VITE_WS_BASE || "ws://localhost:8000/ws";

/**
 * Hook WebRTC (aiortc server-side):
 * - apre WS di signaling: /ws/webrtc/<sessionId>/?token=...
 * - crea RTCPeerConnection
 * - prende microfono (getUserMedia)
 * - manda offer, riceve answer
 * - scambia ICE (trickle)
 * - espone setLocalEnabled() per abilitare/disabilitare audio in base ai turni
 */
export default function useWebRTC(sessionId, accessToken) {
  const wsRef = useRef(null);
  const pcRef = useRef(null);
  const localStreamRef = useRef(null);
  const remoteAudioRef = useRef(null);
  const statusRef = useRef("idle");


  const [status, setStatus] = useState("idle"); // idle | connecting | connected | error | closed
  const [lastError, setLastError] = useState(null);

  useEffect(() => {
    statusRef.current = status;
  }, [status]);


  const canOpen = Boolean(sessionId) && Boolean(accessToken) && accessToken.length > 10;

  const cleanup = useCallback(async (reason = "cleanup") => {
    try {
      // stop local tracks
      if (localStreamRef.current) {
        localStreamRef.current.getTracks().forEach((t) => t.stop());
      }
    } catch {}

    localStreamRef.current = null;

    try {
      if (pcRef.current) await pcRef.current.close();
    } catch {}

    pcRef.current = null;

    try {
      wsRef.current?.close();
    } catch {}

    wsRef.current = null;

    setStatus("closed");
    // eslint-disable-next-line no-console
    console.log("[WEBRTC] cleanup:", reason);
  }, []);

  const setLocalEnabled = useCallback((enabled) => {
    const stream = localStreamRef.current;
    if (!stream) return;
    stream.getAudioTracks().forEach((t) => (t.enabled = !!enabled));
    // eslint-disable-next-line no-console
    console.log("[WEBRTC] local track enabled =", !!enabled);
  }, []);

  const connect = useCallback(async () => {
    if (!canOpen) return;
    if (statusRef.current === "connecting" || statusRef.current === "connected") return;


    setStatus("connecting");
    setLastError(null);

    const url = `${WS_BASE}/webrtc/${sessionId}/?token=${accessToken}`;
    // eslint-disable-next-line no-console
    console.log("[WEBRTC] WS open:", url);

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onerror = (e) => {
      console.error("[WEBRTC] WS error:", e);
      setLastError("WS_ERROR");
      setStatus("error");
    };

    ws.onclose = (ev) => {
      console.log("[WEBRTC] WS closed", { code: ev.code, reason: ev.reason });
      setStatus("closed");
    };


    ws.onmessage = async (evt) => {
      let msg;
      try {
        msg = JSON.parse(evt.data);
      } catch {
        return;
      }

      // eslint-disable-next-line no-console
      console.log("[WEBRTC] RX:", msg);

      if (msg.type === "webrtc.answer") {
        try {
          const pc = pcRef.current;
          if (!pc) return;

          await pc.setRemoteDescription(
            new RTCSessionDescription({ type: msg.type_sdp, sdp: msg.sdp })
          );

          setStatus("connected");
        } catch (err) {
          console.error("[WEBRTC] setRemoteDescription(answer) failed:", err);
          setLastError("BAD_ANSWER");
          setStatus("error");
        }
        return;
      }

      if (msg.type === "webrtc.ice_candidate") {
        const pc = pcRef.current;
        if (!pc) return;

        try {
          const cand = msg.candidate;

          // end-of-candidates
          if (cand === null) {
            await pc.addIceCandidate(null);
            return;
          }

          // server sends: {candidate: {candidate, sdpMid, sdpMLineIndex}}
          const c = cand?.candidate ? cand : cand?.candidate; // defensive
          const candidateObj = cand?.candidate ? cand : null;

          if (candidateObj) {
            await pc.addIceCandidate(new RTCIceCandidate(candidateObj));
          } else if (c) {
            // fallback string format
            await pc.addIceCandidate(
              new RTCIceCandidate({
                candidate: c,
                sdpMid: cand.sdpMid,
                sdpMLineIndex: cand.sdpMLineIndex,
              })
            );
          }
        } catch (err) {
          console.error("[WEBRTC] addIceCandidate(from server) failed:", err);
        }
        return;
      }

      if (msg.type === "webrtc.error") {
        console.error("[WEBRTC] server error:", msg.payload);
        setLastError(msg.payload?.reason || "SERVER_ERROR");
        setStatus("error");
      }
    };

    ws.onopen = async () => {
      try {
        // 1) microfono
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        localStreamRef.current = stream;

        // di default: MUTED finché non ti viene concesso il turno
        stream.getAudioTracks().forEach((t) => (t.enabled = false));

        // 2) peer connection
        const pc = new RTCPeerConnection({
          iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
        });
        pcRef.current = pc;

        pc.oniceconnectionstatechange = () => {
          console.log("[WEBRTC] iceConnectionState =", pc.iceConnectionState);
        };

        pc.onconnectionstatechange = () => {
          console.log("[WEBRTC] connectionState =", pc.connectionState);
        };


        // 3) remote audio playback
        pc.ontrack = (event) => {
          const [remoteStream] = event.streams;
          if (!remoteStream) return;

          if (remoteAudioRef.current) {
            remoteAudioRef.current.srcObject = remoteStream;
            remoteAudioRef.current.play?.().catch(() => {});
          }
        };

        // 4) local audio -> pc
        stream.getTracks().forEach((track) => pc.addTrack(track, stream));

        // 5) ICE browser -> server
        pc.onicecandidate = (event) => {
          const candidate = event.candidate;
          if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

          wsRef.current.send(
            JSON.stringify({
              type: "webrtc.ice_candidate",
              candidate: candidate
                ? {
                    candidate: candidate.candidate,
                    sdpMid: candidate.sdpMid,
                    sdpMLineIndex: candidate.sdpMLineIndex,
                  }
                : null,
            })
          );
        };

        // 6) offer -> server
        const offer = await pc.createOffer({ offerToReceiveAudio: true });
        await pc.setLocalDescription(offer);

        ws.send(
          JSON.stringify({
            type: "webrtc.offer",
            sdp: offer.sdp,
            type_sdp: offer.type,
          })
        );

        console.log("[WEBRTC] offer sent");
      } catch (err) {
        console.error("[WEBRTC] connect failed:", err);
        setLastError(err?.name || "CONNECT_FAILED");
        setStatus("error");
      }
    };
  }, [WS_BASE, accessToken, canOpen, sessionId, status]);

  // cleanup on unmount / session change
  useEffect(() => {
    return () => {
      cleanup("unmount");
    };
  }, [cleanup]);

  return {
    connect,
    cleanup,
    setLocalEnabled,
    remoteAudioRef,
    status,
    lastError,
  };
}
