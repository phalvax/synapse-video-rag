// Web App Dataiku « Synapse » — onglet JS. Version corrigée du 28/09 (sélecteur de modèle).
// CORRECTIFS (cherchez « CORRECTIF ») :
// 1. Le modèle choisi vit dans state.llmId (plus dans un <select> caché qui pouvait ne pas suivre).
// 2. Le modèle réellement utilisé (renvoyé par /ask) s'affiche au-dessus de la réponse.
// 3. Suppression des 4 dernières lignes du gabarit Dataiku ($.getJSON('/first_api_call')) :
//    ici `$` est querySelector, donc `$.getJSON` levait une erreur au chargement.
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const backend = path => getWebAppBackendUrl(path);
const state = {
  theme: localStorage.getItem("synapse-theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"),
  screen: "search", mode: "synthese", videos: [], meetings: [], segments: [], activeVideoId: "",
  scopeOnly: false, history: [], loading: false, selectedFile: null,
  models: [], llmId: "",  // CORRECTIF 1 : source de vérité du modèle choisi
};

async function api(path, options = {}) {
  const response = await fetch(backend(path), {...options, headers: options.body instanceof FormData ? options.headers : {"Content-Type": "application/json", ...(options.headers || {})}});
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `${response.status} ${response.statusText}`);
  return payload;
}

