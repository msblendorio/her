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
const cmdMenu = document.getElementById("cmd-menu");
const attachBtn = document.getElementById("attach-btn");
const fileInput = document.getElementById("file-input");

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
    send: "invia", text_placeholder: "scrivi un messaggio o / per i comandi…",
    text_needs_session: "premi Start (o /start) per parlare con Samantha.",
    schedule_fired: "⏰ attività pianificata [{when}]: {prompt}",
    attach_title: "Allega un file (pdf, md, txt, docx, jpg, png)",
    file_uploading: "carico {name} …",
    file_ask: "{name} caricato — vuoi conservarlo nella wiki o è temporaneo?",
    file_keep: "Conserva nella wiki", file_discard: "Temporaneo (usa e elimina)",
    file_filing: "archivio nella wiki …", file_reading: "leggo il file …",
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
    send: "send", text_placeholder: "type a message, or / for commands…",
    text_needs_session: "press Start (or /start) to talk to Samantha.",
    schedule_fired: "⏰ scheduled task [{when}]: {prompt}",
    attach_title: "Attach a file (pdf, md, txt, docx, jpg, png)",
    file_uploading: "uploading {name} …",
    file_ask: "{name} uploaded — keep it in the wiki, or temporary?",
    file_keep: "Keep in wiki", file_discard: "Temporary (use & delete)",
    file_filing: "filing into the wiki …", file_reading: "reading the file …",
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
    send: "enviar", text_placeholder: "escribe un mensaje o / para los comandos…",
    text_needs_session: "pulsa Start (o /start) para hablar con Samantha.",
    schedule_fired: "⏰ tarea programada [{when}]: {prompt}",
    attach_title: "Adjuntar un archivo (pdf, md, txt, docx, jpg, png)",
    file_uploading: "subiendo {name} …",
    file_ask: "{name} subido — ¿lo conservo en la wiki o es temporal?",
    file_keep: "Conservar en la wiki", file_discard: "Temporal (usar y eliminar)",
    file_filing: "archivando en la wiki …", file_reading: "leyendo el archivo …",
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
    send: "envoyer", text_placeholder: "écris un message, ou / pour les commandes…",
    text_needs_session: "appuie sur Start (ou /start) pour parler à Samantha.",
    schedule_fired: "⏰ tâche programmée [{when}] : {prompt}",
    attach_title: "Joindre un fichier (pdf, md, txt, docx, jpg, png)",
    file_uploading: "import de {name} …",
    file_ask: "{name} importé — le garder dans le wiki ou temporaire ?",
    file_keep: "Garder dans le wiki", file_discard: "Temporaire (lire et supprimer)",
    file_filing: "classement dans le wiki …", file_reading: "lecture du fichier …",
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
    send: "senden", text_placeholder: "schreib eine Nachricht, oder / für Befehle…",
    text_needs_session: "drück Start (oder /start), um mit Samantha zu sprechen.",
    schedule_fired: "⏰ geplante Aufgabe [{when}]: {prompt}",
    attach_title: "Datei anhängen (pdf, md, txt, docx, jpg, png)",
    file_uploading: "lade {name} hoch …",
    file_ask: "{name} hochgeladen — im Wiki behalten oder temporär?",
    file_keep: "Im Wiki behalten", file_discard: "Temporär (lesen & löschen)",
    file_filing: "lege im Wiki ab …", file_reading: "lese die Datei …",
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
  attachBtn.title = t("attach_title");
  // The header meta line embeds a translated word ("ricordi"/"memories"/…),
  // so it has to be rebuilt too — otherwise it stays in whatever language was
  // active when config first loaded.
  if (lastConfig) renderHeaderConfig(lastConfig);
}

