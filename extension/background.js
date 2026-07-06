// AI Career Copilot — background service worker (Manifest V3, v0.8).
//
// v0.8 responsibilities:
//   - Right-click selected text → 快速发送到 Career Copilot
//   - Bridge content-script messages (import PR / analyze JD) to the backend
//   - Trigger a manual GitHub sync from the popup / side panel
//   - Open the Side Panel when the action icon is clicked with modifier keys
//
// Config (API base + JWT) lives in chrome.storage.sync (Options page).

const DEFAULTS = { apiBase: "http://localhost:8000", token: "" };

async function getConfig() {
  const cfg = await chrome.storage.sync.get(DEFAULTS);
  return { ...DEFAULTS, ...cfg };
}

// ---------- Install: context menus + side panel behavior ----------

chrome.runtime.onInstalled.addListener(async () => {
  chrome.contextMenus.create({
    id: "cc-send-selection",
    title: "发送到 Career Copilot（自动识别）",
    contexts: ["selection"],
  });
  chrome.contextMenus.create({
    id: "cc-analyze-selection",
    title: "作为 JD 分析（Career Copilot）",
    contexts: ["selection"],
  });
  chrome.contextMenus.create({
    id: "cc-open-panel",
    title: "打开 Career Copilot 侧边栏",
    contexts: ["page", "selection"],
  });

  // Manifest V3 Side Panel: opens when the action icon is clicked.
  try {
    await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: false });
  } catch (e) {
    console.warn("[CareerCopilot] sidePanel API unavailable:", e);
  }
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === "cc-open-panel") {
    await openSidePanel(tab);
    return;
  }
  if (!info.selectionText) return;
  if (info.menuItemId === "cc-send-selection") {
    await generate("auto", info.selectionText);
  } else if (info.menuItemId === "cc-analyze-selection") {
    await analyzeJd(info.selectionText);
  }
});

async function openSidePanel(tab) {
  try {
    if (tab && tab.id) {
      await chrome.sidePanel.open({ tabId: tab.id });
    }
  } catch (e) {
    console.warn("[CareerCopilot] failed to open side panel:", e);
  }
}

// ---------- Message router: popup / content / sidepanel ----------

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    try {
      if (msg.type === "generate") {
        const data = await generate(msg.taskType || "auto", msg.content);
        sendResponse({ ok: true, data });
      } else if (msg.type === "analyzeJd") {
        const data = await analyzeJd(msg.content);
        sendResponse({ ok: true, data });
      } else if (msg.type === "githubSync") {
        const data = await githubSync();
        sendResponse({ ok: true, data });
      } else if (msg.type === "listEvents") {
        const data = await apiGet("/api/v1/integrations/events?limit=20");
        sendResponse({ ok: true, data });
      } else if (msg.type === "profileSnapshot") {
        const data = await apiGet("/api/v1/profile/snapshot");
        sendResponse({ ok: true, data });
      } else if (msg.type === "openSidePanel") {
        await openSidePanel(sender && sender.tab);
        sendResponse({ ok: true });
      } else {
        sendResponse({ ok: false, error: "unknown_message" });
      }
    } catch (e) {
      sendResponse({ ok: false, error: String(e) });
    }
  })();
  return true; // async response
});

// ---------- HTTP helpers ----------

async function authHeaders() {
  const { token } = await getConfig();
  const h = { "Content-Type": "application/json" };
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

async function apiGet(path) {
  const { apiBase } = await getConfig();
  const resp = await fetch(`${apiBase}${path}`, {
    method: "GET",
    headers: await authHeaders(),
  });
  if (!resp.ok) throw new Error(`${resp.status}`);
  return resp.json();
}

async function apiPost(path, body) {
  const { apiBase } = await getConfig();
  const resp = await fetch(`${apiBase}${path}`, {
    method: "POST",
    headers: await authHeaders(),
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) {
    let detail = `${resp.status}`;
    try {
      const j = await resp.json();
      if (j && j.detail) detail = j.detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return resp.json().catch(() => ({}));
}

// ---------- Feature actions ----------

// /api/v1/generate is an SSE stream. The extension fires the request and
// surfaces a status badge; the web UI is where the actual stream is rendered.
async function generate(taskType, content) {
  const { apiBase } = await getConfig();
  const resp = await fetch(`${apiBase}/api/v1/generate`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify({ task_type: taskType, input_content: content }),
  });
  notify(resp.ok ? "已发送到 Career Copilot" : `发送失败：${resp.status}`);
  return { status: resp.status };
}

async function analyzeJd(content) {
  const data = await apiPost("/api/v1/jd/analyze", { jd_text: content, with_matching: true });
  const score = data && data.overall_score;
  notify(`JD 已分析（匹配度 ${score ?? "-"}）`);
  return data;
}

async function githubSync() {
  const data = await apiPost("/api/v1/oauth/github/sync", {});
  notify(`GitHub 同步 · 新增 ${data.created ?? 0} / 更新 ${data.updated ?? 0}`);
  return data;
}

function notify(message) {
  chrome.action.setBadgeText({ text: "✓" });
  setTimeout(() => chrome.action.setBadgeText({ text: "" }), 3000);
  try {
    chrome.notifications.create({
      type: "basic",
      iconUrl: chrome.runtime.getURL("popup.html"),
      title: "AI Career Copilot",
      message,
      priority: 0,
    });
  } catch (_) {
    // notifications permission optional
  }
  console.log("[CareerCopilot]", message);
}
