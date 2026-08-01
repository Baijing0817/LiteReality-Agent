"""authoring_replay.py — a full, self-contained HTML replay of an authoring run, rebuilt from the
Claude Code session transcript(s): the agent's reasoning, EVERY code edit as a real +/- diff, and
EVERY image it actually looked at (embedded — even ones that were only ever in /tmp).

The `run_trace` log records that an edit/render happened; the *transcript* holds the actual
old/new text and the image bytes. This joins them into one page.

    python authoring/authoring_replay.py <scene_name_or_room_path> [out.html]

Auto-discovers the run's transcripts under ~/.claude/projects for the scene's `_oneshot/room`
cwd (the new mixed-case `LiteReality-Agent` project dirs), ordered by time.
"""

from __future__ import annotations

import base64
import difflib
import glob
import html
import io
import json
import os
import sys
from pathlib import Path

from litereality_agent import REPO_ROOT

try:
    from PIL import Image
except Exception:  # noqa: BLE001
    Image = None

THUMB_W = 480
PROJECTS = Path(os.path.expanduser("~/.claude/projects"))


def find_transcripts(scene: str) -> list[str]:
    """All transcripts for this scene's _oneshot/room cwd in the NEW (mixed-case) repo, by time."""
    pats = [
        f"*LiteReality-Agent*{scene}*oneshot-room",
        f"*LiteReality-Agent*{scene}*oneshot-room-*",
    ]
    seen, files = set(), []
    for pat in pats:
        for d in glob.glob(str(PROJECTS / pat)):
            for f in glob.glob(d + "/*.jsonl"):
                if os.path.basename(f) not in seen:
                    seen.add(os.path.basename(f))
                    files.append(f)
    files.sort(key=os.path.getmtime)
    return files


def shrink(b64: str, media: str) -> str | None:
    try:
        raw = base64.b64decode(b64)
        if Image is None:
            return f"data:{media};base64,{b64}"
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        if im.width > THUMB_W:
            im = im.resize((THUMB_W, round(im.height * THUMB_W / im.width)))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=82)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001
        return None


def diff_block(old: str, new: str) -> str:
    rows, add, rem = [], 0, 0
    for ln in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=2):
        cls = ""
        if ln.startswith("+") and not ln.startswith("+++"):
            cls, add = "add", add + 1
        elif ln.startswith("-") and not ln.startswith("---"):
            cls, rem = "del", rem + 1
        elif ln.startswith("@@"):
            cls = "hunk"
        elif ln.startswith(("+++", "---")):
            continue
        rows.append(f'<div class="dl {cls}">{html.escape(ln) or "&nbsp;"}</div>')
    return (f'<span class="chip">+{add}</span><span class="chip d">−{rem}</span>'
            f'<div class="diff">{"".join(rows)}</div>')


def _epoch(iso: str) -> float:
    """ISO8601 (…Z) -> epoch seconds, without dateutil."""
    import datetime
    try:
        return datetime.datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=datetime.timezone.utc).timestamp()
    except Exception:  # noqa: BLE001
        return 0.0


def load_reasoning(scene: str) -> list[tuple[float, str]]:
    """The agent's reasoning text lives in run_trace (transcript `thinking` is encrypted). Pull the
    `think` events (epoch `t`) from the scene's authoring/materials run-trace logs."""
    out: list[tuple[float, str]] = []
    for base in (os.environ.get("LITEREALITY_FINAL"),
                 str(REPO_ROOT / "run")):
        if not base:
            continue
        tdir = Path(base) / scene / "scene_init" / "obj_stage" / "traces"
        for name in ("authoring_trace.author.jsonl", "authoring_trace.materials.jsonl"):
            f = tdir / name
            if not f.is_file():
                continue
            for line in f.read_text().splitlines():
                try:
                    r = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if r.get("kind") == "think" and r.get("text"):
                    out.append((float(r.get("t", 0)), r["text"]))
        if out:
            break
    return out


