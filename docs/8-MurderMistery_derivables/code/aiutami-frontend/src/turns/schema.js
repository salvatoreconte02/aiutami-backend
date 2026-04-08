// src/turns/schema.js

// Stati possibili del sistema di turni
export const TURN_STATE_IDLE = "IDLE";
export const TURN_STATE_HUMAN_SPEAKING = "HUMAN_SPEAKING";
export const TURN_STATE_AI_SPEAKING = "AI_SPEAKING";

// Forma dello stato (compatibile con il backend TurnState)
export function createInitialTurnState() {
  return {
    state: TURN_STATE_IDLE,
    current_speaker_user_id: null,
    reservation_user_id: null,
    reservation_expires_at: null,
    version: 1,
  };
}
