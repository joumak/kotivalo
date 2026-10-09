"use strict";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const POLL_MS = 3000;
const $ = (id) => document.getElementById(id);

let snap = null;
let clockOffset = 0; // Pi clock minus phone clock, ms
let rampDirty = false;
const busy = new Set(); // inputs the user is touching; don't overwrite them

// --- API -------------------------------------------------------------------------

function token() {
  try { return localStorage.getItem("wakeup-token") || ""; } catch { return ""; }
}

async function api(method, path, body) {
  const opts = { method, headers: { "X-Token": token() } };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch {
    showError("Cannot reach the Pi.");
    return null;
  }
  if (res.status === 401) {
    const t = prompt("Access token:");
    if (t) {
      try { localStorage.setItem("wakeup-token", t); } catch { /* private mode */ }
      return api(method, path, body);
    }
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showError(data.error || `Request failed (${res.status})`);
    return null;
  }
  showError(null);
  render(data);
  return data;
}

const post = (path, body = {}) => api("POST", path, body);
const put = (path, body) => api("PUT", path, body);

function showError(msg) {
  $("error").hidden = !msg;
  $("error").textContent = msg || "";
}

// --- formatting ---------------------------------------------------------------------

function piNow() { return Date.now() + clockOffset; }

function fmtTime(iso) {
  return new Date(iso).toLocaleTimeString("en-GB", {
    hour: "2-digit", minute: "2-digit", timeZone: snap.timezone,
  });
}

function fmtIn(iso) {
  const min = Math.round((Date.parse(iso) - piNow()) / 60000);
  if (min < 1) return "now";
  if (min < 60) return `in ${min} min`;
  const h = Math.floor(min / 60), m = min % 60;
  if (h < 48) return `in ${h} h ${m} min`;
  return `in ${Math.round(h / 24)} days`;
}

const pct = (level) => `${Math.round((level / 254) * 100)}%`;

// --- rendering ------------------------------------------------------------------------

function setChip(el, cls, text) {
  el.className = `chip ${cls}`;
  el.textContent = text;
}

function render(s) {
  snap = s;
  clockOffset = Date.parse(s.now) - Date.now();
  renderStatus(s);
  renderSunrise(s);
  renderNext(s);
  renderLight(s);
  renderAlarms(s);
  renderRamp(s);
  renderDevices(s);
  renderFooter(s);
}

function renderStatus(s) {
  const synced = s.clock_synced;
  setChip($("chip-clock"), synced === false ? "warn" : synced ? "ok" : "", "clock");
  $("clock-warning").hidden = synced !== false;
  const l = s.light;
  const cls = !l.available ? "" : l.error ? "bad" : "ok";
  setChip($("chip-light"), cls, s.radio.fake ? "fake light" : "light");
}

function renderSunrise(s) {
  const run = s.sunrise;
  $("sunrise").hidden = !run;
  if (!run) return;
  $("sunrise-title").textContent = run.kind === "test" ? "Test sunrise" : "Sunrise";
  $("sunrise-bar").style.width = `${Math.round(run.progress * 100)}%`;
  let detail;
  if (run.phase === "hold") {
    detail = run.off ? `Full brightness. Switching off at ${fmtTime(run.off)}.` : "Full brightness.";
  } else {
    detail = `Full brightness at ${fmtTime(run.end)} (${fmtIn(run.end)}).`;
  }
  if (run.failures) detail += ` ${run.failures} commands were lost.`;
  $("sunrise-detail").textContent = detail;
}

function skipButton(o) {
  const b = document.createElement("button");
  b.className = "ghost";
  b.textContent = o.skipped ? "Undo skip" : "Skip";
  b.onclick = () => post("/api/skip", { key: o.key, skip: !o.skipped });
  return b;
}

function renderNext(s) {
  const [first, ...later] = s.upcoming;
  $("next-none").hidden = !!first;
  $("next").hidden = !first;
  if (!first) return;
  $("next-label").textContent = first.label;
  $("next-label").className = first.skipped ? "big skipped" : "big";
  $("next-in").textContent = first.skipped
    ? "Skipped"
    : `${fmtIn(first.alarm)} · fade-in from ${fmtTime(first.start)}`;
  const skip = $("next-skip");
  skip.replaceWith(Object.assign(skipButton(first), { id: "next-skip" }));
  $("later").replaceChildren(...later.map((o) => {
    const li = document.createElement("li");
    const span = document.createElement("span");
    span.textContent = `${o.label} · ${fmtIn(o.alarm)}`;
    if (o.skipped) span.className = "skipped";
    li.append(span, skipButton(o));
    return li;
  }));
}

function renderLight(s) {
  const l = s.light;
  $("no-light").hidden = l.available;
  $("light-controls").hidden = !l.available;
  if (!l.available) return;
  const st = l.state;
  $("on").classList.toggle("active", st.on === true);
  $("off").classList.toggle("active", st.on === false);
  if (!busy.has("level") && st.level) $("level").value = st.level;
  $("level-out").textContent = st.on === false ? "off" : pct($("level").value);
  $("ct-wrap").hidden = !l.caps.supports_ct;
  const k = $("kelvin");
  [k.min, k.max] = l.kelvin_range;
  if (!busy.has("kelvin") && st.kelvin) k.value = st.kelvin;
  $("kelvin-out").textContent = `${k.value} K`;
  $("light-error").hidden = !l.error;
  $("light-error").textContent = l.error ? `Last command failed: ${l.error}` : "";
}

