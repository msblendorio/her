// Browser-side controller. Wires three WebSockets, captures mic + webcam, and
// renders the rolling terminal panel.

const SAMPLE_RATE = 24000;             // OpenAI Realtime expects PCM16 @ 24 kHz
const FRAME_FPS = 1;                   // webcam frames sent per second
const FRAME_JPEG_QUALITY = 0.7;

const terminalEl = document.getElementById("terminal");
const camEl = document.getElementById("cam");
const btn = document.getElementById("toggle-btn");
const statusLine = document.getElementById("status-line");
const a11yBadge = document.getElementById("a11y-badge");
const cfgLine = document.getElementById("cfg-line");
const indicators = Array.from(document.querySelectorAll("#indicators .ind"));
const langSelect = document.getElementById("lang-select");
const textForm = document.getElementById("text-form");
const textInput = document.getElementById("text-input");
const sendBtn = document.getElementById("send-btn");

const LANG_KEY = "her.language";
function getSelectedLanguage() { return langSelect.value || localStorage.getItem(LANG_KEY) || "it"; }

// ── UI translations ───────────────────────────────────────────────────────
const UI_STRINGS = {
  it: {
    start: "Start", stop: "Stop",
    listening: "ascolto", seeing: "vedo", thinking: "penso", speaking: "parlo",
    lang_tooltip: "Lingua di Samantha (applicata alla prossima sessione)",
    no_scene: "— nessuna scena ancora —",
    session_active: "sessione attiva", disconnected: "disconnesso",
    turns: "turni", audio: "audio", cached: "cached", memories: "ricordi",
    boot_perms: "richiesta permessi mic + webcam …",
    perms_denied: "permessi negati: ",
    starting: "avvio sessione lato server …",
    server_err: "server: errore avvio sessione",
    stopping: "chiusura sessione …",
    session_started: "sessione avviata — parla quando vuoi",
    session_closed: "sessione chiusa",
    lang_changed: "lingua: {lang} (applicata alla prossima sessione)",
    mem_loaded: "caricati {n} ricordi dalle sessioni precedenti",
    mem_saved: "salvato — {summary}",
    who_user: "tu  ›", who_asst: "her ›", who_vis: "vis ›", who_sys: "sys ›", who_mem: "mem ›", who_err: "err ›", who_act: "act ›",
    tool_ok: "ok", tool_fail: "errore",
    a11y_on: "modalità accessibilità",
    send: "invia", text_placeholder: "scrivi un messaggio…",
  },
  en: {
    start: "Start", stop: "Stop",
    listening: "listening", seeing: "seeing", thinking: "thinking", speaking: "speaking",
    lang_tooltip: "Samantha's language (applied to the next session)",
    no_scene: "— no scene yet —",
    session_active: "session active", disconnected: "disconnected",
    turns: "turns", audio: "audio", cached: "cached", memories: "memories",
    boot_perms: "requesting mic + webcam permissions …",
    perms_denied: "permissions denied: ",
    starting: "starting session on the server …",
    server_err: "server: failed to start session",
    stopping: "closing session …",
    session_started: "session started — talk whenever",
    session_closed: "session closed",
    lang_changed: "language: {lang} (applied to the next session)",
    mem_loaded: "loaded {n} memories from previous sessions",
    mem_saved: "saved — {summary}",
    who_user: "you ›", who_asst: "her ›", who_vis: "vis ›", who_sys: "sys ›", who_mem: "mem ›", who_err: "err ›", who_act: "act ›",
    tool_ok: "ok", tool_fail: "error",
    a11y_on: "accessibility mode",
    send: "send", text_placeholder: "type a message…",
  },
  es: {
    start: "Iniciar", stop: "Parar",
    listening: "escucho", seeing: "veo", thinking: "pienso", speaking: "hablo",
    lang_tooltip: "Idioma de Samantha (se aplica en la próxima sesión)",
    no_scene: "— aún ninguna escena —",
    session_active: "sesión activa", disconnected: "desconectado",
    turns: "turnos", audio: "audio", cached: "caché", memories: "recuerdos",
    boot_perms: "solicitando permisos de mic + webcam …",
    perms_denied: "permisos denegados: ",
    starting: "iniciando sesión en el servidor …",
    server_err: "servidor: error al iniciar la sesión",
    stopping: "cerrando sesión …",
    session_started: "sesión iniciada — habla cuando quieras",
    session_closed: "sesión cerrada",
    lang_changed: "idioma: {lang} (se aplica en la próxima sesión)",
    mem_loaded: "cargados {n} recuerdos de sesiones anteriores",
    mem_saved: "guardado — {summary}",
    who_user: "tú  ›", who_asst: "her ›", who_vis: "vis ›", who_sys: "sys ›", who_mem: "mem ›", who_err: "err ›", who_act: "act ›",
    tool_ok: "ok", tool_fail: "error",
    a11y_on: "modo accesibilidad",
    send: "enviar", text_placeholder: "escribe un mensaje…",
  },
  fr: {
    start: "Démarrer", stop: "Arrêter",
    listening: "écoute", seeing: "vois", thinking: "réfléchis", speaking: "parle",
    lang_tooltip: "Langue de Samantha (appliquée à la prochaine session)",
    no_scene: "— pas encore de scène —",
    session_active: "session active", disconnected: "déconnecté",
    turns: "tours", audio: "audio", cached: "cache", memories: "souvenirs",
    boot_perms: "demande des permissions micro + webcam …",
    perms_denied: "permissions refusées : ",
    starting: "démarrage de la session côté serveur …",
    server_err: "serveur : échec du démarrage de la session",
    stopping: "fermeture de la session …",
    session_started: "session démarrée — parle quand tu veux",
    session_closed: "session fermée",
    lang_changed: "langue : {lang} (appliquée à la prochaine session)",
    mem_loaded: "{n} souvenirs chargés depuis les sessions précédentes",
    mem_saved: "enregistré — {summary}",
    who_user: "toi ›", who_asst: "her ›", who_vis: "vis ›", who_sys: "sys ›", who_mem: "mem ›", who_err: "err ›", who_act: "act ›",
    tool_ok: "ok", tool_fail: "erreur",
    a11y_on: "mode accessibilité",
    send: "envoyer", text_placeholder: "écris un message…",
  },
  de: {
    start: "Start", stop: "Stopp",
    listening: "höre", seeing: "sehe", thinking: "denke", speaking: "spreche",
    lang_tooltip: "Samanthas Sprache (gilt ab nächster Sitzung)",
    no_scene: "— noch keine Szene —",
    session_active: "Sitzung aktiv", disconnected: "getrennt",
    turns: "Runden", audio: "Audio", cached: "Cache", memories: "Erinnerungen",
    boot_perms: "fordere Mikro- und Webcam-Berechtigungen an …",
    perms_denied: "Berechtigungen verweigert: ",
    starting: "starte Sitzung auf dem Server …",
    server_err: "Server: Sitzung konnte nicht gestartet werden",
    stopping: "Sitzung wird geschlossen …",
    session_started: "Sitzung gestartet — sprich, wann du willst",
    session_closed: "Sitzung geschlossen",
    lang_changed: "Sprache: {lang} (gilt ab nächster Sitzung)",
    mem_loaded: "{n} Erinnerungen aus vorherigen Sitzungen geladen",
    mem_saved: "gespeichert — {summary}",
    who_user: "du  ›", who_asst: "her ›", who_vis: "vis ›", who_sys: "sys ›", who_mem: "mem ›", who_err: "err ›", who_act: "act ›",
    tool_ok: "ok", tool_fail: "Fehler",
    a11y_on: "Barrierefreiheit",
    send: "senden", text_placeholder: "schreib eine Nachricht…",
  },
};

