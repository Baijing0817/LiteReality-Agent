"""Render a finished harness run into ONE self-contained HTML report, so you can watch
EXACTLY what the plan-first agentic loop did, end to end:

  1. Diagnosis & plan — the planner VLM's summary + every item it decided to fix
     (target · problem · intended edit · how to verify · priority).
  2. Surface references & triage — the real-surface evidence the run built.
  3. The exact prompt the stage agent received.
  4. The run — read → think → act: the agent's FULL conversation, every tool call,
     a THUMBNAIL of each image it actually read, and every code edit as an old→new diff.
  5. Every code edit — a digest of all edits, each linked to the plan item(s) it addresses
     with the planner's intended change as the explanation.
  6. Verdict — did each planned fix land? the planner's per-item done/not-done + note,
     which (with the layout + scope checks) IS the gate.
  7. Render progression — every render/compare round.
  8. Final judged views — render | photo.

Everything (images included) is embedded as base64 → a single portable .html. Reads only
what the harness recorded under the iteration's .harness_tracking/ + room_preview/.

    python -m litereality_agent.pipeline.stages.publish.report --scan <scan> --stage 1
    # -> run/<scan>/scene_init/scene_stage/stage_<N>/iteration_<M>/report.html
"""

from __future__ import annotations

import base64
import html
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# --------------------------------------------------------------------------- #
def _data_uri(path: Path, max_side: int = 900, quality: int = 80) -> str | None:
    """Downscaled JPEG data-URI for embedding (None if missing/unreadable)."""
    try:
        from PIL import Image

        im = Image.open(path).convert("RGB")
        w, h = im.size
        if max(w, h) > max_side:
            s = max_side / max(w, h)
            im = im.resize((int(w * s), int(h * s)))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def _esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _img_tag(path: Path, cls: str = "", max_side: int = 900) -> str:
    uri = _data_uri(path, max_side=max_side)
    if not uri:
        return f'<div class="imgmiss">missing: {_esc(path.name)}</div>'
    return f'<img class="{cls}" src="{uri}" loading="lazy">'


def _is_image(p: str) -> bool:
    return str(p).lower().rsplit(".", 1)[-1] in ("jpg", "jpeg", "png", "webp")


def _fmt_t(t) -> str:
    if t is None:
        return ""
    t = float(t)
    return f"{int(t // 60)}:{t % 60:04.1f}" if t >= 60 else f"{t:.1f}s"


def _usage_str(u: dict | None) -> str:
    if not u:
        return ""
    parts = []
    if u.get("output_tokens"):
        parts.append(f"{u['output_tokens']:,} out")
    if u.get("input_tokens"):
        parts.append(f"{u['input_tokens']:,} in")
    if u.get("cache_read_input_tokens"):
        parts.append(f"{u['cache_read_input_tokens']:,} cache")
    return " · ".join(parts)


def _pri_cls(p) -> str:
    s = str(p).lower()
    if s in ("high", "1", "critical"):
        return "hi"
    if s in ("low", "3"):
        return "lo"
    return "med"


def _plan_targets(plan: dict) -> list[str]:
    """The distinct surface/object names the plan touches (for linking edits ↔ plan)."""
    out = []
    for it in plan.get("items") or []:
        t = str(it.get("target") or "").strip()
        if t and t not in out:
            out.append(t)
    return out


def _match_targets(text: str, targets: list[str]) -> list[str]:
    text = text or ""
    return [t for t in targets if t and t in text]


# --------------------------------------------------------------------------- #
def _section_plan(plan: dict, verdict: dict) -> str:
    """§1 — the planner VLM's diagnosis + the concrete plan it wrote BEFORE editing.
    This is the brain of the loop: what the model decided to do, and why."""
    if not plan or not plan.get("items"):
        return ""
    done_by_target: dict[str, dict] = {}
    for v in (verdict.get("items") or []):
        done_by_target.setdefault(str(v.get("target")), v)
    cards = []
    for i, it in enumerate(plan["items"]):
        tgt = str(it.get("target") or "?")
        v = done_by_target.get(tgt) or {}
        done = v.get("done")
        mark = (
            '<span class="vmark ok">✓ done</span>'
            if done
            else ('<span class="vmark no">✗ not done</span>' if done is not None else "")
        )
        rows = ""
        for lbl, key, cls in (("problem", "problem", "prob"), ("edit", "edit", "edit"),
                              ("verify", "verify", "verify")):
            if it.get(key):
                rows += f'<div class="planrow"><span class="plbl {cls}">{lbl}</span>{_esc(it[key])}</div>'
        cards.append(
            f'<div class="planitem" id="plan-{i}">'
            f'<div class="planhead"><span class="pri pri-{_pri_cls(it.get("priority"))}">'
            f'{_esc(it.get("priority") or "")}</span> <b>{_esc(tgt)}</b> {mark}</div>{rows}</div>'
        )
    summ = _esc(plan.get("summary") or "")
    model = _esc(plan.get("_model") or "")
    return (
        f'<section id="plan"><h2>1 · Diagnosis &amp; plan — what the agent decided to do</h2>'
        f'<p class="muted">Before touching any code, the planner VLM{f" ({model})" if model else ""} '
        f"looked at the render vs the photos + the head-on surface references and wrote a concrete, "
        f"per-surface to-do list. The editor then executes every item; each is re-checked afterwards "
        f"(§6). This is the whole decision — there is no opaque similarity score.</p>"
        f'{("<div class=summary><b>planner summary:</b> " + summ + "</div>") if summ else ""}'
        f'<div class="planlist">{"".join(cards)}</div></section>'
    )


