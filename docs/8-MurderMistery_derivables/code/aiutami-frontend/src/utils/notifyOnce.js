export function notifyOnce(key, fn) {
    if (!key) return false;
    if (sessionStorage.getItem(key)) return false; // per-tab
    sessionStorage.setItem(key, "1");
    try { fn?.(); } catch { }
    return true;
}

export function sessionKey(sessionId, suffix) {
    return `session:${sessionId || "unknown"}:${suffix}`;
}