function buildAlarms() {
  $("alarms").replaceChildren(...DAYS.map((day, i) => {
    const row = document.createElement("label");
    row.className = "alarm";
    row.innerHTML =
      `<input type="checkbox" data-day="${i}"><span>${day}</span>` +
      `<input type="time" data-day="${i}" required>`;
    return row;
  }));
  $("alarms").addEventListener("change", saveAlarms);
}

function renderAlarms(s) {
  if (busy.has("alarms")) return;
  s.alarms.forEach((a, i) => {
    const check = document.querySelector(`#alarms input[type=checkbox][data-day="${i}"]`);
    const time = document.querySelector(`#alarms input[type=time][data-day="${i}"]`);
    check.checked = a.enabled;
    if (document.activeElement !== time) time.value = a.time;
    check.closest(".alarm").classList.toggle("off", !a.enabled);
  });
}

function saveAlarms() {
  const alarms = DAYS.map((_, i) => ({
    enabled: document.querySelector(`#alarms input[type=checkbox][data-day="${i}"]`).checked,
    time: document.querySelector(`#alarms input[type=time][data-day="${i}"]`).value || "07:00",
  }));
  put("/api/alarms", { alarms });
}

function renderRamp(s) {
  if (rampDirty) return;
  const f = $("ramp-form");
  for (const [k, v] of Object.entries(s.ramp)) {
    if (f.elements[k]) f.elements[k].value = v;
  }
  $("ramp-save").disabled = true;
}

function renderDevices(s) {
  const pairing = s.pairing_until;
  const pair = $("pair");
  pair.disabled = !!pairing;
  pair.textContent = pairing
    ? `Pairing… ${Math.max(0, Math.round((Date.parse(pairing) - piNow()) / 1000))} s`
    : "Pair";
  $("pair-help").hidden = !pairing;
  $("last-event").textContent = s.last_event ? `Last: ${s.last_event}` : "";

  if (!s.devices.length) {
    const li = document.createElement("li");
    li.className = "muted";
    li.textContent = "No devices paired.";
    $("devices").replaceChildren(li);
    return;
  }
  $("devices").replaceChildren(...s.devices.map((d) => {
    const li = document.createElement("li");
    const row = document.createElement("div");
    row.className = "row between";
    const name = document.createElement("div");
    name.innerHTML = "<div></div><small class='muted'></small>";
    name.firstChild.textContent = `${d.manufacturer || "?"} ${d.model || ""}`;
    name.lastChild.textContent = d.ieee;
    row.append(name);
    if (d.ieee === s.light.ieee) {
      const tag = document.createElement("span");
      tag.className = "chip ok";
      tag.textContent = "alarm light";
      row.append(tag);
    } else if (d.is_light) {
      const use = document.createElement("button");
      use.className = "ghost";
      use.textContent = "Use";
      use.onclick = () => post("/api/target", { ieee: d.ieee });
      row.append(use);
    }
    li.append(row);
    return li;
  }));
}

function renderFooter(s) {
  const parts = [];
  if (s.last_run) parts.push(`Last alarm: ${s.last_run.result}, ${fmtTime(s.last_run.finished)}`);
  if (s.last_test) parts.push(`Last test: ${s.last_test.result}`);
  $("footer").textContent = parts.join(" · ");
}

// --- wiring ---------------------------------------------------------------------------

function trackBusy(el, key) {
  el.addEventListener("pointerdown", () => busy.add(key));
  el.addEventListener("focus", () => busy.add(key));
  el.addEventListener("blur", () => busy.delete(key));
  el.addEventListener("change", () => setTimeout(() => busy.delete(key), 500));
}

function wire() {
  buildAlarms();
  $("on").onclick = () => post("/api/light", { action: "on" });
  $("off").onclick = () => post("/api/light", { action: "off" });
  $("refresh").onclick = () => post("/api/refresh");

  const level = $("level");
  trackBusy(level, "level");
  level.oninput = () => { $("level-out").textContent = pct(level.value); };
  level.onchange = () => post("/api/light", { action: "level", value: +level.value });

  const kelvin = $("kelvin");
  trackBusy(kelvin, "kelvin");
  kelvin.oninput = () => { $("kelvin-out").textContent = `${kelvin.value} K`; };
  kelvin.onchange = () => post("/api/light", { action: "kelvin", value: +kelvin.value });

  const alarms = $("alarms");
  alarms.addEventListener("focusin", () => busy.add("alarms"));
  alarms.addEventListener("focusout", () => busy.delete("alarms"));

  const form = $("ramp-form");
  form.addEventListener("input", () => { rampDirty = true; $("ramp-save").disabled = false; });
  form.onsubmit = async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(form));
    rampDirty = false;
    await put("/api/ramp", {
      duration_min: +data.duration_min,
      hold_min: +data.hold_min,
      warm_kelvin: +data.warm_kelvin,
      cool_kelvin: +data.cool_kelvin,
      gamma: +data.gamma,
    });
  };

  document.querySelectorAll("[data-test]").forEach((b) => {
    b.onclick = () => post("/api/sunrise/test", { minutes: +b.dataset.test });
  });
  $("sunrise-stop").onclick = () => post("/api/sunrise/stop");
  $("pair").onclick = () => post("/api/permit", { seconds: 254 });
}

async function poll() {
  await api("GET", "/api/state");
  setTimeout(poll, POLL_MS);
}

wire();
poll();
