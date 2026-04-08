import { useTurnsWS } from "./useTurnsWS";

export function useTurns(sessionId, user, accessToken) {
  return useTurnsWS(sessionId, user, accessToken);
}
