"""qc_room.py — DETERMINISTIC geometry QC for a built room. No model. Reads room_layout.json
(world-space AABB per object) + the SHELL (floor_z/ceiling_z/walls/openings) and flags:

  below_floor / above_ceiling  — object pokes through the floor or ceiling
  floating / sunk              — floor-standing furniture not resting on the floor
  outside_room                 — object centre outside the room footprint
  wall_clash                   — furniture penetrates a wall slab
  object_clash                 — two furniture pieces interpenetrate
  fixture_over_opening         — a wall fixture sits over a door/window opening

Overlap that is CORRECT is not reported: an undermount sink inside its counter, a built-in oven in
the cabinet run, a chair tucked under a table, a socket on its trunking (see EXPECTED_CONTAINMENT /
PASSTHROUGH). `authoring/qc_fix.py` resolves what IS reported by nudging furniture apart.

Everything is pure arithmetic over AABBs, so it's fast, exact, and needs no LLM.

    .venv/bin/python authoring/qc_room.py --room <room dir>          # one room
    .venv/bin/python authoring/qc_room.py --layout <room_layout.json> --shell <Room.py>
"""

from __future__ import annotations

import argparse
import ast
import glob
import json
import math
import re
from pathlib import Path


def _extract_shell(src: str) -> dict:
    """Brace-matched parse of the `SHELL = {...}` literal — robust to whatever code follows it
    (the shell-editing pass moves the old `\\n\\nif __name__` anchor a regex relied on).

    JSON is the fast path, but the authoring/QC MODEL edits `SHELL` as Python, and the moment it
    writes something valid-Python-but-not-JSON — an adjacent-string note (`"a" "b"`), a trailing
    comma, a tuple — `json.loads` fails and the OLD code returned `{}`, silently blinding every
    geometry check below (no walls, no objects → every clash "passes"). `ast.literal_eval` parses
    the same Python literal, so fall back to it before giving up."""
    m = re.search(r"\bSHELL\s*=\s*\{", src)
    if not m:
        return {}
    i = src.index("{", m.start())
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                blob = src[i:j + 1]
                for parse in (json.loads, ast.literal_eval):
                    try:
                        return parse(blob)
                    except Exception:  # noqa: BLE001
                        continue
                return {}
    return {}


def _obb_mtv_2d(a, b):
    """a,b = (cx, cy, hx, hy, yaw_rad). Rotated-rectangle overlap via the separating-axis theorem.

    Returns the MINIMUM TRANSLATION VECTOR as (depth, (ux, uy)) — the shortest push that separates
    them, with the axis oriented so that moving `b` by +axis*depth (or `a` by -axis*depth) resolves
    the overlap. None when a real separating axis exists (no contact). Exact for boxes, so rotated
    furniture doesn't false-clash. The axis is what makes automatic resolution possible: qc_fix
    nudges along it, which is by construction the smallest move that fixes the collision."""
    def geom(o):
        cx, cy, hx, hy, r = o
        c, s = math.cos(r), math.sin(r)
        ux, uy = (c, s), (-s, c)                       # local box axes
        corners = [(cx + sx * hx * ux[0] + sy * hy * uy[0],
                    cy + sx * hx * ux[1] + sy * hy * uy[1])
                   for sx in (-1, 1) for sy in (-1, 1)]
        return corners, (ux, uy)
    ca, axa = geom(a)
    cb, axb = geom(b)
    best, best_axis = 1e9, None
    for ax in (*axa, *axb):
        L = math.hypot(*ax) or 1.0
        u = (ax[0] / L, ax[1] / L)
        pa = [p[0] * u[0] + p[1] * u[1] for p in ca]
        pb = [p[0] * u[0] + p[1] * u[1] for p in cb]
        ov = min(max(pa), max(pb)) - max(min(pa), min(pb))
        if ov <= 0:
            return None                                # separating axis → not touching
        if ov < best:
            # orient the axis a → b, so +axis always pushes b away from a
            ctr = (sum(p[0] * u[0] + p[1] * u[1] for p in cb) / 4
                   - sum(p[0] * u[0] + p[1] * u[1] for p in ca) / 4)
            best, best_axis = ov, (u if ctr >= 0 else (-u[0], -u[1]))
    return best, best_axis