def _section_refs(manifest: dict, surface_ref: Path) -> str:
    if not manifest:
        return ""
    cards = []
    for s in manifest.get("surfaces", []):
        t = s["triage"]
        img = Path(s["image"])
        if not img.is_absolute():
            img = surface_ref / img.name
        meta = (
            f"cov {t['coverage']:.0%} · {t.get('color_hex') or '--'} · edge_med {t.get('edge_med')}"
        )
        cards.append(
            f'<div class="ref"><div class="reftitle">{_esc(s["name"])} '
            f'<span class="tag tag-{t["class"]}">{_esc(t["class"])}</span></div>'
            f"{_img_tag(img, 'refimg', 460)}"
            f'<div class="refmeta">{_esc(meta)}</div></div>'
        )
    shared = manifest.get("shared_wall_color")
    sh = ""
    if shared:
        sh = (
            f'<div class="shared">shared plain-wall colour '
            f'<span class="swatch" style="background:{_esc(shared["color_hex"])}"></span> '
            f"<code>{_esc(shared['color_hex'])}</code> "
            f"(from {_esc(', '.join(shared['from_walls']))})</div>"
        )
    return (
        f'<section id="refs"><h2>2 · Surface references &amp; triage</h2>'
        f'<p class="muted">Rectified head-on stitch per surface + the plain/detailed '
        f"triage hint. This is the material evidence the run built (once per scan); the agent "
        f"also had per-wall sharp boxed frames + the ~10 verification views (see the prompt + timeline).</p>"
        f'{sh}<div class="refgrid">{"".join(cards)}</div></section>'
    )


def _section_prompt(prompt_md: str) -> str:
    return (
        f'<section id="prompt"><h2>3 · The exact prompt the agent received</h2>'
        f'<p class="muted">The stage brief + run-context (tools, references, hard '
        f"rules) + the plan, sent to the stage agent.</p>"
        f"<details><summary>show full prompt ({len(prompt_md):,} chars)</summary>"
        f'<pre class="prompt">{_esc(prompt_md)}</pre></details></section>'
    )


