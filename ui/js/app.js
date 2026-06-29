// Magpie UI — vanilla JS, no build step. Talks to the FastAPI backend.

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (res.status === 401) {            // session missing/expired → back to login
    showAuthGate();
    throw new Error("not authenticated");
  }
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

// ---------- view switching ----------
function showView(name) {
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
  $$("#tabs button[data-view]").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === name)
  );
  if (name === "history") loadHistory();
  if (name === "hoard") loadHoard();
  if (name === "path") { /* roadmap built on demand */ }
  if (name === "onboard") loadProfile();
  if (name === "status") loadStatus();
}
$$("#tabs button[data-view]").forEach((b) =>
  b.addEventListener("click", () => showView(b.dataset.view))
);

// ---------- theme ----------
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  $("#theme-toggle").textContent = theme === "dark" ? "☀️" : "🌙";
  localStorage.setItem("magpie-theme", theme);
}
function toggleTheme() {
  const cur = document.documentElement.getAttribute("data-theme");
  applyTheme(cur === "dark" ? "light" : "dark");
}
$("#theme-toggle").addEventListener("click", toggleTheme);
applyTheme(localStorage.getItem("magpie-theme") || "light");

// ---------- keyboard shortcuts ----------
const VIEW_BY_KEY = {
  1: "discover", 2: "history", 3: "hoard", 4: "path", 5: "onboard", 6: "status",
};
document.addEventListener("keydown", (e) => {
  const typing = ["INPUT", "TEXTAREA"].includes(document.activeElement.tagName);
  if (e.key === "Escape" && typing) { document.activeElement.blur(); return; }
  if (typing) return;
  if (e.key === "/") { e.preventDefault(); showView("discover"); $("#prompt").focus(); }
  else if (e.key === "t") toggleTheme();
  else if (VIEW_BY_KEY[e.key]) showView(VIEW_BY_KEY[e.key]);
});

// ---------- discover ----------
// Stage → friendly scribble shown while foraging.
const STAGE_LABEL = {
  plan: "planning what to search…",
  search: "searching the web…",
  scrape: "reading articles…",
  rank: "ranking by relevance to you…",
};

let activeStream = null;

$("#discover-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const prompt = $("#prompt").value.trim();
  if (!prompt) return;
  const status = $("#discover-status");
  const cardsEl = $("#cards");
  cardsEl.innerHTML = "";
  status.textContent = "starting the hunt… 🐦";

  if (activeStream) activeStream.close();
  const es = new EventSource(
    `/api/discover/stream?prompt=${encodeURIComponent(prompt)}`
  );
  activeStream = es;

  es.addEventListener("progress", (ev) => {
    const { stage, message } = JSON.parse(ev.data);
    status.textContent = `${STAGE_LABEL[stage] || stage} ${message ? "— " + message : ""}`;
  });

  es.addEventListener("done", (ev) => {
    es.close();
    const { cards } = JSON.parse(ev.data);
    status.textContent = cards.length ? `found ${cards.length} shiny things` : "";
    if (!cards.length) {
      cardsEl.innerHTML = `<p class="empty">nothing new & relevant — try another prompt</p>`;
      return;
    }
    cards.forEach((c) => cardsEl.appendChild(renderCard(c)));
  });

  es.addEventListener("error", (ev) => {
    es.close();
    let msg = "connection lost";
    try { msg = JSON.parse(ev.data).message; } catch (_) {}
    status.innerHTML = `<span class="bad">error: ${escapeHtml(msg)}. Is the model running? Check Status.</span>`;
  });
});

