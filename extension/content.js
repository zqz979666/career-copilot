// AI Career Copilot — content script (v0.8).
//
// Injects a floating action button on:
//   - GitHub PR pages  → 一键导入 PR 内容 (title + body → pr_parse chain)
//   - GitHub PR list   → 一键触发 GitHub 一键同步（拉最近 30 个 PR）
//   - 招聘/JD 页面       → 一键分析当前正文
//
// v0.8 upgrades:
//   - Two-button toolbar (import + open side panel)
//   - Site-specific JD extractors (LinkedIn / Boss / Lagou / 通用)
//   - Uses task_type = "pr_parse" so backend routes to the PR chain
//   - Falls back gracefully when chrome.runtime is unavailable (SPA nav)

(function () {
  const host = location.hostname;
  const isGithubPr = /github\.com\/.+\/pull\/\d+/.test(location.href);
  const isGithubPrList = /github\.com\/.+\/pulls/.test(location.href);
  const isJdPage = !isGithubPr && !isGithubPrList;

  // ---------- extractors ----------

  function extractGithubPr() {
    const title = document.querySelector(".gh-header-title, .js-issue-title");
    const body = document.querySelector(".comment-body, .markdown-body");
    const t = title ? title.innerText.trim() : "";
    const b = body ? body.innerText.trim() : "";
    return `PR: ${t}\n\n${b}`.trim();
  }

  function extractLinkedInJd() {
    const el =
      document.querySelector(".jobs-description__content") ||
      document.querySelector(".jobs-box__html-content") ||
      document.querySelector("main");
    return (el && el.innerText) || "";
  }

  function extractBossJd() {
    const el =
      document.querySelector(".job-detail") ||
      document.querySelector(".job-sec-text") ||
      document.querySelector("main");
    return (el && el.innerText) || "";
  }

  function extractGenericJd() {
    const candidates = Array.from(
      document.querySelectorAll("article, main, .job-detail, .jobs-description, section")
    );
    let best = document.body;
    let bestLen = 0;
    for (const el of candidates) {
      const len = (el.innerText || "").length;
      if (len > bestLen) {
        bestLen = len;
        best = el;
      }
    }
    return best.innerText || "";
  }

  function extractPageJd() {
    let text = "";
    if (/linkedin\.com/.test(host)) text = extractLinkedInJd();
    else if (/zhipin\.com/.test(host)) text = extractBossJd();
    if (!text) text = extractGenericJd();
    return (text || "").trim().slice(0, 8000);
  }

  // ---------- UI ----------

  function makeBar(children) {
    const bar = document.createElement("div");
    Object.assign(bar.style, {
      position: "fixed",
      right: "20px",
      bottom: "20px",
      zIndex: "999999",
      display: "flex",
      gap: "8px",
      alignItems: "center",
    });
    for (const c of children) bar.appendChild(c);
    document.body.appendChild(bar);
    return bar;
  }

  function makeButton(label, opts, onClick) {
    const btn = document.createElement("button");
    btn.textContent = label;
    Object.assign(
      btn.style,
      {
        padding: "10px 14px",
        background: "#4f46e5",
        color: "#fff",
        border: "none",
        borderRadius: "8px",
        boxShadow: "0 4px 12px rgba(0,0,0,.2)",
        cursor: "pointer",
        fontSize: "13px",
      },
      opts && opts.style
    );
    btn.addEventListener("click", onClick);
    return btn;
  }

  function send(type, payload, cb) {
    if (!chrome.runtime || !chrome.runtime.id) {
      alert("扩展未就绪（SPA 页面刷新一下即可）");
      return;
    }
    chrome.runtime.sendMessage({ type, ...payload }, (resp) => {
      const ok = resp && resp.ok;
      if (cb) cb(resp);
      else alert(ok ? "已发送 ✓" : `失败：${resp && resp.error}`);
    });
  }

  function openPanel() {
    send("openSidePanel", {});
  }

  // ---------- mount ----------

  if (isGithubPr) {
    makeBar([
      makeButton("↗ 导入此 PR", null, () =>
        send("generate", { content: extractGithubPr(), taskType: "pr_parse" })
      ),
      makeButton("⇪ 侧边栏", { style: { background: "#111827" } }, openPanel),
    ]);
    return;
  }
  if (isGithubPrList) {
    makeBar([
      makeButton("⇆ 拉取我的 PR", null, () =>
        send("githubSync", {}, (resp) => {
          const d = resp && resp.data;
          const msg = d
            ? `已同步：抓取 ${d.fetched}，新增 ${d.created}，更新 ${d.updated}`
            : `失败：${resp && resp.error}`;
          alert(msg);
        })
      ),
    ]);
    return;
  }
  if (isJdPage) {
    makeBar([
      makeButton("↗ 分析此 JD", null, () =>
        send("analyzeJd", { content: extractPageJd() }, (resp) => {
          const d = resp && resp.data;
          const s = d && d.overall_score;
          alert(d ? `已分析（匹配度 ${s ?? "-"}）` : `失败：${resp && resp.error}`);
        })
      ),
      makeButton("⇪ 侧边栏", { style: { background: "#111827" } }, openPanel),
    ]);
  }
})();