def _section_trajectory(rows: list[dict], root: Path, targets: list[str]) -> str:
    chip_cls = {"Read": "read", "Bash": "bash", "Edit": "edit", "Write": "edit",
                "Glob": "read", "Grep": "read", "TodoWrite": "meta"}
    items = []
    n_tool = 0
    for r in rows:
        kind = r.get("kind")
        ts = f'<span class="ts">{_fmt_t(r.get("t"))}</span>'
        if kind == "text":
            items.append(f'<div class="think">{ts}{_esc(r.get("text"))}</div>')
        elif kind == "thinking":
            items.append(f'<div class="think dim">{ts}<i>{_esc(r.get("text"))}</i></div>')
        elif kind == "usage":
            items.append(
                f'<div class="usage">{ts}turn {_esc(r.get("turn"))} · '
                f"{_esc(_usage_str(r.get('usage')))}</div>"
            )
        elif kind == "round":
            items.append(
                f'<div class="roundmark">{ts}◉ round {_esc(r.get("round"))} — '
                f"render / compare ({_esc(len(r.get('images') or []))} views) "
                f'<span class="muted">see progression below</span></div>'
            )
        elif kind == "tool":
            n_tool += 1
            name = r.get("name", "?")
            brief = (r.get("brief") or "").strip()
            cls = chip_cls.get(name, "meta")
            dt = f'<span class="dt">{_fmt_t(r.get("dt"))}</span>' if r.get("dt") is not None else ""
            body = _esc(r.get("cmd") or brief)
            # inline thumbnail of an image the agent READ (what it consumed)
            thumb = ""
            if name == "Read" and _is_image(brief):
                p = Path(brief)
                if not p.is_absolute():
                    p = root / brief
                if p.exists():
                    thumb = f'<div class="thumb">{_img_tag(p, "", 340)}</div>'
            # Edit/Write -> old->new diff, + which plan target(s) this edit touches
            extra = ""
            d = r.get("diff")
            if d:
                old, new = d.get("old"), d.get("new")
                hit = _match_targets((old or "") + " " + (new or ""), targets)
                tags = "".join(f'<a class="ttag" href="#plan-0">{_esc(t)}</a>' for t in hit)
                extra = (
                    f'<details class="diff" open><summary>edit · '
                    f'{_esc(Path(str(d.get("file") or "")).name)}'
                    f'{(" → " + tags) if tags else ""}</summary>'
                    + (f'<pre class="old">{_esc(old)}</pre>' if old else "")
                    + (f'<pre class="new">{_esc(new)}</pre>' if new else "")
                    + "</details>"
                )
            rr = r.get("result")
            if rr and rr.get("text"):
                rcls = "rok" if rr.get("ok") else "rerr"
                rtxt = rr["text"]
                first = rtxt.splitlines()[0] if rtxt else ""
                extra += (
                    f'<details class="res {rcls}"><summary>result · {_esc(first[:80])}</summary>'
                    f"<pre>{_esc(rtxt)}</pre></details>"
                )
            items.append(
                f'<div class="act"><span class="chip chip-{cls}">{n_tool}. {_esc(name)}</span>'
                f'{ts}{dt}<code class="brief">{body}</code>{thumb}{extra}</div>'
            )
        elif kind == "result":
            items.append(
                f'<div class="result">{ts}✓ agent finished — {_esc(r.get("num_turns"))} turns, '
                f"${_esc(round(r.get('cost_usd') or 0, 2))}, {_fmt_t(r.get('duration_s'))}"
                + (f" · {_esc((r.get('result_tail') or '')[-300:])}" if r.get("result_tail") else "")
                + "</div>"
            )
        elif kind == "error":
            items.append(f'<div class="err">{ts}⚠ {_esc(r.get("error"))}</div>')
    return (
        f'<section id="run"><h2>4 · The run — read → think → act</h2>'
        f'<p class="muted">{n_tool} actions, in order. The agent\'s own words are in grey '
        f"(that\'s where it decides what to look at next); actions are colour-coded "
        f"(Read=blue, Bash=amber, Edit=green). Each image the agent READ shows its thumbnail; "
        f"each edit expands to the old→new diff tagged with the plan surface it changes; tool "
        f"results expand to their output. Timestamps are elapsed; per-turn token usage is shown.</p>"
        f'<div class="timeline">{"".join(items)}</div></section>'
    )


def _collect_edits(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("kind") == "tool"
            and r.get("name") in ("Edit", "Write") and r.get("diff")]


def _section_edits(rows: list[dict], plan: dict) -> str:
    """§5 — a focused digest of every code edit, linked to the plan item it satisfies."""
    edits = _collect_edits(rows)
    if not edits:
        return ""
    targets = _plan_targets(plan)
    plan_by_target: dict[str, dict] = {}
    for i, it in enumerate(plan.get("items") or []):
        plan_by_target.setdefault(str(it.get("target")), {**it, "_i": i})
    cards = []
    for n, r in enumerate(edits, 1):
        d = r["diff"]
        old, new = d.get("old"), d.get("new")
        hit = _match_targets((old or "") + " " + (new or ""), targets)
        # explanation = the planner's intended edit for the matched target(s)
        expl = ""
        for t in hit:
            pit = plan_by_target.get(t)
            if pit and pit.get("edit"):
                expl += (
                    f'<div class="editexpl"><a class="ttag" href="#plan-{pit["_i"]}">{_esc(t)}</a> '
                    f'<span class="muted">plan:</span> {_esc(pit["edit"])}</div>'
                )
        cards.append(
            f'<div class="editcard"><div class="edithead">'
            f'<span class="chip chip-edit">{n}</span> '
            f'<code class="brief">{_esc(Path(str(d.get("file") or "")).name)}</code>'
            f'<span class="ts" style="margin-left:8px">{_fmt_t(r.get("t"))}</span></div>'
            f"{expl}"
            + (f'<pre class="old">{_esc(old)}</pre>' if old else "")
            + (f'<pre class="new">{_esc(new)}</pre>' if new else "")
            + "</div>"
        )
    return (
        f'<section id="edits"><h2>5 · Every code edit ({len(edits)})</h2>'
        f'<p class="muted">Every change the agent made to the room definition, in order, as an '
        f"old→new diff. Where the edit touches a planned surface, it is linked to that plan item "
        f"and annotated with the planner\'s intended change (the \"what it does\").</p>"
        f'<div class="editlist">{"".join(cards)}</div></section>'
    )