// ---------- adjacency suggestions ----------
async function loadSuggestions() {
  const box = $("#suggestions");
  box.innerHTML = `<span class="suggest-chip loading">thinking…</span>`;
  try {
    const { suggestions } = await api("/api/suggestions");
    if (!suggestions.length) {
      box.innerHTML = `<span class="suggest-empty">add skills in Profile first</span>`;
      return;
    }
    box.innerHTML = "";
    suggestions.forEach((s) => {
      const chip = document.createElement("button");
      chip.className = "suggest-chip";
      chip.textContent = s.topic;
      chip.title = s.reason || "";
      chip.addEventListener("click", () => {
        $("#prompt").value = s.topic;
        $("#discover-form").requestSubmit();
      });
      box.appendChild(chip);
    });
  } catch (err) {
    box.innerHTML = `<span class="suggest-empty">${escapeHtml(err.message)}</span>`;
  }
}
$("#refresh-suggest").addEventListener("click", loadSuggestions);

function renderCard(c) {
  const el = document.createElement("article");
  el.className = "card";
  const links = (c.links || [])
    .map((u) => `<a href="${u}" target="_blank" rel="noopener">${u}</a>`)
    .join("<br>");
  const tags = (c.tags || []).map((t) => `<span class="tag">${t}</span>`).join("");
  el.innerHTML = `
    <span class="relevance">relevance ${(c.relevance_score ?? 0).toFixed(2)}</span>
    <h3>${escapeHtml(c.title)}</h3>
    <p class="overview">${escapeHtml(c.overview || "")}</p>
    ${c.why_relevant ? `<p class="why">Why relevant: ${escapeHtml(c.why_relevant)}</p>` : ""}
    <div class="links">${links}</div>
    <div class="tags">${tags}</div>
    <div class="card-actions">
      <button class="learn">＋ Add to hoard</button>
      <button class="skip">Skip</button>
      <span class="feedback">
        <button class="fb" data-type="thumbs_up" title="More like this">👍</button>
        <button class="fb" data-type="thumbs_down" title="Less like this">👎</button>
        <button class="fb" data-type="too_basic" title="Too basic">too basic</button>
        <button class="fb" data-type="too_advanced" title="Too advanced">too advanced</button>
        <button class="fb" data-type="irrelevant" title="Not relevant">irrelevant</button>
      </span>
    </div>`;
  // Feedback buttons tune future ranking (need a persisted card id).
  el.querySelectorAll(".fb").forEach((b) => {
    if (c.id == null) { b.disabled = true; return; }
    b.addEventListener("click", async () => {
      await api("/api/signal", {
        method: "POST",
        body: JSON.stringify({ card_id: c.id, type: b.dataset.type }),
      });
      el.querySelectorAll(".fb").forEach((x) => x.classList.remove("chosen"));
      b.classList.add("chosen");
    });
  });
  const learnBtn = el.querySelector(".learn");
  if (c.status === "learned") {
    el.classList.add("learned");
    learnBtn.textContent = "✓ Hoarded";
  }
  learnBtn.addEventListener("click", async (ev) => {
    await api("/api/learn", {
      method: "POST",
      body: JSON.stringify({
        card_id: c.id ?? null, title: c.title, overview: c.overview || "",
        source_url: c.source_url ?? null, tags: c.tags || [],
      }),
    });
    el.classList.add("learned");
    ev.target.textContent = "✓ Hoarded";
  });
  el.querySelector(".skip").addEventListener("click", () => el.remove());
  return el;
}

// ---------- history ----------
async function loadHistory() {
  const el = $("#history");
  $("#history-cards").innerHTML = "";
  const { runs } = await api("/api/history");
  if (!runs.length) {
    el.innerHTML = `<p class="empty">no past hunts yet — go discover something</p>`;
    return;
  }
  el.innerHTML = "";
  runs.forEach((r) => {
    const btn = document.createElement("button");
    btn.className = "run";
    const when = new Date(r.created_at).toLocaleString();
    btn.innerHTML =
      `<span class="prompt">${escapeHtml(r.prompt)}</span>` +
      `<span class="meta">${r.cards} cards · ${when} ` +
      `<span class="del" title="Delete this run">✕</span></span>`;
    btn.addEventListener("click", (ev) => {
      if (ev.target.classList.contains("del")) return; // handled below
      openRun(r.id, btn);
    });
    btn.querySelector(".del").addEventListener("click", async (ev) => {
      ev.stopPropagation();
      if (!confirm("Delete this run and its saved cards?")) return;
      await api(`/api/run/${r.id}`, { method: "DELETE" });
      loadHistory();
    });
    el.appendChild(btn);
  });
}

