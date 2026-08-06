"""Watch an authoring run and stream it to a browser: the room as it is built, beside the trace.

`publish` produces the artifact you keep. This produces the one you *watch* — it points at a run
that is still going, recompiles `Room.py` whenever the agent saves it, and hands the browser both
the fresh geometry and the agent's own event log. Nothing here is on the pipeline's critical path:
the server only reads the run tree and writes into `<authoring_root>/.live/`, so it can be started,
killed, and restarted at any point in a run without disturbing it.

It lives under `pipeline/` because finding those things IS run-tree layout knowledge — where the
authored room sits, where each pass writes its trace — which `room_ops` deliberately does not have
(see the note in `publish/viewer.py`). The compile itself is a room-ops capability and is called as
one, so the dependency still points inward.

    python -m litereality_agent.pipeline.realism_authoring.live <scan> [--port 8770]
    litereality live <scan>

Rebuilds land in two phases, because the two halves of a room have very different costs. Assembling
`Room.py` takes seconds; baking the SHELL's node-graph materials takes the better part of a minute
and is dominated by loading the .blend, so turning the bake resolution down barely helps. Waiting
for it would make every save feel slow, but skipping it is worse: a procedural wall/floor material
has no glTF representation and exports with neither a texture nor a base colour, so an unbaked room
renders as flat grey and the materials the agent just chose are invisible.

So the page gets the geometry the moment it compiles, and the baked room replaces it in place a
little later — two swaps, no reload, and the camera never moves. A bake whose geometry has already
been superseded by a newer save is dropped rather than published stale.
"""

from __future__ import annotations

import argparse
import json
import shutil
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from litereality_agent.pipeline.context import RunContext
from litereality_agent.pipeline.realism_authoring.live import page

# Every pass writes its own trace file, and a run has several. Globbed rather than listed so a new
# pass shows up in the feed without editing this module.
TRACE_GLOBS = ("trace.jsonl", "authoring_trace*.jsonl")


def trace_dirs(context: RunContext) -> list[Path]:
    """Where this run's tracers write, most interesting first."""
    return [context.object_root / "traces", context.scene_dir / "traces"]


@dataclass
class _Trace:
    """Merged view of every trace file in a run, tailed by byte offset.

    Offsets matter more than they look: an authoring trace grows to megabytes (one event carries the
    whole system prompt), and re-reading every file on every poll would burn more time than the
    poll interval. We keep what we have parsed and only read the tail each pass.
    """

    dirs: list[Path]
    events: list[dict] = field(default_factory=list)
    _offsets: dict[Path, int] = field(default_factory=dict)

    def refresh(self) -> None:
        fresh = []
        for d in self.dirs:
            if not d.is_dir():
                continue
            for pattern in TRACE_GLOBS:
                for path in sorted(d.glob(pattern)):
                    if path.name.endswith(".raw.jsonl"):
                        continue  # the normalised sibling says the same thing, smaller
                    fresh += self._tail(path)
        if fresh:
            # Passes run concurrently and each file is only ordered within itself, so the merged
            # feed is sorted by wall clock. Events already delivered keep their place.
            self.events += sorted(fresh, key=lambda e: e.get("t") or 0.0)

    def _tail(self, path: Path) -> list[dict]:
        out: list[dict] = []
        try:
            size = path.stat().st_size
            seen = self._offsets.get(path, 0)
            if size <= seen:
                # Truncated or rewritten (a re-run of the same pass) — start over rather than
                # slicing into the middle of a line.
                if size < seen:
                    self._offsets[path] = 0
                    seen = 0
                else:
                    return out
            with path.open("rb") as fh:
                fh.seek(seen)
                blob = fh.read()
            # Only consume through the last complete line; a tracer may be mid-write.
            cut = blob.rfind(b"\n")
            if cut < 0:
                return out
            self._offsets[path] = seen + cut + 1
            for line in blob[:cut].splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
        except OSError:
            pass
        return out

    def since(self, cursor: int) -> list[dict]:
        return self.events[max(0, cursor):]