def _section_verdict(verdict: dict, gate_pass: bool, out_of_scope: list, layout: dict) -> str:
    """§6 — the planner's per-item done/not-done (this IS the gate, with scope+layout checks)."""
    items = verdict.get("items") or []
    done_n = sum(1 for v in items if v.get("done"))
    rows = []
    for v in items:
        done = v.get("done")
        rows.append(
            f'<div class="vitem {"ok" if done else "no"}">'
            f'<div class="vhead"><span class="vmark {"ok" if done else "no"}">'
            f'{"✓" if done else "✗"}</span> <b>{_esc(v.get("target"))}</b></div>'
            f'<div class="vnote">{_esc(v.get("note"))}</div></div>'
        )
    checks = []
    checks.append(
        f'<li class="{"ok" if not out_of_scope else "no"}">no out-of-scope edits — '
        f'{("clean" if not out_of_scope else _esc(", ".join(map(str, out_of_scope))[:200]))}</li>'
    )
    viol = (layout or {}).get("violations") or []
    checks.append(
        f'<li class="{"ok" if not viol else "no"}">no layout violations — '
        f'{("clean" if not viol else str(len(viol)) + " violation(s)")}</li>'
    )
    checks.append(
        f'<li class="{"ok" if verdict.get("all_done") else "no"}">every plan item done — '
        f'{done_n}/{len(items)}</li>'
    )
    summ = _esc(verdict.get("summary") or "")
    badge = (
        f'<span class="badge {"ok" if gate_pass else "no"}">gate '
        f"{'PASSED' if gate_pass else 'FAILED'}</span>"
    )
    return (
        f'<section id="verdict"><h2>6 · Verdict — did each planned fix land? {badge}</h2>'
        f'<p class="muted">After the edits, the planner VLM re-read the new render vs the photos '
        f"and marked each plan item done / not-done. That, plus the scope + layout hard-checks, IS "
        f"the gate — no SSIM, no opaque score. Not-done items are fed back into the next attempt.</p>"
        f'<ul class="checks">{"".join(checks)}</ul>'
        f'{("<div class=summary><b>verify summary:</b> " + summ + "</div>") if summ else ""}'
        f'<div class="vlist">{"".join(rows)}</div></section>'
    )


def _section_progression(iter_dir: Path) -> str:
    rdir = iter_dir / ".harness_tracking" / "rounds"
    if not rdir.is_dir():
        rdir = iter_dir / "rounds"
    if not rdir.is_dir():
        return ""
    rounds = sorted(
        (p for p in rdir.glob("round_*") if any(p.glob("*.jpg"))),
        key=lambda p: int(p.name.split("_")[1]),
    )
    if not rounds:
        return ""
    blocks = []
    for rp in rounds:
        k = int(rp.name.split("_")[1])
        imgs = sorted(rp.glob("*.jpg"))
        label = "round 0 · seeded baseline" if k == 0 else f"round {k} · after edit → render"
        thumbs = "".join(
            f'<div class="prog"><div class="progf">{_esc(im.stem)}</div>{_img_tag(im, "progimg", 460)}</div>'
            for im in imgs[:10]
        )
        blocks.append(
            f'<div class="proground"><div class="proglabel">{_esc(label)} '
            f'<span class="muted">({len(imgs)} views)</span></div>'
            f'<div class="progrow">{thumbs}</div></div>'
        )
    return (
        f'<section id="progression"><h2>7 · Render progression — every render / compare round</h2>'
        f'<p class="muted">room_preview/ is overwritten on each render, so each round is '
        f"snapshotted here. round 0 = the seeded baseline; each later round = one "
        f"edit→render cycle. LEFT half = reconstruction, RIGHT half = photo.</p>"
        f"{''.join(blocks)}</section>"
    )


def _section_renders(pairs: list[dict]) -> str:
    cards = []
    for p in pairs:
        sb = Path(p.get("sidebyside", ""))
        cards.append(
            f'<div class="rend"><div class="rendtitle">{_esc(p["frame"])} '
            f'<span class="lr">render | photo</span></div>{_img_tag(sb, "rendimg", 900)}</div>'
        )
    return (
        f'<section id="finalviews"><h2>8 · Final judged views (render&nbsp;|&nbsp;photo)</h2>'
        f'<p class="muted">The final views the planner judged in §6 — LEFT is the reconstruction, '
        f"RIGHT the ground-truth photo.</p>"
        f'<div class="rendgrid">{"".join(cards)}</div></section>'
    )


