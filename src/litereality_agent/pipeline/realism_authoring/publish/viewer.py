"""Export a reconstructed room to a SINGLE self-contained Three.js HTML file.

The GLB is Draco+JPEG compressed then embedded as a base64 data URI, so the result is compact and
opens by double-click — no server, no sidecar files. Three.js loads from a CDN (needs internet the
first time).

The page ships four panels, all built by default from artifacts the pipeline already produces:

  · orbit + an "articulate" slider that scrubs the baked door/window/drawer swing clips
  · OBJECTS  — every top-level node in the room: hide one, or click to isolate it. Derived from
               the GLB's own node names, so it needs no sidecar metadata.
  · QC       — the deterministic geometry violations from `authoring.qc_room` (no model involved):
               objects below the floor, floating, outside the room, fixtures over an opening.
  · COMPARE  — real-vs-render pairs at the capture's own ARKit poses, embedded as JPEG.
  · TRACE    — the run's own event log (run/<scan>/scene_init/obj_stage/traces/trace.jsonl) as a readable timeline
               with per-stage durations.

    python -m litereality_agent.pipeline.realism_authoring.publish.viewer <Room.glb> <out.html> ["Room label"] \
           [--room=DIR] [--scan=NAME] [--compare=DIR]
"""

from __future__ import annotations

import base64
import html as _html
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_COMPRESS_SCRIPT = r"""
import bpy, sys
inp, outp = sys.argv[-2], sys.argv[-1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=inp)
kw = dict(filepath=outp, export_format='GLB', export_draco_mesh_compression_enable=True,
          export_draco_mesh_compression_level=6, export_image_format='JPEG',
          export_extras=True, export_animations=True)
try: bpy.ops.export_scene.gltf(export_jpeg_quality=75, **kw)
except TypeError: bpy.ops.export_scene.gltf(**kw)
"""


def _compress_glb(glb: Path) -> Path:
    """Draco-compress geometry + JPEG textures via Blender (keeping extras + animation clips), so
    the embedded viewer stays compact. Returns the original if Blender is unavailable / no smaller."""
    blender = os.environ.get("LITEREALITY_BLENDER", "")
    binp = Path(blender) / "blender" if blender else None
    if not (binp and binp.exists()):
        return glb
    out = Path(tempfile.mkdtemp()) / (glb.stem + "_c.glb")
    scr = out.parent / "_c.py"
    scr.write_text(_COMPRESS_SCRIPT)
    try:
        subprocess.run([str(binp), "-b", "--factory-startup", "--python", str(scr), "--",
                        str(glb), str(out)], capture_output=True, timeout=600)
    except Exception:  # noqa: BLE001
        return glb
    return out if out.is_file() and out.stat().st_size < glb.stat().st_size else glb


def collect_qc(room_dir: Path | None) -> dict:
    """Deterministic geometry QC for the room (no model). Returns {} when it can't run, so a
    missing layout degrades the panel rather than failing the export."""
    if not room_dir:
        return {}
    out: dict = {}
    try:
        from litereality_agent.pipeline.qc.checks import qc

        r = qc(str(room_dir))
        out = {
            "n_furniture": r.get("n_furniture", 0),
            "violations": [
                {"object": o, "check": c, "detail": d} for o, c, d in r.get("violations", [])
            ],
        }
    except Exception as e:  # noqa: BLE001
        out = {"error": f"{type(e).__name__}: {e}"}

    # Fold in the MESH collision map when one sits beside the room. Without this the panel reports
    # only the box-based positional checks and shows a clean tick on a room with known
    # interpenetration — a viewer that certifies a scene it never actually checked.
    try:
        maps = sorted(Path(room_dir).glob("collision_map*after*.json")) \
            or sorted(Path(room_dir).glob("collision_map*.json"))
        if maps:
            m = json.loads(maps[-1].read_text())
            out.setdefault("violations", [])
            out["n_mesh_checked"] = len(m.get("objects", []))
            for c in m.get("clashes", []):
                f = c.get("fix") or {}
                d = (f"{f['dist'] * 1000:.0f} mm — needs "
                     f"({f['dir'][0]:+.2f},{f['dir'][1]:+.2f})") if f else "no escape found"
                out["violations"].append({"object": f"{c['a']} × {c['b']}",
                                          "check": "mesh_clash", "detail": d})
            out.pop("error", None)
    except Exception:  # noqa: BLE001
        pass
    return out


