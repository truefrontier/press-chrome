const DEFAULT_WS = "ws://127.0.0.1:18793/ws";
const DEFAULT_TRUST = "shared_plus_active";

async function load() {
  const data = await chrome.storage.local.get(["token", "wsUrl", "trust", "paused"]);
  document.getElementById("token").value = data.token || "";
  document.getElementById("wsUrl").value = data.wsUrl || DEFAULT_WS;
  document.getElementById("trust").value = data.trust || DEFAULT_TRUST;
  document.getElementById("paused").checked = Boolean(data.paused);
}

async function save() {
  const token = document.getElementById("token").value.trim();
  const wsUrl = document.getElementById("wsUrl").value.trim() || DEFAULT_WS;
  const trust = document.getElementById("trust").value || DEFAULT_TRUST;
  const paused = document.getElementById("paused").checked;
  await chrome.storage.local.set({ token, wsUrl, trust, paused });
  const el = document.getElementById("status");
  el.textContent = "Saved. Extension will reconnect.";
  el.className = "ok";
}

document.getElementById("save").addEventListener("click", () => {
  save().catch((err) => {
    const el = document.getElementById("status");
    el.textContent = String(err);
    el.className = "err";
  });
});

load();