async function openRun(runId, btn) {
  $$("#history .run").forEach((b) => b.classList.remove("active"));
  btn.classList.add("active");
  const wrap = $("#history-cards");
  wrap.innerHTML = `<p class="status-line">loading…</p>`;
  const { cards } = await api(`/api/run/${runId}`);
  wrap.innerHTML = "";
  if (!cards.length) {
    wrap.innerHTML = `<p class="empty">this run saved no cards</p>`;
    return;
  }
  cards.forEach((c) => wrap.appendChild(renderCard(c)));
}

// ---------- hoard ----------
async function loadHoard() {
  const el = $("#hoard");
  const { learned } = await api("/api/learned");
  lastLearned = learned;
  setHoardMode("list");
  if (!learned.length) {
    el.innerHTML = `<p class="empty">empty hoard — go forage something</p>`;
    return;
  }
  el.innerHTML = "";
  learned.forEach((t) => {
    const item = document.createElement("div");
    item.className = "item";
    item.innerHTML =
      `<div class="item-body"><h4>${escapeHtml(t.title)}</h4>` +
      `${t.summary ? `<div>${escapeHtml(t.summary)}</div>` : ""}</div>` +
      `<button class="del" title="Forget this">✕</button>`;
    item.querySelector(".del").addEventListener("click", async () => {
      if (!confirm(`Forget "${t.title}"? Magpie may surface it again later.`)) return;
      await api(`/api/learned/${t.id}`, { method: "DELETE" });
      item.remove();
      if (!$("#hoard").children.length)
        $("#hoard").innerHTML = `<p class="empty">empty hoard — go forage something</p>`;
    });
    el.appendChild(item);
  });
}

// ---------- hoard: list / graph toggle ----------
let lastLearned = [];
$("#view-list").addEventListener("click", () => setHoardMode("list"));
$("#view-graph").addEventListener("click", () => setHoardMode("graph"));

function setHoardMode(mode) {
  const graph = mode === "graph";
  $("#hoard").style.display = graph ? "none" : "";
  $("#hoard-graph").style.display = graph ? "" : "none";
  $("#view-list").classList.toggle("active", !graph);
  $("#view-graph").classList.toggle("active", graph);
  if (graph) renderGraph(lastLearned);
}