def collect_trace(scan: str | None) -> list[dict]:
    """The run's event log as a list of dicts, oldest first. Looks in the same places the
    tracer writes to. Returns [] if the scan never traced."""
    if not scan:
        return []
    roots = []
    fin = os.environ.get("LITEREALITY_FINAL")
    out = os.environ.get("LITEREALITY_OUTPUT")
    from litereality_agent import REPO_ROOT as repo  # run/ lives here
    for base in (fin, out, repo / "run"):
        if not base:
            continue
        b = Path(base)
        for tdir in (b / scan / "scene_init" / "obj_stage" / "traces", b / scan / "traces"):
            roots.append(tdir / "trace.jsonl")
            # one file per authoring pass (author / materials / qc) — glob so a new pass is
            # picked up without touching this list, and so no pass can hide another.
            try:
                roots += sorted(tdir.glob("authoring_trace*.jsonl"))
            except Exception:  # noqa: BLE001, PERF203
                pass
    seen: set = set()
    out: list[dict] = []
    for p in roots:
        try:
            if not p.is_file() or p.resolve() in seen:
                continue
            seen.add(p.resolve())
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except Exception:  # noqa: BLE001, PERF203
                        pass
        except Exception:  # noqa: BLE001, PERF203
            continue
    # init events and the authoring loop are separate files; interleave by wall-clock so the
    # timeline reads as one run.
    out.sort(key=lambda e: e.get("t") or 0)
    return out


def collect_pairs(compare_dir: Path | None, max_pairs: int = 12) -> list[tuple[str, str]]:
    """Real-vs-render comparison pairs as (frame_label, jpeg data URI).

    The PNGs render_vs_capture writes are ~1.4 MB each; re-encoded to JPEG the whole set is well
    under a megabyte, which keeps the page self-contained without bloating it.
    """
    if not compare_dir:
        return []
    d = Path(compare_dir)
    src = d / "pairs" if (d / "pairs").is_dir() else d
    files = sorted(src.glob("pair_*.png")) + sorted(src.glob("pair_*.jpg"))
    if not files:
        return []
    out = []
    try:
        import io

        from PIL import Image
    except Exception:  # noqa: BLE001  (Pillow missing -> just skip the panel)
        return []
    for f in files[:max_pairs]:
        try:
            im = Image.open(f).convert("RGB")
            im.thumbnail((1400, 1400))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=78)
            uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
            out.append((f.stem.replace("pair_", "frame "), uri))
        except Exception:  # noqa: BLE001, PERF203
            continue
    return out


