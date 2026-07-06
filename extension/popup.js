// AI Career Copilot — popup (quick capture, v0.8).

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

$("send").addEventListener("click", async () => {
  const content = $("content").value.trim();
  if (!content) {
    $("status").textContent = "请输入内容";
    return;
  }
  $("status").textContent = "发送中…";
  try {
    await bg("generate", { taskType: $("task").value, content });
    $("status").textContent = "已发送 ✓";
    $("content").value = "";
  } catch (e) {
    $("status").textContent = `失败：${e.message}`;
  }
});

$("gh-sync").addEventListener("click", async () => {
  $("status").textContent = "GitHub 同步中…";
  try {
    const d = await bg("githubSync");
    $("status").textContent = `已同步 · 新增 ${d.created}, 更新 ${d.updated}`;
  } catch (e) {
    $("status").textContent = `同步失败：${e.message}`;
  }
});

$("panel").addEventListener("click", async () => {
  try {
    await bg("openSidePanel");
    window.close();
  } catch (e) {
    $("status").textContent = `无法打开：${e.message}`;
  }
});

$("opts").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});
