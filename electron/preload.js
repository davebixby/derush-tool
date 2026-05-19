// Preload script — runs in the renderer with limited privileges.
// For now we expose nothing: the existing HTML/JS frontend talks to the
// Python backend over HTTP, exactly like in a regular browser. If later we
// want to swap that for IPC (faster, no HTTP overhead), this is where the
// bridge would be wired.
//
// Keeping it empty also keeps the security posture tight: nodeIntegration is
// off and contextIsolation is on, so the page can't reach into Node APIs.