def build_from_transcript(scene: str, out: Path) -> None:
    transcripts = find_transcripts(scene)
    if not transcripts:
        raise SystemExit(f"no transcripts found for {scene} under {PROJECTS}")
    print("using transcripts:")
    for t in transcripts:
        print(f"  {os.path.getsize(t)//1024}KB  {os.path.basename(t)}")

    # (epoch, sort_tiebreak, html) events, merged from transcript + run_trace reasoning, time-sorted
    ev: list[tuple[float, int, str]] = []
    edits: list[str] = []
    gallery: list[str] = []
    n_edit = n_img = n_think = n_tool = 0
    tool_by_id: dict[str, str] = {}

    for ti, t in enumerate(transcripts):
        pass_name = "materials" if ti == len(transcripts) - 1 and len(transcripts) > 1 else "author"
        seq = 0
        for line in open(t):
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            ts = _epoch(r.get("timestamp", "")) or (ti * 1e6 + seq)
            seq += 1
            m = r.get("message", {})
            content = m.get("content")
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                bt = b.get("type")
                if bt == "text":
                    txt = (b.get("text") or "").strip()
                    if txt:
                        ev.append((ts, seq, f'<div class="ev say">🗣 {html.escape(txt[:700])}</div>'))
                elif bt == "tool_use":
                    name = b.get("name", "?").split("__")[-1]
                    tool_by_id[b.get("id", "")] = name
                    inp = b.get("input", {}) or {}
                    if name in ("Edit", "Write"):
                        n_edit += 1
                        f = os.path.basename(str(inp.get("file_path", "?")))
                        d = diff_block(inp.get("old_string", ""),
                                       inp.get("new_string", inp.get("content", "")))
                        card = (f'<div class="edit"><div class="ehead">✏️ edit #{n_edit} · '
                                f'<b>{name}</b> <span class="file">{html.escape(f)}</span> '
                                f'<span class="muted">[{pass_name}]</span></div>{d}</div>')
                        ev.append((ts, seq, f'<div class="ev editrow">{card}</div>'))
                        edits.append(card)
                    else:
                        n_tool += 1
                        hint = next((str(inp[k]) for k in
                                     ("query", "target", "prompt", "command", "file_path", "path")
                                     if inp.get(k)), "")
                        ev.append((ts, seq, f'<div class="ev tool">🔧 <b>{html.escape(name)}</b> '
                                   f'<span class="hint">{html.escape(hint[:130])}</span></div>'))
                elif bt == "tool_result":
                    of = tool_by_id.get(b.get("tool_use_id", ""), "")
                    cc = b.get("content")
                    imgs = []
                    if isinstance(cc, list):
                        for x in cc:
                            if isinstance(x, dict) and x.get("type") == "image":
                                src = x.get("source", {})
                                uri = shrink(src.get("data", ""), src.get("media_type", "image/png"))
                                if uri:
                                    imgs.append(uri)
                    if imgs:
                        n_img += len(imgs)
                        thumbs = "".join(f'<a href="{u}" target="_blank"><img src="{u}"></a>' for u in imgs)
                        ev.append((ts, seq, f'<div class="ev img">🖼 <span class="muted">{html.escape(of)} →</span> {thumbs}</div>'))
                        gallery.extend(imgs)

    # merge the agent's reasoning (from run_trace) into the same timeline by time
    for tt, txt in load_reasoning(scene):
        n_think += 1
        ev.append((tt, -1, f'<div class="ev think">💭 {html.escape(txt[:700])}</div>'))

    ev.sort(key=lambda e: (e[0], e[1]))
    timeline = [e[2] for e in ev]

    _emit(scene, timeline, edits, gallery, n_think, n_edit, n_tool, n_img, out,
          "rebuilt from the session transcript")