function t(key, params = {}) {
  const dict = UI_STRINGS[getSelectedLanguage()] || UI_STRINGS.it;
  let s = dict[key] || UI_STRINGS.it[key] || key;
  for (const [k, v] of Object.entries(params)) s = s.replace(`{${k}}`, v);
  return s;
}

function applyLanguage() {
  langSelect.title = t("lang_tooltip");
  for (const el of indicators) el.textContent = t(el.dataset.key);
  btn.textContent = running ? t("stop") : t("start");
  textInput.placeholder = t("text_placeholder");
  sendBtn.textContent = t("send");
}

function setTextInputEnabled(on) {
  textInput.disabled = !on;
  sendBtn.disabled = !on;
}

let running = false;
let micStream = null;
let camStream = null;
let audioCtx = null;
let micNode = null;
let micSource = null;
let playbackCtx = null;
let playbackTime = 0;

let wsAudio = null;
let wsVision = null;
let wsEvents = null;
let frameTimer = null;
let assistantBuffer = "";
let lastAssistantLineEl = null;

// ── UI helpers ────────────────────────────────────────────────────────────
function setStatus(text) { statusLine.textContent = text; }

function fmtSecs(s) {
  s = Math.max(0, Math.floor(s));
  const m = Math.floor(s / 60), r = s % 60;
  return m > 0 ? `${m}m${r.toString().padStart(2, "0")}s` : `${r}s`;
}

