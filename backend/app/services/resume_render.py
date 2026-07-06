"""Render a structured resume (JSON) into Markdown / HTML / PDF.

PDF generation uses WeasyPrint, which depends on system libraries
(pango/cairo). It is imported lazily and guarded: when unavailable,
:func:`render_pdf` raises :class:`PdfUnavailableError` and the API degrades to
HTML/Markdown export.
"""
from __future__ import annotations

from html import escape
from typing import Any


class PdfUnavailableError(RuntimeError):
    """Raised when WeasyPrint (and its system deps) are not installed."""


def _get(d: dict, *keys: str, default: Any = None) -> Any:
    for k in keys:
        v = d.get(k)
        if v:
            return v
    return default


def render_markdown(content: dict[str, Any]) -> str:
    basic = content.get("basic_info") or {}
    lines: list[str] = []

    name = _get(basic, "name", default="姓名")
    lines.append(f"# {name}")
    contact = [
        _get(basic, "headline"),
        _get(basic, "email"),
        _get(basic, "phone"),
        _get(basic, "location"),
    ]
    contact = [str(c) for c in contact if c]
    if contact:
        lines.append(" · ".join(contact))

    summary = content.get("summary")
    if summary:
        lines += ["", "## 个人简介", str(summary)]

    skills = content.get("skills") or []
    if skills:
        lines += ["", "## 技能", "、".join(str(s) for s in skills)]

    experiences = content.get("experiences") or []
    if experiences:
        lines += ["", "## 工作经历"]
        for exp in experiences:
            if not isinstance(exp, dict):
                continue
            header = " | ".join(
                str(x) for x in [exp.get("company"), exp.get("title")] if x
            )
            dates = " – ".join(
                str(x) for x in [exp.get("start_date"), exp.get("end_date")] if x
            )
            lines.append(f"### {header}" + (f"  ({dates})" if dates else ""))
            for b in exp.get("bullets") or []:
                lines.append(f"- {b}")

    projects = content.get("projects") or []
    if projects:
        lines += ["", "## 项目经历"]
        for p in projects:
            if not isinstance(p, dict):
                continue
            title = str(p.get("name") or "项目")
            role = p.get("role")
            lines.append(f"### {title}" + (f"  ({role})" if role else ""))
            if p.get("summary"):
                lines.append(str(p["summary"]))
            for h in p.get("highlights") or []:
                lines.append(f"- {h}")
            tech = p.get("tech_stack") or []
            if tech:
                lines.append("**技术栈**：" + "、".join(str(t) for t in tech))

    education = content.get("education") or []
    if education:
        lines += ["", "## 教育经历"]
        for ed in education:
            if not isinstance(ed, dict):
                continue
            parts = [ed.get("school"), ed.get("degree"), ed.get("major")]
            header = " | ".join(str(x) for x in parts if x)
            dates = " – ".join(
                str(x) for x in [ed.get("start_date"), ed.get("end_date")] if x
            )
            lines.append(f"- {header}" + (f"  ({dates})" if dates else ""))

    return "\n".join(lines).strip() + "\n"


_HTML_STYLE = """
body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
       color: #1a1a1a; max-width: 800px; margin: 32px auto; line-height: 1.55;
       font-size: 14px; padding: 0 24px; }
h1 { font-size: 26px; margin: 0 0 4px; }
h2 { font-size: 16px; border-bottom: 2px solid #333; padding-bottom: 4px;
     margin: 22px 0 10px; }
h3 { font-size: 14px; margin: 12px 0 4px; }
.contact { color: #555; margin-bottom: 8px; }
ul { margin: 4px 0 8px; padding-left: 20px; }
li { margin: 2px 0; }
.tech { color: #555; font-size: 13px; }
"""


def render_html(content: dict[str, Any]) -> str:
    basic = content.get("basic_info") or {}
    out: list[str] = [
        "<!doctype html><html lang='zh'><head><meta charset='utf-8'>",
        f"<style>{_HTML_STYLE}</style></head><body>",
    ]
    out.append(f"<h1>{escape(str(_get(basic, 'name', default='姓名')))}</h1>")
    contact = [
        _get(basic, "headline"),
        _get(basic, "email"),
        _get(basic, "phone"),
        _get(basic, "location"),
    ]
    contact = [escape(str(c)) for c in contact if c]
    if contact:
        out.append(f"<div class='contact'>{' · '.join(contact)}</div>")

    if content.get("summary"):
        out.append("<h2>个人简介</h2>")
        out.append(f"<p>{escape(str(content['summary']))}</p>")

    skills = content.get("skills") or []
    if skills:
        out.append("<h2>技能</h2>")
        out.append(f"<p>{escape('、'.join(str(s) for s in skills))}</p>")

    experiences = content.get("experiences") or []
    if experiences:
        out.append("<h2>工作经历</h2>")
        for exp in experiences:
            if not isinstance(exp, dict):
                continue
            header = " | ".join(str(x) for x in [exp.get("company"), exp.get("title")] if x)
            dates = " – ".join(str(x) for x in [exp.get("start_date"), exp.get("end_date")] if x)
            out.append(f"<h3>{escape(header)}{f' ({escape(dates)})' if dates else ''}</h3>")
            bullets = exp.get("bullets") or []
            if bullets:
                out.append("<ul>" + "".join(f"<li>{escape(str(b))}</li>" for b in bullets) + "</ul>")

    projects = content.get("projects") or []
    if projects:
        out.append("<h2>项目经历</h2>")
        for p in projects:
            if not isinstance(p, dict):
                continue
            role = p.get("role")
            out.append(f"<h3>{escape(str(p.get('name') or '项目'))}{f' ({escape(str(role))})' if role else ''}</h3>")
            if p.get("summary"):
                out.append(f"<p>{escape(str(p['summary']))}</p>")
            highlights = p.get("highlights") or []
            if highlights:
                out.append("<ul>" + "".join(f"<li>{escape(str(h))}</li>" for h in highlights) + "</ul>")
            tech = p.get("tech_stack") or []
            if tech:
                out.append(f"<p class='tech'>技术栈：{escape('、'.join(str(t) for t in tech))}</p>")

    education = content.get("education") or []
    if education:
        out.append("<h2>教育经历</h2><ul>")
        for ed in education:
            if not isinstance(ed, dict):
                continue
            parts = [ed.get("school"), ed.get("degree"), ed.get("major")]
            header = " | ".join(str(x) for x in parts if x)
            dates = " – ".join(str(x) for x in [ed.get("start_date"), ed.get("end_date")] if x)
            out.append(f"<li>{escape(header)}{f' ({escape(dates)})' if dates else ''}</li>")
        out.append("</ul>")

    out.append("</body></html>")
    return "".join(out)


def render_pdf(content: dict[str, Any]) -> bytes:
    """Render the resume to PDF bytes. Raises :class:`PdfUnavailableError`."""
    try:
        from weasyprint import HTML  # type: ignore
    except Exception as e:  # noqa: BLE001 - ImportError or OSError (missing libs)
        raise PdfUnavailableError(
            "PDF export requires WeasyPrint + system libs (pango/cairo). "
            "Install with: pip install '.[pdf]'"
        ) from e
    return HTML(string=render_html(content)).write_pdf()
