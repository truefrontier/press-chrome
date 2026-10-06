/**
 * Press Chrome — MV3 service worker.
 * Outbound WebSocket to localhost daemon; Share toggle; list/read/active/history.
 * No chrome.debugger. Read-only only.
 */

const DEFAULT_WS = "ws://127.0.0.1:18793/ws";
const DEFAULT_TRUST = "shared_plus_active";
const ALARM_RECONNECT = "press-chrome-reconnect";
const VERSION = "1.0.0";

let ws = null;
let reconnectTimer = null;
let sharedTabIds = new Set();
let paused = false;

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.get(["trust", "paused", "sharedTabIds"], (data) => {
    const patch = {};
    if (!data.trust) patch.trust = DEFAULT_TRUST;
    if (data.paused === undefined) patch.paused = false;
    if (!Array.isArray(data.sharedTabIds)) patch.sharedTabIds = [];
    if (Object.keys(patch).length) chrome.storage.local.set(patch);
  });
  chrome.alarms.create(ALARM_RECONNECT, { periodInMinutes: 0.4 });
  connect();
});

chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create(ALARM_RECONNECT, { periodInMinutes: 0.4 });
  loadShared().then(connect);
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM_RECONNECT) {
    if (!ws || ws.readyState > 1) connect();
  }
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local") return;
  if (changes.token || changes.wsUrl) {
    disconnect();
    connect();
  }
  if (changes.paused) {
    paused = Boolean(changes.paused.newValue);
    pushStatus();
  }
  if (changes.sharedTabIds) {
    sharedTabIds = new Set(changes.sharedTabIds.newValue || []);
    updateBadge();
    pushStatus();
  }
});

chrome.action.onClicked.addListener(async (tab) => {
  if (!tab?.id) return;
  await loadShared();
  if (sharedTabIds.has(tab.id)) {
    sharedTabIds.delete(tab.id);
  } else {
    sharedTabIds.add(tab.id);
  }
  await saveShared();
  updateBadge();
  pushStatus();
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (sharedTabIds.has(tabId)) {
    sharedTabIds.delete(tabId);
    saveShared();
    updateBadge();
  }
});

async function loadShared() {
  const data = await chrome.storage.local.get(["sharedTabIds", "paused", "trust"]);
  sharedTabIds = new Set(data.sharedTabIds || []);
  paused = Boolean(data.paused);
  return data;
}

async function saveShared() {
  await chrome.storage.local.set({ sharedTabIds: [...sharedTabIds] });
}

function updateBadge() {
  const n = sharedTabIds.size;
  chrome.action.setBadgeText({ text: n ? String(n) : "" });
  chrome.action.setBadgeBackgroundColor({ color: "#2E86AB" });
}

async function getSettings() {
  const data = await chrome.storage.local.get(["token", "wsUrl", "trust", "paused"]);
  return {
    token: (data.token || "").trim(),
    wsUrl: (data.wsUrl || DEFAULT_WS).trim(),
    trust: data.trust || DEFAULT_TRUST,
    paused: Boolean(data.paused),
  };
}

function disconnect() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (ws) {
    try {
      ws.close();
    } catch {
      /* ignore */
    }
    ws = null;
  }
}

async function connect() {
  const { token, wsUrl, trust, paused: p } = await getSettings();
  paused = p;
  await loadShared();
  updateBadge();
  if (!token) {
    console.info("[press-chrome] no token in options — not connecting");
    return;
  }
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }
  try {
    ws = new WebSocket(wsUrl);
  } catch (err) {
    console.warn("[press-chrome] WS create failed", err);
    scheduleReconnect();
    return;
  }
  ws.onopen = () => {
    ws.send(
      JSON.stringify({
        type: "hello",
        token,
        version: VERSION,
        trust,
        paused,
      }),
    );
  };
  ws.onmessage = (ev) => {
    let msg;
    try {
      msg = JSON.parse(ev.data);
    } catch {
      return;
    }
    handleMessage(msg).catch((err) => {
      console.warn("[press-chrome] handler error", err);
      if (msg?.id) {
        safeSend({ id: msg.id, ok: false, error: String(err?.message || err), code: 5 });
      }
    });
  };
  ws.onclose = () => {
    ws = null;
    scheduleReconnect();
  };
  ws.onerror = () => {
    /* onclose will fire */
  };
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, 3000);
}

function safeSend(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(obj));
  }
}

function pushStatus() {
  safeSend({
    type: "status_push",
    paused,
    shared_count: sharedTabIds.size,
    trust: DEFAULT_TRUST,
  });
}

async function handleMessage(msg) {
  if (!msg || typeof msg !== "object") return;
  if (msg.type === "hello_ack") {
    console.info("[press-chrome] connected to daemon", msg);
    pushStatus();
    return;
  }
  const id = msg.id;
  const type = msg.type;
  if (!type || type === "hello_ack") return;

  if (paused && type !== "ping") {
    safeSend({ id, ok: false, error: "agent_access_paused", code: 4 });
    return;
  }

  switch (type) {
    case "ping":
      safeSend({ id, ok: true, version: VERSION });
      break;
    case "list":
      safeSend({ id, ok: true, tabs: await listTabs() });
      break;
    case "show":
      safeSend(await showTab(id, msg.tabId));
      break;
    case "read":
      safeSend(await readTab(id, msg.tabId));
      break;
    case "active":
      safeSend(await readActive(id));
      break;
    case "history":
      safeSend(await historySearch(id, msg.limit, msg.query));
      break;
    default:
      safeSend({
        id,
        ok: false,
        error: `unknown_type:${type}`,
        code: 2,
        hint: "Write actions are not shipped. See docs/FUTURE_ACTIONS.md",
      });
  }
}

