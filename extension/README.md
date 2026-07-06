# AI Career Copilot — Chrome Extension (v0.8 Beta+)

Manifest V3 浏览器扩展，覆盖 v0.8 PMO 文档中 §Chrome Extension 基础版全部要求：

- **右键选中文本** → 发送到 Career Copilot（自动识别 / 作为 JD 分析 / 打开侧边栏）
- **GitHub PR 页面** → 悬浮按钮「↗ 导入此 PR」，一键把 PR title + body 发送为 `pr_parse`
- **GitHub PRs 列表** → 悬浮按钮「⇆ 拉取我的 PR」，一键触发后端 `/api/v1/oauth/github/sync`
- **招聘网站 JD 页面**（LinkedIn / Boss / Lagou / 通用启发式）→ 一键分析当前 JD
- **Popup 快速录入** → 支持 `auto`/`weekly_report`/`star`/`pr_parse` 等意图，并可一键触发 GitHub 同步
- **Side Panel** → 打开侧边栏后可查看 Profile 概览（版本 / 条目数 / summary）、最近同步事件列表、快速录入
- 快捷键 `Alt+Shift+C` 打开扩展 Action

## 安装（开发者模式）

1. 启动后端（v0.8）：`make up`（默认 `http://localhost:8000`）。
2. Chrome → `chrome://extensions` → 打开「开发者模式」→「加载已解压的扩展程序」→ 选择本 `extension/` 目录。
3. 点击扩展图标 → ⚙ 设置 → 填入 API 地址与 JWT Token。
   - 不填 Token 走匿名 Level 0（受频率限制）；填入后可保存历史并积累 Profile。
4. 若要使用 GitHub 集成，先在 Web 工作台完成 GitHub OAuth 绑定（`/api/v1/oauth/github/authorize`），随后扩展的「⇆ GitHub 同步」按钮即可用。

## v0.8 相对 v0.5 的变化

| 能力 | v0.5 原型 | v0.8 |
| --- | --- | --- |
| Manifest 权限 | `contextMenus/storage/activeTab/scripting` | + `sidePanel` + `notifications` |
| 命令 | 无 | `Alt+Shift+C` 打开 Action |
| Side Panel | 无 | ✅ 侧边栏（Profile / GitHub 同步事件） |
| GitHub PR 列表页 | 无 | ✅ 一键触发后端 GitHub 同步 |
| JD 抽取 | 通用启发式 | 通用 + LinkedIn/Boss 定制 |
| 内容通知 | Badge + console | Badge + `chrome.notifications` |

## 说明

- `/api/v1/generate` 为 SSE 流式接口，原型中仅触发并以角标/通知提示；完整流式渲染在 Web 工作台完成。
- 未内置图标 PNG（避免二进制文件）；Chrome 会使用默认图标，不影响功能。
- Side Panel 需 Chrome ≥ 114；旧版浏览器降级为仅 popup + content script。