// Lightweight dependency-free force layout: topics linked to their tags.
function renderGraph(topics) {
  const svg = $("#hoard-graph");
  const W = svg.clientWidth || 800, H = 480;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.innerHTML = "";
  if (!topics.length) {
    svg.innerHTML = `<text x="50%" y="50%" text-anchor="middle" fill="#9aa1ad">empty hoard</text>`;
    return;
  }
  // Build nodes (topics + distinct tags) and edges (topic—tag).
  const nodes = [], idx = {}, edges = [];
  const add = (id, label, kind) => {
    if (idx[id] != null) return idx[id];
    idx[id] = nodes.length;
    nodes.push({ id, label, kind,
      x: W / 2 + (Math.random() - 0.5) * 200, y: H / 2 + (Math.random() - 0.5) * 200,
      vx: 0, vy: 0 });
    return idx[id];
  };
  topics.forEach((t, i) => {
    const tn = add("t" + i, t.title, "topic");
    (t.tags || []).forEach((tag) => edges.push([tn, add("tag:" + tag, tag, "tag")]));
  });
  // Simple force sim: repulsion between all, springs along edges, center pull.
  for (let iter = 0; iter < 220; iter++) {
    for (let a = 0; a < nodes.length; a++) {
      for (let b = a + 1; b < nodes.length; b++) {
        let dx = nodes[a].x - nodes[b].x, dy = nodes[a].y - nodes[b].y;
        let d2 = dx * dx + dy * dy || 0.01, f = 1800 / d2;
        let d = Math.sqrt(d2);
        nodes[a].vx += (dx / d) * f; nodes[a].vy += (dy / d) * f;
        nodes[b].vx -= (dx / d) * f; nodes[b].vy -= (dy / d) * f;
      }
    }
    edges.forEach(([a, b]) => {
      let dx = nodes[b].x - nodes[a].x, dy = nodes[b].y - nodes[a].y;
      let d = Math.sqrt(dx * dx + dy * dy) || 0.01, f = (d - 90) * 0.02;
      nodes[a].vx += (dx / d) * f; nodes[a].vy += (dy / d) * f;
      nodes[b].vx -= (dx / d) * f; nodes[b].vy -= (dy / d) * f;
    });
    nodes.forEach((n) => {
      n.vx += (W / 2 - n.x) * 0.002; n.vy += (H / 2 - n.y) * 0.002;
      n.x += n.vx *= 0.85; n.y += n.vy *= 0.85;
      n.x = Math.max(20, Math.min(W - 20, n.x));
      n.y = Math.max(20, Math.min(H - 20, n.y));
    });
  }
  const ns = "http://www.w3.org/2000/svg";
  edges.forEach(([a, b]) => {
    const l = document.createElementNS(ns, "line");
    l.setAttribute("x1", nodes[a].x); l.setAttribute("y1", nodes[a].y);
    l.setAttribute("x2", nodes[b].x); l.setAttribute("y2", nodes[b].y);
    l.setAttribute("class", "edge");
    svg.appendChild(l);
  });
  nodes.forEach((n) => {
    const g = document.createElementNS(ns, "g");
    const c = document.createElementNS(ns, "circle");
    c.setAttribute("cx", n.x); c.setAttribute("cy", n.y);
    c.setAttribute("r", n.kind === "tag" ? 6 : 9);
    c.setAttribute("class", "node " + n.kind);
    const txt = document.createElementNS(ns, "text");
    txt.setAttribute("x", n.x + 11); txt.setAttribute("y", n.y + 4);
    txt.setAttribute("class", "node-label " + n.kind);
    txt.textContent = n.label.length > 26 ? n.label.slice(0, 25) + "…" : n.label;
    g.appendChild(c); g.appendChild(txt); svg.appendChild(g);
  });
}

// ---------- roadmap ----------
$("#build-roadmap").addEventListener("click", loadRoadmap);
async function loadRoadmap() {
  const ol = $("#roadmap");
  ol.innerHTML = `<li class="status-line">planning your path…</li>`;
  try {
    const { roadmap } = await api("/api/roadmap");
    if (!roadmap.length) {
      ol.innerHTML = `<li class="empty">add skills/learned topics first</li>`;
      return;
    }
    ol.innerHTML = "";
    roadmap.forEach((s) => {
      const li = document.createElement("li");
      li.className = "step";
      li.innerHTML =
        `<button class="step-topic">${escapeHtml(s.topic)}</button>` +
        `${s.reason ? `<div class="step-reason">${escapeHtml(s.reason)}</div>` : ""}`;
      li.querySelector(".step-topic").addEventListener("click", () => {
        $("#prompt").value = s.topic;
        showView("discover");
        $("#discover-form").requestSubmit();
      });
      ol.appendChild(li);
    });
  } catch (err) {
    ol.innerHTML = `<li class="bad">error: ${escapeHtml(err.message)}</li>`;
  }
}

// ---------- profile / onboard ----------
async function loadProfile() {
  const prof = await api("/api/profile");
  const summary = $("#profile-summary");
  if (!prof.domains.length) {
    summary.innerHTML = `<span class="empty">no profile yet — fill the form below</span>`;
  } else {
    summary.innerHTML = prof.domains
      .map(
        (d) => `<div><strong>${escapeHtml(d.name)}</strong>: ` +
          (d.skills.map((s) => `<span class="pill">${escapeHtml(s)}</span>`).join("") || "—") +
          `</div>`
      )
      .join("");
  }
  // build per-domain skill inputs from the domains field
  renderSkillFields();
}