def _obb_penetration_2d(a, b):
    """Penetration depth only — the historical shape of this helper."""
    mtv = _obb_mtv_2d(a, b)
    return mtv[0] if mtv else None

FURNITURE = {"table", "chair", "sofa", "storage", "television", "bed", "desk", "cabinet",
             "refrigerator", "stove", "oven", "sink", "toilet", "bathtub"}
FLOOR_STANDING = {"table", "chair", "sofa", "storage", "desk", "cabinet", "bed",
                  "refrigerator", "stove", "sink", "toilet", "bathtub"}

# Wall-mounted things the authoring pass adds. Matched on `category`, NOT on id prefix: the ids the
# pass actually emits are Socket0 / Trunking0 / Panel0 / Noticeboard0, so the old prefix list
# ("WallSocket", "CableTrunking", "WallPanel", "NoticeBoard", …) matched nothing and every
# fixture check silently passed on every scene.
WALL_MOUNTED = {"whiteboard", "noticeboard", "board", "socket", "switch", "radiator", "shelf",
                "panel", "sign", "poster", "sensor", "dispenser", "access_panel", "ac", "heater",
                "thermostat", "vent", "mirror", "clock", "hook", "window_frame", "door_frame"}

# Long runs and trims that legitimately pass behind, under or through everything else — a socket
# mounted ON its trunking, a radiator sitting over the skirting, two cable runs crossing at a
# corner are all correct. Never report a pair where either side is one of these.
PASSTHROUGH = {"trunking", "conduit", "skirting", "ceiling_grid", "cornice", "rail"}

# Open structures whose bounding box is mostly VOID. Holding other things inside that envelope is
# what they are for, so a solid-box overlap test says nothing about them: in Office-Elliott a cream
# panel leans on the wall behind slotted shelving — visible in the Wall0 stitch, correctly modelled,
# and reported as a 0.74 m clash until this list existed.
OPEN_FRAME = {"shelf", "shelving", "rack", "bookcase", "bookshelf"}

# Interpenetration that is CORRECT and must not be reported or "fixed": an undermount sink is
# inside its counter, a built-in oven is inside the cabinet run, a chair tucks under a table.
# Nudging these apart makes the scene worse, so the resolver honours the same list. Order-free.
EXPECTED_CONTAINMENT = {
    ("chair", "table"), ("chair", "desk"),                          # tucked in
    ("sink", "storage"), ("sink", "cabinet"), ("sink", "table"),    # basin in its counter/vanity
    ("oven", "storage"), ("oven", "cabinet"),                       # built-in appliance
    ("stove", "storage"), ("stove", "cabinet"),
    ("television", "storage"), ("television", "cabinet"),           # set on / mounted to a unit
}

# Fixture pairs that overlap by construction (the frame wraps its opening).
EXPECTED_FIXTURE_OVERLAP = {("window", "window_frame"), ("door", "door_frame")}


def _expected(cat_a: str, cat_b: str, table=EXPECTED_CONTAINMENT) -> bool:
    """Is this category pair an overlap we EXPECT? Order-independent."""
    return (cat_a, cat_b) in table or (cat_b, cat_a) in table


# tolerances (metres)
Z_TOL = 0.05          # poke through floor/ceiling
FLOAT_TOL = 0.08      # gap under floor-standing furniture
SUNK_TOL = 0.05
WALL_PEN = 0.10       # furniture penetration into a wall slab
OBJ_PEN = 0.10        # furniture-furniture interpenetration
FIXTURE_PEN = 0.08    # wall-fixture overlap, measured in the wall's own plane
FIXTURE_PERP = 0.75   # how far off a wall a fixture can sit and still count as mounted to it