_CSS = """
:root{--bg:#0f1216;--panel:#171b21;--ink:#dfe4ea;--muted:#8b94a0;--line:#262c34;
--read:#3b82f6;--bash:#d97706;--edit:#16a34a;--meta:#6b7280}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.55 -apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1120px;margin:0 auto;padding:28px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:0 0 10px;color:#fff}
section{background:var(--panel);border:1px solid var(--line);border-radius:12px;
padding:18px 20px;margin:18px 0;scroll-margin-top:56px}
.muted{color:var(--muted);margin:.2em 0 1em}.lr{color:var(--muted);font-size:12px;float:right}
.hdr{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:6px 0 2px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:8px 14px}
.kpi .muted{margin:0;font-size:11px}.kpi b{font-size:18px}
.badge{padding:3px 10px;border-radius:20px;font-weight:700;font-size:12px}
.badge.ok{background:#0c3;color:#021}.badge.no{background:#c33;color:#fee}
.toc{position:sticky;top:0;z-index:5;display:flex;gap:14px;flex-wrap:wrap;padding:10px 14px;
margin:10px 0 6px;background:#0d1014ee;border:1px solid var(--line);border-radius:10px;backdrop-filter:blur(6px)}
.toc a{color:#9cc4ff;text-decoration:none;font-size:13px}.toc a:hover{text-decoration:underline}
details{margin:.5em 0}summary{cursor:pointer;color:#9cc4ff}
pre.prompt{white-space:pre-wrap;background:#0b0e12;border:1px solid var(--line);
border-radius:8px;padding:14px;max-height:520px;overflow:auto;font-size:12px;color:#c8d0da}
.summary{background:#0b0e12;border:1px solid var(--line);border-radius:8px;padding:12px;margin:10px 0}
/* plan */
.planlist{display:flex;flex-direction:column;gap:10px}
.planitem{background:#0b0e12;border:1px solid var(--line);border-left:4px solid var(--meta);border-radius:8px;padding:10px 12px}
.planhead{font-weight:600;margin-bottom:5px;display:flex;align-items:center;gap:8px}
.pri{font-size:10px;text-transform:uppercase;font-weight:700;padding:2px 7px;border-radius:5px}
.pri-hi{background:#3a1616;color:#f0a0a0}.pri-med{background:#33270f;color:#e6b465}.pri-lo{background:#1a2a1a;color:#9fd8a0}
.planrow{margin:3px 0;padding-left:2px}
.plbl{display:inline-block;min-width:58px;font-size:10px;text-transform:uppercase;font-weight:700;
padding:1px 6px;border-radius:4px;margin-right:8px;text-align:center}
.plbl.prob{background:#33232a;color:#d08fa0}.plbl.edit{background:#10301c;color:#6fd897}.plbl.verify{background:#13243d;color:#7fb0f0}
.vmark{font-size:11px;font-weight:700;padding:1px 8px;border-radius:10px}
.vmark.ok{background:#0c3a1c;color:#7fe0a0}.vmark.no{background:#3a1616;color:#f0a0a0}
/* refs */
.refgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}
.ref{background:#0b0e12;border:1px solid var(--line);border-radius:8px;padding:8px}
.refimg,.rendimg{width:100%;border-radius:6px;display:block}
.reftitle{font-weight:600;margin-bottom:6px;display:flex;justify-content:space-between;align-items:center}
.refmeta{color:var(--muted);font-size:12px;margin-top:6px}
.tag{font-size:11px;padding:1px 7px;border-radius:10px}
.tag-plain{background:#23303f;color:#8fb6e0}.tag-detailed{background:#3a2a14;color:#e0b070}
.tag-low_coverage{background:#33232a;color:#d08fa0}
.shared{margin:0 0 12px;color:var(--muted)}.swatch{display:inline-block;width:14px;height:14px;
border-radius:3px;vertical-align:middle;border:1px solid #0008}
/* timeline */
.timeline{display:flex;flex-direction:column;gap:7px}
.think{background:#12161c;border-left:3px solid var(--meta);padding:8px 12px;border-radius:0 6px 6px 0;color:#c4ccd6}
.act{display:flex;gap:10px;align-items:flex-start;flex-wrap:wrap}
.chip{font-size:11px;font-weight:700;padding:3px 9px;border-radius:6px;white-space:nowrap;flex:none}
.chip-read{background:#13243d;color:#7fb0f0}.chip-bash{background:#33270f;color:#e6b465}
.chip-edit{background:#10301c;color:#6fd897}.chip-meta{background:#222831;color:#9aa4b0}
.brief{font-size:12px;color:#aab3bf;word-break:break-all;background:#0b0e12;padding:2px 7px;border-radius:5px}
.thumb{flex-basis:100%;margin-top:4px}.thumb img{max-width:360px;border:1px solid var(--line);border-radius:6px}
.result{background:#10301c;color:#9fe7bf;padding:8px 12px;border-radius:6px}
.err{background:#3a1414;color:#f0a0a0;padding:8px 12px;border-radius:6px}
.ts{display:inline-block;min-width:48px;color:#5f6b78;font-size:11px;font-variant-numeric:tabular-nums;margin-right:8px}
.dt{color:#d9a406;font-size:11px;margin-right:6px}
.think.dim{opacity:.7;border-left-color:#3a4a36}
.usage{color:#6b7686;font-size:11px;padding:1px 0 1px 4px}
.roundmark{background:#1a2230;border:1px solid #2a3b52;color:#9cc4ff;font-weight:600;
padding:6px 12px;border-radius:6px;margin:4px 0}
.ttag{font-size:11px;background:#13243d;color:#7fb0f0;padding:1px 7px;border-radius:5px;text-decoration:none;margin-left:4px}
details.diff summary{color:#7fcf9a}details.res summary{color:#9aa4b0}
details.diff pre,details.res pre,.editcard pre{white-space:pre-wrap;font-size:11px;border-radius:6px;padding:8px;
max-height:340px;overflow:auto;margin:4px 0}
pre.old{background:#2a1414;color:#e6a3a3;border:1px solid #46201f}
pre.new{background:#10250f;color:#a3e0a3;border:1px solid #1f461f}
details.res pre{background:#0b0e12;color:#aab3bf;border:1px solid var(--line)}
details.res.rerr summary{color:#e0908a}
/* edits digest */
.editlist{display:flex;flex-direction:column;gap:12px}
.editcard{background:#0b0e12;border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.edithead{display:flex;align-items:center;gap:8px;margin-bottom:4px}
.editexpl{font-size:12px;color:#c8d0da;margin:4px 0 6px;padding:4px 8px;background:#101720;border-radius:6px}
/* verdict */
.checks{list-style:none;padding:0;margin:6px 0 12px;display:flex;flex-direction:column;gap:4px}
.checks li{padding:4px 10px;border-radius:6px;font-size:13px}
.checks li.ok{background:#0c2a18;color:#9fe0bb}.checks li.no{background:#301414;color:#f0a0a0}
.vlist{display:flex;flex-direction:column;gap:8px}
.vitem{background:#0b0e12;border:1px solid var(--line);border-left-width:4px;border-radius:8px;padding:8px 12px}
.vitem.ok{border-left-color:#2a8f52}.vitem.no{border-left-color:#c0392b}
.vhead{font-weight:600;display:flex;align-items:center;gap:8px}.vnote{color:#c4ccd6;margin-top:3px}
/* progression + renders */
.proground{margin:0 0 18px}.proglabel{font-weight:600;margin-bottom:8px;color:#cdd6e0}
.progrow{display:flex;gap:10px;overflow-x:auto;padding-bottom:6px}
.prog{flex:none;width:300px}.progf{font-size:11px;color:var(--muted);margin-bottom:3px}
.progimg{width:100%;border:1px solid var(--line);border-radius:6px;display:block}
.rendgrid{display:flex;flex-direction:column;gap:16px}
.rend{background:#0b0e12;border:1px solid var(--line);border-radius:8px;padding:8px}
.rendtitle{margin-bottom:6px;font-weight:600}
.imgmiss{color:#a55;font-size:12px;padding:20px;text-align:center}
code{font-family:ui-monospace,Menlo,monospace}
.stageblock{border-top:2px solid var(--line);margin-top:28px;padding-top:6px}
.stagehead{background:linear-gradient(180deg,#1a2029,#141920);border:1px solid var(--line);
border-radius:12px;padding:16px 20px;margin:14px 0}.stagehead h1{font-size:20px}
.overview{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0 8px}
.ovcard{flex:1;min-width:150px;text-decoration:none;color:var(--ink);background:var(--panel);
border:1px solid var(--line);border-left:4px solid var(--muted);border-radius:10px;padding:12px 14px}
.ovcard.ok{border-left-color:#16a34a}.ovcard.no{border-left-color:#c0392b}
.ovstage{font-size:12px;color:var(--muted)}.ovname{font-weight:700;font-size:15px;margin:2px 0}
.ovscore{font-size:13px;font-weight:700}.ovcard.ok .ovscore{color:#3fd07a}.ovcard.no .ovscore{color:#e77}
"""