async function trustMode() {
  const { trust } = await getSettings();
  return trust || DEFAULT_TRUST;
}

async function listTabs() {
  await loadShared();
  const trust = await trustMode();
  const tabs = await chrome.tabs.query({});
  const out = [];
  for (const t of tabs) {
    if (t.id == null) continue;
    const shared = sharedTabIds.has(t.id);
    const active = Boolean(t.active);
    let include = shared;
    if (trust === "shared_plus_active" && active) include = true;
    if (trust === "all_tabs_meta") include = true;
    if (!include) continue;
    out.push(tabMeta(t, shared));
  }
  return out;
}

function tabMeta(t, shared) {
  return {
    id: t.id,
    title: t.title || "",
    url: t.url || "",
    shared: Boolean(shared),
    active: Boolean(t.active),
    windowId: t.windowId,
    pinned: Boolean(t.pinned),
  };
}

async function isAllowed(tab) {
  if (!tab || tab.id == null) return false;
  await loadShared();
  if (sharedTabIds.has(tab.id)) return true;
  const trust = await trustMode();
  if (trust === "shared_plus_active" && tab.active) return true;
  return false;
}

async function showTab(reqId, tabId) {
  const id = Number(tabId);
  let tab;
  try {
    tab = await chrome.tabs.get(id);
  } catch {
    return { id: reqId, ok: false, error: "not_found", code: 3 };
  }
  if (!(await isAllowed(tab))) {
    return { id: reqId, ok: false, error: "not_shared", code: 3 };
  }
  return {
    id: reqId,
    ok: true,
    tab: tabMeta(tab, sharedTabIds.has(tab.id)),
  };
}

async function extractFromTab(tabId) {
  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId },
      files: ["content.js"],
    });
  } catch {
    /* may already be injected or restricted page */
  }
  try {
    const resp = await chrome.tabs.sendMessage(tabId, { type: "extract" });
    if (resp?.ok) return resp;
  } catch {
    /* fall through to inline */
  }
  try {
    const [inj] = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => {
        function stripChrome(root) {
          root
            .querySelectorAll(
              "script,style,noscript,svg,iframe,nav,header,footer,aside,form,button,[role='navigation'],[role='banner'],[role='contentinfo']",
            )
            .forEach((n) => n.remove());
        }
        function plaintext(el) {
          return (el.textContent || "").replace(/\s+/g, " ").trim();
        }
        const prefer =
          document.querySelector("article") ||
          document.querySelector("main") ||
          document.querySelector("[role='main']");
        if (prefer) {
          const clone = prefer.cloneNode(true);
          stripChrome(clone);
          const t = plaintext(clone);
          if (t.length >= 80) return { ok: true, text: t, method: "readability" };
        }
        const body = document.body?.cloneNode(true);
        if (!body) return { ok: false, text: "", method: "none" };
        stripChrome(body);
        body.querySelectorAll("nav,header,footer,aside").forEach((n) => n.remove());
        const text = plaintext(body);
        return { ok: Boolean(text), text, method: text ? "readability" : "none" };
      },
    });
    return inj?.result || { ok: false, text: "", method: "none" };
  } catch (err) {
    return { ok: false, text: "", method: "none", error: String(err?.message || err) };
  }
}

async function readTab(reqId, tabId) {
  const id = Number(tabId);
  let tab;
  try {
    tab = await chrome.tabs.get(id);
  } catch {
    return { id: reqId, ok: false, error: "not_found", code: 3 };
  }
  if (!(await isAllowed(tab))) {
    return { id: reqId, ok: false, error: "not_shared", code: 3 };
  }
  if (!tab.url || tab.url.startsWith("chrome://") || tab.url.startsWith("chrome-extension://")) {
    return { id: reqId, ok: false, error: "restricted_url", code: 5 };
  }
  const extracted = await extractFromTab(id);
  return {
    id: reqId,
    ok: Boolean(extracted.ok),
    tabId: id,
    title: tab.title || "",
    url: tab.url || "",
    method: extracted.method,
    text: extracted.text || "",
    error: extracted.error,
    code: extracted.ok ? undefined : 5,
  };
}

async function readActive(reqId) {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const tab = tabs[0];
  if (!tab?.id) {
    return { id: reqId, ok: false, error: "no_active_tab", code: 3 };
  }
  const result = await readTab(reqId, tab.id);
  result.shared = sharedTabIds.has(tab.id);
  return result;
}

async function historySearch(reqId, limit, query) {
  const max = Math.min(Math.max(Number(limit) || 20, 1), 200);
  const text = (query || "").trim();
  try {
    const items = await chrome.history.search({
      text,
      maxResults: max,
      startTime: 0,
    });
    return {
      id: reqId,
      ok: true,
      items: (items || []).map((h) => ({
        id: h.id,
        title: h.title || "",
        url: h.url || "",
        lastVisitTime: h.lastVisitTime,
        visitCount: h.visitCount,
        typedCount: h.typedCount,
      })),
    };
  } catch (err) {
    return {
      id: reqId,
      ok: false,
      error: String(err?.message || err),
      code: 5,
      hint: "Requires history permission; reload extension after Load Unpacked.",
    };
  }
}

// Kick off
loadShared().then(() => {
  updateBadge();
  connect();
});
