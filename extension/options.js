// AI Career Copilot — options page

const DEFAULTS = { apiBase: "http://localhost:8000", token: "" };
const $ = (id) => document.getElementById(id);

async function load() {
  const cfg = await chrome.storage.sync.get(DEFAULTS);
  $("apiBase").value = cfg.apiBase || DEFAULTS.apiBase;
  $("token").value = cfg.token || "";
}

$("save").addEventListener("click", async () => {
  await chrome.storage.sync.set({
    apiBase: $("apiBase").value.trim() || DEFAULTS.apiBase,
    token: $("token").value.trim(),
  });
  $("saved").textContent = "已保存 ✓";
  setTimeout(() => ($("saved").textContent = ""), 2000);
});

load();