function fmtTokens(n) {
  if (n < 1000) return `${n}`;
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

function renderA11yBadge(snap) {
  if (!a11yBadge) return;
  const on = !!(snap && snap.accessibility);
  a11yBadge.hidden = !on;
  if (on) a11yBadge.textContent = t("a11y_on");
}

function renderStatusBar(snap) {
  const u = snap.usage || {};
  const tok = u.tokens || {};
  const cost = (u.cost_usd || 0).toFixed(4);
  const upt = fmtSecs(snap.uptime_s || 0);
  const audioIn = fmtTokens(tok.audio_in || 0);
  const audioOut = fmtTokens(tok.audio_out || 0);
  const cachedSum = (tok.audio_in_cached || 0) + (tok.text_in_cached || 0);
  const cached = cachedSum > 0 ? ` · ${t("cached")} ${fmtTokens(cachedSum)}` : "";
  const session = snap.active ? t("session_active") : t("disconnected");
  const audioLbl = t("audio");
  statusLine.innerHTML =
    `${session} · ⏱ ${upt} · ` +
    `<span style="color:var(--ok)">$${cost}</span> · ` +
    `↑ ${audioIn} ${audioLbl} · ↓ ${audioOut} ${audioLbl} · ` +
    `${u.responses || 0} ${t("turns")}${cached}`;
  renderA11yBadge(snap);
}

function appendLine(kind, who, text) {
  const div = document.createElement("div");
  div.className = `line ${kind}`;
  const whoSpan = document.createElement("span");
  whoSpan.className = "who";
  whoSpan.textContent = who;
  const textSpan = document.createElement("span");
  textSpan.className = "text";
  textSpan.textContent = text;
  div.appendChild(whoSpan);
  div.appendChild(textSpan);
  terminalEl.appendChild(div);
  terminalEl.scrollTop = terminalEl.scrollHeight;
  return div;
}

function updateIndicators(snap) {
  for (const el of indicators) {
    const key = el.dataset.key;
    el.classList.toggle("active", !!snap[key]);
  }
}

// ── audio playback ────────────────────────────────────────────────────────
function ensurePlaybackCtx() {
  if (!playbackCtx) {
    playbackCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: SAMPLE_RATE });
    playbackTime = playbackCtx.currentTime;
  }
}

function playPcm16(buf) {
  ensurePlaybackCtx();
  const i16 = new Int16Array(buf);
  const f32 = new Float32Array(i16.length);
  for (let i = 0; i < i16.length; i++) f32[i] = i16[i] / 0x8000;

  const audioBuf = playbackCtx.createBuffer(1, f32.length, SAMPLE_RATE);
  audioBuf.copyToChannel(f32, 0);
  const src = playbackCtx.createBufferSource();
  src.buffer = audioBuf;
  src.connect(playbackCtx.destination);
  const startAt = Math.max(playbackCtx.currentTime + 0.02, playbackTime);
  src.start(startAt);
  playbackTime = startAt + audioBuf.duration;
}

