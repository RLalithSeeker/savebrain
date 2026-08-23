// popup.js -- speed presets map to the pacing knobs in content.js.
// Moderate is the default: human-shaped gaps without wasting your evening.

const PRESETS = {
  safe: { scrollMin: 3500, scrollMax: 8000, breakEvery: 6, breakMin: 30000, breakMax: 90000 },
  moderate: { scrollMin: 2200, scrollMax: 5200, breakEvery: 8, breakMin: 18000, breakMax: 55000 },
  brisk: { scrollMin: 1200, scrollMax: 3000, breakEvery: 12, breakMin: 8000, breakMax: 25000 },
};

const $ = (id) => document.getElementById(id);

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

function buildSettings() {
  const preset = PRESETS[$("speed").value] || PRESETS.moderate;
  return {
    ...preset,
    port: parseInt($("port").value, 10) || 8799,
    maxPosts: parseInt($("max").value, 10) || 400,
    idleStop: 6,
  };
}

async function checkBridge(port) {
  try {
    const r = await fetch("http://127.0.0.1:" + port + "/status");
    return await r.json();
  } catch (_) {
    return null;
  }
}

async function refresh() {
  const tab = await activeTab();
  if (!tab || !/instagram\.com/.test(tab.url || "")) {
    $("stat").innerHTML = '<span class="dot-na">open your Saved page first</span>';
    return;
  }
  let status = null;
  try {
    status = await chrome.tabs.sendMessage(tab.id, { type: "SB_STATUS" });
  } catch (_) {}
  const bridge = await checkBridge(parseInt($("port").value, 10) || 8799);
  const bdot = bridge
    ? '<span class="dot-ok">bridge ok (' + bridge.total_in_inbox + " stored)</span>"
    : '<span class="dot-bad">bridge offline - run: python savebrain.py bridge</span>';
  const run = status
    ? (status.running ? "collecting" : "idle") + " - posts " + status.total
    : "content script not loaded (reload the tab)";
  $("stat").innerHTML = run + "<br>" + bdot;
}

$("start").addEventListener("click", async () => {
  const settings = buildSettings();
  await chrome.storage.local.set({ sb_settings: settings });
  const tab = await activeTab();
  try {
    await chrome.tabs.sendMessage(tab.id, { type: "SB_START", settings });
    $("stat").textContent = "started - watch the panel on the page";
  } catch (e) {
    $("stat").innerHTML = '<span class="dot-bad">reload the Instagram tab, then retry</span>';
  }
  setTimeout(refresh, 1500);
});

$("stop").addEventListener("click", async () => {
  const tab = await activeTab();
  try {
    await chrome.tabs.sendMessage(tab.id, { type: "SB_STOP" });
  } catch (_) {}
  setTimeout(refresh, 300);
});

$("port").addEventListener("change", refresh);
document.addEventListener("DOMContentLoaded", refresh);
setInterval(refresh, 2500);
