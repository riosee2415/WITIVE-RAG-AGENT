"""transcript 분석 결과 → reports/YYYY-MM-DD-<slug>.html 발행."""
from __future__ import annotations

import datetime as dt
import html
import re
from pathlib import Path


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text or "", flags=re.UNICODE).strip().lower()
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:50] or "session"


def write_html_report(info: dict, root: Path, session_id: str) -> Path:
    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    today = dt.date.today().strftime("%Y-%m-%d")
    first_prompt = (info.get("user_prompts") or ["session"])[0]
    slug = slugify(first_prompt) or session_id[:8]
    out = reports_dir / f"{today}-{slug}.html"
    if out.exists():
        for i in range(2, 100):
            cand = reports_dir / f"{today}-{slug}-{i}.html"
            if not cand.exists():
                out = cand
                break

    u = info.get("usage", {}) or {}
    in_tok = int(u.get("input", 0))
    out_tok = int(u.get("output", 0))
    cache_r = int(u.get("cache_read", 0))
    cache_c = int(u.get("cache_create", 0))

    rows_changes = "".join(
        f"<li><code>{html.escape(c)}</code></li>" for c in info.get("changes", [])
    ) or "<li><em>변경 없음</em></li>"

    rows_tools = "".join(
        f"<tr><td>{html.escape(t.get('name', ''))}</td>"
        f"<td><code>{html.escape(str(t.get('input', ''))[:240])}</code></td></tr>"
        for t in (info.get("tools") or [])[:80]
    ) or "<tr><td colspan='2'><em>도구 호출 없음</em></td></tr>"

    rows_errors = "".join(
        f"<li><pre>{html.escape(e)}</pre></li>" for e in (info.get("errors") or [])[:20]
    ) or "<li><em>에러 없음</em></li>"

    rows_prompts = "".join(
        f"<li><pre>{html.escape(p)}</pre></li>" for p in (info.get("user_prompts") or [])[:20]
    ) or "<li><em>프롬프트 없음</em></li>"

    rows_subagents = "".join(
        f"<li><code>{html.escape(s)}</code></li>" for s in (info.get("subagents_called") or [])
    ) or "<li><em>서브에이전트 호출 없음</em></li>"

    body = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<title>{html.escape(today)} — {html.escape(slug)}</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:1000px;margin:2rem auto;padding:0 1rem;color:#222;line-height:1.5}}
h1{{border-bottom:2px solid #333;padding-bottom:.4rem;margin-bottom:.4rem}}
h2{{margin-top:2rem;padding:.4rem .6rem;background:#f5f5f5;border-left:4px solid #555;font-size:1.1em}}
table{{border-collapse:collapse;width:100%;font-size:.9em}}
th,td{{border:1px solid #ddd;padding:.4rem .6rem;text-align:left;vertical-align:top}}
th{{background:#fafafa}}
code{{background:#f0f0f0;padding:.1rem .3rem;border-radius:3px;font-size:.9em;font-family:Consolas,monospace}}
pre{{background:#f7f7f7;padding:.6rem;border-radius:4px;overflow-x:auto;white-space:pre-wrap;word-break:break-word;font-size:.85em;margin:.3rem 0}}
.kpi{{display:flex;gap:.6rem;flex-wrap:wrap;margin:.6rem 0}}
.kpi div{{flex:1;min-width:140px;padding:.6rem .8rem;background:#f5f5f5;border-radius:6px;border:1px solid #e5e5e5}}
.kpi b{{display:block;font-size:1.5em;color:#222;margin-bottom:.2rem}}
.kpi span{{font-size:.85em;color:#666}}
.meta{{color:#666;font-size:.9em}}
ul{{padding-left:1.2rem}}
</style></head><body>
<h1>{html.escape(today)} — {html.escape(slug)}</h1>
<p class="meta"><strong>session</strong>: <code>{html.escape(session_id)}</code> · 발행: {dt.datetime.now().isoformat(timespec='seconds')}</p>

<h2>토큰 사용량</h2>
<div class="kpi">
  <div><b>{in_tok:,}</b><span>input</span></div>
  <div><b>{out_tok:,}</b><span>output</span></div>
  <div><b>{cache_r:,}</b><span>cache read</span></div>
  <div><b>{cache_c:,}</b><span>cache create</span></div>
</div>

<h2>사용자 프롬프트 ({len(info.get("user_prompts") or [])}개)</h2>
<ul>{rows_prompts}</ul>

<h2>변경 파일 ({len(info.get("changes") or [])}개)</h2>
<ul>{rows_changes}</ul>

<h2>호출된 서브에이전트</h2>
<ul>{rows_subagents}</ul>

<h2>도구 호출 (최대 80개)</h2>
<table><thead><tr><th style="width:140px">도구</th><th>입력 요약</th></tr></thead><tbody>{rows_tools}</tbody></table>

<h2>에러 로그 (최대 20개)</h2>
<ul>{rows_errors}</ul>

<hr>
<p class="meta"><small>자동 발행: <code>.claude/scripts/post_stop_orchestrator.py</code></small></p>
</body></html>"""

    out.write_text(body, encoding="utf-8")
    return out