// ── webcam frames ─────────────────────────────────────────────────────────
function startFrameSender() {
  if (frameTimer) return;
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  frameTimer = setInterval(async () => {
    if (!wsVision || wsVision.readyState !== WebSocket.OPEN) return;
    if (camEl.videoWidth === 0) return;
    // Downsize to keep payload small (Moondream resizes internally anyway).
    const targetW = 512;
    const scale = targetW / camEl.videoWidth;
    canvas.width = targetW;
    canvas.height = Math.round(camEl.videoHeight * scale);
    ctx.drawImage(camEl, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((res) =>
      canvas.toBlob(res, "image/jpeg", FRAME_JPEG_QUALITY)
    );
    if (blob && wsVision.readyState === WebSocket.OPEN) {
      const ab = await blob.arrayBuffer();
      wsVision.send(ab);
    }
  }, Math.round(1000 / FRAME_FPS));
}

function stopFrameSender() {
  if (frameTimer) {
    clearInterval(frameTimer);
    frameTimer = null;
  }
}

// ── session lifecycle ─────────────────────────────────────────────────────
async function startSession() {
  btn.disabled = true;
  setStatus(t("boot_perms"));
  try {
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    camStream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
    camEl.srcObject = camStream;
  } catch (e) {
    setStatus(t("perms_denied") + e.message);
    btn.disabled = false;
    return;
  }

  setStatus(t("starting"));
  const res = await fetch("/api/session/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ language: getSelectedLanguage() }),
  });
  if (!res.ok) {
    setStatus(t("server_err"));
    btn.disabled = false;
    return;
  }
  langSelect.disabled = true;

  // Open the three WebSockets.
  const wsBase = (location.protocol === "https:" ? "wss://" : "ws://") + location.host;
  wsAudio = new WebSocket(wsBase + "/ws/audio");
  wsAudio.binaryType = "arraybuffer";
  wsVision = new WebSocket(wsBase + "/ws/vision");
  wsVision.binaryType = "arraybuffer";
  wsEvents = new WebSocket(wsBase + "/ws/events");

  wsAudio.onmessage = (ev) => {
    if (ev.data instanceof ArrayBuffer) playPcm16(ev.data);
  };
  wsAudio.onopen = async () => {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    await audioCtx.audioWorklet.addModule("/static/mic-worklet.js");
    micSource = audioCtx.createMediaStreamSource(micStream);
    micNode = new AudioWorkletNode(audioCtx, "mic-processor", {
      processorOptions: { targetRate: SAMPLE_RATE },
    });
    micNode.port.onmessage = (e) => {
      if (wsAudio && wsAudio.readyState === WebSocket.OPEN) {
        wsAudio.send(e.data);
      }
    };
    micSource.connect(micNode);
    // The worklet doesn't need to drive output, but Chrome won't pull data
    // unless the graph reaches the destination. Use a silent gain.
    const sink = audioCtx.createGain();
    sink.gain.value = 0;
    micNode.connect(sink).connect(audioCtx.destination);
  };

  wsEvents.onmessage = (ev) => {
    let m;
    try { m = JSON.parse(ev.data); } catch { return; }
    switch (m.type) {
      case "user_text":
        assistantBuffer = "";
        lastAssistantLineEl = null;
        appendLine("user", t("who_user"), m.data);
        break;
      case "assistant_text":
        assistantBuffer += m.data;
        if (!lastAssistantLineEl) {
          lastAssistantLineEl = appendLine("asst", t("who_asst"), assistantBuffer);
        } else {
          lastAssistantLineEl.querySelector(".text").textContent = assistantBuffer;
          terminalEl.scrollTop = terminalEl.scrollHeight;
        }
        break;
      case "assistant_done":
        assistantBuffer = "";
        lastAssistantLineEl = null;
        break;
      case "caption":
        // Vision captions still drive the seeing/last_caption state on the
        // server and are injected into the model as context — but we don't
        // render them in the terminal: too noisy, and they don't help the
        // user follow the conversation.
        break;
      case "status":
        updateIndicators(m.data);
        renderStatusBar(m.data);
        break;
      case "error":
        appendLine("err", t("who_err"), JSON.stringify(m.data));
        break;
      case "memory_loaded":
        appendLine("sys", t("who_mem"), t("mem_loaded", { n: m.data.count }));
        break;
      case "tool_call": {
        const { name, args, result } = m.data || {};
        const argStr = typeof args === "string" ? args : JSON.stringify(args);
        const ok = result && result.ok;
        const tail = ok
          ? `→ ${t("tool_ok")}${result.result ? " (" + String(result.result).slice(0, 80) + ")" : ""}`
          : `→ ${t("tool_fail")}: ${result && result.error ? result.error : "?"}`;
        appendLine(ok ? "sys" : "err", t("who_act"), `${name}(${argStr || ""}) ${tail}`);
        break;
      }
      case "memory_saved":
        appendLine("sys", t("who_mem"), t("mem_saved", { summary: m.data.summary }));
        if (m.data.key_facts && m.data.key_facts.length) {
          for (const f of m.data.key_facts) appendLine("sys", "    ·", f);
        }
        // refresh memory count in header
        fetch("/api/config").then((r) => r.json()).then(renderHeaderConfig);
        break;
    }
  };

  startFrameSender();
  running = true;
  btn.textContent = t("stop");
  btn.classList.add("on");
  btn.disabled = false;
  setTextInputEnabled(true);
  setStatus(t("session_active"));
  appendLine("sys", t("who_sys"), t("session_started"));
}