_TEMPLATE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
  html,body{margin:0;height:100%;background:#1a1c1f;color:#e8e8ea;font:14px/1.4 system-ui,sans-serif;overflow:hidden}
  /* canvas is a REPLACED element: `inset:0` alone leaves width:auto resolving to the
     intrinsic (attribute) size, i.e. window x devicePixelRatio. Pin it explicitly. */
  #c{position:fixed;inset:0;display:block;width:100%;height:100%}
  #hud{position:fixed;left:14px;top:12px;z-index:2;pointer-events:none}
  #hud b{font-size:15px;font-weight:600} #hud small{opacity:.6}
  #bar{position:fixed;left:14px;bottom:12px;z-index:2;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
  #bar button{pointer-events:auto;background:#2a2d31;color:#e8e8ea;border:1px solid #3a3d42;border-radius:7px;padding:6px 11px;cursor:pointer;font:13px system-ui}
  #bar button:hover{background:#34383d}
  #art{pointer-events:auto;display:none;align-items:center;gap:8px;background:#2a2d31;border:1px solid #3a3d42;border-radius:7px;padding:5px 11px}
  #art input{width:130px} #art label{opacity:.8}
  #load{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;z-index:3;opacity:.7}

  /* ---- objects panel: hide / isolate individual objects ---- */
  #objs{position:fixed;right:12px;top:12px;z-index:6;width:224px;max-height:76%;display:none;
        flex-direction:column;background:rgba(28,30,34,.95);border:1px solid #3a3d42;border-radius:10px;
        backdrop-filter:blur(6px);overflow:hidden}
  #objs.on{display:flex}
  #objs .ph{display:flex;align-items:center;gap:6px;padding:8px 10px;border-bottom:1px solid #3a3d42;cursor:pointer;user-select:none}
  #objs .ph b{font-size:12px} #objs .ph .cnt{color:#9aa0a8;font-size:11px}
  #objs .ph .car{margin-left:auto;color:#9aa0a8;font-size:10px;transition:transform .15s}
  #objs.min .car{transform:rotate(-90deg)} #objs.min .body,#objs.min .act{display:none}
  #objs .act{display:flex;gap:6px;padding:6px 9px;border-bottom:1px solid #3a3d42}
  #objs .act button{flex:1;background:none;border:1px solid #3a3d42;border-radius:6px;color:#9aa0a8;
                    font:11px system-ui;padding:4px 0;cursor:pointer}
  #objs .act button:hover{color:#5ab0ff;border-color:#5ab0ff}
  #objs .body{overflow:auto;padding:4px;display:flex;flex-direction:column;gap:1px}
  #objs .sec{font-size:10px;color:#9aa0a8;text-transform:uppercase;letter-spacing:.5px;padding:6px 6px 2px}
  #objs .row{display:flex;align-items:center;gap:7px;padding:5px 6px;border-radius:5px;cursor:pointer}
  #objs .row:hover{background:rgba(255,255,255,.06)}
  #objs .row.off{opacity:.4} #objs .row.iso{background:rgba(90,176,255,.18);outline:1px solid rgba(90,176,255,.4)}
  #objs .row .sw{width:9px;height:9px;border-radius:3px;flex:0 0 auto}
  #objs .row .nm{flex:1;min-width:0;overflow-wrap:anywhere;font-size:12px}
  #objs .row .pc{color:#9aa0a8;font-size:10px} #objs .row .eye{color:#9aa0a8;font-size:11px;padding:0 2px}

  /* ---- info drawer: QC + trace ---- */
  #drawer{position:fixed;left:0;right:0;bottom:0;z-index:7;max-height:58%;display:none;
          flex-direction:column;background:rgba(24,26,29,.97);border-top:1px solid #3a3d42;backdrop-filter:blur(8px)}
  #drawer.on{display:flex}
  #drawer .tabs{display:flex;gap:4px;padding:8px 12px 0;border-bottom:1px solid #3a3d42}
  #drawer .tabs button{background:none;border:0;border-bottom:2px solid transparent;color:#9aa0a8;
                       font:13px system-ui;padding:7px 12px;cursor:pointer}
  #drawer .tabs button.sel{color:#e8e8ea;border-bottom-color:#5ab0ff}
  #drawer .tabs .x{margin-left:auto;color:#9aa0a8;cursor:pointer;padding:7px 10px}
  #drawer .pane{overflow:auto;padding:10px 14px 16px;display:none} #drawer .pane.sel{display:block}
  .qcok{color:#5fd39a} .qcbad{color:#ff8f6b}
  table.qc{border-collapse:collapse;width:100%;font-size:12.5px}
  table.qc th,table.qc td{text-align:left;padding:5px 10px 5px 0;border-bottom:1px solid #2a2d31;vertical-align:top}
  table.qc th{color:#9aa0a8;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.4px}
  .tl{display:flex;flex-direction:column;gap:0;font-size:12.5px}
  .tl .ev{display:grid;grid-template-columns:74px 150px 1fr;gap:10px;padding:4px 0;border-bottom:1px solid #232629}
  .tl .ev .tt{color:#9aa0a8;font-variant-numeric:tabular-nums}
  .tl .ev .kd{font-weight:600} .tl .ev .dl{color:#c8ccd2;overflow-wrap:anywhere}
  .tl .ev.err .kd{color:#ff8f6b} .tl .ev.ok .kd{color:#5fd39a}\n  .tl .ev.edit .kd{color:#e0a866} .tl .ev.img .kd{color:#5ab0ff}\n  .tl .ev.think{opacity:.72} .tl .ev.think .dl{font-style:italic}
  .muted{color:#9aa0a8}
  #cmpWrap{display:flex;flex-direction:column;gap:8px;align-items:flex-start}
  #cmpImg{max-width:100%;border-radius:6px;border:1px solid #2a2d31}
  #cmpNav{display:flex;gap:8px;align-items:center}
  #cmpNav button{background:#2a2d31;color:#e8e8ea;border:1px solid #3a3d42;border-radius:6px;
                 padding:4px 10px;cursor:pointer;font:12px system-ui}
  #cmpNav button:hover{background:#34383d}
</style></head>
<body>
<canvas id="c"></canvas>
<div id="hud"><b>__LABEL__</b><br><small>drag to orbit · scroll to zoom · right-drag to pan · <b>walk</b>: WASD, shift to run, esc to exit</small></div>
<div id="bar">
  <button id="reset">reset view</button>
  <button id="walk">walk (WASD)</button>
  <button id="bg">background</button>
  <button id="tObjs">objects</button>
  <button id="tQc">QC __QCBADGE__</button>
  <button id="tCompare">real vs render</button>
  <button id="tTrace">trace</button>
  <span id="art"><label>articulate</label><input id="open" type="range" min="0" max="100" value="100"><span id="pct">doors open</span></span>
</div>

<div id="objs">
  <div class="ph" id="oHead"><b>objects</b><span class="cnt" id="oCnt"></span><span class="car">▾</span></div>
  <div class="act"><button id="oAll">show all</button><button id="oShell">shell only</button></div>
  <div class="body" id="oBody"></div>
</div>

<div id="drawer">
  <div class="tabs">
    <button data-p="qc" class="sel">QC</button><button data-p="compare">real vs render</button><button data-p="trace">trace</button>
    <span class="x" id="dClose">✕</span>
  </div>
  <div class="pane sel" id="pQc">__QC_HTML__</div>
  <div class="pane" id="pCompare">__PAIRS_HTML__</div>
  <div class="pane" id="pTrace">__TRACE_HTML__</div>
</div>
<div id="load">loading…</div>
<script type="importmap">{ "imports": {
  "three": "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",
  "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"
}}</script>
<script type="module">
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { PointerLockControls } from 'three/addons/controls/PointerLockControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const GLB = "__GLB__";
const canvas = document.getElementById('c');
const renderer = new THREE.WebGLRenderer({canvas, antialias:true, preserveDrawingBuffer:true});
renderer.setPixelRatio(Math.min(devicePixelRatio,2));
renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.0;
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
const BGS = [0x1a1c1f, 0xffffff, 0x808080]; let bgi = 0;
scene.background = new THREE.Color(BGS[0]);
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

const camera = new THREE.PerspectiveCamera(50, innerWidth/innerHeight, 0.01, 1000);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true; controls.dampingFactor = 0.08;

function resize(){ renderer.setSize(innerWidth,innerHeight,true); camera.aspect=innerWidth/innerHeight; camera.updateProjectionMatrix(); }
addEventListener('resize', resize); resize();

const CENTER = new THREE.Vector3(); let HOME = new THREE.Vector3();
const ROOM = {box:null, floorY:0};
function frame(obj){
  const box = new THREE.Box3().setFromObject(obj);
  const s = box.getSize(new THREE.Vector3()); box.getCenter(CENTER);
  if(obj !== scene){
    /* Walk bounds come from the SHELL, not the whole scene: the export also carries helpers like
       `daylight_card` that sit outside the walls, which would inflate the box until the clamp
       stopped containing anything, and could drag the floor plane below the actual floor. */
    const shell = new THREE.Box3(); let got = false; let fy = null;
    obj.traverse(o=>{
      if(!o.isMesh) return;
      const n = o.name || '';
      if(/^(wall|floor|ceiling)/i.test(n)){ shell.expandByObject(o); got = true; }
      if(/^floor/i.test(n)){ const t = new THREE.Box3().setFromObject(o).max.y;
                             fy = (fy === null) ? t : Math.min(fy, t); }
    });
    ROOM.box = got ? shell : box.clone();
    ROOM.floorY = (fy === null) ? ROOM.box.min.y : fy;   // stand ON the floor mesh when there is one
  }
  const r = Math.max(s.x,s.y,s.z)*0.5;
  const d = r / Math.sin(THREE.MathUtils.degToRad(camera.fov*0.5));
  HOME.set(CENTER.x + d*0.8, CENTER.y + d*0.55, CENTER.z + d*0.8);
  camera.position.copy(HOME); controls.target.copy(CENTER);
  camera.near = Math.max(d/500, 0.01); camera.far = d*20; camera.updateProjectionMatrix();
  controls.update();
}

let mixer = null, actions = [];
const draco = new DRACOLoader();
draco.setDecoderPath('https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/libs/draco/');
const loader = new GLTFLoader(); loader.setDRACOLoader(draco);
loader.parse(_b64ToArrayBuffer(GLB.split(',')[1]), '', (gltf)=>{
  scene.add(gltf.scene);
  frame(gltf.scene);
  buildObjects(gltf.scene);
  const clips = gltf.animations || [];
  if(clips.length){
    mixer = new THREE.AnimationMixer(gltf.scene);
    actions = clips.map(c=>{ const a=mixer.clipAction(c); a.play(); a.paused=true; return a; });
    document.getElementById('art').style.display = 'inline-flex';
    /* DOORS land open — a closed leaf hides the articulation that was reconstructed, and in walk
       mode it walls you out of the doorway you are standing in. Only doors: opening every clip
       would also pull each drawer out (Drawer_*_slide) and swing the window sashes, which is
       clutter, not information. The slider still scrubs everything together. */
    for(const a of actions){
      const c = a.getClip();
      if(/door/i.test(c.name)) a.time = c.duration;
    }
    mixer.update(0);
  }
  document.getElementById('load').remove();
}, (e)=>{ document.getElementById('load').textContent = 'load error: '+e; });

function setOpen(frac){
  for(const a of actions){ a.time = frac * a.getClip().duration; }
  if(mixer) mixer.update(0);
  document.getElementById('pct').textContent = frac<=0.02 ? 'closed' : (frac>=0.98 ? 'open' : Math.round(frac*100)+'%');
}
document.getElementById('open').oninput = (e)=> setOpen(e.target.value/100);
document.getElementById('reset').onclick = ()=> { setWalk(false); frame(scene); };
document.getElementById('bg').onclick = ()=>{ bgi=(bgi+1)%BGS.length; scene.background.setHex(BGS[bgi]); };

/* ---------- walk mode: WASD at standing height ----------
   The camera is PINNED to the floor plane every frame, so W/S move you across the room rather
   than flying you through the ceiling — the point is to see the room from where a person's eyes
   actually are, which is the only viewpoint the reconstruction was ever judged against. */
const EYE = 1.6, SPEED = 2.4, RUN = 2.4;      // metres, m/s, sprint multiplier
const walk = new PointerLockControls(camera, renderer.domElement);
const keys = Object.create(null);
let walking = false;
addEventListener('keydown', e=>{ if(e.target.tagName!=='INPUT') keys[e.code]=true; });
addEventListener('keyup',   e=>{ keys[e.code]=false; });

function setWalk(on){
  if(on === walking) return;
  walking = on;
  controls.enabled = !on;
  document.getElementById('walk').textContent = on ? 'exit walk (esc)' : 'walk (WASD)';
  if(on){
    // Enter where you already are if that is inside the room; otherwise start at the centre,
    // since the default framing sits well outside the walls looking in.
    const b = ROOM.box;
    const inside = b && camera.position.x > b.min.x && camera.position.x < b.max.x
                     && camera.position.z > b.min.z && camera.position.z < b.max.z;
    if(!inside) camera.position.set(CENTER.x, 0, CENTER.z);
    camera.position.y = ROOM.floorY + EYE;
    walk.lock();
  } else {
    walk.unlock();
    controls.target.set(CENTER.x, camera.position.y, CENTER.z);
    controls.update();
  }
}
walk.addEventListener('unlock', ()=> setWalk(false));   // esc, or focus loss
document.getElementById('walk').onclick = ()=> setWalk(!walking);

const _fwd = new THREE.Vector3(), _right = new THREE.Vector3();
function stepWalk(dt){
  const f = (keys['KeyW']?1:0) - (keys['KeyS']?1:0);
  const s = (keys['KeyD']?1:0) - (keys['KeyA']?1:0);
  if(f || s){
    const v = SPEED * ((keys['ShiftLeft']||keys['ShiftRight']) ? RUN : 1) * dt;
    camera.getWorldDirection(_fwd); _fwd.y = 0; _fwd.normalize();   // horizontal heading only
    _right.crossVectors(_fwd, camera.up).normalize();
    camera.position.addScaledVector(_fwd, f*v).addScaledVector(_right, s*v);
  }
  camera.position.y = ROOM.floorY + EYE;                 // pinned every frame — never drifts up
  if(ROOM.box){                                          // stay inside the shell
    const m = 0.30;
    camera.position.x = Math.min(Math.max(camera.position.x, ROOM.box.min.x+m), ROOM.box.max.x-m);
    camera.position.z = Math.min(Math.max(camera.position.z, ROOM.box.min.z+m), ROOM.box.max.z-m);
  }
}

/* ---------- objects: hide one, or click to isolate ---------- */
const CAT={table:0xe0a866,desk:0xe0a866,chair:0x5b8def,television:0x8a7bd8,sofa:0xe07b9a,bed:0xe6c25b,
           storage:0x54c08c,cabinet:0x54c08c,shelf:0x54c08c,sink:0x54c08c,door:0xff7a3c,window:0x27c7e0,
           wall:0x6b7480,floor:0x565e68,ceiling:0x565e68,object:0x9aa7b0};
const SHELL=/^(Wall|Floor|Ceiling|Room|Shell)/i;
function cat(n){const s=n.toLowerCase();
  for(const k of Object.keys(CAT)) if(s.includes(k)) return k;
  return 'object';}
function hex(v){return '#'+v.toString(16).padStart(6,'0');}
function meshCount(o){let n=0;o.traverse(c=>{if(c.isMesh)n++;});return n;}

const OB={rows:[],iso:null};
function buildObjects(root){
  OB.rows=[];OB.iso=null;
  let kids=root.children.slice();
  if(kids.length===1 && kids[0].children.length && /^(scene|rootnode|root|)$/i.test(kids[0].name||''))
    kids=kids[0].children.slice();
  for(const node of kids){
    const nm=node.name||''; const mc=meshCount(node);
    if(!nm||!mc) continue;
    OB.rows.push({node,name:nm,cat:cat(nm),n:mc,shell:SHELL.test(nm)});
  }
  OB.rows.sort((a,b)=>(a.shell-b.shell)||a.name.localeCompare(b.name,undefined,{numeric:true}));
  renderObjects();
  document.getElementById('objs').classList.toggle('on', OB.rows.length>0);
}
function renderObjects(){
  const body=document.getElementById('oBody');
  const main=OB.rows.filter(r=>!r.shell), sh=OB.rows.filter(r=>r.shell);
  document.getElementById('oCnt').textContent=OB.rows.length+' nodes';
  const row=r=>{const i=OB.rows.indexOf(r);
    return `<div class="row" data-i="${i}"><span class="sw" style="background:${hex(CAT[r.cat]||CAT.object)}"></span>`+
           `<span class="nm">${r.name}</span><span class="pc">${r.n}p</span><span class="eye">◉</span></div>`;};
  body.innerHTML = main.map(row).join('') + (sh.length?'<div class="sec">shell</div>'+sh.map(row).join(''):'');
  body.querySelectorAll('.row').forEach(el=>{const i=+el.dataset.i;
    el.querySelector('.eye').onclick=e=>{e.stopPropagation();OB.rows[i].node.visible=!OB.rows[i].node.visible;OB.iso=null;sync();};
    el.onclick=()=>{ OB.iso=(OB.iso===i)?null:i;
      OB.rows.forEach((r,j)=>{r.node.visible = (OB.iso===null)?true:(j===OB.iso);}); sync();};});
  sync();
}
function sync(){
  document.querySelectorAll('#oBody .row').forEach(el=>{const r=OB.rows[+el.dataset.i];
    el.classList.toggle('off', !r.node.visible);
    el.classList.toggle('iso', OB.iso===OB.rows.indexOf(r));
    el.querySelector('.eye').textContent = r.node.visible?'◉':'○';});
}
document.getElementById('oAll').onclick=()=>{OB.iso=null;OB.rows.forEach(r=>r.node.visible=true);sync();};
document.getElementById('oShell').onclick=()=>{OB.iso=null;OB.rows.forEach(r=>r.node.visible=r.shell);sync();};
document.getElementById('oHead').onclick=()=>document.getElementById('objs').classList.toggle('min');
document.getElementById('tObjs').onclick=()=>document.getElementById('objs').classList.toggle('on');

/* ---------- drawer: QC + trace ---------- */
const drawer=document.getElementById('drawer');
function openPane(p){drawer.classList.add('on');
  document.querySelectorAll('#drawer .tabs button').forEach(b=>b.classList.toggle('sel',b.dataset.p===p));
  document.querySelectorAll('#drawer .pane').forEach(el=>el.classList.toggle('sel',el.id==='p'+p[0].toUpperCase()+p.slice(1)));}
document.querySelectorAll('#drawer .tabs button').forEach(b=>b.onclick=()=>openPane(b.dataset.p));
document.getElementById('dClose').onclick=()=>drawer.classList.remove('on');
document.getElementById('tQc').onclick=()=>drawer.classList.contains('on')&&document.querySelector('#drawer .tabs button.sel').dataset.p==='qc'?drawer.classList.remove('on'):openPane('qc');
document.getElementById('tCompare').onclick=()=>drawer.classList.contains('on')&&document.querySelector('#drawer .tabs button.sel').dataset.p==='compare'?drawer.classList.remove('on'):openPane('compare');
document.getElementById('tTrace').onclick=()=>drawer.classList.contains('on')&&document.querySelector('#drawer .tabs button.sel').dataset.p==='trace'?drawer.classList.remove('on'):openPane('trace');

const PAIRS = __PAIRS_JSON__;
let ci = 0;
function showPair(i){
  if(!PAIRS.length) return;
  ci = (i + PAIRS.length) % PAIRS.length;
  document.getElementById('cmpImg').src = PAIRS[ci][1];
  document.getElementById('cmpLbl').textContent = PAIRS[ci][0] + '  (' + (ci+1) + '/' + PAIRS.length + ')';
}
if(PAIRS.length){
  document.getElementById('cmpPrev').onclick=()=>showPair(ci-1);
  document.getElementById('cmpNext').onclick=()=>showPair(ci+1);
  showPair(0);
}

function _b64ToArrayBuffer(b64){ const bin=atob(b64), n=bin.length, u=new Uint8Array(n); for(let i=0;i<n;i++)u[i]=bin.charCodeAt(i); return u.buffer; }
let _prev = performance.now();
(function loop(){
  requestAnimationFrame(loop);
  const now = performance.now(); const dt = Math.min((now-_prev)/1000, 0.1); _prev = now;
  if(walking) stepWalk(dt); else controls.update();
  renderer.render(scene,camera);
})();
</script></body></html>
"""


def _qc_html(qc: dict) -> str:
    if not qc:
        return '<p class="muted">No QC data — pass --room so the room layout can be checked.</p>'
    if qc.get("error"):
        return f'<p class="qcbad">QC could not run: {_html.escape(qc["error"])}</p>'
    v = qc.get("violations", [])
    head = (f'<p><b>{qc.get("n_furniture", 0)}</b> furniture objects checked — '
            + (f'<span class="qcbad"><b>{len(v)}</b> violation{"s" if len(v) != 1 else ""}</span>'
               if v else '<span class="qcok">clean, no geometric violations</span>') + '</p>')
    if not v:
        return head
    rows = "".join(
        f'<tr><td><b>{_html.escape(str(x["object"]))}</b></td>'
        f'<td class="qcbad">{_html.escape(str(x["check"]))}</td>'
        f'<td>{_html.escape(str(x["detail"]))}</td></tr>' for x in v)
    return (head + '<table class="qc"><tr><th>object</th><th>check</th><th>detail</th></tr>'
            + rows + '</table>'
            + '<p class="muted">Deterministic geometry check — no model involved. '
              'Run quality again with <code>uv run litereality stage quality &lt;scene&gt;</code>.</p>')


_OK = {"ok", "done", "complete", "completed"}


def _trace_html(events: list[dict]) -> str:
    if not events:
        return ('<p class="muted">No trace for this scan. Init writes '
                '<code>traces/trace.jsonl</code>; the authoring passes write '
                '<code>traces/authoring_trace.jsonl</code>.</p>')
    icon = {"render": "\U0001f5bc", "read_image": "\U0001f441", "critic": "\u2696",
            "fetch_material": "\U0001f3a8", "Edit": "\u270f", "Write": "\u270f",
            "Read": "\U0001f4c4", "Glob": "\U0001f50e", "Grep": "\U0001f50e", "Bash": "\u2318",
            "select_views": "\U0001f39e", "compile": "\u2699"}
    t0 = events[0].get("t") or 0
    total = (events[-1].get("t") or t0) - t0
    n_tool = sum(1 for e in events if e.get("kind") == "tool")
    n_edit = sum(1 for e in events if e.get("kind") == "tool" and e.get("file"))
    n_img = sum(1 for e in events if e.get("kind") == "tool" and e.get("image"))
    head = (f'<p><b>{len(events)}</b> events over <b>{total/60:.1f} min</b> — '
            f'<b>{n_tool}</b> tool calls, <b>{n_edit}</b> edits, <b>{n_img}</b> image ops</p>')
    out = [head, '<div class="tl">']
    for e in events:
        kind = str(e.get("kind", "?"))
        dt = e.get("dt")
        stamp = f"{float(dt):7.1f}s" if isinstance(dt, (int, float)) else ""
        status = str(e.get("status", "")).lower()
        cls = "ok" if status in _OK else ("err" if status in {"error", "fail", "failed"} else "")
        if kind == "tool":
            tool = str(e.get("tool", "?"))
            label = icon.get(tool, "\u2022") + " " + tool
            bits = []
            if e.get("file"):
                d = e.get("delta_lines")
                bits.append(f'edited {e["file"]}' + (f' ({d:+d} lines)' if isinstance(d, int) and d else ''))
            if e.get("image"):
                bits.append(Path(str(e["image"])).name)
            if e.get("hint"):
                bits.append(str(e["hint"]))
            detail = " · ".join(bits)
            cls = "edit" if e.get("file") else ("img" if e.get("image") else cls)
        elif kind == "images":
            imgs = e.get("images") or []
            label = "\U0001f5bc rendered"
            detail = " · ".join(Path(str(i)).name for i in imgs)
            if e.get("n_images", 0) > len(imgs):
                detail += f"  (+{e['n_images'] - len(imgs)} more)"
            cls = "img"
        elif kind == "think":
            label = "\U0001f4ad think"
            detail = str(e.get("text", ""))
            cls = "think"
        else:
            label = kind + (f" · {e['stage']}" if e.get("stage") else "")
            skip = {"kind", "t", "dt", "scan", "stage", "status", "seq", "pass"}
            detail = " · ".join(f"{k}={e[k]}" for k in e if k not in skip and e[k] not in (None, ""))
            if status:
                detail = status + (" · " if detail else "") + detail
        out.append(f'<div class="ev {cls}"><span class="tt">{stamp}</span>'
                   f'<span class="kd">{_html.escape(label)}</span>'
                   f'<span class="dl">{_html.escape(detail)[:400]}</span></div>')
    out.append("</div>")
    return "".join(out)


def _pairs_html(pairs: list) -> str:
    if not pairs:
        return ('<p class="muted">No comparison pairs. Build them with<br>'
                '<code>uv run python -m litereality_agent.room_format.rendering.room_render.render_vs_capture '
                '--scan &lt;scan dir&gt; --room &lt;room dir&gt; --out &lt;out&gt;/compare --frames 6</code><br>'
                'or run <code>uv run litereality stage publish &lt;scene&gt;</code> — publish builds them by default '
                '(COMPARE_FRAMES=0 to skip).</p>')
    return ('<div id="cmpWrap"><div id="cmpNav"><button id="cmpPrev">◀ prev</button>'
            '<button id="cmpNext">next ▶</button><span class="muted" id="cmpLbl"></span></div>'
            '<img id="cmpImg" alt="real vs render"></div>'
            '<p class="muted">LEFT the reconstruction rendered from the capture\'s own ARKit pose, '
            'RIGHT the real photo at that pose.</p>')


def export_html(glb: str | Path, out: str | Path, label: str | None = None, compress: bool = True,
                room_dir: str | Path | None = None, scan: str | None = None,
                qc: dict | None = None, trace: list[dict] | None = None,
                compare_dir: str | Path | None = None, pairs: list | None = None) -> Path:
    glb, out = Path(glb), Path(out)
    if not glb.is_file():
        raise FileNotFoundError(glb)
    label = label or glb.stem
    qc = collect_qc(Path(room_dir) if room_dir else None) if qc is None else qc
    trace = collect_trace(scan) if trace is None else trace
    pairs = collect_pairs(Path(compare_dir) if compare_dir else None) if pairs is None else pairs
    nviol = len(qc.get("violations", []))
    src = _compress_glb(glb) if compress else glb
    uri = "data:model/gltf-binary;base64," + base64.b64encode(src.read_bytes()).decode()
    html = (_TEMPLATE
            .replace("__QC_HTML__", _qc_html(qc))
            .replace("__TRACE_HTML__", _trace_html(trace))
            .replace("__PAIRS_HTML__", _pairs_html(pairs))
            .replace("__PAIRS_JSON__", json.dumps(pairs))
            # a tick only when a check actually RAN and found nothing — never on a failed/absent one
            .replace("__QCBADGE__", f"({nviol})" if nviol
                     else "✓" if (qc and not qc.get("error")) else "?" if qc else "")
            .replace("__GLB__", uri)
            .replace("__LABEL__", label)
            .replace("__TITLE__", f"{label} — LiteReality"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def main(argv) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    opts = {a.split("=", 1)[0]: a.split("=", 1)[1] for a in argv[1:] if a.startswith("--") and "=" in a}
    if len(args) < 2:
        print(__doc__)
        return 2
    qc = collect_qc(Path(opts["--room"]) if opts.get("--room") else None)
    trace = collect_trace(opts.get("--scan"))
    pairs = collect_pairs(Path(opts["--compare"]) if opts.get("--compare") else None)
    out = export_html(args[0], args[1], args[2] if len(args) > 2 else None,
                      qc=qc, trace=trace, pairs=pairs)
    mb = out.stat().st_size / 1024 / 1024
    nv = len(qc.get("violations", []))
    print(f"viewer → {out}  ({mb:.1f} MB, self-contained)")
    print(f"   panels: objects · QC ({nv} violation(s))"
          + (f" · compare ({len(pairs)} pairs)" if pairs else "")
          + (f" · trace ({len(trace)} events)" if trace else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