_TOC = (
    '<nav class="toc">'
    '<a href="#plan">1 · Plan</a><a href="#refs">2 · References</a>'
    '<a href="#prompt">3 · Prompt</a><a href="#run">4 · Run</a>'
    '<a href="#edits">5 · Edits</a><a href="#verdict">6 · Verdict</a>'
    '<a href="#progression">7 · Progression</a><a href="#finalviews">8 · Final views</a></nav>'
)


def _load_iter(iter_dir: Path) -> dict:
    track = iter_dir / ".harness_tracking"

    def _j(name):
        f = track / name
        return json.loads(f.read_text()) if f.is_file() else {}

    prompt_md = (track / "prompt.md").read_text() if (track / "prompt.md").is_file() else ""
    rows = (
        [json.loads(l) for l in (track / "trajectory.jsonl").read_text().splitlines() if l.strip()]
        if (track / "trajectory.jsonl").is_file()
        else []
    )
    verify = _j("verify.json")
    plan = _j("plan.json") or (verify.get("plan") if isinstance(verify.get("plan"), dict) else {})
    return {
        "prompt_md": prompt_md,
        "rows": rows,
        "verify": verify,
        "plan": plan or {},
        "plan_verify": verify.get("plan_verify") or {},
        "agent": verify.get("agent") or {},
        "pairs": verify.get("pairs") or [],
        "out_of_scope": verify.get("out_of_scope_edits") or [],
        "layout": verify.get("layout") or {},
    }


