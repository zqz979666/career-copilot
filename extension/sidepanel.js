// AI Career Copilot — Side Panel controller (v0.8).
//
// Talks to the extension's service worker via chrome.runtime.sendMessage so
// the same auth/apiBase config drives every panel action.

const $ = (id) => document.getElementById(id);

function bg(type, payload = {}) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage({ type, ...payload }, (resp) => {
      if (!resp) return reject(new Error("no_response"));
      if (!resp.ok) return reject(new Error(resp.error || "failed"));
      resolve(resp.data);
    });
  });
}

async function loadProfile() {
  try {
    const snap = await bg("profileSnapshot");
    $("entry-count").textContent = snap.entry_count ?? 0;
    $("version").textContent = snap.version ?? 0;
    $("summary").textContent = snap.summary || "(尚未生成 Profile 摘要)";
  } catch (e) {
    $("summary").textContent = `载入失败：${e.message}`;
  }
}

function renderEvents(list) {
  const ul = $("events");
  ul.innerHTML = "";
  if (!list || list.length === 0) {
    const li = document.createElement("li");
    li.className = "muted";
    li.textContent = "暂无同步事件。链接 GitHub 后即可看到。";
    ul.appendChild(li);
    return;
  }
  for (const e of list) {
    const li = document.createElement("li");
    const badge = document.createElement("span");
    badge.className = "pill " + (e.status === "processed" ? "ok" : e.status === "failed" ? "err" : "");
    badge.textContent = e.status;
    li.appendChild(badge);
    const meta = document.createElement("span");
    meta.textContent = `${e.provider}/${e.event_type} · ${new Date(e.created_at).toLocaleString()}`;
    li.appendChild(meta);
    ul.appendChild(li);
  }
}

async function loadEvents() {
  try {
    const data = await bg("listEvents");
    renderEvents(data.items || []);
  } catch (e) {
    renderEvents([]);
  }
}

$("send").addEventListener("click", async () => {
  const content = $("quick").value.trim();
  if (!content) return ($("status").textContent = "请输入内容");
  $("status").textContent = "发送中…";
  try {
    await bg("generate", { content, taskType: $("task").value });
    $("status").textContent = "已发送 ✓";
    $("quick").value = "";
  } catch (e) {
    $("status").textContent = `失败：${e.message}`;
  }
});

$("gh-sync").addEventListener("click", async () => {
  $("gh-sync").disabled = true;
  $("gh-sync").textContent = "同步中…";
  try {
    const d = await bg("githubSync");
    alert(`同步完成：抓取 ${d.fetched} / 新增 ${d.created} / 更新 ${d.updated}`);
    await Promise.all([loadEvents(), loadProfile()]);
  } catch (e) {
    alert(`失败：${e.message}`);
  } finally {
    $("gh-sync").disabled = false;
    $("gh-sync").textContent = "⇆ 拉取最近 PR";
  }
});

$("refresh-profile").addEventListener("click", loadProfile);
$("refresh-events").addEventListener("click", loadEvents);
$("opts").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

loadProfile();
loadEvents();