def _load(room_dir=None, layout=None, shell=None):
    if layout is None:
        cands = sorted(glob.glob(str(Path(room_dir).parent) + "/**/room_layout.json", recursive=True),
                       key=lambda p: Path(p).stat().st_mtime, reverse=True)
        layout = cands[0] if cands else None
    if shell is None:
        shell = str(Path(room_dir) / "Room.py")
    objs = json.loads(Path(layout).read_text())
    objs = objs if isinstance(objs, list) else objs.get("objects", [])
    SHELL = _extract_shell(Path(shell).read_text())
    return objs, SHELL, layout


def _overlap(a, b):
    """AABB overlap extents [dx,dy,dz] or None (a/b are dicts with bbox_min/max)."""
    lo = [max(a["bbox_min"][i], b["bbox_min"][i]) for i in range(3)]
    hi = [min(a["bbox_max"][i], b["bbox_max"][i]) for i in range(3)]
    return [hi[i] - lo[i] for i in range(3)] if all(hi[i] > lo[i] for i in range(3)) else None


def _wall_frame(w):
    """(sx, sy, ux, uy, length) for a SHELL wall — origin + along-wall unit vector. None if degenerate."""
    sx, sy = w["start"]
    ex, ey = w["end"]
    dx, dy = ex - sx, ey - sy
    L = math.hypot(dx, dy)
    return (sx, sy, dx / L, dy / L, L) if L > 1e-9 else None


def assign_wall(center, walls, max_perp=FIXTURE_PERP):
    """Which wall is this thing mounted on? → (wall_id, t_along, perp_dist), nearest wins.

    None when nothing is close enough — that's how ceiling-mounted items (grids, vents) and
    free-standing furniture drop out of the wall-fixture checks instead of being forced onto a wall."""
    best = None
    for wid, w in (walls or {}).items():
        fr = _wall_frame(w)
        if not fr:
            continue
        sx, sy, ux, uy, L = fr
        rx, ry = center[0] - sx, center[1] - sy
        t = rx * ux + ry * uy
        if not (-0.25 <= t <= L + 0.25):
            continue                                   # projects off the ends of this wall
        perp = abs(rx * uy - ry * ux)
        if perp <= max_perp and (best is None or perp < best[2]):
            best = (wid, t, perp)
    return best


def wall_span(o, wall):
    """A fixture's extent in its wall's OWN frame: (t0, t1, z0, z1, d0, d1) — along-wall metres from
    the wall start, height, and depth out from the wall plane. All three axes matter: two fixtures
    can share a patch of wall and still not touch, one being mounted in front of the other.

    Walls are frequently diagonal, so a world AABB is a fat useless proxy — projecting onto the
    wall's along-axis is what makes 'do these two boards overlap' answerable at all.

    The projection is exact, not the AABB's support function. A plate of along half-length A and
    perpendicular half-thickness T sitting on a wall with direction (ux,uy) has world AABB halves
        hx = A·|ux| + T·|uy|,   hy = A·|uy| + T·|ux|
    so A and T invert straight out of that 2x2 system. Taking the support |hx·ux| + |hy·uy| instead
    yields A + 2T·|ux·uy| — an over-estimate of up to T per object, which on a 30° wall was enough
    to fabricate a 0.16 m 'overlap' between two fixtures that merely abut. The system is singular
    on a 45° wall (|ux| = |uy|), where support is the best available fallback."""
    fr = _wall_frame(wall)
    if not fr:
        return None
    sx, sy, ux, uy, _ = fr
    bmin, bmax = o["bbox_min"], o["bbox_max"]
    cx, cy = (bmin[0] + bmax[0]) / 2, (bmin[1] + bmax[1]) / 2
    hx, hy = (bmax[0] - bmin[0]) / 2, (bmax[1] - bmin[1]) / 2
    t = (cx - sx) * ux + (cy - sy) * uy
    a, b = abs(ux), abs(uy)
    det = a * a - b * b
    if abs(det) > 1e-6:
        half = (a * hx - b * hy) / det          # along-wall half-length A
        thick = (a * hy - b * hx) / det         # perpendicular half-thickness T
    else:                                       # 45° wall — the system is singular
        half, thick = abs(hx * ux) + abs(hy * uy), abs(hx * uy) + abs(hy * ux)
    half, thick = max(half, 0.0), max(thick, 0.0)
    d = abs((cx - sx) * uy - (cy - sy) * ux)    # centre's distance out from the wall plane
    return (t - half, t + half, bmin[2], bmax[2], d - thick, d + thick)