def _emit(scene, timeline, edits, gallery, n_think, n_edit, n_tool, n_img, out, src):
    gallery_html = "".join(f'<a href="{u}" target="_blank"><img src="{u}"></a>' for u in gallery)
    edits_html = "".join(edits)
    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(scene)} — authoring replay</title>
<style>
:root{{color-scheme:light dark}}
body{{font:14px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#0e0f12;color:#e7e7e7}}
@media(prefers-color-scheme:light){{body{{background:#fafafa;color:#181818}}}}
header{{padding:16px 22px;border-bottom:1px solid #333;position:sticky;top:0;background:inherit;z-index:5}}
h1{{font-size:17px;margin:0 0 4px}} .muted{{opacity:.6}}
nav button{{font:inherit;background:#1d2027;color:inherit;border:1px solid #333;border-radius:7px;padding:5px 12px;margin:8px 6px 0 0;cursor:pointer}}
nav button.on{{background:#2d6cdf;border-color:#2d6cdf;color:#fff}}
main{{padding:16px 22px;max-width:1120px}} section{{display:none}} section.on{{display:block}}
.ev{{padding:5px 9px;margin:3px 0;border-left:3px solid #333;border-radius:3px}}
.ev.think{{border-color:#8a6;font-style:italic;opacity:.9}}
.ev.say{{border-color:#6ad;opacity:.95}}
.ev.tool{{border-color:#59f;font-family:ui-monospace,monospace;font-size:12.5px}}
.ev.img{{border-color:#c7a}} .ev.pass{{border-color:#2d6cdf;margin-top:12px;font-size:15px}}
.ev.img img{{height:150px;margin:4px 6px 0 0;border-radius:5px;border:1px solid #333;vertical-align:top}}
.file{{color:#e9a;font-family:ui-monospace,monospace}} .hint{{opacity:.65}}
.edit{{border:1px solid #333;border-radius:8px;margin:6px 0;overflow:hidden}}
.ehead{{padding:5px 9px;background:#171a20}}
.chip{{display:inline-block;background:rgba(80,200,120,.2);color:#7d7;border-radius:4px;padding:0 6px;margin:5px 4px;font-family:ui-monospace,monospace;font-size:12px}}
.chip.d{{background:rgba(220,80,80,.2);color:#e88}}
.diff{{font-family:ui-monospace,monospace;font-size:12px;overflow-x:auto}}
.dl{{padding:0 9px;white-space:pre}}
.dl.add{{background:rgba(80,200,120,.14)}} .dl.del{{background:rgba(220,80,80,.14)}} .dl.hunk{{background:#1d2430;color:#8bf}}
.grid a img{{height:175px;border-radius:6px;border:1px solid #333;margin:0 8px 8px 0}}
</style></head><body>
<header>
  <h1>{html.escape(scene)} — authoring replay</h1>
  <div class="muted">{n_think} reasoning · {n_edit} code edits · {n_tool} other tools · {n_img} images — {html.escape(src)}</div>
  <nav>
    <button data-t="tl" class="on">Timeline</button>
    <button data-t="ed">Edits ({n_edit})</button>
    <button data-t="im">Images ({n_img})</button>
  </nav>
</header>
<main>
  <section id="tl" class="on">{''.join(timeline)}</section>
  <section id="ed">{edits_html or '<p class="muted">no edits</p>'}</section>
  <section id="im"><div class="grid">{gallery_html or '<p class="muted">no images</p>'}</div></section>
</main>
<script>
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{{
 document.querySelectorAll('nav button').forEach(x=>x.classList.remove('on'));
 document.querySelectorAll('section').forEach(s=>s.classList.remove('on'));
 b.classList.add('on');document.getElementById(b.dataset.t).classList.add('on');}});
</script></body></html>"""
    out.write_text(doc, encoding="utf-8")
    print(f"wrote {out}  ({out.stat().st_size/1e6:.1f} MB · {n_edit} edits · {n_img} images · {n_think} thoughts)")


def _trace_files(scene: str) -> tuple[Path | None, list[Path]]:
    """(traces_dir, [author, materials, qc jsonl that exist]) for a scene, from the enriched run_trace."""
    for base in (os.environ.get("LITEREALITY_FINAL"),
                 str(REPO_ROOT / "run"),
                 os.environ.get("LITEREALITY_OUTPUT")):
        if not base:
            continue
        td = Path(base) / scene / "scene_init" / "obj_stage" / "traces"
        files = [td / f"authoring_trace.{p}.jsonl" for p in ("author", "materials", "qc")]
        files = [f for f in files if f.is_file()]
        if files:
            return td, files
    return None, []


def _trace_is_enriched(files: list[Path]) -> bool:
    """True once run_trace started storing edit old/new (so we can render real diffs from it alone)."""
    for f in files:
        for line in f.read_text().splitlines():
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if r.get("kind") == "tool" and r.get("old") is not None:
                return True
    return False


def build_from_trace(scene: str, out: Path) -> None:
    """Self-contained replay straight from the enriched run_trace (no transcript needed)."""
    import base64 as _b64
    td, files = _trace_files(scene)
    if not files:
        raise SystemExit(f"no run_trace for {scene}")
    ev: list[tuple[float, int, str]] = []
    edits, gallery = [], []
    n_edit = n_img = n_think = n_tool = 0
    for f in files:
        for line in f.read_text().splitlines():
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            k = r.get("kind")
            t = float(r.get("t", 0))
            seq = int(r.get("seq", 0))
            if k == "think":
                n_think += 1
                ev.append((t, seq, f'<div class="ev think">💭 {html.escape(r.get("text",""))}</div>'))
            elif k == "tool" and r.get("old") is not None:
                n_edit += 1
                d = diff_block(r.get("old", ""), r.get("new", ""))
                card = (f'<div class="edit"><div class="ehead">✏️ edit #{n_edit} · '
                        f'<b>{html.escape(str(r.get("tool","")))}</b> '
                        f'<span class="file">{html.escape(str(r.get("file","")))}</span> '
                        f'<span class="muted">[{html.escape(str(r.get("pass","")))}]</span></div>{d}</div>')
                ev.append((t, seq, f'<div class="ev editrow">{card}</div>'))
                edits.append(card)
            elif k == "tool":
                n_tool += 1
                ev.append((t, seq, f'<div class="ev tool">🔧 <b>{html.escape(str(r.get("tool","")))}</b> '
                           f'<span class="hint">{html.escape(str(r.get("hint",""))[:130])}</span></div>'))
            elif k == "images":
                uris = []
                for rel in (r.get("saved") or []):
                    p = (td / rel) if td else Path(rel)
                    if p.is_file():
                        try:
                            uris.append("data:image/jpeg;base64," + _b64.b64encode(p.read_bytes()).decode())
                        except Exception:  # noqa: BLE001
                            pass
                if uris:
                    n_img += len(uris)
                    thumbs = "".join(f'<a href="{u}" target="_blank"><img src="{u}"></a>' for u in uris)
                    ev.append((t, seq, f'<div class="ev img">🖼 {thumbs}</div>'))
                    gallery.extend(uris)
    ev.sort(key=lambda e: (e[0], e[1]))
    _emit(scene, [e[2] for e in ev], edits, gallery, n_think, n_edit, n_tool, n_img, out,
          "from the enriched run-trace")


def build(scene: str, out: Path) -> None:
    """Prefer the self-contained enriched run_trace; fall back to the session transcript for runs
    made before run_trace captured edit diffs + image copies."""
    _, files = _trace_files(scene)
    if files and _trace_is_enriched(files):
        build_from_trace(scene, out)
    else:
        build_from_transcript(scene, out)


if __name__ == "__main__":
    arg = sys.argv[1]
    scene = Path(arg).name if "/" in arg else arg
    default_out = Path.cwd() / f"{scene}_authoring_replay.html"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else default_out
    build(scene, out)