def _kpis_html(d: dict, gate_pass: bool) -> str:
    pv = d["plan_verify"]
    ag = d["agent"]
    items = pv.get("items") or d["plan"].get("items") or []
    done_n = sum(1 for v in (pv.get("items") or []) if v.get("done"))
    # total output tokens from the trajectory usage rows
    out_tok = sum((r.get("usage") or {}).get("output_tokens", 0)
                  for r in d["rows"] if r.get("kind") == "usage")
    kpis = [
        ("plan items", len(items)),
        ("done", f"{done_n}/{len(items)}"),
        ("rounds", ag.get("rounds")),
        ("agent turns", ag.get("turns")),
        ("output tokens", f"{out_tok:,}" if out_tok else None),
        ("agent $", ag.get("cost_usd")),
        ("duration", _fmt_t(ag.get("duration_s"))),
    ]
    return "".join(
        f'<div class="kpi"><div class="muted">{_esc(k)}</div><b>{_esc(v)}</b></div>'
        for k, v in kpis if v is not None
    )


def _gate_pass(d: dict) -> bool:
    return bool(
        not d["out_of_scope"]
        and not (d["layout"].get("violations"))
        and d["plan_verify"].get("all_done")
    )


def _stage_sections(d: dict, surface_ref: Path, manifest: dict) -> str:
    targets = _plan_targets(d["plan"])
    from litereality_agent import REPO_ROOT as root
    gate_pass = _gate_pass(d)
    return (
        f"{_section_plan(d['plan'], d['plan_verify'])}"
        f"{_section_refs(manifest, surface_ref)}"
        f"{_section_prompt(d['prompt_md'])}"
        f"{_section_trajectory(d['rows'], root, targets)}"
        f"{_section_edits(d['rows'], d['plan'])}"
        f"{_section_verdict(d['plan_verify'], gate_pass, d['out_of_scope'], d['layout'])}"
    )


# --------------------------------------------------------------------------- #
def build_html(
    scan: str,
    stage: int,
    iter_dir: Path,
    surface_ref: Path,
    manifest: dict,
    critic_instructions: str = "",  # kept for caller compat; unused (critic retired)
) -> str:
    d = _load_iter(iter_dir)
    gate_pass = _gate_pass(d)
    badge = (
        f'<span class="badge {"ok" if gate_pass else "no"}">gate '
        f"{'PASSED' if gate_pass else 'FAILED'}</span>"
    )
    name, scope = STAGE_META.get(stage, (f"stage{stage}", ""))
    body = (
        f'<div class="wrap">'
        f"<h1>Harness run · {_esc(scan)} · stage {stage} — {_esc(name)} "
        f'<span class="muted" style="font-size:13px">({_esc(iter_dir.name)})</span></h1>'
        f'<p class="muted">{_esc(scope)} — the plan-first agentic loop: diagnose → plan → edit '
        f"→ verify. Below: the plan, the evidence, the exact prompt, the agent\'s every "
        f"read/think/edit, each code change, and the per-item verdict that IS the gate.</p>"
        f'<div class="hdr">{badge}{_kpis_html(d, gate_pass)}</div>'
        f"{_TOC}"
        f"{_stage_sections(d, surface_ref, manifest)}"
        f"{_section_progression(iter_dir)}"
        f"{_section_renders(d['pairs'])}"
        f"</div>"
    )
    return (
        f'<!doctype html><html><head><meta charset="utf-8">'
        f"<title>harness · {_esc(scan)} · stage {stage}</title>"
        f"<style>{_CSS}</style></head><body>{body}</body></html>"
    )


# --------------------------------------------------------------------------- #
STAGE_META = {
    1: ("materials", "walls / floor / ceiling PBR materials"),
    2: ("wall_objects", "sockets · skirting · trunking · boards · fixtures"),
    3: ("objects", "furniture + procedural doors/windows (deferred)"),
}