// The input field is always usable so slash commands (/help, /start, …) work
// even when no session is running. `on` only tracks whether free-form text
// reaches the live session; the submit handler enforces that.
let canSendText = false;
function setTextInputEnabled(on) {
  canSendText = !!on;
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

// A readable label for the Anthropic model id (e.g. "claude-opus-4-8" →
// "Claude Opus"), shown next to its cost in the status bar.
function prettyClaude(model) {
  const m = (model || "").toLowerCase();
  if (m.includes("opus")) return "Claude Opus";
  if (m.includes("sonnet")) return "Claude Sonnet";
  if (m.includes("haiku")) return "Claude Haiku";
  return "Claude";
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
  const anth = u.anthropic || {};
  // Combined OpenAI + Anthropic cost (fall back to the OpenAI-only field for
  // older snapshots that predate the breakdown).
  const total = (u.cost_total_usd != null ? u.cost_total_usd : (u.cost_usd || 0));
  const cost = total.toFixed(4);
  const upt = fmtSecs(snap.uptime_s || 0);
  const audioIn = fmtTokens(tok.audio_in || 0);
  const audioOut = fmtTokens(tok.audio_out || 0);
  const cachedSum = (tok.audio_in_cached || 0) + (tok.text_in_cached || 0);
  const cached = cachedSum > 0 ? ` · ${t("cached")} ${fmtTokens(cachedSum)}` : "";
  const session = snap.active ? t("session_active") : t("disconnected");
  const audioLbl = t("audio");
  // When Cowork/wiki (Claude) has spent anything, show the split so the user
  // sees both API costs — labelled by the actual model behind each (the
  // OpenAI realtime model and the Anthropic/Claude one), not the vendor names.
  let costHtml = `<span style="color:var(--ok)">$${cost}</span>`;
  if ((anth.cost_usd || 0) > 0) {
    const oa = (u.cost_usd || 0).toFixed(4);
    const cl = (anth.cost_usd || 0).toFixed(4);
    const cfg = lastConfig || {};
    const oaLbl = cfg.model || "OpenAI";
    const clLbl = prettyClaude(cfg.anthropic_model);
    costHtml += ` <span style="opacity:.65">(${oaLbl} $${oa} · ${clLbl} $${cl})</span>`;
  }
  statusLine.innerHTML =
    `${session} · ⏱ ${upt} · ` +
    `${costHtml} · ` +
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
      case "schedule_fired":
        appendLine("sys", t("who_sys"),
          t("schedule_fired", { when: m.data.when, prompt: m.data.prompt }));
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

// ── Slash commands ──────────────────────────────────────────────────────
// A small client-side command system. Anything the user types starting with
// "/" is handled here instead of being sent to the model. `/help` lists them.
function sysLine(text) { return appendLine("sys", t("who_sys"), text); }
function errLine(text) { return appendLine("err", t("who_err"), text); }

async function apiGet(path) {
  const r = await fetch(path);
  return r.json();
}
async function apiSend(path, method, body) {
  const r = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = {};
  try { data = await r.json(); } catch {}
  return { ok: r.ok, data };
}

// Slash commands are a power-user surface: the keywords and their help text
// stay in English — the universal CLI convention (Claude Code, Slack, IDEs).
// Only strings that surface in the normal conversation flow (notifications,
// the no-session hint, the input placeholder) are localized via UI_STRINGS.
const CMD_TEXT = {
  help: "list commands", clear: "clear the terminal",
  lang: "change language or list the available ones",
  memory: "show saved memories", wiki: "list wiki entries",
  tools: "list agentic tools", cowork: "Cowork (Claude) status",
  start: "start the session", stop: "stop the session",
  schedule: "tasks scheduled at fixed times (cron)",
  pulse: "periodic presence: on/off or interval",
  forge: "teach a new skill by describing it (no demo)",
};
function cmdDesc(name) {
  return CMD_TEXT[name.slice(1)] || name.slice(1);
}

// ── command handlers ──
function cmdHelp() {
  sysLine("available commands (type / for autocomplete):");
  for (const c of COMMANDS) {
    const a = c.args ? " " + c.args : "";
    sysLine(`  ${c.name}${a}  —  ${cmdDesc(c.name)}`);
  }
}

function cmdClear() {
  terminalEl.innerHTML = "";
  lastAssistantLineEl = null;
  assistantBuffer = "";
}

function cmdLang(args) {
  const code = (args[0] || "").toLowerCase();
  if (!code) {
    const list = Array.from(langSelect.options).map((o) => `${o.value} (${o.textContent})`);
    sysLine(list.join(", "));
    return;
  }
  const opt = Array.from(langSelect.options).find((o) => o.value === code);
  if (!opt) { errLine(`?: ${code}`); return; }
  langSelect.value = code;
  langSelect.dispatchEvent(new Event("change"));
}

async function cmdMemory() {
  const d = await apiGet("/api/memory");
  if (!d.enabled) { sysLine("memory: off"); return; }
  sysLine(`${t("memories")}: ${d.count}`);
  for (const e of (d.entries || []).slice(-5)) sysLine(`  · ${e.summary}`);
}

async function cmdWiki() {
  const d = await apiGet("/api/wiki");
  sysLine(`wiki: ${d.count || 0}${d.enabled ? "" : " (off)"}`);
  for (const p of (d.pages || []).slice(0, 20)) sysLine(`  · ${p.title || p.slug}`);
}

async function cmdTools() {
  const d = await apiGet("/api/tools");
  const names = (d.tools || []).map((x) => x.name);
  sysLine(`tools (${names.length})${d.enabled ? "" : " — off"}: ${names.join(", ")}`);
}

async function cmdCowork() {
  const d = await apiGet("/api/cowork");
  sysLine(`cowork: ${d.configured ? "on" : "off"} · ${d.model || "?"} · ${d.credential || "—"} · skills ${(d.skills || []).length}`);
}

function cmdStart() {
  if (running) { sysLine(t("session_active")); return; }
  startSession();
}
function cmdStop() {
  if (!running) { sysLine(t("disconnected")); return; }
  stopSession();
}

function fmtJob(j) {
  return `  #${j.id}  [${j.when}]  ${j.prompt}${j.enabled ? "" : "  (off)"}`;
}

async function cmdSchedule(args, raw) {
  const sub = (args[0] || "list").toLowerCase();
  if (sub === "list" || sub === "ls") {
    const d = await apiGet("/api/schedule");
    const jobs = d.jobs || [];
    sysLine(`schedule (${jobs.length})${d.enabled ? "" : " — off"}:`);
    for (const j of jobs) sysLine(fmtJob(j));
    if (!jobs.length) sysLine("  —  /schedule add <cron> | <testo>");
    return;
  }
  if (sub === "add") {
    const m = raw.match(/^\/schedule\s+add\s+([\s\S]+)$/i);
    if (!m || !m[1].includes("|")) {
      errLine("uso: /schedule add <cron> | <testo>   (es. 0 9 * * * | dammi il buongiorno)");
      return;
    }
    const [cronPart, ...rest] = m[1].split("|");
    const when = cronPart.trim();
    const prompt = rest.join("|").trim();
    const { ok, data } = await apiSend("/api/schedule", "POST", { when, prompt });
    if (!ok) { errLine(data.error || "errore"); return; }
    sysLine("ok:");
    sysLine(fmtJob(data.job));
    return;
  }
  if (sub === "rm" || sub === "del" || sub === "remove") {
    const id = args[1];
    if (!id) { errLine("uso: /schedule rm <id>"); return; }
    const { data } = await apiSend(`/api/schedule/${id}`, "DELETE");
    sysLine(data.ok ? `ok: #${id} rimosso` : `?: #${id}`);
    return;
  }
  if (sub === "on" || sub === "off") {
    const id = args[1];
    if (!id) { errLine(`uso: /schedule ${sub} <id>`); return; }
    const want = sub === "on";
    const d = await apiGet("/api/schedule");
    const job = (d.jobs || []).find((j) => j.id === id);
    if (!job) { errLine(`?: #${id}`); return; }
    if (job.enabled !== want) await apiSend(`/api/schedule/${id}/toggle`, "POST");
    sysLine(`ok: #${id} ${want ? "on" : "off"}`);
    return;
  }
  errLine(`unknown command: /schedule ${sub} — try /help`);
}

function renderPulse(s) {
  sysLine(
    `pulse: ${s.enabled ? "on" : "off"} · ` +
    `interval ${Math.round(s.interval_s)}s · ` +
    `${s.active ? "running" : "stopped"}`
  );
}

async function cmdPulse(args) {
  const a = (args[0] || "").toLowerCase();
  if (!a) { renderPulse(await apiGet("/api/pulse")); return; }
  let body = null;
  if (a === "on") body = { enabled: true };
  else if (a === "off") body = { enabled: false };
  else if (/^\d+$/.test(a)) body = { enabled: true, interval_s: parseInt(a, 10) };
  else { errLine("uso: /pulse [on | off | <secondi>]"); return; }
  const { data } = await apiSend("/api/pulse", "POST", body);
  renderPulse(data);
}

// A skill forged in the terminal but not yet saved: {name, description,
// script, summary}. The preview/confirm split mirrors the conversational
// forge_session so nothing lands on disk without an explicit "save".
let pendingForge = null;

function fmtSkill(s) {
  const icon = s.origin === "forge" ? "🔨" : "🎥";
  return `  ${icon} ${s.slug}  —  ${s.summary || s.description || s.name || ""}`;
}

async function cmdForge(args, raw) {
  const sub = (args[0] || "").toLowerCase();

  if (!sub || sub === "list" || sub === "ls") {
    const d = await apiGet("/api/forge");
    const skills = d.skills || [];
    sysLine(`skills (${skills.length}):`);
    for (const s of skills) sysLine(fmtSkill(s));
    if (!skills.length) sysLine("  —  /forge <nome> | <descrizione>");
    return;
  }

  if (sub === "save" || sub === "ok") {
    if (!pendingForge) { errLine("niente da salvare — prima /forge <nome> | <descrizione>"); return; }
    const { ok, data } = await apiSend("/api/forge/confirm", "POST", pendingForge);
    if (!ok) { errLine(data.error || "errore"); return; }
    sysLine(`ok: forgiata '${data.slug}'`);
    pendingForge = null;
    return;
  }

  if (sub === "cancel" || sub === "annulla") {
    if (!pendingForge) { sysLine("niente in sospeso"); return; }
    sysLine(`annullata '${pendingForge.name}'`);
    pendingForge = null;
    return;
  }

  if (sub === "rm" || sub === "del" || sub === "remove") {
    const slug = args[1];
    if (!slug) { errLine("uso: /forge rm <slug>"); return; }
    const { data } = await apiSend(`/api/forge/${slug}`, "DELETE");
    sysLine(data.ok ? `ok: '${slug}' rimossa` : `?: '${slug}'`);
    return;
  }

  // Otherwise: forge from "<name> | <description>".
  const m = raw.match(/^\/forge\s+([\s\S]+)$/i);
  if (!m || !m[1].includes("|")) {
    errLine("uso: /forge <nome> | <descrizione>   (es. focus | chiudi Slack e attiva Non Disturbare)");
    return;
  }
  const [namePart, ...rest] = m[1].split("|");
  const name = namePart.trim();
  const description = rest.join("|").trim();
  if (!name || !description) { errLine("uso: /forge <nome> | <descrizione>"); return; }

  sysLine(`forgiatura '${name}'…`);
  const { ok, data } = await apiSend("/api/forge", "POST", { name, description });
  if (!ok) { errLine(data.error || "non sono riuscita a forgiarla"); return; }
  sysLine(`preview: ${data.summary || "(nessun riassunto)"}`);
  for (const w of (data.warnings || [])) sysLine(`  ⚠ ${w}`);
  pendingForge = { name, description, script: data.script, summary: data.summary };
  sysLine("  →  /forge save  per salvare,  /forge cancel  per annullare");
}

const COMMANDS = [
  { name: "/help", run: cmdHelp },
  { name: "/clear", run: cmdClear },
  { name: "/lang", args: "[it|en|es|fr|de]", run: cmdLang },
  { name: "/memory", run: cmdMemory },
  { name: "/wiki", run: cmdWiki },
  { name: "/tools", run: cmdTools },
  { name: "/cowork", run: cmdCowork },
  { name: "/start", run: cmdStart },
  { name: "/stop", run: cmdStop },
  { name: "/schedule", args: "[list | add <cron> | <text> | rm <id> | on|off <id>]", run: cmdSchedule },
  { name: "/pulse", args: "[on | off | <seconds>]", run: cmdPulse },
  { name: "/forge", args: "[<name> | <description> | save | cancel | rm <slug>]", run: cmdForge },
];

async function handleCommand(raw) {
  appendLine("user", t("who_user"), raw);
  const parts = raw.slice(1).split(/\s+/);
  const name = "/" + (parts.shift() || "").toLowerCase();
  const cmd = COMMANDS.find((c) => c.name === name);
  if (!cmd) { errLine(`unknown command: ${name} — try /help`); return; }
  try {
    await cmd.run(parts, raw);
  } catch (err) {
    errLine(String(err && err.message ? err.message : err));
  }
}

// ── autocomplete menu ──
let menuItems = [];
let menuIndex = -1;

function commandQuery() {
  const v = textInput.value;
  if (!v.startsWith("/") || v.includes(" ")) return null;
  return v.slice(1).toLowerCase();
}

function hideMenu() {
  cmdMenu.hidden = true;
  menuItems = [];
  menuIndex = -1;
}

function renderMenu() {
  const q = commandQuery();
  if (q === null) { hideMenu(); return; }
  menuItems = COMMANDS.filter((c) => c.name.slice(1).startsWith(q));
  if (!menuItems.length) { hideMenu(); return; }
  if (menuIndex >= menuItems.length) menuIndex = menuItems.length - 1;
  cmdMenu.innerHTML = "";
  menuItems.forEach((c, i) => {
    const li = document.createElement("li");
    if (i === menuIndex) li.classList.add("active");
    const n = document.createElement("span");
    n.className = "cmd-name"; n.textContent = c.name;
    li.appendChild(n);
    if (c.args) {
      const a = document.createElement("span");
      a.className = "cmd-args"; a.textContent = c.args;
      li.appendChild(a);
    }
    const d = document.createElement("span");
    d.className = "cmd-desc"; d.textContent = cmdDesc(c.name);
    li.appendChild(d);
    li.addEventListener("mousedown", (e) => { e.preventDefault(); acceptMenu(i); });
    cmdMenu.appendChild(li);
  });
  cmdMenu.hidden = false;
}

function acceptMenu(i) {
  const c = menuItems[i] || menuItems[0];
  if (!c) return;
  // Complete to the command name + a trailing space, ready for args.
  textInput.value = c.name + " ";
  hideMenu();
  textInput.focus();
}

textInput.addEventListener("input", () => { menuIndex = -1; renderMenu(); });
textInput.addEventListener("blur", () => setTimeout(hideMenu, 120));
textInput.addEventListener("keydown", (e) => {
  if (cmdMenu.hidden || !menuItems.length) return;
  if (e.key === "ArrowDown") {
    e.preventDefault();
    menuIndex = (menuIndex + 1) % menuItems.length;
    renderMenu();
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    menuIndex = (menuIndex - 1 + menuItems.length) % menuItems.length;
    renderMenu();
  } else if (e.key === "Tab") {
    e.preventDefault();
    acceptMenu(menuIndex < 0 ? 0 : menuIndex);
  } else if (e.key === "Enter") {
    // Only intercept Enter when an item is actively highlighted; otherwise
    // let the form submit (so typing a full command + Enter runs it).
    if (menuIndex >= 0) { e.preventDefault(); acceptMenu(menuIndex); }
  } else if (e.key === "Escape") {
    e.preventDefault();
    hideMenu();
  }
});

textForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  hideMenu();
  const text = textInput.value.trim();
  if (!text) return;
  textInput.value = "";
  if (text.startsWith("/")) { await handleCommand(text); return; }
  if (!canSendText || !running) { sysLine(t("text_needs_session")); return; }
  try {
    await fetch("/api/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
  } catch {
    errLine("send failed");
  }
});

// ── File upload → wiki ──────────────────────────────────────────────────
// 📎 → pick a file → POST /api/upload (it's saved, not yet filed). Samantha
// then asks (by voice if a session is live) whether to keep it in the wiki or
// treat it as temporary; the two inline buttons resolve that either way.
function refreshWikiCount() {
  fetch("/api/config").then((r) => r.json()).then(renderHeaderConfig).catch(() => {});
}

function renderUploadActions(id, label) {
  const row = document.createElement("div");
  row.className = "upload-actions";
  const keepBtn = document.createElement("button");
  keepBtn.textContent = t("file_keep");
  const tempBtn = document.createElement("button");
  tempBtn.textContent = t("file_discard");
  const resolve = async (action, busyKey) => {
    keepBtn.disabled = tempBtn.disabled = true;
    sysLine(t(busyKey));
    const { ok, data } = await apiSend(`/api/upload/${id}/${action}`, "POST");
    if (!ok) { errLine(data.error || "error"); return; }
    if (data.message) appendLine("asst", t("who_asst"), data.message);
    if (action === "keep") refreshWikiCount();
  };
  keepBtn.addEventListener("click", () => resolve("keep", "file_filing"));
  tempBtn.addEventListener("click", () => resolve("discard", "file_reading"));
  row.appendChild(keepBtn);
  row.appendChild(tempBtn);
  terminalEl.appendChild(row);
  terminalEl.scrollTop = terminalEl.scrollHeight;
}

async function uploadFile(file) {
  if (!file) return;
  sysLine(t("file_uploading", { name: file.name }));
  const body = new FormData();
  body.append("file", file);
  let res, data = {};
  try {
    res = await fetch("/api/upload", { method: "POST", body });
    try { data = await res.json(); } catch {}
  } catch {
    errLine("upload failed");
    return;
  }
  if (!res.ok || !data.ok) { errLine(data.error || "upload failed"); return; }
  sysLine(t("file_ask", { name: data.label }));
  renderUploadActions(data.id, data.label);
}

attachBtn.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => {
  const file = fileInput.files && fileInput.files[0];
  fileInput.value = "";
  if (file) uploadFile(file);
});

// Drag & drop a file anywhere on the input bar → same flow as the 📎 button,
// with the text input highlighted as the drop target. Window-level handlers
// swallow stray drops so a misfire never navigates the app away from the file.
const inputBarEl = document.querySelector(".input-bar");
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => e.preventDefault());
if (inputBarEl) {
  inputBarEl.addEventListener("dragover", (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    textInput.classList.add("drag-over");
  });
  inputBarEl.addEventListener("dragleave", (e) => {
    if (!inputBarEl.contains(e.relatedTarget)) textInput.classList.remove("drag-over");
  });
  inputBarEl.addEventListener("drop", (e) => {
    e.preventDefault();
    textInput.classList.remove("drag-over");
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) uploadFile(file);
  });
}

let lastConfig = null;
function renderHeaderConfig(c) {
  lastConfig = c;
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