function renderSkillFields() {
  const domains = splitCsv($("#domains").value);
  const box = $("#skills-fields");
  box.innerHTML = domains
    .map(
      (d) => `<label>Skills under ${escapeHtml(d)}
        <input class="skill-input" data-domain="${escapeHtml(d)}" placeholder="comma separated" /></label>`
    )
    .join("");
}
$("#domains").addEventListener("input", renderSkillFields);

$("#onboard-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const domains = splitCsv($("#domains").value);
  const skills = {};
  $$(".skill-input").forEach((i) => { skills[i.dataset.domain] = splitCsv(i.value); });
  const known = splitCsv($("#known").value);
  await api("/api/init", {
    method: "POST",
    body: JSON.stringify({ domains, skills, known }),
  });
  loadProfile();
});

// ---------- status ----------
async function loadStatus() {
  const box = $("#status-box");
  box.textContent = "Checking…";
  try {
    const h = await api("/api/health");
    box.innerHTML = h.ok
      ? `<span class="ok">✓ Ollama reachable</span> at ${h.host}<br>
         model: <strong>${h.resolved_model}</strong><br>
         available: ${h.available.join(", ")}`
      : `<span class="bad">✗ ${escapeHtml(h.error)}</span>`;
  } catch (err) {
    box.innerHTML = `<span class="bad">✗ ${err.message}</span>`;
  }
}

// ---------- utils ----------
function splitCsv(s) {
  return (s || "").split(",").map((x) => x.trim()).filter(Boolean);
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---------- auth ----------
let authMode = "login";

function pickError(data, status) {
  const d = data && data.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d) && d.length) return d[0].msg || "invalid input";
  return `error ${status}`;
}

function setAuthMode(mode) {
  authMode = mode;
  const signup = mode === "signup";
  $("#tab-login").classList.toggle("active", !signup);
  $("#tab-signup").classList.toggle("active", signup);
  $("#name-row").hidden = !signup;
  $("#auth-submit").textContent = signup ? "Sign up" : "Log in";
  $("#auth-password").autocomplete = signup ? "new-password" : "current-password";
  $("#auth-error").hidden = true;
}
$("#tab-login").addEventListener("click", () => setAuthMode("login"));
$("#tab-signup").addEventListener("click", () => setAuthMode("signup"));

$("#pw-toggle").addEventListener("click", () => {
  const input = $("#auth-password");
  const btn = $("#pw-toggle");
  const show = input.type === "password";
  input.type = show ? "text" : "password";
  btn.textContent = show ? "Hide" : "Show";
  btn.setAttribute("aria-pressed", String(show));
  btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
});

function showAuthGate() {
  $("#auth-gate").hidden = false;
  $("#user-box").hidden = true;
  // Show the Google button only when the server has OAuth configured.
  fetch("/api/auth/config")
    .then((r) => r.json())
    .then((c) => { $("#google-row").hidden = !c.google_enabled; })
    .catch(() => {});
}

function onAuthed(user) {
  $("#auth-gate").hidden = true;
  $("#user-box").hidden = false;
  $("#user-email").textContent = user.email;
  $("#user-email").title = user.email;
  loadSuggestions();
}

$("#auth-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const err = $("#auth-error");
  err.hidden = true;
  const email = $("#auth-email").value.trim();
  const password = $("#auth-password").value;
  const display_name = $("#auth-name").value.trim();
  const signup = authMode === "signup";
  const body = signup ? { email, password, display_name } : { email, password };
  try {
    const res = await fetch(signup ? "/api/auth/signup" : "/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(pickError(data, res.status));
    onAuthed(data);
  } catch (e2) {
    err.textContent = e2.message;
    err.hidden = false;
  }
});

$("#logout-btn").addEventListener("click", async () => {
  await fetch("/api/auth/logout", { method: "POST" }).catch(() => {});
  location.reload();
});

// ---------- startup ----------
async function boot() {
  try {
    const res = await fetch("/api/auth/me");
    if (res.ok) { onAuthed(await res.json()); return; }
  } catch (_) { /* fall through to login */ }
  showAuthGate();
}
boot();
