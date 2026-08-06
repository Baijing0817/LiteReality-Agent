"""The live page: one HTML string, no build step and no sidecar files.

This is the *streaming* sibling of `room_ops/viewer.py`. That one packs a finished room into a
single self-contained file you can mail to someone; this one stays connected to a run in progress.
The difference that matters is the swap: a finished viewer loads its glb once, while this page
replaces the geometry in place on every rebuild and never touches the camera. Reloading the page
instead would be far less code, but it throws away where the viewer was standing — and watching
an agent work is exactly when you want to keep looking at the wall it is working on.

Three.js comes from the same CDN and version `room_ops/viewer.py` already pins, so a live page and
an exported page render identically and neither adds a dependency to the repo.
"""

from __future__ import annotations

import html
import json

THREE = "0.160.0"

_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__LABEL__ — LiteReality live</title>
<style>
  :root{--bg:#14161a;--panel:#1b1e24;--line:#2c313a;--ink:#e9eaee;--dim:#9aa2ae;--accent:#5ab0ff;
        --ok:#49c26a;--warn:#f0a53c;--bad:#ef6a6a}
  *{box-sizing:border-box}
  html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);
    font:13px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;overflow:hidden}
  #wrap{display:grid;grid-template-columns:1fr 380px;height:100%}
  #stage{position:relative;min-width:0}
  canvas{display:block;width:100%;height:100%}

  #bar{position:absolute;left:14px;top:12px;right:14px;display:flex;gap:10px;align-items:center;
       pointer-events:none;z-index:3}
  #bar .t{font-weight:600;font-size:14px}
  .pill{display:inline-flex;align-items:center;gap:7px;background:rgba(27,30,36,.9);
        border:1px solid var(--line);border-radius:20px;padding:5px 12px;backdrop-filter:blur(6px)}
  .dot{width:7px;height:7px;border-radius:50%;background:var(--ok);flex:0 0 auto}
  .dot.building{background:var(--warn);animation:pulse 1s ease-in-out infinite}
  .dot.failed{background:var(--bad)}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}
  #hint{position:absolute;left:14px;bottom:12px;color:var(--dim);font-size:12px;z-index:3;
        pointer-events:none;text-shadow:0 1px 3px rgba(0,0,0,.6)}

  #side{background:var(--panel);border-left:1px solid var(--line);display:flex;flex-direction:column;
        min-height:0}
  #shead{padding:12px 14px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:8px}
  #shead b{font-size:13px} #shead span{color:var(--dim);font-size:11px;margin-left:auto}
  #feed{flex:1;overflow:auto;padding:6px 0;min-height:0}
  .ev{display:grid;grid-template-columns:52px 1fr;gap:9px;padding:5px 14px;border-left:2px solid transparent}
  .ev:hover{background:rgba(255,255,255,.035)}
  .ev .dt{color:#69707c;font-variant-numeric:tabular-nums;font-size:11px;text-align:right;padding-top:1px}
  .ev .bd{min-width:0}
  .ev .k{display:inline-block;font-size:10px;letter-spacing:.4px;text-transform:uppercase;
         color:var(--dim);margin-right:6px}
  .ev .d{overflow-wrap:anywhere;color:#cfd4dc}
  .ev.tool{border-left-color:var(--accent)} .ev.tool .k{color:var(--accent)}
  .ev.think{border-left-color:#7d7fe0} .ev.think .d{color:#b9bcf0;font-style:italic}
  .ev.err{border-left-color:var(--bad)} .ev.err .d{color:#ffb3b3}
  .ev.session{border-left-color:var(--ok)} .ev.session .k{color:var(--ok)}
  .ev .sub{color:#7c838f;font-size:11px}
  #empty{color:var(--dim);padding:18px 14px;font-size:12px}
  #foot{border-top:1px solid var(--line);padding:8px 14px;color:var(--dim);font-size:11px;
        display:flex;gap:10px}
  #foot b{color:var(--ink);font-weight:600}
</style>
</head><body>

<div id="wrap">
  <div id="stage">
    <canvas id="c"></canvas>
    <div id="bar">
      <span class="pill t">__LABEL__</span>
      <span class="pill"><i class="dot" id="dot"></i><span id="status">waiting for a build</span></span>
      <span class="pill" id="meta"></span>
    </div>
    <div id="hint">drag to orbit · scroll to zoom · right-drag to pan</div>
  </div>

  <div id="side">
    <div id="shead"><b>Agent trace</b><span id="tcount">—</span></div>
    <div id="feed"><div id="empty">No trace yet. Events appear here as the agent works.</div></div>
    <div id="foot"><span>build <b id="fbuild">—</b></span><span>compile <b id="fsecs">—</b></span>
      <span>objects <b id="fobj">—</b></span></div>
  </div>
</div>

<script type="importmap">{ "imports": {
  "three": "https://cdn.jsdelivr.net/npm/three@__THREE__/build/three.module.js",
  "three/addons/": "https://cdn.jsdelivr.net/npm/three@__THREE__/examples/jsm/"
}}</script>
<script type="module">
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const POLL = __POLL__;

const canvas = document.getElementById('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x14161a);
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

const camera = new THREE.PerspectiveCamera(50, 1, 0.05, 500);
camera.position.set(6, 5, 8);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;

function resize() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (canvas.width !== w || canvas.height !== h) {
    renderer.setSize(w, h, false);
    camera.aspect = w / h; camera.updateProjectionMatrix();
  }
}
(function tick() { resize(); controls.update(); renderer.render(scene, camera); requestAnimationFrame(tick); })();

const draco = new DRACOLoader();
draco.setDecoderPath('https://cdn.jsdelivr.net/npm/three@__THREE__/examples/jsm/libs/draco/');
const loader = new GLTFLoader().setDRACOLoader(draco);

/* Free a swapped-out room. Three keeps GPU buffers alive until they are explicitly disposed, so
   without this a long authoring session leaks a full room per rebuild and eventually loses the
   WebGL context — the viewer would die exactly during the long runs it exists to watch. */
function dispose(root) {
  root.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    for (const m of [].concat(o.material || [])) {
      if (!m) continue;
      for (const k of Object.keys(m)) { const v = m[k]; if (v && v.isTexture) v.dispose(); }
      m.dispose();
    }
  });
}

let current = null, framed = false;

function frame(root) {
  const box = new THREE.Box3().setFromObject(root);
  if (box.isEmpty()) return;
  const size = box.getSize(new THREE.Vector3()), mid = box.getCenter(new THREE.Vector3());
  const span = Math.max(size.x, size.y, size.z) || 5;
  controls.target.copy(mid);
  camera.position.copy(mid).add(new THREE.Vector3(span * 0.9, span * 0.75, span * 0.9));
  camera.near = span / 500; camera.far = span * 40; camera.updateProjectionMatrix();
}

async function swap(build) {
  const gltf = await loader.loadAsync('room.glb?b=' + build);
  const root = gltf.scene;
  // Blender is Z-up, three is Y-up. The exporter already rotates, so nothing to do here — but
  // keep the room centred on its own origin so orbiting feels the same across rebuilds.
  if (current) { scene.remove(current); dispose(current); }
  current = root; scene.add(root);
  if (!framed) { frame(root); framed = true; }   // never re-frame: the camera is the user's
  let n = 0; root.traverse((o) => { if (o.isMesh) n++; });
  document.getElementById('fobj').textContent = n;
}

/* ---- state polling ---------------------------------------------------------------------- */
const feed = document.getElementById('feed');
const dot = document.getElementById('dot');
const statusEl = document.getElementById('status');
let seenBuild = -1, cursor = 0, loading = false;

const KIND = {
  tool: 'tool', think: 'think', session_start: 'session', session_end: 'session',
  trace_start: 'session', result: 'result', images: 'images',
};

function line(e) {
  const cls = e.is_error ? 'err' : (KIND[e.kind] || '');
  const el = document.createElement('div');
  el.className = 'ev ' + cls;
  const dt = (e.dt == null) ? '' : (e.dt < 60 ? e.dt.toFixed(1) + 's'
            : Math.floor(e.dt / 60) + 'm' + String(Math.round(e.dt % 60)).padStart(2, '0'));
  let kind = e.kind || 'log', detail = '', sub = '';
  if (e.kind === 'tool') { kind = e.tool || 'tool'; detail = e.hint || ''; }
  else if (e.kind === 'think') { detail = e.text || ''; }
  else if (e.kind === 'result') { kind = 'ok'; detail = (e.secs != null ? e.secs.toFixed(1) + 's' : '');
                                  if (e.chars) sub = e.chars + ' chars'; }
  else if (e.kind === 'session_start') { detail = (e.model || '') + ' · ' + (e.pass || ''); }
  else if (e.kind === 'session_end') { detail = (e.calls || 0) + ' calls'
                                       + (e.cost_usd ? ' · $' + Number(e.cost_usd).toFixed(2) : ''); }
  else if (e.kind === 'images') { detail = (e.n_images || 0) + ' image(s)'; }
  else { detail = e.msg || e.name || e.stage || e.status || ''; }
  el.innerHTML = '<div class="dt"></div><div class="bd"><span class="k"></span>'
               + '<span class="d"></span><div class="sub"></div></div>';
  el.querySelector('.dt').textContent = dt;
  el.querySelector('.k').textContent = kind;
  el.querySelector('.d').textContent = String(detail).slice(0, 400);
  el.querySelector('.sub').textContent = sub;
  return el;
}

async function poll() {
  try {
    const s = await fetch('state?since=' + cursor, { cache: 'no-store' }).then((r) => r.json());

    const busy = s.status === 'building' || s.baking;
    dot.className = 'dot ' + (busy ? 'building' : s.status === 'failed' ? 'failed' : '');
    statusEl.textContent = s.status === 'building' ? 'compiling…'
      : s.status === 'failed' ? (s.error || 'build failed')
      : s.baking ? 'baking materials…'
      : s.build > 0 ? 'build ' + s.build + ' · ' + (s.phase === 'baked' ? 'materials' : 'geometry')
      : 'waiting for a build';
    document.getElementById('meta').textContent = s.mb ? s.mb.toFixed(0) + ' MB' : '';
    document.getElementById('fbuild').textContent = s.build || '—';
    document.getElementById('fsecs').textContent = (s.compile_s ? s.compile_s.toFixed(1) + 's' : '—')
      + (s.bake_s ? ' +' + s.bake_s.toFixed(0) + 's bake' : '');

    if (s.events && s.events.length) {
      const stick = feed.scrollTop + feed.clientHeight > feed.scrollHeight - 60;
      const first = document.getElementById('empty');
      if (first) first.remove();
      for (const e of s.events) feed.appendChild(line(e));
      cursor = s.cursor;
      document.getElementById('tcount').textContent = s.total + ' events';
      if (stick) feed.scrollTop = feed.scrollHeight;
    }

    if (s.build > 0 && s.build !== seenBuild && !loading) {
      loading = true;
      const b = s.build;
      try { await swap(b); seenBuild = b; } catch (err) { console.error('swap failed', err); }
      loading = false;
    }
  } catch (err) { /* server restarting — keep polling */ }
  setTimeout(poll, POLL);
}
poll();
window.__live = { camera, controls, scene, root: () => current, frame: () => current && frame(current) };
</script>
</body></html>
"""


def render(label: str, poll_ms: int = 700) -> str:
    """The full page for one live room. `label` is shown in the title bar and browser tab."""
    return (
        _PAGE.replace("__LABEL__", html.escape(label))
        .replace("__THREE__", THREE)
        .replace("__POLL__", json.dumps(int(poll_ms)))
    )