class LiveRoom:
    """Compiles on change and holds what the page needs to ask for."""

    def __init__(
        self,
        context: RunContext,
        poll: float = 1.0,
        bake: bool = True,
        bake_resolution: int = 1024,
    ) -> None:
        self.context = context
        self.poll = poll
        self.bake = bake
        self.bake_resolution = bake_resolution
        self.room = context.authored_room
        self.source = self.room / "Room.py"
        self.serve_dir = context.authoring_root / ".live"
        self.serve_dir.mkdir(parents=True, exist_ok=True)
        self.glb = self.serve_dir / "room.glb"

        self.build = 0
        self.status = "idle"
        self.phase = "none"
        self.error = ""
        self.compile_s = 0.0
        self.bake_s = 0.0
        self.baking = False
        self.trace = _Trace(trace_dirs(context))
        # Bumped on every source change. A bake carries the generation it started from and is
        # dropped if a newer save has landed meanwhile, so the page never gets materials baked
        # onto geometry that no longer exists.
        self._gen = 0
        self._stamp: float | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()

    # -- publishing --------------------------------------------------------------------
    def _publish(self, built: Path, phase: str) -> None:
        """Swap `built` in as the served room. Renamed rather than copied in place so a poll
        landing mid-write never sees half a glb."""
        tmp = self.serve_dir / "room.glb.tmp"
        shutil.copy2(built, tmp)
        tmp.replace(self.glb)
        with self._lock:
            self.build += 1
            self.phase = phase

    # -- compilation -------------------------------------------------------------------
    def rebuild(self) -> bool:
        """Compile `Room.py` and publish the geometry. Returns True when the page has new geometry.

        The bake, when enabled, continues on its own thread and publishes a second time.
        """
        from litereality_agent.room_ops import api

        with self._lock:
            self.status, self.error = "building", ""
            gen = self._gen
        started = time.time()
        try:
            built = api.compile_room(self.room, self.context.preview_dir, bake=False)
        except Exception as exc:  # noqa: BLE001 — a broken Room.py must not kill the server
            with self._lock:
                self.status, self.error = "failed", f"{type(exc).__name__}: {exc}"
            return False
        if not built or not Path(built).is_file():
            with self._lock:
                self.status, self.error = "failed", "compile produced no Room.glb"
            return False

        self._publish(Path(built), "geometry")
        with self._lock:
            self.compile_s = time.time() - started
            self.status = "idle"

        if self.bake:
            threading.Thread(target=self._bake, args=(gen,), daemon=True).start()
        return True

    def _bake(self, gen: int) -> None:
        """Flatten the SHELL's node materials into a copy of the room, then publish it.

        Baked into a sibling file, never the served one: `bake_room` re-exports to the path it is
        given, so pointing it at the live glb would blank the page for the length of the bake.
        """
        from litereality_agent.room_ops import api

        with self._lock:
            self.baking = True
        started = time.time()
        out = self.serve_dir / "baked.glb"
        try:
            rc = api.bake_room(
                self.context.preview_dir / "Room.blend", out, resolution=self.bake_resolution
            )
            superseded = gen != self._gen
            if rc == 0 and out.is_file() and not superseded:
                self._publish(out, "baked")
                with self._lock:
                    self.bake_s = time.time() - started
        except Exception:  # noqa: BLE001 — a failed bake leaves the geometry build standing
            pass
        finally:
            with self._lock:
                self.baking = False

    # -- watching ----------------------------------------------------------------------
    def _changed(self) -> bool:
        try:
            stamp = self.source.stat().st_mtime
        except OSError:
            return False
        if self._stamp is None or stamp != self._stamp:
            self._stamp = stamp
            with self._lock:
                self._gen += 1
            return True
        return False

    def watch(self) -> None:
        while not self._stop.is_set():
            try:
                self.trace.refresh()
                if self._changed():
                    self.rebuild()
            except Exception:  # noqa: BLE001 — the watcher outlives any single bad iteration
                pass
            self._stop.wait(self.poll)

    def stop(self) -> None:
        self._stop.set()

    # -- what the page asks for --------------------------------------------------------
    def state(self, cursor: int) -> dict:
        with self._lock:
            build, status, error, secs = self.build, self.status, self.error, self.compile_s
            phase, baking, bake_s = self.phase, self.baking, self.bake_s
        events = self.trace.since(cursor)
        return {
            "build": build,
            "status": status,
            "phase": phase,
            "baking": baking,
            "bake_s": round(bake_s, 2),
            "error": error,
            "compile_s": round(secs, 2),
            "mb": round(self.glb.stat().st_size / 1e6, 1) if self.glb.is_file() else 0,
            "events": events,
            "cursor": cursor + len(events),
            "total": len(self.trace.events),
        }


def _handler(room: LiveRoom, label: str):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args) -> None:  # noqa: D102 — one line per poll is pure noise
            pass

        def _send(self, body: bytes, ctype: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's spelling
            route = urlparse(self.path)
            path = route.path.rstrip("/") or "/"
            if path == "/":
                return self._send(page.render(label).encode(), "text/html; charset=utf-8")
            if path == "/state":
                since = int((parse_qs(route.query).get("since") or ["0"])[0] or 0)
                return self._send(json.dumps(room.state(since)).encode(), "application/json")
            if path == "/room.glb":
                if not room.glb.is_file():
                    self.send_error(404, "no build yet")
                    return
                return self._send(room.glb.read_bytes(), "model/gltf-binary")
            self.send_error(404)

    return Handler


def serve(
    target: str,
    *,
    port: int = 8770,
    host: str = "127.0.0.1",
    poll: float = 1.0,
    output_root: str | None = None,
    bake: bool = True,
    bake_resolution: int = 1024,
) -> int:
    """Run the live viewer for `target` until interrupted."""
    context = RunContext.resolve(target, output_root=output_root)
    if not (context.authored_room / "Room.py").is_file():
        raise SystemExit(
            f"no authored room for {context.scan} — expected {context.authored_room / 'Room.py'}"
        )

    room = LiveRoom(context, poll=poll, bake=bake, bake_resolution=bake_resolution)
    room.trace.refresh()
    watcher = threading.Thread(target=room.watch, daemon=True)
    watcher.start()

    server = ThreadingHTTPServer((host, port), _handler(room, context.scan))
    url = f"http://{host}:{port}/"
    print(f"live viewer  {url}")
    print(f"  room   {context.authored_room / 'Room.py'}")
    print(f"  traces {', '.join(str(d) for d in trace_dirs(context) if d.is_dir()) or '(none yet)'}")
    print(
        "  rebuilds on every save · "
        + ("geometry first, materials baked right after" if bake else "geometry only (--no-bake)")
        + " · ctrl-c to stop"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        room.stop()
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="live authoring viewer")
    ap.add_argument("target", metavar="SCAN_OR_SCENE")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--poll", type=float, default=1.0, help="seconds between Room.py checks")
    ap.add_argument("--output-root")
    ap.add_argument(
        "--no-bake", dest="bake", action="store_false",
        help="geometry only — faster, but procedural SHELL materials render flat",
    )
    ap.add_argument("--bake-resolution", type=int, default=1024)
    args = ap.parse_args(argv)
    return serve(
        args.target, port=args.port, host=args.host, poll=args.poll,
        output_root=args.output_root, bake=args.bake, bake_resolution=args.bake_resolution,
    )


if __name__ == "__main__":
    raise SystemExit(main())