async function stopSession() {
  btn.disabled = true;
  setStatus(t("stopping"));
  stopFrameSender();

  try { wsAudio && wsAudio.close(); } catch {}
  try { wsVision && wsVision.close(); } catch {}
  try { wsEvents && wsEvents.close(); } catch {}
  wsAudio = wsVision = wsEvents = null;

  if (micNode) { try { micNode.disconnect(); } catch {} micNode = null; }
  if (micSource) { try { micSource.disconnect(); } catch {} micSource = null; }
  if (audioCtx) { try { await audioCtx.close(); } catch {} audioCtx = null; }
  if (playbackCtx) { try { await playbackCtx.close(); } catch {} playbackCtx = null; }
  if (micStream) { micStream.getTracks().forEach((t) => t.stop()); micStream = null; }
  if (camStream) { camStream.getTracks().forEach((t) => t.stop()); camStream = null; }
  camEl.srcObject = null;

  await fetch("/api/session/stop", { method: "POST" });

  running = false;
  btn.textContent = t("start");
  btn.classList.remove("on");
  btn.disabled = false;
  setTextInputEnabled(false);
  langSelect.disabled = false;
  updateIndicators({ listening: false, seeing: false, thinking: false, speaking: false });
  // Re-render status bar with the final usage of the just-ended session so
  // the cost remains visible after stopping.
  try {
    const snap = await fetch("/api/state").then((r) => r.json());
    renderStatusBar(snap);
  } catch {
    setStatus(t("disconnected"));
  }
  appendLine("sys", t("who_sys"), t("session_closed"));
}

btn.addEventListener("click", () => {
  if (!running) startSession();
  else stopSession();
});

textForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = textInput.value.trim();
  if (!text || !running) return;
  textInput.value = "";
  try {
    await fetch("/api/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
  } catch {
    appendLine("err", t("who_err"), "send failed");
  }
});

function renderHeaderConfig(c) {
  const memTag = c.memory_enabled ? ` · ${c.memory_count} ${t("memories")}` : "";
  const verTag = c.version ? ` · v${c.version}` : "";
  cfgLine.textContent = `${c.model} · ${c.voice} · vision ${c.vision_enabled ? "on" : "off"}${memTag}${verTag}`;
}

// Populate language dropdown, then fetch initial config + state.
(async () => {
  try {
    const r = await fetch("/api/languages").then((x) => x.json());
    const preferred = localStorage.getItem(LANG_KEY) || r.default || "it";
    langSelect.innerHTML = "";
    for (const [code, label] of Object.entries(r.languages)) {
      const opt = document.createElement("option");
      opt.value = code;
      opt.textContent = label;
      if (code === preferred) opt.selected = true;
      langSelect.appendChild(opt);
    }
  } catch {
    // fallback: hard-code IT only
    langSelect.innerHTML = '<option value="it" selected>Italiano</option>';
  }
  langSelect.addEventListener("change", () => {
    localStorage.setItem(LANG_KEY, langSelect.value);
    // Re-render every visible string in the new language immediately.
    applyLanguage();
    try { fetch("/api/state").then((x) => x.json()).then(renderStatusBar); } catch {}
    if (running) {
      appendLine("sys", t("who_sys"), t("lang_changed", { lang: langSelect.value }));
    }
  });

  applyLanguage();
  try {
    const c = await fetch("/api/config").then((x) => x.json());
    renderHeaderConfig(c);
  } catch {}
  try {
    const s = await fetch("/api/state").then((x) => x.json());
    renderStatusBar(s);
  } catch {}
})();