def _stage_block(scan, stage, iter_dir, surface_ref, manifest) -> str:
    d = _load_iter(iter_dir)
    gate_pass = _gate_pass(d)
    name, scope = STAGE_META.get(stage, (f"stage{stage}", ""))
    badge = (
        f'<span class="badge {"ok" if gate_pass else "no"}">gate '
        f"{'PASSED' if gate_pass else 'FAILED'}</span>"
    )
    summ = _esc((d["plan"] or {}).get("summary") or "")
    return (
        f'<div class="stageblock" id="stage{stage}">'
        f'<div class="stagehead"><h1>Stage {stage} · {_esc(name)} '
        f'<span class="muted" style="font-size:13px;font-weight:400">— {_esc(scope)} '
        f"· {_esc(iter_dir.name)}</span></h1>"
        f'<div class="hdr">{badge}{_kpis_html(d, gate_pass)}</div>'
        f'{("<p class=summary>" + summ + "</p>") if summ else ""}</div>'
        f"{_stage_sections(d, surface_ref, manifest)}"
        f"{_section_progression(iter_dir)}"
        f"{_section_renders(d['pairs'])}"
        f"</div>"
    )


def build_run_html(scan: str, config, critic_prompt_fn=None) -> str:
    """One page covering every stage that ran, with an overview strip + sticky nav."""
    stages = []
    for st in (1, 2, 3):
        it = _latest_iter(config.SCENE_STAGE / f"stage_{st}")
        if it:
            stages.append((st, it))
    manifest = (
        json.loads(config.SURFACE_REF_MANIFEST.read_text())
        if config.SURFACE_REF_MANIFEST.is_file()
        else {}
    )
    cards, navs, blocks = [], [], []
    for st, it in stages:
        d = _load_iter(it)
        gate_pass = _gate_pass(d)
        pv = d["plan_verify"]
        done_n = sum(1 for v in (pv.get("items") or []) if v.get("done"))
        n = len(pv.get("items") or d["plan"].get("items") or [])
        name = STAGE_META.get(st, (f"stage{st}",))[0]
        cards.append(
            f'<a class="ovcard {"ok" if gate_pass else "no"}" href="#stage{st}">'
            f'<div class="ovstage">Stage {st}</div><div class="ovname">{_esc(name)}</div>'
            f'<div class="ovscore">{"PASS" if gate_pass else "FAIL"} · {done_n}/{n} done</div></a>'
        )
        navs.append(f'<a href="#stage{st}">Stage {st} · {_esc(name)}</a>')
        blocks.append(_stage_block(scan, st, it, config.SURFACE_REF, manifest))
    body = (
        f'<div class="wrap">'
        f"<h1 style='font-size:26px'>Harness run · {_esc(scan)}</h1>"
        f'<p class="muted">How the reconstruction was refined, stage by stage — the plan each '
        f"stage wrote, the references it looked at, the exact prompt, the agent\'s every "
        f"read/think/edit, each code change, and the per-item verdict.</p>"
        f'<div class="overview">{"".join(cards)}</div>'
        f'<nav class="toc">{"".join(navs)}</nav>'
        f'{"".join(blocks)}'
        f"</div>"
    )
    return (
        f'<!doctype html><html><head><meta charset="utf-8">'
        f"<title>harness run · {_esc(scan)}</title>"
        f"<style>{_CSS}</style></head><body>{body}</body></html>"
    )


def _latest_iter(stage_dir: Path) -> Path | None:
    its = sorted(
        (p for p in stage_dir.glob("iteration_*")
         if (p / ".harness_tracking" / "verify.json").is_file()),
        key=lambda p: int(p.name.split("_")[1]),
    )
    return its[-1] if its else None


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scan", required=True)
    ap.add_argument("--stage", type=int, default=1)
    ap.add_argument("--iteration", type=int, default=0, help="0 = latest")
    ap.add_argument("--run", action="store_true", help="ONE combined report across all stages")
    ap.add_argument("--out", help="output html path")
    a = ap.parse_args()

    os.environ["LITEREALITY_SCAN"] = Path(str(a.scan).rstrip("/")).name
    from . import config

    if a.run:
        html_str = build_run_html(config.SCAN, config)
        out = Path(a.out) if a.out else (config.SCENE_STAGE / "run_report.html")
        out.write_text(html_str, encoding="utf-8")
        print(f"run report -> {out}  ({len(html_str.encode())/1e6:.1f} MB, self-contained)")
        return 0

    stage_dir = config.SCENE_STAGE / f"stage_{a.stage}"
    iter_dir = (stage_dir / f"iteration_{a.iteration}") if a.iteration else _latest_iter(stage_dir)
    if not iter_dir or not iter_dir.is_dir():
        raise SystemExit(f"no iteration with a verify.json under {stage_dir}")
    manifest = (
        json.loads(config.SURFACE_REF_MANIFEST.read_text())
        if config.SURFACE_REF_MANIFEST.is_file()
        else {}
    )
    html_str = build_html(config.SCAN, a.stage, iter_dir, config.SURFACE_REF, manifest)
    out = Path(a.out) if a.out else (iter_dir / "report.html")
    out.write_text(html_str, encoding="utf-8")
    print(f"report -> {out}  ({len(html_str.encode())/1e6:.1f} MB, self-contained)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