def qc(room_dir=None, layout=None, shell=None):
    objs, SHELL, layout_path = _load(room_dir, layout, shell)
    byid = {o["id"]: o for o in objs}
    floor_z = SHELL.get("floor_z", byid.get("Floor0", {}).get("top_z", -1e9))
    ceil_z = SHELL.get("ceiling_z", byid.get("Ceiling0", {}).get("top_z", 1e9))
    floor = byid.get("Floor0")
    fmin, fmax = (floor["bbox_min"], floor["bbox_max"]) if floor else ([-1e9] * 3, [1e9] * 3)
    furn = [o for o in objs if o["category"] in FURNITURE]

    V = []  # (object, check, detail)
    for o in furn:
        bmin, bmax, c = o["bbox_min"], o["bbox_max"], o["center"]
        if bmin[2] < floor_z - Z_TOL:
            V.append((o["id"], "below_floor", f"bottom {bmin[2]:.2f} < floor {floor_z:.2f}"))
        if bmax[2] > ceil_z + Z_TOL:
            V.append((o["id"], "above_ceiling", f"top {bmax[2]:.2f} > ceiling {ceil_z:.2f}"))
        if o["category"] in FLOOR_STANDING:
            gap = bmin[2] - floor_z
            if gap > FLOAT_TOL:
                V.append((o["id"], "floating", f"{gap:.2f} m above the floor"))
            elif gap < -SUNK_TOL:
                V.append((o["id"], "sunk", f"{-gap:.2f} m into the floor"))
        if not (fmin[0] - 0.10 <= c[0] <= fmax[0] + 0.10 and fmin[1] - 0.10 <= c[1] <= fmax[1] + 0.10):
            V.append((o["id"], "outside_room", f"centre ({c[0]:.2f},{c[1]:.2f}) outside footprint"))
        # wall clash: use the ACTUAL wall segment (SHELL start/end/thickness), not the AABB — walls are
        # often diagonal, so AABBs are fat and useless. Flag when the object CENTRE lies inside the wall
        # slab (perp distance to the wall line < thickness/2, within the segment span). Furniture resting
        # against a wall has its centre ~half-its-depth away, well outside the thin slab → no false hit.
        for wid, w in (SHELL.get("walls") or {}).items():
            sx, sy = w["start"]
            ex, ey = w["end"]
            dx, dy = ex - sx, ey - sy
            L2 = dx * dx + dy * dy
            if L2 == 0:
                continue
            t = ((c[0] - sx) * dx + (c[1] - sy) * dy) / L2
            if not (0.0 <= t <= 1.0):
                continue  # centre projects off the ends of this wall
            px, py = sx + t * dx, sy + t * dy
            perp = ((c[0] - px) ** 2 + (c[1] - py) ** 2) ** 0.5
            if perp < w.get("thickness", 0.1) / 2 + 0.02:  # centre is inside the wall slab
                V.append((o["id"], "wall_clash", f"centre inside {wid} (perp {perp:.2f} m)"))
                break
    # object clash: ORIENTED-box footprint overlap (SAT) + vertical overlap, from SHELL center/size/yaw.
    # Skips chair-under-table tucks. Oriented boxes remove the rotated-furniture false positives.
    shobjs = SHELL.get("objects", {})

    def _obb(o):
        so = shobjs.get(o["id"])
        if not so:
            return None
        cx, cy, cz = so["center"]
        w, d, h = so["size"]
        return (cx, cy, w / 2, d / 2, math.radians(so.get("yaw", 0)), cz, h / 2)

    fo = [(o, _obb(o)) for o in furn]
    for i in range(len(fo)):
        for j in range(i + 1, len(fo)):
            (oi, bi), (oj, bj) = fo[i], fo[j]
            if bi is None or bj is None or _expected(oi["category"], oj["category"]):
                continue
            zov = min(bi[5] + bi[6], bj[5] + bj[6]) - max(bi[5] - bi[6], bj[5] - bj[6])
            if zov <= 0.05:
                continue  # don't share a height band → can't collide
            pen = _obb_penetration_2d(bi[:5], bj[:5])
            if pen and pen > 0.08:
                V.append((oi["id"], "object_clash", f"footprint into {oj['id']} ~{pen:.2f} m"))

    # ---- wall fixtures -----------------------------------------------------------------------
    # Everything below works in each wall's OWN plane (along-wall metres × height), never in world
    # AABBs: walls are often diagonal, and a diagonal thin plate's world AABB is fat enough to
    # overlap half the room.
    walls_shell = SHELL.get("walls", {})
    fixtures = [o for o in objs if o["category"] in WALL_MOUNTED]
    mounted = []  # (obj, wall_id, t0, t1, z0, z1, d0, d1)
    for o in fixtures:
        hit = assign_wall(o["center"], walls_shell)
        if not hit:
            continue  # not near any wall (ceiling-mounted, or free-standing) — not our business
        span = wall_span(o, walls_shell[hit[0]])
        if span:
            mounted.append((o, hit[0], *span))

    # NB: fixture ↔ fixture overlap is intentionally NOT flagged — two wall fixtures sharing a patch
    # of wall happens legitimately (e.g. a socket on trunking, stacked plates) and was noisy, so it
    # was removed. Only fixtures over an OPENING are still reported below.

    # fixture over a door/window opening (opening rect taken from the SHELL, same wall frame)
    for oid, op in (SHELL.get("openings") or {}).items():
        w = walls_shell.get(op["wall"])
        if not w:
            continue
        o0, o1 = op["offset"], op["offset"] + op["width"]
        sill = SHELL["floor_z"] + op.get("sill", 0)
        z0, z1 = sill, sill + op["height"]
        for o, wid, t0, t1, fz0, fz1, _d0, _d1 in mounted:
            # a window's own frame belongs over its opening — that's the frame doing its job
            if (wid != op["wall"] or o["category"] in PASSTHROUGH
                    or _expected(o["category"], op.get("type", ""), EXPECTED_FIXTURE_OVERLAP)):
                continue
            ov_t = min(t1, o1) - max(t0, o0)
            ov_z = min(fz1, z1) - max(fz0, z0)
            if ov_t > FIXTURE_PEN and ov_z > FIXTURE_PEN:
                V.append((o["id"], "fixture_over_opening",
                          f"sits over {oid} on {op['wall']} ~{min(ov_t, ov_z):.2f} m"))

    return {"layout": layout_path, "n_furniture": len(furn), "n_fixtures": len(mounted),
            "violations": V}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--room")
    ap.add_argument("--layout")
    ap.add_argument("--shell")
    a = ap.parse_args()
    r = qc(a.room, a.layout, a.shell)
    V = r["violations"]
    print(f"QC {r['layout']}\n  furniture: {r['n_furniture']}  "
          f"wall fixtures: {r.get('n_fixtures', 0)}  violations: {len(V)}")
    for oid, chk, detail in V:
        print(f"  ✗ {oid:16} {chk:20} {detail}")
    if not V:
        print("  ✓ clean — no geometric violations")
    return 1 if V else 0


if __name__ == "__main__":
    raise SystemExit(main())
