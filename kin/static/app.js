// Kin family dashboard. All untrusted text goes through textContent (el() helper); never innerHTML.
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  let state = { people: [], todos: [], items: [], alerts: [], purchases: [], transcript: [], status: {}, config: {} };

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
  function fill(listId, emptyId, nodes) {
    const list = $(listId);
    list.replaceChildren(...nodes);
    $(emptyId).hidden = nodes.length > 0;
  }

  // ---------- header ----------
  function renderStatus() {
    const s = state.status || {};
    const mode = $("mode");
    const asking = s.mode === "ask";
    mode.textContent = asking ? "ASKING" : "LISTENING";
    mode.className = "badge " + (asking ? "mode-ask" : "mode-listen");
    const band = s.band || "disconnected";
    $("band").className = "badge band-" + (["connected", "sim", "disconnected"].includes(band) ? band : "disconnected");
    $("band-text").textContent = band === "connected" ? "Band connected" : band === "sim" ? "Band simulated" : "Band offline";
    const note = $("note");
    note.textContent = s.note || "";
    note.hidden = !s.note;
    if (state.config.wearer) {
      $("wearer").textContent = state.config.wearer;
      document.title = "Kin · " + state.config.wearer;
    }
    if (state.config.spend_limit_cents) $("limit").textContent = "Limit per purchase: " + money(state.config.spend_limit_cents);
  }

  // ---------- transcript ----------
  function lineNode(l) {
    const imp = Number(l.importance);
    const cls = imp < 0 ? "imp-pending" : imp === 0 ? "imp-0" : imp === 1 ? "imp-1" : "imp-2";
    const li = el("li", "line " + cls);
    li.dataset.id = l.id;
    li.appendChild(el("span", "who", (l.name || l.speaker || "Someone") + ":"));
    li.appendChild(el("span", "text", l.text));
    if (imp >= 2 && l.category) li.appendChild(el("span", "chip", l.category));
    else if (imp === 1 && l.category) li.appendChild(el("span", "chip", l.category));
    li.appendChild(el("span", "time", clock(l.ts)));
    return li;
  }
  function renderTranscript() {
    const box = $("transcript");
    const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
    fill("transcript", "transcript-empty", state.transcript.map(lineNode));
    if (nearBottom) box.scrollTop = box.scrollHeight;
  }
  function addLine(row) {
    if (state.transcript.some((l) => l.id === row.id)) return;
    state.transcript.push(row);
    if (state.transcript.length > 200) state.transcript.shift();
    const box = $("transcript");
    const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
    const n = lineNode(row);
    n.classList.add("fresh");
    box.appendChild(n);
    $("transcript-empty").hidden = true;
    if (nearBottom) box.scrollTop = box.scrollHeight;
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
  function renderPeople() {
    fill("people", "people-empty", state.people.filter(Boolean).map((p) => {
      const c = el("article", "card");
      const h = el("h3", null, p.name);
      if (p.relationship) h.appendChild(el("span", "rel", p.relationship));
      c.appendChild(h);
      if (p.last_seen) c.appendChild(el("p", "seen", "Last seen " + ago(p.last_seen)));
      const ul = el("ul", "facts");
      (p.facts || []).forEach((f) => {
        const li = el("li");
        li.appendChild(el("span", "grow", f.text));
        const del = el("button", "ghost", "Remove");
        del.title = "Remove this fact";
        del.onclick = () => api("DELETE", "/api/fact/" + Number(f.id));
        li.appendChild(del);
        ul.appendChild(li);
      });
      if (!(p.facts || []).length) c.appendChild(el("p", "seen", "No facts yet."));
      else c.appendChild(ul);
      return c;
    }));
  }

  // ---------- todos ----------
  function renderTodos() {
    fill("todos", "todos-empty", state.todos.filter((t) => !t.done).map((t) => {
      const li = el("li");
      const body = el("div", "grow");
      body.appendChild(el("div", null, t.text));
      if (t.due) body.appendChild(el("span", "reason", "Due: " + t.due));
      li.appendChild(body);
      const b = el("button", "done", "Done ✓");
      b.onclick = () => { b.disabled = true; api("POST", "/api/todo/" + Number(t.id) + "/done"); };
      li.appendChild(b);
      return li;
    }));
  }

  // ---------- items ----------
  function renderItems() {
    // latest location per item first
    fill("items", "items-empty", state.items.map((i) => {
      const li = el("li");
      if (i.snapshot) {
        const file = String(i.snapshot).split(/[\\/]/).pop();
        const img = el("img");
        img.alt = "Photo of " + i.item;
        img.loading = "lazy";
        img.src = "/snapshots/" + encodeURIComponent(file);
        img.onerror = () => img.remove();
        li.appendChild(img);
      }
      const body = el("div", "grow");
      body.appendChild(el("div", "item-name", i.item));
      body.appendChild(el("div", null, i.location));
      const meta = el("div", "src", (i.source || "") + " · " + ago(i.ts));
      body.appendChild(meta);
      li.appendChild(body);
      return li;
    }));
  }

  // ---------- alerts ----------
  function renderAlerts() {
    const nodes = state.alerts.map((a) => {
      const li = el("li", "alert");
      li.appendChild(el("span", "pill kind", a.kind || "alert"));
      li.appendChild(el("span", "grow", a.text));
      li.appendChild(el("span", "time", ago(a.ts)));
      return li;
    });
    fill("alerts", "alerts-empty", nodes);
    $("alerts-panel").classList.toggle("has-alerts", nodes.length > 0);
  }

  // ---------- purchases ----------
  function renderPurchases() {
    fill("purchases", "purchases-empty", state.purchases.map((p) => {
      const li = el("li");
      const ok = /^(allowed|approved|succeeded|paid|ok)$/i.test(p.status || "");
      li.appendChild(el("span", "pill " + (ok ? "ok" : "bad"), ok ? "allowed" : (p.status || "blocked")));
      const body = el("div", "grow");
      body.appendChild(el("div", null, (p.item || "") + (p.merchant ? " · " + p.merchant : "")));
      if (p.reason) body.appendChild(el("span", "reason", p.reason));
      li.appendChild(body);
      li.appendChild(el("span", "amount", money(p.amount_cents)));
      return li;
    }));
  }

  function renderAll() {
    renderStatus(); renderTranscript(); renderPeople(); renderTodos();
    renderItems(); renderAlerts(); renderPurchases();
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
    refreshTimer = setTimeout(refresh, 150);
  }

  function onEvent(ev) {
    const t = ev.table, row = ev.row || {};
    if (t === "status") { state.status = Object.assign({}, state.status, row); renderStatus(); }
    else if (t === "transcript") addLine(row);
    else if (t === "transcript_rated") rateLine(row);
    else scheduleRefresh();
  }

  let ws = null, backoff = 500;
  function connect() {
    ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
    ws.onopen = () => {
      backoff = 500;
      $("live").className = "badge live-on";
      $("live").title = "Live connection to Kin";
      refresh();
    };
    ws.onmessage = (m) => { try { onEvent(JSON.parse(m.data)); } catch (e) { console.warn(e); } };
    ws.onclose = () => {
      $("live").className = "badge live-off";
      $("live").title = "Reconnecting…";
      setTimeout(connect, backoff);
      backoff = Math.min(backoff * 2, 8000);
    };
  }

  $("person-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = $("p-name").value.trim();
    if (!name) return;
    await api("POST", "/api/person", { name, relationship: $("p-rel").value.trim() });
    $("p-name").value = ""; $("p-rel").value = "";
    $("p-name").focus();
  });

  setInterval(() => { renderPeople(); renderItems(); renderAlerts(); }, 60000); // refresh "x min ago"
  refresh();
  connect();
})();