function escapeHtml(value) { const box = document.createElement("div"); box.textContent = value == null ? "" : String(value); return box.innerHTML; }
const icon = id => `<svg aria-hidden="true"><use href="#${id}"></use></svg>`;
function fmtTime(seconds) { const n = Math.max(0, Math.floor(Number(seconds) || 0)); const h = Math.floor(n / 3600); const m = Math.floor((n % 3600) / 60); const s = n % 60; return h ? `${h}:${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}` : `${m}:${String(s).padStart(2,"0")}`; }
function fmtDuration(seconds) { const m = Math.round((Number(seconds) || 0) / 60); return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`; }
function fmtDate(value) { if (!value) return "Date non renseignée"; const date = new Date(`${value}T12:00:00`); return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("fr-FR", {day:"2-digit", month:"short", year:"numeric"}).format(date); }

let toastTimer;
function toast(message, error = false) { const node = $("#toast"); node.textContent = message; node.classList.toggle("is-error", error); node.classList.add("is-visible"); clearTimeout(toastTimer); toastTimer = setTimeout(() => node.classList.remove("is-visible"), 4800); }

function applyTheme() {
  document.documentElement.dataset.theme = state.theme;
  localStorage.setItem("synapse-theme", state.theme);
  $("#theme-toggle").innerHTML = `${icon(state.theme === "dark" ? "i-sun" : "i-moon")}<span>${state.theme === "dark" ? "Thème clair" : "Thème sombre"}</span>`;
}

function showScreen(name) {
  state.screen = name;
  $$(".screen").forEach(node => node.classList.toggle("is-active", node.id === `screen-${name}`));
  $$(".nav-item").forEach(node => node.classList.toggle("is-active", node.dataset.screen === name));
  $("#sidebar").classList.remove("is-open"); $("#sidebar-scrim").classList.remove("is-visible");
  if (name === "library") loadMeetings();
  if (name === "dashboard") loadStats();
  window.scrollTo({top: 0, behavior: "smooth"});
}

async function loadHealth() {
  try {
    const data = await api("health");
    $("#sidebar-health").textContent = `${data.video_count} médias · connectée`;
    $(".sidebar-status").classList.add("is-online");
  } catch (_) { $("#sidebar-health").textContent = "Connexion indisponible"; }
}

async function loadModels() {
  try {
    const data = await api("models");
    if (data.error) toast(`Liste des modèles indisponible : ${data.error}`, true);
    state.models = data.models || [];
    const configured = state.models.find(model => model.configured) || state.models[0];
    const select = $("#model-select");
    select.innerHTML = `<option value="">Choisir un modèle</option>` + state.models.map(model => `<option value="${escapeHtml(model.id)}">${escapeHtml(model.name)}</option>`).join("");
    setModel(configured?.id || "");
  } catch (error) { toast(`Modèles : ${error.message}`, true); }
}

// CORRECTIF 1 : un seul endroit change le modèle (état + select caché + menu).
function setModel(id) {
  state.llmId = id || "";
  const select = $("#model-select");
  if (select) select.value = state.llmId;
  renderModelPicker();
  console.debug("[Synapse] modèle choisi :", state.llmId || "(aucun)");
}

function modelProfile(model) {
  const value = `${model.id} ${model.name}`.toLowerCase();
  if (value.includes("sol")) return {tier: "MAX", note: "Raisonnement avancé", price: "Premium", tone: "sol"};
  if (value.includes("terra")) return {tier: "PRO", note: "Équilibre qualité / coût", price: "Standard", tone: "terra"};
  if (value.includes("luna")) return {tier: "ECO", note: "Rapide pour les recherches", price: "Économique", tone: "luna"};
  return {tier: "DATAIKU", note: "Modèle de la connexion active", price: "Configuré", tone: "default"};
}

function renderModelPicker() {
  const menu = $("#model-menu");
  const models = state.models, selectedId = state.llmId;
  const selected = models.find(model => model.id === selectedId);
  $("#model-current").textContent = selected ? selected.name : "Choisir un modèle";
  menu.innerHTML = models.length ? models.map(model => {
    const profile = modelProfile(model);
    return `<button class="model-option ${model.id === selectedId ? "is-selected" : ""}" type="button" role="option" aria-selected="${model.id === selectedId}" data-model-id="${escapeHtml(model.id)}"><span class="model-option-mark ${profile.tone}">${icon("i-spark")}</span><span class="model-option-copy"><strong>${escapeHtml(model.name)}</strong><small>${profile.note}</small></span><span class="model-option-meta"><b>${profile.tier}</b><small>${profile.price}</small></span>${model.id === selectedId ? icon("i-check") : ""}</button>`;
  }).join("") : `<p class="model-empty">Aucun modèle Dataiku disponible.</p>`;
}

function closeModelPicker() {
  $("#model-picker").classList.remove("is-open");
  $("#model-trigger").setAttribute("aria-expanded", "false");
}

async function loadVideos(preferred = "") {
  const select = $("#video-select");
  try {
    const data = await api("videos");
    state.videos = data.videos || [];
    select.innerHTML = state.videos.length ? state.videos.map(video => `<option value="${escapeHtml(video.video_id)}">${escapeHtml(video.title)}</option>`).join("") : `<option value="">Aucune réunion indexée</option>`;
    const wanted = preferred || state.activeVideoId;
    state.activeVideoId = state.videos.some(video => video.video_id === wanted) ? wanted : (state.videos[0]?.video_id || "");
    select.value = state.activeVideoId;
    await activateVideo(state.activeVideoId);
  } catch (error) { select.innerHTML = `<option>Chargement impossible</option>`; toast(error.message, true); }
}

async function activateVideo(videoId, autoplay = false, seek = null) {
  state.activeVideoId = videoId;
  const video = state.videos.find(item => item.video_id === videoId);
  const audio = $("#audio-player");
  if (!video) { $("#media-title").textContent = "Sélectionnez une réunion"; $("#media-meta").textContent = "—"; audio.removeAttribute("src"); state.segments = []; renderTranscript(); return; }
  $("#video-select").value = videoId;
  $("#media-title").textContent = video.title;
  $("#media-meta").textContent = `${fmtDate(video.meeting_date)} · ${fmtDuration(video.duration_s)} · ${video.language}`;
  audio.src = backend(video.media_url);
  if (seek != null) audio.addEventListener("loadedmetadata", function ready() { audio.currentTime = Number(seek) || 0; if (autoplay) audio.play().catch(() => {}); audio.removeEventListener("loadedmetadata", ready); });
  updateScope();
  $("#transcript").innerHTML = `<p class="empty-copy">Chargement de la transcription…</p>`;
  try { const data = await api(`segments/${encodeURIComponent(videoId)}`); state.segments = data.segments || []; renderTranscript(); }
  catch (error) { state.segments = []; $("#transcript").innerHTML = `<p class="empty-copy">${escapeHtml(error.message)}</p>`; }
}

function updateScope() {
  const pill = $("#scope-pill");
  const video = state.videos.find(item => item.video_id === state.activeVideoId);
  if (state.scopeOnly && video) { pill.textContent = `Cible : ${video.title}`; pill.classList.remove("is-hidden"); }
  else pill.classList.add("is-hidden");
}

function renderTranscript() {
  const filter = $("#transcript-filter").value.trim().toLowerCase();
  const rows = state.segments.filter(row => !filter || row.text.toLowerCase().includes(filter));
  $("#transcript-count").textContent = `${rows.length} passage${rows.length > 1 ? "s" : ""}`;
  $("#transcript").innerHTML = rows.length ? rows.map(row => `<button class="transcript-row" data-time="${row.start_s}"><time>${fmtTime(row.start_s)}</time><span>${escapeHtml(row.text)}</span></button>`).join("") : `<p class="empty-copy">Aucun passage à afficher.</p>`;
  $$(".transcript-row").forEach(row => row.addEventListener("click", () => { $("#audio-player").currentTime = Number(row.dataset.time) || 0; $("#audio-player").play().catch(() => {}); }));
}

function renderLoading() {
  const start = Date.now();
  $("#answer-zone").innerHTML = `<div class="thinking card"><div class="thinking-orbit"><i></i></div><div><strong>Synapse analyse votre mémoire</strong><p>Recherche sémantique · vérification du contexte · génération sourcée</p></div><span id="elapsed">0 s</span></div>`;
  return setInterval(() => { const node = $("#elapsed"); if (node) node.textContent = `${Math.floor((Date.now() - start) / 1000)} s`; }, 250);
}

function linkCitations(value) { return escapeHtml(value).replace(/\[S(\d+)\]/g, '<span class="cite-ref">[S$1]</span>'); }

// CORRECTIF 2 : nom lisible du modèle qui a VRAIMENT répondu.
function modelName(id) { const model = state.models.find(item => item.id === id); return model ? model.name : String(id || "").split(":").pop(); }

function renderAnswer(data, question, elapsed) {
  if (data.not_found) { $("#answer-zone").innerHTML = `<div class="notice-card">${icon("i-search")}<div><strong>Aucune preuve suffisante</strong><p>${escapeHtml(data.note)}</p></div></div>`; return; }
  const reliability = data.reliability || {score: 0, label: "Non calculée", reasons: []};
  const sources = data.sources || [];
  const used = data.llm_used ? ` · ${escapeHtml(modelName(data.llm_id))}` : "";
  $("#answer-zone").innerHTML = `
    <article class="answer-card card"><div class="answer-label"><span>${data.mode === "strict" ? "EXTRAITS STRICTS" : "RÉPONSE SYNAPSE"}</span><span>${Math.max(1, Math.round(elapsed / 1000))} s${used}</span></div><h3>${escapeHtml(question)}</h3><div class="answer-copy">${linkCitations(data.answer || "")}</div>
      <div class="reliability"><div class="reliability-ring" style="--score:${reliability.score}"><strong>${reliability.score}</strong><small>/100</small></div><div><span>Fiabilité ${escapeHtml(reliability.label)}</span><p>Indice interne de qualité des preuves, pas une probabilité.</p><ul>${reliability.reasons.map(reason => `<li>${escapeHtml(reason)}</li>`).join("")}</ul></div></div>
    </article>
    <div class="sources-title"><div><span class="kicker">TRAÇABILITÉ</span><h3>Passages mobilisés</h3></div><b>${sources.length} source${sources.length > 1 ? "s" : ""}</b></div>
    <div class="source-list">${sources.map(source => { const meta = source.metadata || {}; const meeting = meta.meeting || {}; return `<button class="source-card" data-video="${escapeHtml(meta.video_id)}" data-time="${Number(meta.start_s) || 0}"><span class="source-index">${escapeHtml(source.id)}</span><span class="source-main"><span class="source-title"><strong>${escapeHtml(source.title)}</strong><time>${fmtTime(meta.start_s)}</time></span><span class="source-meta">${escapeHtml(meeting.author || "Auteur non renseigné")} · ${escapeHtml(fmtDate(meeting.meeting_date))}</span><span class="source-quote">${escapeHtml(source.text)}</span></span><span class="source-play">${icon("i-play")}</span></button>`; }).join("")}</div>`;
  $$(".source-card").forEach(card => card.addEventListener("click", async () => { await activateVideo(card.dataset.video, true, card.dataset.time); $(".evidence-panel").scrollIntoView({behavior:"smooth", block:"start"}); }));
}

async function askQuestion(question) {
  const clean = question.trim(); if (!clean || state.loading) return;
  state.loading = true; $("#question").value = clean; $("#ask-button").disabled = true; $("#ask-button span").textContent = "Analyse…";
  const started = Date.now(), timer = renderLoading();
  try {
    // CORRECTIF 1 : on envoie state.llmId (et non la valeur du <select> caché).
    const data = await api("ask", {method:"POST", body:JSON.stringify({question:clean, mode:state.mode, video_id:state.scopeOnly ? state.activeVideoId : "", llm_id:state.llmId, history:state.history.slice(-6)})});
    clearInterval(timer); renderAnswer(data, clean, Date.now() - started);
    state.history.push({role:"user", content:clean}, {role:"assistant", content:data.answer || ""});
    if (data.note && !data.llm_used && state.mode === "synthese") toast(data.note);
  } catch (error) { clearInterval(timer); $("#answer-zone").innerHTML = `<div class="notice-card is-error">${icon("i-shield")}<div><strong>Analyse interrompue</strong><p>${escapeHtml(error.message)}</p></div></div>`; }
  finally { state.loading = false; $("#ask-button").disabled = false; $("#ask-button span").textContent = "Analyser"; }
}

async function loadMeetings() {
  try { const data = await api("meetings"); state.meetings = data.meetings || []; renderMeetings(); }
  catch (error) { $("#meeting-list").innerHTML = `<div class="notice-card is-error">${escapeHtml(error.message)}</div>`; }
}

function renderMeetings() {
  const query = $("#library-search").value.trim().toLowerCase(), status = $("#library-status").value;
  const rows = state.meetings.filter(item => (!status || item.status === status) && (!query || [item.title, item.author, item.mission, item.description, ...(item.tags || [])].join(" ").toLowerCase().includes(query)));
  $("#library-count").textContent = `${rows.length} réunion${rows.length > 1 ? "s" : ""}`;
  $("#meeting-list").innerHTML = rows.length ? rows.map(item => `<article class="meeting-card card"><div class="meeting-date"><b>${item.meeting_date ? item.meeting_date.slice(8,10) : "—"}</b><span>${item.meeting_date ? fmtDate(item.meeting_date).split(" ")[1] : "date"}</span></div><div class="meeting-body"><div class="meeting-top"><span class="status-chip ${item.status}"><i></i>${item.status === "indexed" ? "Indexé" : "En traitement"}</span><span class="classification">${escapeHtml(item.classification || "Interne")}</span></div><h2>${escapeHtml(item.title)}</h2><p>${escapeHtml(item.description)}</p><div class="meeting-details"><span>${escapeHtml(item.author)}</span><span>${escapeHtml(item.mission)}</span><span>${escapeHtml(item.meeting_time || "")}</span></div><div class="tag-row">${(item.tags || []).map(tag => `<i>${escapeHtml(tag)}</i>`).join("")}</div></div>${item.video_id ? `<button class="round-action" data-open-video="${escapeHtml(item.video_id)}">${icon("i-play")}</button>` : `<span class="processing-mark"><span></span><span></span><span></span></span>`}</article>`).join("") : `<div class="empty-library"><span>${icon("i-library")}</span><h2>Aucune réunion trouvée</h2><p>Importez une première fiche ou modifiez vos filtres.</p></div>`;
  $$('[data-open-video]').forEach(button => button.addEventListener("click", async () => { showScreen("search"); await activateVideo(button.dataset.openVideo); }));
}

function selectFile(file) {
  if (!file) return; state.selectedFile = file;
  $("#drop-title").textContent = file.name; $("#drop-subtitle").textContent = `${(file.size / 1024 / 1024).toFixed(1)} Mo · prêt à envoyer`; $("#drop-zone").classList.add("has-file");
}

function uploadForm(event) {
  event.preventDefault();
  const form = event.currentTarget, file = state.selectedFile || $("#file-input").files?.[0];
  if (!file) { toast("Ajoutez un fichier audio ou vidéo.", true); return; }
  if (!form.reportValidity()) return;
  const data = new FormData(form); data.set("file", file);
  $("#upload-progress").classList.remove("is-hidden"); $("#upload-name").textContent = file.name; $("#upload-status").textContent = "Envoi sécurisé vers Dataiku…";
  $("#upload-percent").textContent = "0 %"; $("#upload-bar").style.width = "0%"; $("#upload-submit").disabled = true;
  const xhr = new XMLHttpRequest();
  xhr.upload.onprogress = e => { if (e.lengthComputable) { const p = Math.round(e.loaded / e.total * 100); $("#upload-percent").textContent = `${p} %`; $("#upload-bar").style.width = `${p}%`; } };
  xhr.onload = async () => { let payload = {}; try { payload = JSON.parse(xhr.responseText || "{}"); } catch (_) {} $("#upload-submit").disabled = false;
    if (xhr.status < 200 || xhr.status >= 300) { $("#upload-status").textContent = payload.error || "Échec de l’import"; toast(payload.error || "Échec de l’import", true); return; }
    $("#upload-percent").textContent = "100 %"; $("#upload-bar").style.width = "100%"; $("#upload-status").textContent = payload.message; $$(".pipeline span").forEach((node, index) => node.classList.toggle("is-active", index === 1)); toast(payload.message); form.reset(); state.selectedFile = null; $("#drop-zone").classList.remove("has-file"); $("#drop-title").textContent = "Déposer le fichier ici"; $("#drop-subtitle").textContent = "ou parcourir votre appareil"; $("#description-count").textContent = "0"; await Promise.allSettled([loadMeetings(), loadHealth()]);
  };
  xhr.onerror = () => { $("#upload-submit").disabled = false; toast("Connexion interrompue pendant l’envoi.", true); };
  xhr.open("POST", backend("upload")); xhr.send(data);
}

async function loadStats() {
  try {
    const data = await api("stats");
    const cards = [["i-file", data.video_count, "Médias indexés"], ["i-spark", data.chunk_count, "Passages recherchables"], ["i-clock", fmtDuration(data.duration_s), "Mémoire analysée"], ["i-shield", `${data.metadata_completion}%`, "Fiches complètes"]];
    $("#kpi-grid").innerHTML = cards.map(([id,value,label]) => `<article class="kpi-card card"><span>${icon(id)}</span><div><strong>${escapeHtml(value)}</strong><small>${escapeHtml(label)}</small></div></article>`).join("");
    const max = Math.max(1, ...data.last_videos.map(video => Number(video.segment_count) || 0));
    $("#coverage-chart").innerHTML = data.last_videos.map(video => `<div class="chart-bar" title="${escapeHtml(video.title)}"><i style="height:${Math.max(12, Number(video.segment_count) / max * 180)}px"></i><strong>${escapeHtml(video.title)}</strong><span>${video.segment_count}</span></div>`).join("") || `<p class="empty-copy">Aucune donnée.</p>`;
    $("#recent-videos").innerHTML = data.last_videos.map(video => `<div class="recent-item"><span>${icon("i-play")}</span><div><strong>${escapeHtml(video.title)}</strong><small>${fmtDate(video.meeting_date)} · ${fmtDuration(video.duration_s)}</small></div></div>`).join("") || `<p class="empty-copy">Aucun média.</p>`;
  } catch (error) { $("#kpi-grid").innerHTML = `<div class="notice-card is-error">${escapeHtml(error.message)}</div>`; }
}

function bindEvents() {
  $$(".nav-item").forEach(node => node.addEventListener("click", () => showScreen(node.dataset.screen)));
  $$('[data-go]').forEach(node => node.addEventListener("click", () => showScreen(node.dataset.go)));
  $("#theme-toggle").addEventListener("click", () => { state.theme = state.theme === "dark" ? "light" : "dark"; applyTheme(); });
  $("#menu-toggle").addEventListener("click", () => { $("#sidebar").classList.add("is-open"); $("#sidebar-scrim").classList.add("is-visible"); });
  $("#sidebar-scrim").addEventListener("click", () => { $("#sidebar").classList.remove("is-open"); $("#sidebar-scrim").classList.remove("is-visible"); });
  $("#model-trigger").addEventListener("click", () => { const picker = $("#model-picker"); const open = picker.classList.toggle("is-open"); $("#model-trigger").setAttribute("aria-expanded", String(open)); });
  // CORRECTIF 1 : un seul écouteur délégué sur le menu (il survit au re-rendu des options).
  $("#model-menu").addEventListener("click", event => { const option = event.target.closest("[data-model-id]"); if (!option) return; setModel(option.dataset.modelId); closeModelPicker(); });
  document.addEventListener("click", event => { if (!event.target.isConnected) return; if (!$("#model-picker").contains(event.target)) closeModelPicker(); });
  $$("[data-mode]").forEach(button => button.addEventListener("click", () => { state.mode = button.dataset.mode; $$("[data-mode]").forEach(node => node.classList.toggle("is-active", node === button)); $(".model-field").classList.toggle("is-hidden", state.mode === "strict"); }));
  $("#ask-form").addEventListener("submit", event => { event.preventDefault(); askQuestion($("#question").value); });
  $("#question").addEventListener("keydown", event => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); askQuestion(event.target.value); } });
  $$("#examples button").forEach(button => button.addEventListener("click", () => askQuestion(button.textContent)));
  $("#video-select").addEventListener("change", event => activateVideo(event.target.value)); $("#refresh-videos").addEventListener("click", () => loadVideos(state.activeVideoId));
  $("#scope-toggle").addEventListener("change", event => { state.scopeOnly = event.target.checked; updateScope(); }); $("#transcript-filter").addEventListener("input", renderTranscript);
  $("#library-search").addEventListener("input", renderMeetings); $("#library-status").addEventListener("change", renderMeetings); $("#refresh-stats").addEventListener("click", loadStats);
  $("#upload-form").addEventListener("submit", uploadForm); $("#file-input").addEventListener("change", event => selectFile(event.target.files?.[0]));
  $("#upload-form textarea[name=description]").addEventListener("input", event => $("#description-count").textContent = event.target.value.length);
  const drop = $("#drop-zone"); ["dragenter","dragover"].forEach(name => drop.addEventListener(name, event => { event.preventDefault(); drop.classList.add("is-dragging"); })); ["dragleave","drop"].forEach(name => drop.addEventListener(name, event => { event.preventDefault(); drop.classList.remove("is-dragging"); })); drop.addEventListener("drop", event => selectFile(event.dataTransfer.files?.[0]));
}

async function boot() {
  applyTheme(); bindEvents();
  const now = new Date(); $("#upload-form [name=meeting_date]").value = now.toISOString().slice(0,10); $("#upload-form [name=meeting_time]").value = `${String(now.getHours()).padStart(2,"0")}:${String(now.getMinutes()).padStart(2,"0")}`;
  await Promise.allSettled([loadHealth(), loadModels(), loadVideos(), loadMeetings(), loadStats()]);
}
boot();
