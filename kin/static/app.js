// Kin family dashboard. All untrusted text goes through textContent (el() helper); never innerHTML.
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  let state = { people: [], todos: [], items: [], alerts: [], purchases: [], transcript: [], status: {}, config: {} };
  let live = false;
  let loaded = false;                 // first snapshot rendered (so we don't animate the whole page on load)
  const acked = new Set();            // alerts acknowledged in this browser (server also stores seen=1)
  const newUntil = new Map();         // person id -> timestamp until which the card shows as NEW

  const CATEGORY = {
    small_talk: "small talk", transaction: "transaction", person_fact: "about someone", plan: "plan",
    item_location: "where things are", health: "health", money_safety: "scam risk", emotional: "family news", other: "noted",
  };
  const ALERT = {
    scam: { icon: "⚠️", label: "Possible scam", tone: "bad" },
    fall: { icon: "🆘", label: "Possible fall", tone: "bad" },
    fall_emergency: { icon: "🚨", label: "No response after fall", tone: "bad" },
    fall_ok: { icon: "✅", label: "Fall check: they're okay", tone: "ok" },
    spending: { icon: "💳", label: "Purchase blocked", tone: "bad" },
  };

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }
  function ago(ts) {
    if (!ts) return "";
    const m = Math.floor((Date.now() / 1000 - ts) / 60);
    if (m < 1) return "just now";
    if (m < 60) return m + " min ago";
    if (m < 1440) return Math.floor(m / 60) + " h ago";
    return Math.floor(m / 1440) + " d ago";
  }
  function clock(ts) {
    return new Date(ts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }
  function money(c) { return "$" + (Number(c || 0) / 100).toFixed(2); }
  function cap(s) { s = String(s || ""); return s.charAt(0).toUpperCase() + s.slice(1); }

  // Keyed list rendering: reuse a node while its content signature is unchanged, so animations
  // only play for things that are actually new or changed (not on every refresh).
  function keyed(container, rows, key, sig, build, onChange) {
    const old = new Map();
    for (const n of container.children) old.set(n.dataset.key, n);
    const nodes = rows.map((r) => {
      const k = String(key(r)), s = sig(r);
      const prev = old.get(k);
      if (prev && prev.dataset.sig === s) return prev;
      const n = build(r, prev);
      n.dataset.key = k; n.dataset.sig = s;
      if (loaded && onChange) onChange(n, r, prev);
      return n;
    });
    // Only touch the DOM if the order or nodes changed (keeps running animations alive).
    const same = nodes.length === container.children.length && nodes.every((n, i) => container.children[i] === n);
    if (!same) container.replaceChildren(...nodes);
    return nodes.length;
  }
  function toggleEmpty(emptyId, count) { const e = $(emptyId); if (e) e.hidden = count > 0; }

  // ---------- status strip ----------
  function renderStatus() {
    const s = state.status || {};
    const asking = s.mode === "ask";
    const mode = $("mode");
    if (!live) { mode.className = "mode mode-off"; $("mode-text").textContent = "OFFLINE"; }
    else {
      mode.className = "mode " + (asking ? "mode-ask" : "mode-listen");
      $("mode-text").textContent = asking ? "ASKING KIN" : "LISTENING";
    }
    document.body.classList.toggle("asking", live && asking);
    const band = ["connected", "sim", "disconnected"].includes(s.band) ? s.band : "disconnected";
    $("band").className = "chip-status band-" + band;
    $("band-text").textContent = band === "connected" ? "Band connected" : band === "sim" ? "Band simulated" : "Band offline";
    const note = $("note");
    note.textContent = s.note || "";
    note.hidden = !s.note;
    if (state.config.wearer) {
      $("wearer").textContent = state.config.wearer;
      document.title = "Kin · " + state.config.wearer;
    }
    $("limit").textContent = state.config.spend_limit_cents ? "limit " + money(state.config.spend_limit_cents) : "";
  }
  function renderLive() {
    $("live").className = "chip-status " + (live ? "live-on" : "live-off");
    $("live-text").textContent = live ? "Live" : "Reconnecting…";
    renderStatus();
  }
  function tick() { $("clock").textContent = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); }

  // ---------- Kin is speaking ----------
  let speakTimer = null, speakHide = null;
  function showSpeaking(text) {
    const box = $("speaking");
    clearTimeout(speakTimer); clearTimeout(speakHide);
    $("speaking-text").textContent = text;
    box.classList.remove("out");
    if (box.hidden) { box.hidden = false; } else { box.style.animation = "none"; void box.offsetWidth; box.style.animation = ""; }
    const words = String(text).split(/\s+/).length;
    const ms = Math.min(14000, Math.max(5000, words * 420 + 2000));
    speakTimer = setTimeout(() => {
      box.classList.add("out");
      speakHide = setTimeout(() => { box.hidden = true; box.classList.remove("out"); }, 400);
    }, ms);
  }

  // ---------- transcript ----------
  function speakerName(l) {
    if (l.speaker === "kin") return "Kin";
    if (l.name) return l.name;
    if (l.speaker === "wearer") return state.config.wearer || "Wearer";
    return cap(l.speaker || "Someone");
  }
  // A question to Kin is never rated; it's the unrated line just before Kin's reply.
  function isQuestion(l) {
    if (Number(l.importance) >= 0 || l.speaker === "kin") return false;
    const i = state.transcript.indexOf(l);
    const next = i >= 0 ? state.transcript[i + 1] : null;
    return !!(next && next.speaker === "kin");
  }
  function lineNode(l) {
    let imp = Number(l.importance);
    const isKin = l.speaker === "kin";
    const asked = isQuestion(l);
    if (imp < 0 && !asked && l.ts && Date.now() / 1000 - l.ts > 45) imp = 1;   // never rated: show plain
    const cls = isKin ? "kin" : asked ? "asked" : imp < 0 ? "imp-pending" : "imp-" + Math.min(imp, 3);
    const li = el("li", "line " + cls);
    li.dataset.id = l.id;
    li.appendChild(el("span", "who", speakerName(l)));
    li.appendChild(el("span", "text", l.text));
    if (asked) li.appendChild(el("span", "chip", "asked Kin"));
    else if (!isKin && imp >= 1 && l.category && l.category !== "small_talk") {
      const chip = el("span", "chip", CATEGORY[l.category] || String(l.category).replace(/_/g, " "));
      if (l.category === "money_safety") chip.classList.add("danger");
      li.appendChild(chip);
    } else if (!isKin && imp === 0) {
      li.appendChild(el("span", "chip quiet", "small talk"));
    }
    li.appendChild(el("span", "time", clock(l.ts)));
    return li;
  }
  function nearBottom(box) { return box.scrollHeight - box.scrollTop - box.clientHeight < 120; }
  function renderTranscript() {
    const box = $("transcript");
    const stick = nearBottom(box);
    box.replaceChildren(...state.transcript.map(lineNode));
    toggleEmpty("transcript-empty", state.transcript.length);
    if (stick || !loaded) box.scrollTop = box.scrollHeight;
  }
  function addLine(row) {
    if (state.transcript.some((l) => l.id === row.id)) return;
    state.transcript.push(row);
    if (state.transcript.length > 200) { state.transcript.shift(); $("transcript").firstElementChild?.remove(); }
    const box = $("transcript");
    const stick = nearBottom(box);
    const n = lineNode(row);
    n.classList.add("fresh");
    box.appendChild(n);
    toggleEmpty("transcript-empty", 1);
    if (stick) box.scrollTop = box.scrollHeight;
    if (row.speaker === "kin") {
      const prev = state.transcript[state.transcript.length - 2];
      if (prev && isQuestion(prev)) rateLine({ id: prev.id, importance: prev.importance, category: prev.category });
      if (row.text) showSpeaking(row.text);
    }
  }
  function rateLine(row) {
    const l = state.transcript.find((x) => x.id === row.id);
    if (!l) return;
    l.importance = row.importance;
    l.category = row.category;
    const old = $("transcript").querySelector('[data-id="' + Number(row.id) + '"]');
    if (old) old.replaceWith(lineNode(l));
  }

  // ---------- people ----------
  const MAX_FACTS = 4;
  function personCard(p, prev) {
    const c = el("article", "card");
    const top = el("div", "card-top");
    top.appendChild(el("span", "avatar", (String(p.name || "?").trim().charAt(0) || "?").toUpperCase()));
    const head = el("div", "grow");
    head.appendChild(el("h3", null, p.name));
    const meta = el("div");
    if (p.relationship) meta.appendChild(el("span", "rel", p.relationship));
    if (p.last_seen) meta.appendChild(el("span", "seen", "seen " + ago(p.last_seen)));
    head.appendChild(meta);
    top.appendChild(head);
    c.appendChild(top);

    const facts = p.facts || [];
    const known = new Set(prev ? JSON.parse(prev.dataset.facts || "[]") : []);
    c.dataset.facts = JSON.stringify(facts.map((f) => f.id));
    if (!facts.length) c.appendChild(el("p", "no-facts", "No facts yet."));
    else {
      const ul = el("ul", "facts");
      facts.slice(0, MAX_FACTS).forEach((f) => {
        const li = el("li", loaded && prev && !known.has(f.id) ? "fresh-fact" : null);
        li.appendChild(el("span", "grow", f.text));
        const del = el("button", "ghost", "×");
        del.title = "Remove this fact";
        del.setAttribute("aria-label", "Remove fact: " + f.text);
        del.onclick = () => api("DELETE", "/api/fact/" + Number(f.id));
        li.appendChild(del);
        ul.appendChild(li);
      });
      c.appendChild(ul);
      if (facts.length > MAX_FACTS) c.appendChild(el("p", "more", "+ " + (facts.length - MAX_FACTS) + " more"));
    }
    if ((newUntil.get(p.id) || 0) > Date.now()) c.classList.add("new");
    return c;
  }
  function expireNew() {
    for (const c of $("people").querySelectorAll(".card.new")) {
      if ((newUntil.get(Number(c.dataset.key)) || 0) <= Date.now()) c.classList.remove("new");
    }
  }
  function renderPeople() {
    const rows = state.people.filter(Boolean);
    const n = keyed($("people"), rows, (p) => p.id,
      (p) => JSON.stringify([p.name, p.relationship, ago(p.last_seen), (p.facts || []).map((f) => [f.id, f.text])]),
      personCard,
      (node, p, prev) => {
        if (!prev) {
          newUntil.set(p.id, Date.now() + 9000);
          node.classList.add("new");
          node.scrollIntoView({ block: "nearest", behavior: "smooth" });
          setTimeout(expireNew, 9100);
        } else if (!node.classList.contains("new") && prev.dataset.facts !== node.dataset.facts) {
          node.classList.add("updated");
        }
      });
    toggleEmpty("people-empty", n);
  }

  // ---------- todos ----------
  function renderTodos() {
    const rows = state.todos.filter((t) => !t.done);
    const n = keyed($("todos"), rows, (t) => t.id, (t) => JSON.stringify([t.text, t.due]), (t) => {
      const li = el("li");
      const body = el("div", "grow");
      body.appendChild(el("div", "todo-text", t.text));
      if (t.due) body.appendChild(el("span", "due", t.due));
      li.appendChild(body);
      const b = el("button", "done", "Done ✓");
      b.onclick = () => { b.disabled = true; api("POST", "/api/todo/" + Number(t.id) + "/done"); };
      li.appendChild(b);
      return li;
    }, (node, t, prev) => { if (!prev) node.classList.add("fresh"); });
    toggleEmpty("todos-empty", n);
  }

  // ---------- items (latest location per item) ----------
  function renderItems() {
    const seen = new Set();
    const rows = state.items.filter((i) => {
      const k = String(i.item || "").toLowerCase();
      if (seen.has(k)) return false;
      seen.add(k); return true;
    });
    const n = keyed($("items"), rows, (i) => i.id, (i) => JSON.stringify([i.item, i.location, i.snapshot, ago(i.ts)]), (i) => {
      const li = el("li");
      if (i.snapshot) {
        const file = String(i.snapshot).split(/[\\/]/).pop();
        const img = el("img");
        img.alt = "Photo of " + i.item;
        img.src = "/snapshots/" + encodeURIComponent(file);
        img.onerror = () => img.remove();
        li.appendChild(img);
      }
      const body = el("div", "grow");
      body.appendChild(el("div", "item-name", i.item));
      body.appendChild(el("div", "item-loc", cap(i.location)));
      const meta = el("div", "src");
      if (i.source === "vision") meta.appendChild(el("span", "cam", "📷 seen by camera"));
      else meta.appendChild(el("span", null, "🎙 heard"));
      meta.appendChild(document.createTextNode(" · " + ago(i.ts)));
      body.appendChild(meta);
      li.appendChild(body);
      return li;
    }, (node, i, prev) => { if (!prev) node.classList.add("fresh"); });
    toggleEmpty("items-empty", n);
  }

  // ---------- alerts: pinned until acknowledged ----------
  function isOpen(a) { return !Number(a.seen) && !acked.has(a.id); }
  // A fall followed by "they're okay" shows as one calm pin; acknowledging it clears both.
  function resolvedBy(a) {
    if (a.kind !== "fall") return null;
    return state.alerts.find((b) => b.kind === "fall_ok" && b.ts >= a.ts && isOpen(b)) || null;
  }
  function acknowledge(a, node) {
    const ids = [a.id].concat(a.kind === "fall_ok"
      ? state.alerts.filter((f) => f.kind === "fall" && f.ts <= a.ts && isOpen(f)).map((f) => f.id) : []);
    ids.forEach((id) => { acked.add(id); api("POST", "/api/alert/" + Number(id) + "/seen"); });
    if (node) node.remove();
    renderAlerts();
  }
  function renderAlerts() {
    const open = state.alerts.filter((a) => isOpen(a) && !resolvedBy(a)).sort((x, y) => x.ts - y.ts);
    const pinned = $("pinned");
    keyed(pinned, open, (a) => a.id, (a) => JSON.stringify([a.kind, a.text]), (a) => {
      const meta = ALERT[a.kind] || { icon: "⚠️", label: cap(String(a.kind || "alert").replace(/_/g, " ")), tone: "bad" };
      const d = el("div", "pin" + (meta.tone === "ok" ? " calm" : ""));
      d.setAttribute("role", "alert");
      d.appendChild(el("span", "pin-icon", meta.icon));
      const body = el("div", "grow");
      body.appendChild(el("div", "pin-kind", meta.label));
      body.appendChild(el("div", "pin-text", a.text));
      d.appendChild(body);
      d.appendChild(el("span", "pin-time", clock(a.ts)));
      const b = el("button", null, "Got it ✓");
      b.onclick = () => acknowledge(a, d);
      d.appendChild(b);
      return d;
    });
    pinned.hidden = open.length === 0;

    const done = state.alerts.filter((a) => !isOpen(a) || resolvedBy(a)).slice(0, 3);
    const n = keyed($("history"), done, (a) => a.id, (a) => JSON.stringify([a.kind, a.text, ago(a.ts)]), (a) => {
      const li = el("li");
      const meta = ALERT[a.kind];
      li.appendChild(el("span", "pill " + (meta && meta.tone === "ok" ? "ok" : "bad"), meta ? meta.label : (a.kind || "alert")));
      li.appendChild(el("span", "grow", a.text));
      li.appendChild(el("span", "time", ago(a.ts)));
      return li;
    });
    $("history-panel").hidden = n === 0;
  }

  // ---------- purchases ----------
  function renderPurchases() {
    const n = keyed($("purchases"), state.purchases, (p) => p.id, (p) => JSON.stringify([p.status, p.reason]), (p) => {
      const li = el("li");
      const ok = /^(allowed|approved|succeeded|paid|ok)$/i.test(p.status || "");
      li.appendChild(el("span", "pill " + (ok ? "ok" : "bad"), ok ? "allowed" : (p.status || "blocked")));
      const body = el("div", "grow");
      body.appendChild(el("div", null, (p.item || "") + (p.merchant ? " · " + p.merchant : "")));
      if (p.reason) body.appendChild(el("span", "reason", p.reason));
      li.appendChild(body);
      li.appendChild(el("span", "amount", money(p.amount_cents)));
      return li;
    });
    $("purchases-panel").hidden = n === 0;
  }

  function renderAll() {
    const box = $("transcript");
    const stick = !loaded || nearBottom(box);
    renderStatus(); renderTranscript(); renderPeople(); renderTodos();
    renderItems(); renderAlerts(); renderPurchases();
    if (stick) requestAnimationFrame(() => { box.scrollTop = box.scrollHeight; });
    loaded = true;
  }

  // ---------- data ----------
  async function api(method, url, body) {
    try {
      const r = await fetch(url, {
        method, headers: body ? { "Content-Type": "application/json" } : {},
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!r.ok) console.warn(method, url, r.status);
      scheduleRefresh();
      return r.ok ? r.json() : null;
    } catch (e) { console.warn(e); }
  }
  async function refresh() {
    try {
      const r = await fetch("/api/snapshot", { cache: "no-store" });
      const s = await r.json();
      state = Object.assign(state, s);
      renderAll();
    } catch (e) { console.warn("snapshot failed", e); }
  }
  let refreshTimer = null;
  function scheduleRefresh() {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(refresh, 120);
  }

  function onEvent(ev) {
    const t = ev.table, row = ev.row || {};
    if (t === "status") { state.status = Object.assign({}, state.status, row); renderStatus(); }
    else if (t === "transcript") addLine(row);
    else if (t === "transcript_rated") rateLine(row);
    else scheduleRefresh();
  }

  let backoff = 500;
  function connect() {
    const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
    ws.onopen = () => { backoff = 500; live = true; renderLive(); refresh(); };
    ws.onmessage = (m) => { try { onEvent(JSON.parse(m.data)); } catch (e) { console.warn(e); } };
    ws.onclose = () => {
      live = false; renderLive();
      setTimeout(connect, backoff);
      backoff = Math.min(backoff * 2, 8000);
    };
  }

  // ---------- theme toggle (remembered per browser) ----------
  function applyTheme(t) {
    if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
    else delete document.documentElement.dataset.theme;
  }
  try { applyTheme(localStorage.getItem("kin-theme")); } catch (e) { /* storage blocked */ }
  $("theme").addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme ||
      (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    applyTheme(next);
    try { localStorage.setItem("kin-theme", next); } catch (e) { /* storage blocked */ }
  });

  $("person-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = $("p-name").value.trim();
    if (!name) return;
    await api("POST", "/api/person", { name, relationship: $("p-rel").value.trim() });
    $("p-name").value = ""; $("p-rel").value = "";
    $("p-name").closest("details").open = false;
  });

  setInterval(() => { renderPeople(); renderItems(); renderAlerts(); }, 30000); // refresh "x min ago"
  setInterval(tick, 5000); tick();
  renderLive();
  refresh();
  connect();
})();
