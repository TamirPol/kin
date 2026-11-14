// Kin family dashboard. Turns Kin's memory into plain sentences a family member can read at a glance.
// All untrusted text goes through textContent (el() helper); never innerHTML.
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  let state = { people: [], todos: [], items: [], alerts: [], purchases: [], transcript: [], status: {}, config: {} };
  let live = false;
  let everLive = false;      // first load: say 'Connecting…', not 'Can't reach Kin'
  let lostAt = 0;
  let loaded = false;
  const acked = new Set();          // alerts acknowledged in this browser (server also stores seen=1)
  const seenKeys = new Map();       // list id -> Set of row keys already shown (to highlight new rows)
  const openFolds = new Set();      // small-talk runs the viewer expanded
  let convoOpen = false;
  let convoPrimed = false;          // chat already drawn once since it was opened
  const KIN_FEW = 4;                // Kin replies shown before "Show more"
  let kinMore = false;
  let summary = null;               // {text, ts} from /api/summary

  // ---------- small helpers ----------
  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }
  function add(parent, ...kids) { for (const k of kids) if (k) parent.appendChild(typeof k === "string" ? document.createTextNode(k) : k); return parent; }
  const now = () => Date.now() / 1000;
  function ago(ts) {
    if (!ts) return "";
    const m = Math.floor((now() - ts) / 60);
    if (m < 1) return "just now";
    if (m < 60) return m + " min ago";
    if (m < 1440) { const h = Math.floor(m / 60); return h + (h === 1 ? " hour ago" : " hours ago"); }
    const d = Math.floor(m / 1440); return d === 1 ? "yesterday" : d + " days ago";
  }
  function clock(ts) { return new Date(ts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); }
  function money(c) { return "$" + (Number(c || 0) / 100).toFixed(2); }
  function cap(s) { s = String(s || "").trim(); return s.charAt(0).toUpperCase() + s.slice(1); }
  function icon(id, cls) {
    const NS = "http://www.w3.org/2000/svg";
    const wrap = el("span", cls);
    wrap.setAttribute("aria-hidden", "true");
    const svg = document.createElementNS(NS, "svg"); svg.setAttribute("class", "i");
    const use = document.createElementNS(NS, "use"); use.setAttribute("href", "#" + id);
    svg.appendChild(use); wrap.appendChild(svg);
    return wrap;
  }
  function midnight() { const d = new Date(); d.setHours(0, 0, 0, 0); return d.getTime() / 1000; }
  function wearer() { return state.config.wearer || "Your loved one"; }
  function words(s) { return String(s || "").trim().split(/\s+/).filter(Boolean).length; }
  // Kin's one-word acknowledgements ("Yes?") are not part of the story.
  function isFiller(l) { return l.speaker === "kin" && words(l.text) <= 1; }
  function his(rel) {
    rel = String(rel || "").trim();
    if (!rel) return "";
    return /^(his|her|their|a|an|the|my)\b/i.test(rel) ? rel : "his " + rel;
  }

  // Mark rows that weren't on screen before so they glow briefly.
  function fresh(listId, key, node) {
    let s = seenKeys.get(listId);
    if (!s) { s = new Set(); seenKeys.set(listId, s); }
    const k = String(key);
    if (loaded && !s.has(k)) node.classList.add("fresh");
    s.add(k);
    return node;
  }
  function fill(listId, nodes, emptyId) {
    $(listId).replaceChildren(...nodes);
    if (emptyId) $(emptyId).hidden = nodes.length > 0;
  }

  // ---------- names ----------
  function speakerMap() {
    const m = new Map();
    for (const p of state.people) if (p && p.speaker) m.set(p.speaker, p);
    return m;
  }
  function nameOf(l, map) {
    if (l.speaker === "kin") return "Kin";
    if (l.speaker === "wearer") return wearer();
    const p = (map || speakerMap()).get(l.speaker);
    if (p) return p.name;
    if (l.name && l.name !== "Kin") return l.name;
    return "Someone";
  }
  function lastHeard() {
    for (let i = state.transcript.length - 1; i >= 0; i--) {
      const l = state.transcript[i];
      if (l.speaker !== "kin") return l.ts;
    }
    return 0;
  }

  // ---------- alerts -> plain sentences ----------
  function isOpen(a) { return !Number(a.seen) && !acked.has(a.id); }
  function kinSpokeNear(ts) {
    return state.transcript.some((l) => l.speaker === "kin" && !isFiller(l) && l.ts >= ts - 3 && l.ts <= ts + 25);
  }
  function okAfter(fall, pool) { return pool.find((b) => b.kind === "fall_ok" && b.ts >= fall.ts && b.ts - fall.ts < 600) || null; }

  // Returns {tone: 'bad'|'warn', title, details[]} or null to skip.
  function describe(a, pool) {
    const at = " at " + clock(a.ts);
    const text = String(a.text || "");
    if (a.kind === "scam") {
      const d = [];
      const why = /\((.+)\)/.exec(text);
      if (why) d.push(cap(why[1].replace(/\.$/, "")) + ".");
      if (kinSpokeNear(a.ts)) d.push("Kin warned him not to send money.");
      const lock = /locked for (\d+) minutes/i.exec(text);
      if (lock) d.push("Purchases are paused for " + lock[1] + " minutes.");
      return { tone: "bad", title: "Possible scam call" + at, details: d };
    }
    if (a.kind === "fall") {
      const ok = okAfter(a, pool);
      if (ok) return { tone: "warn", title: "He may have fallen" + at,
        details: ["Kin asked if he was OK and he tapped his band to say he's fine."] };
      return { tone: "bad", title: "He may have fallen" + at,
        details: ["Kin asked if he's OK and is waiting for him to tap his band."] };
    }
    if (a.kind === "fall_emergency") {
      return { tone: "bad", title: "No answer after a possible fall" + at,
        details: ["He didn't answer when Kin asked if he was OK.", "Call him or go check on him now."] };
    }
    if (a.kind === "fall_ok") return null;            // shown together with its fall
    if (a.kind === "wander") {
      const d = [/lost touch/i.test(text) ? "Kin lost touch with his band." : "His band is far from home."];
      d.push("Call him or go look for him.");
      return { tone: "bad", title: "He may have wandered off" + at, details: d };
    }
    if (a.kind === "spending") {
      return { tone: "warn", title: "Kin stopped a purchase" + at, details: [cap(text.replace(/^Blocked:\s*/i, ""))] };
    }
    return { tone: "bad", title: cap(String(a.kind || "Alert").replace(/_/g, " ")) + at, details: text ? [text] : [] };
  }

  // Alerts that mean "he may not be OK": they turn the top red and notify the family's devices.
  const URGENT = new Set(["scam", "fall", "fall_emergency", "wander"]);
  // A few words on what Kin did about it, for the status line and the device notification.
  function shortAction(a, pool) {
    if (a.kind === "scam") return kinSpokeNear(a.ts) ? "Kin warned him" : "";
    if (a.kind === "fall") return okAfter(a, pool) ? "He tapped his band to say he's fine" : "Kin asked if he's OK";
    if (a.kind === "fall_emergency") return "He didn't answer Kin";
    if (a.kind === "wander") return "Call him or go look for him";
    return "";
  }
  function reason(a, pool) {
    const m = describe(a, pool);
    if (!m) return "";
    const s = shortAction(a, pool);
    return m.title + (s ? " · " + s : "");
  }
  let baseTitle = document.title;

  // ---------- 1. the top line ----------
  function renderHero() {
    const hero = $("hero"), title = $("hero-title"), sub = $("hero-sub"), det = $("hero-details"), ack = $("hero-ack");
    const name = wearer();
    $("wearer-top").textContent = name;
    baseTitle = "Kin · " + name;
    if (!flashTimer) document.title = baseTitle;

    const open = state.alerts.filter(isOpen);
    // a fall he answered "I'm fine" to is over, and a fall that became an emergency shows once, as the emergency
    const settled = (a) => a.kind === "fall" && (okAfter(a, state.alerts) ||
      state.alerts.some((b) => b.kind === "fall_emergency" && b.ts >= a.ts && b.ts - a.ts < 90));
    const rank = (x) => (URGENT.has(x.a.kind) ? 0 : x.m.tone === "bad" ? 1 : 2);
    const msgs = open.filter((a) => !settled(a)).map((a) => ({ a, m: describe(a, open) })).filter((x) => x.m)
      .sort((x, y) => (rank(x) === rank(y) ? y.a.ts - x.a.ts : rank(x) - rank(y)));

    sub.replaceChildren(); det.replaceChildren();
    if (msgs.length) {
      const top = msgs[0].m, topA = msgs[0].a;
      if (URGENT.has(topA.kind)) {
        hero.className = "hero alarm";
        title.textContent = name + " may not be OK";
        const why = el("span", "why", top.title);
        sub.appendChild(why);
        const s = shortAction(topA, open);
        if (s) { sub.appendChild(el("span", "sep", "·")); sub.appendChild(el("span", null, s)); }
        sub.hidden = false;
        if (s) top.details = top.details.filter((d) => !d.toLowerCase().startsWith(s.toLowerCase()));   // said already
      } else {
        hero.className = "hero " + (top.tone === "bad" ? "alarm" : "warn");
        title.textContent = top.title;
        sub.hidden = true;
      }
      top.details.forEach((d) => det.appendChild(el("li", null, d)));
      msgs.slice(1).forEach((x) => det.appendChild(el("li", "also-alert", "Also: " + x.m.title)));
      det.hidden = det.children.length === 0;
      ack.hidden = false;
      ack.textContent = "I've checked on him";
      ack.onclick = () => {
        ack.disabled = true;
        open.forEach((a) => { acked.add(a.id); api("POST", "/api/alert/" + Number(a.id) + "/seen"); });
        ack.disabled = false;
        renderAll();
      };
      return;
    }

    det.hidden = true; ack.hidden = true; sub.hidden = false;
    const s = state.status || {};
    const heard = lastHeard();
    const heardText = heard ? "Last heard " + ago(heard) : "Nothing heard yet today";
    const parts = [];
    if (!live && (!everLive || Date.now() - lostAt < 8000)) {
      hero.className = "hero calm";               // connecting, or a quick restart: no alarm
      title.textContent = "Connecting to Kin…";
      parts.push(name);
    } else if (!live) {
      hero.className = "hero off";
      title.textContent = "Can't reach Kin right now";
      parts.push("Trying to reconnect…");
      if (heard) parts.push(heardText);
    } else if (s.band === "disconnected") {
      hero.className = "hero warn";
      title.textContent = "Kin can't hear " + name + " right now";
      parts.push("His band isn't connected", heardText);
    } else {
      hero.className = "hero calm";
      title.textContent = name + " is OK";
      parts.push(s.mode === "ask" ? "He's asking Kin something" : "Kin is listening", heardText);
    }
    parts.forEach((p, i) => { if (i) sub.appendChild(el("span", "sep", "·")); sub.appendChild(el("span", null, p)); });

    // Warnings already handled today stay visible as one quiet line.
    const today = midnight();
    const handled = state.alerts.filter((a) => !isOpen(a) && a.ts >= today);
    const titles = handled.map((a) => describe(a, handled)).filter(Boolean)
      .sort((x, y) => (x.tone === y.tone ? 0 : x.tone === "bad" ? -1 : 1)).map((m) => m.title.charAt(0).toLowerCase() + m.title.slice(1));
    if (titles.length) {
      det.appendChild(el("li", "earlier-line", "Earlier today: " + titles.slice(0, 3).join("; ") + ". Someone checked on him."));
      det.hidden = false;
    }
  }

  // ---------- Kin is telling him (live) ----------
  let speakTimer = null, speakHide = null;
  function showSpeaking(text) {
    const box = $("speaking");
    clearTimeout(speakTimer); clearTimeout(speakHide);
    $("speaking-text").textContent = text;
    box.classList.remove("out");
    box.hidden = false;
    const ms = Math.min(14000, Math.max(5000, words(text) * 420 + 2000));
    speakTimer = setTimeout(() => {
      box.classList.add("out");
      speakHide = setTimeout(() => { box.hidden = true; box.classList.remove("out"); }, 400);
    }, ms);
  }

  // ---------- 2. today ----------
  function renderPeople() {
    const today = midnight();
    const map = speakerMap();
    const people = state.people.filter(Boolean);
    const seenToday = people.filter((p) => (p.last_seen || 0) >= today);
    const nodes = seenToday.map((p) => {
      const li = el("li");
      li.appendChild(el("span", "avatar", String(p.name || "?").trim().charAt(0).toUpperCase()));
      const body = el("div", "grow");
      const head = el("div", "big");
      add(head, el("strong", null, p.name));
      if (p.relationship) add(head, " ", el("span", "rel", his(p.relationship)));
      body.appendChild(head);
      body.appendChild(el("div", "when", "Talked with him " + ago(p.last_seen)));
      const facts = (p.facts || []).slice(0, 4);
      if (facts.length) {
        const ul = el("ul", "facts");
        facts.forEach((f) => {
          const fl = el("li");
          fl.appendChild(el("span", null, f.text));
          const x = el("button", "x", "✕");
          x.type = "button";
          x.title = "Kin got this wrong: remove it";
          x.setAttribute("aria-label", "Remove: " + f.text);
          x.onclick = () => { x.disabled = true; api("DELETE", "/api/fact/" + Number(f.id)); };
          fl.appendChild(x);
          ul.appendChild(fl);
        });
        body.appendChild(ul);
      }
      li.appendChild(body);
      return fresh("people", p.id, li);
    });
    fill("people", nodes, "people-empty");

    // Voices Kin couldn't put a name to, and people known from before.
    const unknown = new Set();
    for (const l of state.transcript) {
      if (l.ts < today || l.speaker === "kin" || l.speaker === "wearer") continue;
      if (!map.has(l.speaker) && !l.name) unknown.add(l.speaker);
    }
    const bits = [];
    if (unknown.size) bits.push("Kin also heard " + (unknown.size === 1 ? "1 voice" : unknown.size + " voices") + " it didn't recognize.");
    const before = people.filter((p) => (p.last_seen || 0) < today);
    if (before.length) bits.push("Kin also knows " + before.slice(0, 4).map((p) => p.name + (p.relationship ? " (" + p.relationship + ")" : "")).join(", ") + (before.length > 4 ? " and others." : "."));
    $("people-also").textContent = bits.join(" ");
    $("people-also").hidden = bits.length === 0;
    if (!seenToday.length && unknown.size) $("people-empty").textContent = "No one Kin knows yet today.";
    else $("people-empty").textContent = "No visitors yet today.";
  }

  function renderTodos() {
    const rows = state.todos.filter((t) => !Number(t.done));
    const nodes = rows.map((t) => {
      const li = el("li");
      const body = el("div", "grow");
      let text = cap(t.text).replace(/\.$/, "");
      const due = String(t.due || "").trim();
      if (due && !text.toLowerCase().includes(due.toLowerCase())) text += " " + due;
      body.appendChild(el("div", "big", text));
      body.appendChild(el("div", "when", "He mentioned it " + ago(t.ts)));
      li.appendChild(body);
      const b = el("button", "done", "Done");
      b.type = "button";
      b.title = "Mark as done";
      b.setAttribute("aria-label", "Mark as done: " + text);
      b.onclick = () => { b.disabled = true; api("POST", "/api/todo/" + Number(t.id) + "/done"); };
      li.appendChild(b);
      return fresh("todos", t.id, li);
    });
    fill("todos", nodes, "todos-empty");
  }

  function renderItems() {
    const seen = new Set();
    const rows = state.items.filter((i) => {
      const k = String(i.item || "").toLowerCase();
      if (seen.has(k)) return false;
      seen.add(k); return true;
    }).slice(0, 6);
    const nodes = rows.map((i) => {
      const li = el("li");
      if (i.snapshot) {
        const file = String(i.snapshot).split(/[\\/]/).pop();
        const img = el("img", "thumb");
        img.alt = "Photo of the " + i.item;
        img.src = "/snapshots/" + encodeURIComponent(file);
        img.onerror = () => img.remove();
        img.onclick = () => img.classList.toggle("zoom");
        li.appendChild(img);
      } else li.appendChild(icon("i-key", "place"));
      const body = el("div", "grow");
      const head = el("div", "big");
      add(head, el("strong", null, cap(i.item) + ":"), " " + String(i.location || "").replace(/\.$/, ""));
      body.appendChild(head);
      body.appendChild(el("div", "when", (i.source === "vision" ? "Kin's camera saw it " : "He said so ") + ago(i.ts)));
      li.appendChild(body);
      return fresh("items", i.id, li);
    });
    fill("items", nodes, "items-empty");
  }

  // Kin's answers, paired with the question he asked; Kin's own warnings stand alone.
  function renderKinSaid() {
    const t = state.transcript.filter((l) => !isFiller(l));
    const out = [];
    t.forEach((l, i) => {
      if (l.speaker !== "kin") return;
      const prev = t[i - 1];
      const q = prev && prev.speaker === "wearer" && Number(prev.importance) < 0 && l.ts - prev.ts < 40 ? prev : null;
      out.push({ l, q });
    });
    const WHY = { scam: "Warning him about the scam call:", fall: "Checking on him after a possible fall:",
      fall_ok: "When he said he was fine:", fall_emergency: "When he didn't answer:", wander: "When he may have wandered:" };
    const why = (l) => {
      let best = null;
      for (const a of state.alerts) {
        const d = Math.abs(l.ts - a.ts);
        if (d < 4 && WHY[a.kind] && (!best || d < best.d)) best = { d, a };
      }
      return best ? WHY[best.a.kind] : "";
    };
    // Newest first; the latest few, the rest behind "Show more".
    const all = out.reverse();
    const shown = kinMore ? all.slice(0, 20) : all.slice(0, KIN_FEW);
    const more = $("kinsaid-more");
    more.hidden = all.length <= KIN_FEW;
    more.textContent = kinMore ? "Show fewer" : "Show " + (Math.min(all.length, 20) - KIN_FEW) + " more";
    more.setAttribute("aria-expanded", String(kinMore));
    // Older replies count as already seen, so "Show more" doesn't flash them as new.
    all.slice(shown.length).forEach(({ l }) => fresh("kinsaid", l.id, el("li")));
    const nodes = shown.map(({ l, q }) => {
      const li = el("li");
      const body = el("div", "grow");
      if (q) body.appendChild(el("div", "q", "He asked: “" + q.text + "”"));
      else if (why(l)) body.appendChild(el("div", "q", why(l)));
      body.appendChild(el("div", "a", "“" + l.text + "”"));
      body.appendChild(el("div", "when", clock(l.ts)));
      li.appendChild(body);
      return fresh("kinsaid", l.id, li);
    });
    fill("kinsaid", nodes, "kinsaid-empty");
  }

  function renderPurchases() {
    const nodes = state.purchases.slice(0, 5).map((p) => {
      const ok = /^(allowed|approved|succeeded|paid|ok)$/i.test(p.status || "");
      const li = el("li");
      const body = el("div", "grow");
      const head = el("div", "big");
      add(head, el("span", "badge " + (ok ? "ok" : "bad"), ok ? "Bought" : "Stopped"), " ",
        cap(p.item || "something") + (p.merchant ? " from " + p.merchant : "") + ", " + money(p.amount_cents));
      body.appendChild(head);
      if (!ok && p.reason) body.appendChild(el("div", "detail", "Why: " + p.reason));
      body.appendChild(el("div", "when", clock(p.ts)));
      li.appendChild(body);
      return fresh("purchases", p.id, li);
    });
    fill("purchases", nodes);
    $("money-card").hidden = nodes.length === 0;
  }

  function renderEarlier() {
    const done = state.alerts.filter((a) => !isOpen(a));
    const nodes = done.map((a) => ({ a, m: describe(a, done) })).filter((x) => x.m).slice(0, 5).map(({ a, m }) => {
      const li = el("li");
      const body = el("div", "grow");
      body.appendChild(el("div", "big", m.title));
      if (m.details[0]) body.appendChild(el("div", "detail", m.details[0]));
      body.appendChild(el("div", "when", "Someone checked on him"));
      li.appendChild(body);
      return li;
    });
    fill("earlier", nodes);
    $("earlier-card").hidden = nodes.length === 0;
  }

  // ---------- 3. the conversation ----------
  // Newest first: the latest line is at the top and live lines arrive there.
  function renderConvo() {
    const lines = state.transcript.filter((l) => !isFiller(l)).reverse();
    const btn = $("convo-toggle");
    btn.textContent = convoOpen ? "Hide the conversation"
      : lines.length ? "See what was said today (" + lines.length + (lines.length === 1 ? " line)" : " lines)")
      : "See what was said today";
    btn.setAttribute("aria-expanded", String(convoOpen));
    const box = $("convo");
    box.hidden = !convoOpen;
    if (!convoOpen) { convoPrimed = false; return; }

    const map = speakerMap();
    const nodes = [];
    let lastWho = null, lastTs = 0;
    for (let i = 0; i < lines.length; i++) {
      // Two or more lines of small talk in a row fold into one line.
      if (Number(lines[i].importance) === 0) {
        let j = i;
        while (j < lines.length && Number(lines[j].importance) === 0) j++;
        const run = lines.slice(i, j);
        const runKey = String(run[run.length - 1].id);   // the run's oldest line: stays put as the run grows
        if (run.length >= 2 && !openFolds.has(runKey)) {
          const f = el("button", "fold", "+ " + run.length + " lines of small talk");
          f.type = "button";
          f.onclick = () => { openFolds.add(runKey); renderConvo(); };
          const li = el("li", "msg-fold"); li.appendChild(f); nodes.push(li);
          lastWho = null;
          i = j - 1;
          continue;
        }
      }
      const l = lines[i];
      const who = nameOf(l, map);
      const cls = l.speaker === "kin" ? "kin" : l.speaker === "wearer" ? "me" : "them";
      const li = el("li", "msg " + cls);
      // Name and time once per turn, not on every bubble.
      if (who !== lastWho || Math.abs(l.ts - lastTs) > 120) li.appendChild(el("span", "who", who + " · " + clock(l.ts)));
      li.appendChild(el("div", "bubble", l.text));
      if (l.category === "money_safety" && Number(l.importance) >= 1) {
        li.classList.add("danger");
        li.appendChild(el("span", "flag", "Kin flagged this as a possible scam"));
      }
      // Only lines that arrive while the chat is open slide in.
      if (convoPrimed) nodes.push(fresh("convo", l.id, li));
      else { fresh("convo", l.id, el("li")); nodes.push(li); }
      lastWho = who; lastTs = l.ts;
    }
    if (!nodes.length) nodes.push(el("li", "chat-empty", "Nothing heard yet today."));
    box.replaceChildren(...nodes);
    convoPrimed = true;
  }

  // ---------- today so far ----------
  function renderSummary() {
    const t = $("summary-text"), w = $("summary-when");
    const text = summary && String(summary.text || "").trim();
    t.textContent = text || "Kin is putting together today's summary…";
    t.classList.toggle("is-empty", !text);
    w.hidden = !(text && summary.ts);
    if (!w.hidden) w.textContent = "Updated " + ago(summary.ts);
  }
  async function loadSummary() {
    try {
      const r = await fetch("/api/summary", { cache: "no-store" });
      if (r.ok) { summary = await r.json(); renderSummary(); }
    } catch (e) { console.warn("summary failed", e); }
  }

  function renderAll() {
    renderSummary(); renderHero(); renderPeople(); renderTodos(); renderItems(); renderKinSaid();
    renderPurchases(); renderEarlier(); renderConvo();
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
      state = Object.assign(state, await r.json());
      // Alerts already there when the page opens aren't news; anything newer that the live feed missed is.
      for (const a of state.alerts) { if (!loaded) notified.add(a.id); else announce(a); }
      renderAll();
    } catch (e) { console.warn("snapshot failed", e); }
  }
  let refreshTimer = null;
  function scheduleRefresh() { clearTimeout(refreshTimer); refreshTimer = setTimeout(refresh, 150); }

  // ---------- device alerts ----------
  // Browser notifications need permission asked from a click; the choice is remembered on this device.
  const canNotify = "Notification" in window;
  const notified = new Set();          // alert ids already announced on this page
  let alertsOn = false;
  try { alertsOn = localStorage.getItem("kin-alerts") === "on"; } catch (e) { /* storage blocked */ }
  let audio = null;
  function unlockAudio() {
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      if (!audio) audio = new AC();
      if (audio.state === "suspended") audio.resume();
    } catch (e) { audio = null; }
  }
  function chime() {       // two soft notes, about a second long
    try {
      if (!audio) unlockAudio();
      if (!audio || audio.state !== "running") return;
      const t0 = audio.currentTime;
      [[660, 0], [880, .28]].forEach(([f, d]) => {
        const o = audio.createOscillator(), g = audio.createGain();
        o.type = "sine"; o.frequency.value = f;
        g.gain.setValueAtTime(0, t0 + d);
        g.gain.linearRampToValueAtTime(.18, t0 + d + .04);
        g.gain.exponentialRampToValueAtTime(.001, t0 + d + .7);
        o.connect(g).connect(audio.destination);
        o.start(t0 + d); o.stop(t0 + d + .75);
      });
    } catch (e) { /* no sound, that's fine */ }
  }
  let flashTimer = null;
  function flashTitle() {
    if (!document.hidden || flashTimer) return;
    let on = false;
    flashTimer = setInterval(() => { on = !on; document.title = on ? "⚠ Kin alert" : baseTitle; }, 1000);
  }
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && flashTimer) { clearInterval(flashTimer); flashTimer = null; document.title = baseTitle; }
  });
  // Notifications blocked by the browser: the button still turns on the sound, so it never looks dead.
  function alertsActive() { return alertsOn && canNotify && Notification.permission !== "default"; }
  function renderAlertsBtn() {
    const b = $("alerts-btn");
    if (!b) return;
    if (!canNotify) { b.hidden = true; return; }
    const perm = Notification.permission, on = alertsActive();
    b.hidden = false;
    b.classList.toggle("on", on);
    b.setAttribute("aria-pressed", String(on));
    $("alerts-label").textContent = perm === "denied" ? (on ? "Sound alerts on" : "Turn on sound alerts")
      : on ? "Alerts on" : "Turn on alerts";
    b.title = perm === "denied"
      ? "This browser blocks notifications for this page, so Kin will play a sound here instead. Click to " + (on ? "turn it off." : "turn it on.")
      : on ? "This device will alert you if he may not be OK. Click to turn off."
      : "Get a notification on this device if he may not be OK";
  }
  async function toggleAlerts() {
    unlockAudio();
    if (!canNotify) return;
    if (alertsActive()) alertsOn = false;
    else {
      let perm = Notification.permission;
      if (perm === "default") { try { perm = await Notification.requestPermission(); } catch (e) { perm = "denied"; } }
      alertsOn = perm !== "default";      // granted: notifications + sound; denied: sound only
    }
    try { localStorage.setItem("kin-alerts", alertsOn ? "on" : "off"); } catch (e) { /* storage blocked */ }
    renderAlertsBtn();
    if (alertsOn) chime();                // so they hear what an alert sounds like
  }
  function announce(a) {
    if (!URGENT.has(a.kind) || Number(a.seen) || acked.has(a.id) || notified.has(a.id)) return;
    notified.add(a.id);
    flashTitle();
    if (!alertsActive()) return;
    chime();
    if (!canNotify || Notification.permission !== "granted") return;
    try {
      const n = new Notification(wearer() + " may not be OK", {
        body: reason(a, state.alerts.concat([a])), tag: "kin-" + a.id, requireInteraction: true, icon: "/static/kin-mark.svg",
      });
      n.onclick = () => { window.focus(); n.close(); };
    } catch (e) { /* e.g. mobile browsers that only allow notifications from a service worker */ }
  }

  function onEvent(ev) {
    const t = ev.table, row = ev.row || {};
    if (t === "alerts" && row.id != null) announce(row);
    if (t === "status") { state.status = Object.assign({}, state.status, row); renderHero(); return; }
    if (t === "interim" || t === "mic") return;
    if (t === "summary") { summary = row; renderSummary(); return; }
    if (t === "transcript" && row.speaker === "kin" && words(row.text) > 1) showSpeaking(row.text);
    scheduleRefresh();
  }

  let backoff = 500;
  function connect() {
    const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
    ws.onopen = () => { backoff = 500; live = true; everLive = true; lostAt = 0; refresh(); loadSummary(); };
    ws.onmessage = (m) => { try { onEvent(JSON.parse(m.data)); } catch (e) { console.warn(e); } };
    ws.onclose = () => {
      if (live) lostAt = Date.now();
      live = false; renderHero(); setTimeout(renderHero, 8500);
      setTimeout(connect, backoff);
      backoff = Math.min(backoff * 2, 8000);
    };
  }

  // ---------- controls ----------
  if ($("alerts-btn")) $("alerts-btn").addEventListener("click", toggleAlerts);
  renderAlertsBtn();
  $("kinsaid-more").addEventListener("click", () => { kinMore = !kinMore; renderKinSaid(); });
  $("convo-toggle").addEventListener("click", () => { convoOpen = !convoOpen; renderConvo(); });

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

  function tick() {
    const d = new Date();
    $("clock").textContent = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    const td = $("today-date");
    if (td) td.textContent = d.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  }
  setInterval(() => { if (loaded) renderAll(); }, 30000);    // keep "x min ago" fresh
  setInterval(tick, 5000); tick();
  renderHero();
  refresh();
  connect();
})();
