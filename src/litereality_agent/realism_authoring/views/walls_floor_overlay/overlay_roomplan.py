#!/usr/bin/env python3
"""
Overlay RoomPlan USDZ wall/floor geometry onto RGB scan frames.

Usage:
  python overlay_roomplan.py /path/to/scene_folder
  python overlay_roomplan.py /path/to/scene_folder --output /path/to/output

The scene folder is expected to contain:
  - room.usdz
  - frame_00000.jpg, frame_00000.json, ...

The per-frame JSON files provide camera intrinsics and ARKit camera poses.
The USDZ contains USDA parametric wall/floor assets.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from litereality_agent.fonts import font as _shared_font

NUMBER_RE = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"
NEAR_PLANE_METERS = 0.05

# Depth-based occlusion (for multi-room scans): a wall from ANOTHER room projects into a
# frame even when it is behind the near room's wall. We test each wall's surface against
# the ARKit depth map — a wall point counts as occluded if it sits further than the sensor
# depth at its pixel (+ tolerance). Walls below WALL_MIN_VISIBLE visible fraction are
# dropped (not drawn, not counted); partially-occluded walls have their coverage scaled.
WALL_MIN_VISIBLE = float(os.environ.get("OVERLAY_OCCLUSION_MIN", "0.15"))
OCCLUSION_TOL_M = float(os.environ.get("OVERLAY_OCCLUSION_TOL_M", "0.2"))


@dataclass
class Mesh:
    name: str
    category: str
    points: np.ndarray
    faces: list[list[int]]
    edges: list[tuple[int, int]]
    parent: str | None = None
    outline_points: np.ndarray | None = None


def parse_numbers(text: str) -> list[float]:
    return [float(value) for value in re.findall(NUMBER_RE, text)]


def parse_matrix4d(usda: str) -> np.ndarray:
    match = re.search(r"matrix4d\s+xformOp:transform\s*=\s*\(\s*\((.*?)\)\s*\)", usda, re.S)
    if not match:
        return np.eye(4, dtype=float)
    values = parse_numbers(match.group(1))
    if len(values) != 16:
        raise ValueError(f"Expected 16 matrix values, found {len(values)}")
    return np.array(values, dtype=float).reshape(4, 4)


def parse_vec3_array(usda: str, field_name: str) -> np.ndarray:
    match = re.search(re.escape(field_name) + r"\s*=\s*\[(.*?)\]", usda, re.S)
    if not match:
        raise ValueError(f"Missing USDA array: {field_name}")
    values = parse_numbers(match.group(1))
    if len(values) % 3:
        raise ValueError(f"{field_name} does not contain vec3 values")
    return np.array(values, dtype=float).reshape(-1, 3)


def parse_int_array(usda: str, field_name: str) -> list[int]:
    match = re.search(re.escape(field_name) + r"\s*=\s*\[(.*?)\]", usda, re.S)
    if not match:
        raise ValueError(f"Missing USDA array: {field_name}")
    return [int(value) for value in re.findall(r"-?\d+", match.group(1))]


def usd_row_transform(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """USD matrices in these files place translation in the final row."""
    homogeneous = np.c_[points, np.ones(len(points))]
    return (homogeneous @ matrix)[:, :3]


def cube_mesh(
    name: str, category: str, scale: np.ndarray, transform: np.ndarray, parent: str | None = None
) -> Mesh:
    local = np.array(
        [
            [-0.5, -0.5, -0.5],
            [0.5, -0.5, -0.5],
            [0.5, 0.5, -0.5],
            [-0.5, 0.5, -0.5],
            [-0.5, -0.5, 0.5],
            [0.5, -0.5, 0.5],
            [0.5, 0.5, 0.5],
            [-0.5, 0.5, 0.5],
        ],
        dtype=float,
    )
    points = usd_row_transform(local * scale, transform)
    faces = [
        [0, 1, 2, 3],
        [4, 7, 6, 5],
        [0, 4, 5, 1],
        [3, 2, 6, 7],
        [1, 5, 6, 2],
        [0, 3, 7, 4],
    ]
    return Mesh(
        name=name,
        category=category,
        points=points,
        faces=faces,
        edges=edges_from_faces(faces),
        parent=parent,
    )


def edges_from_faces(faces: Iterable[Sequence[int]]) -> list[tuple[int, int]]:
    edges: set[tuple[int, int]] = set()
    for face in faces:
        for i, start in enumerate(face):
            end = face[(i + 1) % len(face)]
            edges.add(tuple(sorted((start, end))))
    return sorted(edges)


def ordered_boundary_loop(faces: Sequence[Sequence[int]]) -> list[int]:
    edge_counts: dict[tuple[int, int], int] = {}
    for face in faces:
        for index, start in enumerate(face):
            end = face[(index + 1) % len(face)]
            edge = tuple(sorted((start, end)))
            edge_counts[edge] = edge_counts.get(edge, 0) + 1

    boundary_edges = [edge for edge, count in edge_counts.items() if count == 1]
    if not boundary_edges:
        return []

    adjacency: dict[int, list[int]] = {}
    for start, end in boundary_edges:
        adjacency.setdefault(start, []).append(end)
        adjacency.setdefault(end, []).append(start)

    start = min(adjacency)
    loop = [start]
    previous = None
    current = start
    for _ in range(len(boundary_edges) + 2):
        neighbors = adjacency.get(current, [])
        next_candidates = [neighbor for neighbor in neighbors if neighbor != previous]
        if not next_candidates:
            break
        next_point = next_candidates[0]
        if next_point == start:
            break
        loop.append(next_point)
        previous, current = current, next_point
    return loop


def convex_hull(points: np.ndarray) -> list[tuple[float, float]]:
    if len(points) == 0:
        return []
    unique = sorted({(float(point[0]), float(point[1])) for point in points})
    if len(unique) <= 2:
        return unique

    def cross(origin: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - origin[0]) * (b[1] - origin[1]) - (a[1] - origin[1]) * (b[0] - origin[0])

    lower: list[tuple[float, float]] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)

    upper: list[tuple[float, float]] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)

    return lower[:-1] + upper[:-1]


def polygon_centroid(points: Sequence[tuple[float, float]]) -> tuple[float, float]:
    if not points:
        return 0.0, 0.0
    area = 0.0
    cx = 0.0
    cy = 0.0
    for index, point in enumerate(points):
        next_point = points[(index + 1) % len(points)]
        cross = point[0] * next_point[1] - next_point[0] * point[1]
        area += cross
        cx += (point[0] + next_point[0]) * cross
        cy += (point[1] + next_point[1]) * cross
    if abs(area) < 1e-6:
        mean = np.mean(np.array(points), axis=0)
        return float(mean[0]), float(mean[1])
    area *= 0.5
    return cx / (6 * area), cy / (6 * area)


def polygon_area(points: Sequence[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    area = 0.0
    for index, point in enumerate(points):
        next_point = points[(index + 1) % len(points)]
        area += point[0] * next_point[1] - next_point[0] * point[1]
    return abs(area) * 0.5


def face_area_3d(points: np.ndarray) -> float:
    if len(points) < 3:
        return 0.0
    area = 0.0
    origin = points[0]
    for index in range(1, len(points) - 1):
        area += np.linalg.norm(np.cross(points[index] - origin, points[index + 1] - origin)) * 0.5
    return float(area)


def clip_polygon_to_image(
    points: Sequence[tuple[float, float]],
    width: int,
    height: int,
) -> list[tuple[float, float]]:
    def clip_edge(
        polygon: list[tuple[float, float]],
        inside,
        intersect,
    ) -> list[tuple[float, float]]:
        if not polygon:
            return []
        clipped: list[tuple[float, float]] = []
        previous = polygon[-1]
        previous_inside = inside(previous)
        for current in polygon:
            current_inside = inside(current)
            if current_inside:
                if not previous_inside:
                    clipped.append(intersect(previous, current))
                clipped.append(current)
            elif previous_inside:
                clipped.append(intersect(previous, current))
            previous = current
            previous_inside = current_inside
        return clipped

    def intersect_x(x_value: float):
        def inner(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
            if abs(b[0] - a[0]) < 1e-9:
                return x_value, a[1]
            t = (x_value - a[0]) / (b[0] - a[0])
            return x_value, a[1] + t * (b[1] - a[1])

        return inner

    def intersect_y(y_value: float):
        def inner(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
            if abs(b[1] - a[1]) < 1e-9:
                return a[0], y_value
            t = (y_value - a[1]) / (b[1] - a[1])
            return a[0] + t * (b[0] - a[0]), y_value

        return inner

    polygon = list(points)
    polygon = clip_edge(polygon, lambda p: p[0] >= 0, intersect_x(0))
    polygon = clip_edge(polygon, lambda p: p[0] <= width - 1, intersect_x(width - 1))
    polygon = clip_edge(polygon, lambda p: p[1] >= 0, intersect_y(0))
    polygon = clip_edge(polygon, lambda p: p[1] <= height - 1, intersect_y(height - 1))
    return polygon


def clip_camera_polygon_to_near(points: np.ndarray, near: float = NEAR_PLANE_METERS) -> np.ndarray:
    polygon = [point for point in points]
    if not polygon:
        return np.empty((0, 3), dtype=float)

    def depth(point: np.ndarray) -> float:
        return float(-point[2])

    clipped: list[np.ndarray] = []
    previous = polygon[-1]
    previous_inside = depth(previous) > near
    for current in polygon:
        current_inside = depth(current) > near
        if current_inside:
            if not previous_inside:
                t = (near - depth(previous)) / (depth(current) - depth(previous))
                clipped.append(previous + t * (current - previous))
            clipped.append(current)
        elif previous_inside:
            t = (near - depth(previous)) / (depth(current) - depth(previous))
            clipped.append(previous + t * (current - previous))
        previous = current
        previous_inside = current_inside

    if len(clipped) < 3:
        return np.empty((0, 3), dtype=float)
    return np.array(clipped, dtype=float)


def points_in_polygon(points: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    x = points[:, 0]
    y = points[:, 1]
    inside = np.zeros(len(points), dtype=bool)
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        intersects = ((yi > y) != (yj > y)) & (
            x < (xj - xi) * (y - yi) / ((yj - yi) if abs(yj - yi) > 1e-12 else 1e-12) + xi
        )
        inside ^= intersects
        j = i
    return inside


def draw_floor_ray_outline(
    line_draw: ImageDraw.ImageDraw,
    intrinsics: np.ndarray,
    camera_pose: np.ndarray,
    floor_outline_points: np.ndarray,
    width: int,
    height: int,
    color: tuple[int, int, int, int],
    line_width: int,
    step: int = 8,
    from_bottom: bool = False,
) -> tuple[bool, tuple[float, float] | None]:
    floor_y = float(np.mean(floor_outline_points[:, 1]))
    floor_polygon_xz = floor_outline_points[:, [0, 2]]
    xs = np.arange(step / 2, width, step)
    ys = np.arange(step / 2, height, step)
    grid_x, grid_y = np.meshgrid(xs, ys)
    pixels = np.column_stack([grid_x.ravel(), grid_y.ravel()])

    fx, fy = intrinsics[0, 0], intrinsics[1, 1]
    cx, cy = intrinsics[0, 2], intrinsics[1, 2]
    dirs_camera = np.column_stack(
        [
            (pixels[:, 0] - cx) / fx,
            -(pixels[:, 1] - cy) / fy,
            -np.ones(len(pixels)),
        ]
    )
    rotation = camera_pose[:3, :3]
    origin = camera_pose[:3, 3]
    dirs_world = dirs_camera @ rotation.T
    denom = dirs_world[:, 1]
    valid = np.abs(denom) > 1e-8
    t = np.full(len(pixels), np.nan, dtype=float)
    t[valid] = (floor_y - origin[1]) / denom[valid]
    valid &= t > 0

    hits = origin + dirs_world * t[:, None]
    hit_xz = hits[:, [0, 2]]
    inside = np.zeros(len(pixels), dtype=bool)
    if np.any(valid):
        inside[valid] = points_in_polygon(hit_xz[valid], floor_polygon_xz)

    mask = inside.reshape(len(ys), len(xs))
    if not np.any(mask):
        return False, None

    boundary_points: list[tuple[float, float]] = []
    for col in range(mask.shape[1]):
        rows = np.flatnonzero(mask[:, col])
        if len(rows) == 0:
            continue
        # Floor: trace the far (top) edge of the visible region; ceiling: trace
        # the near (bottom) edge where it meets the walls.
        row = int(rows[-1] if from_bottom else rows[0])
        edge = ys[row] + step / 2 if from_bottom else ys[row] - step / 2
        boundary_points.append((float(xs[col]), min(float(height - 1), max(0.0, float(edge)))))

    if len(boundary_points) >= 4:
        coords = np.array(boundary_points, dtype=float)
        window = min(9, len(coords) if len(coords) % 2 == 1 else len(coords) - 1)
        if window >= 3:
            pad = window // 2
            padded_y = np.pad(coords[:, 1], (pad, pad), mode="edge")
            kernel = np.ones(window) / window
            coords[:, 1] = np.convolve(padded_y, kernel, mode="valid")
        line_draw.line([tuple(point) for point in coords], fill=color, width=line_width)

    visible_pixels = pixels[inside]
    center = tuple(np.median(visible_pixels, axis=0))
    return True, center


def floor_mesh(name: str, usda: str) -> Mesh:
    points = parse_vec3_array(usda, "point3f[] points")
    counts = parse_int_array(usda, "int[] faceVertexCounts")
    indices = parse_int_array(usda, "int[] faceVertexIndices")
    transform = parse_matrix4d(usda)
    world_points = usd_row_transform(points, transform)

    faces: list[list[int]] = []
    offset = 0
    for count in counts:
        face = indices[offset : offset + count]
        if len(face) >= 3:
            faces.append(face)
        offset += count

    top_z = float(np.max(points[:, 2]))
    top_faces = [
        face for face in faces if all(abs(points[index, 2] - top_z) < 1e-5 for index in face)
    ]
    boundary_loop = ordered_boundary_loop(top_faces)
    outline_points = world_points[boundary_loop] if boundary_loop else None

    return Mesh(
        name=name,
        category="floor",
        points=world_points,
        faces=faces,
        edges=edges_from_faces(faces),
        outline_points=outline_points,
    )


def mesh_label(mesh: Mesh) -> str:
    if mesh.parent:
        return f"{mesh.name}@{mesh.parent}"
    return mesh.name


def semantic_color(mesh: Mesh) -> tuple[int, int, int]:
    wall_palette = [
        (230, 65, 70),
        (40, 145, 255),
        (70, 180, 90),
        (245, 155, 45),
        (170, 95, 225),
        (0, 170, 170),
        (235, 95, 170),
        (150, 155, 45),
        (105, 125, 235),
        (230, 120, 70),
        (70, 170, 135),
        (190, 90, 90),
        (95, 185, 235),
        (210, 180, 65),
        (150, 110, 220),
    ]
    if mesh.category == "wall":
        match = re.search(r"\d+", mesh.name)
        index = int(match.group(0)) if match else 0
        return wall_palette[index % len(wall_palette)]
    if mesh.category == "floor":
        return (0, 205, 235)
    if mesh.category == "ceiling":
        return (200, 140, 240)
    if mesh.category == "door":
        return (85, 245, 145)
    if mesh.category == "window":
        return (95, 165, 255)
    return (255, 255, 255)


def derive_ceiling(meshes: list[Mesh]) -> Mesh | None:
    """RoomPlan exports no ceiling, so derive one: the floor boundary loop raised
    to the top of the walls. Treated like the floor (a horizontal plane) for
    projection/labelling."""
    floor = next(
        (
            mesh
            for mesh in meshes
            if mesh.category == "floor"
            and mesh.outline_points is not None
            and len(mesh.outline_points) >= 3
        ),
        None,
    )
    walls = [mesh for mesh in meshes if mesh.category == "wall"]
    if floor is None or not walls:
        return None
    ceiling_y = max(float(np.max(wall.points[:, 1])) for wall in walls)
    outline = floor.outline_points.copy()
    outline[:, 1] = ceiling_y
    faces = [list(range(len(outline)))]
    return Mesh(
        name="Ceiling0",
        category="ceiling",
        points=outline.copy(),
        faces=faces,
        edges=edges_from_faces(faces),
        outline_points=outline,
    )


def load_meshes(usdz_path: Path) -> list[Mesh]:
    meshes: list[Mesh] = []
    with zipfile.ZipFile(usdz_path) as archive:
        for name in archive.namelist():
            wall_asset = re.search(r"assets/Parametric/Walls/(Wall\d+)/(Wall\d+)\.usda$", name)
            opening_asset = re.search(
                r"assets/Parametric/Walls/(Wall\d+)/(Door\d+|Window\d+)\.usda$", name
            )
            if wall_asset or opening_asset:
                usda = archive.read(name).decode("utf-8")
                transform = parse_matrix4d(usda)
                scale_match = re.search(r"double3\s+xformOp:scale\s*=\s*\((.*?)\)", usda, re.S)
                if not scale_match:
                    continue
                scale = np.array(parse_numbers(scale_match.group(1)), dtype=float)
                if len(scale) == 3:
                    stem = Path(name).stem
                    if stem.startswith("Door"):
                        category = "door"
                        parent = opening_asset.group(1) if opening_asset else None
                    elif stem.startswith("Window"):
                        category = "window"
                        parent = opening_asset.group(1) if opening_asset else None
                    else:
                        category = "wall"
                        parent = None
                    meshes.append(cube_mesh(stem, category, scale, transform, parent))
            elif re.search(r"assets/Parametric/Floors/Floor\d+\.usda$", name):
                usda = archive.read(name).decode("utf-8")
                meshes.append(floor_mesh(Path(name).stem, usda))
    ceiling = derive_ceiling(meshes)
    if ceiling is not None:
        meshes.append(ceiling)
    return meshes


def load_frame_meta(json_path: Path) -> tuple[np.ndarray, np.ndarray]:
    data = json.loads(json_path.read_text())
    intrinsics = np.array(data["intrinsics"], dtype=float).reshape(3, 3)
    camera_pose = np.array(data["cameraPoseARFrame"], dtype=float).reshape(4, 4)
    return intrinsics, camera_pose


def world_to_camera(points: np.ndarray, camera_pose: np.ndarray) -> np.ndarray:
    homogeneous = np.c_[
        np.nan_to_num(points, nan=0.0, posinf=0.0, neginf=0.0), np.ones(len(points))
    ]
    camera_from_world = np.nan_to_num(np.linalg.inv(camera_pose), nan=0.0, posinf=0.0, neginf=0.0)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        camera_points = (camera_from_world @ homogeneous.T).T[:, :3]
    camera_points[~np.isfinite(camera_points)] = np.nan
    return camera_points


def project_camera_points(camera_points: np.ndarray, intrinsics: np.ndarray) -> np.ndarray:
    depth = -camera_points[:, 2]
    pixels = np.empty((len(camera_points), 2), dtype=float)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        pixels[:, 0] = intrinsics[0, 0] * camera_points[:, 0] / depth + intrinsics[0, 2]
        pixels[:, 1] = intrinsics[1, 1] * (-camera_points[:, 1]) / depth + intrinsics[1, 2]
    pixels[~np.isfinite(pixels)] = np.nan
    return pixels


def clip_segment_to_near(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    da = -a[2]
    db = -b[2]
    if da <= NEAR_PLANE_METERS and db <= NEAR_PLANE_METERS:
        return None
    if da > NEAR_PLANE_METERS and db > NEAR_PLANE_METERS:
        return a, b

    # Interpolate in depth space to the near plane.
    t = (NEAR_PLANE_METERS - da) / (db - da)
    clipped = a + t * (b - a)
    if da <= NEAR_PLANE_METERS:
        return clipped, b
    return a, clipped


def visible_line(
    camera_points: np.ndarray,
    intrinsics: np.ndarray,
    edge: tuple[int, int],
    width: int,
    height: int,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    clipped = clip_segment_to_near(camera_points[edge[0]], camera_points[edge[1]])
    if clipped is None:
        return None
    pixels = project_camera_points(np.array(clipped), intrinsics)
    margin = max(width, height) * 2
    if (
        np.all(pixels[:, 0] < -margin)
        or np.all(pixels[:, 0] > width + margin)
        or np.all(pixels[:, 1] < -margin)
        or np.all(pixels[:, 1] > height + margin)
    ):
        return None
    return tuple(pixels[0]), tuple(pixels[1])


def draw_face(
    overlay: Image.Image,
    camera_points: np.ndarray,
    intrinsics: np.ndarray,
    face: list[int],
    color: tuple[int, int, int, int],
) -> None:
    face_points = camera_points[face]
    if np.any(-face_points[:, 2] <= NEAR_PLANE_METERS):
        return
    pixels = project_camera_points(face_points, intrinsics)
    polygon = [tuple(p) for p in pixels]
    ImageDraw.Draw(overlay, "RGBA").polygon(polygon, fill=color)


def draw_dotted_line(
    draw: ImageDraw.ImageDraw,
    start: tuple[float, float],
    end: tuple[float, float],
    fill: tuple[int, int, int, int],
    width: int,
    dash: float = 18.0,
    gap: float = 12.0,
) -> None:
    x0, y0 = start
    x1, y1 = end
    length = math.hypot(x1 - x0, y1 - y0)
    if length < 1:
        return
    dx = (x1 - x0) / length
    dy = (y1 - y0) / length
    distance = 0.0
    while distance < length:
        segment_end = min(distance + dash, length)
        draw.line(
            (
                x0 + dx * distance,
                y0 + dy * distance,
                x0 + dx * segment_end,
                y0 + dy * segment_end,
            ),
            fill=fill,
            width=width,
        )
        distance += dash + gap


def draw_dotted_polygon(
    draw: ImageDraw.ImageDraw,
    points: Sequence[tuple[float, float]],
    fill: tuple[int, int, int, int],
    width: int,
) -> None:
    if len(points) < 2:
        return
    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        draw_dotted_line(draw, start, end, fill, width)


def draw_label(
    draw: ImageDraw.ImageDraw,
    text: str,
    center: tuple[float, float],
    fill: tuple[int, int, int, int],
    bounds: tuple[int, int],
    font_size: int,
) -> None:
    try:
        font = _shared_font(font_size)
    except OSError:
        font = ImageFont.load_default()
    x, y = center
    box = draw.textbbox((x, y), text, font=font, anchor="mm")
    pad = 9
    left, top, right, bottom = box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad
    width, height = bounds
    dx = max(0, -left) + min(0, width - right)
    dy = max(0, -top) + min(0, height - bottom)
    if dx or dy:
        x += dx
        y += dy
        box = draw.textbbox((x, y), text, font=font, anchor="mm")
        left, top, right, bottom = box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad
    draw.rounded_rectangle(
        (left, top, right, bottom),
        radius=5,
        fill=(0, 0, 0, 150),
    )
    draw.text((x, y), text, font=font, anchor="mm", fill=fill)


def draw_stats_panel(
    image: Image.Image,
    walls: Sequence[str],
    floors: Sequence[str],
    ceilings: Sequence[str] = (),
) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    try:
        title_font = _shared_font(30)
        text_font = _shared_font(24)
    except OSError:
        title_font = ImageFont.load_default()
        text_font = ImageFont.load_default()

    lines = [
        f"Walls ({len(walls)}): {', '.join(walls) if walls else 'none'}",
        f"Floors ({len(floors)}): {', '.join(floors) if floors else 'none'}",
        f"Ceilings ({len(ceilings)}): {', '.join(ceilings) if ceilings else 'none'}",
    ]
    title = "Visible RoomPlan Elements"
    padding = 16
    gap = 8
    text_boxes = [draw.textbbox((0, 0), title, font=title_font)]
    text_boxes.extend(draw.textbbox((0, 0), line, font=text_font) for line in lines)
    panel_width = min(
        image.width - 32,
        max(box[2] - box[0] for box in text_boxes) + padding * 2,
    )
    panel_height = padding * 2 + (text_boxes[0][3] - text_boxes[0][1]) + gap
    panel_height += sum(box[3] - box[1] for box in text_boxes[1:]) + gap * (len(lines) - 1)
    x0, y0 = 16, 16
    draw.rounded_rectangle(
        (x0, y0, x0 + panel_width, y0 + panel_height),
        radius=8,
        fill=(0, 0, 0, 170),
        outline=(255, 255, 255, 80),
        width=1,
    )
    y = y0 + padding
    draw.text((x0 + padding, y), title, font=title_font, fill=(255, 255, 255, 245))
    y += text_boxes[0][3] - text_boxes[0][1] + gap
    for line in lines:
        draw.text((x0 + padding, y), line, font=text_font, fill=(235, 245, 250, 240))
        box = draw.textbbox((0, 0), line, font=text_font)
        y += box[3] - box[1] + gap


def clamp_point(
    point: tuple[float, float], width: int, height: int, margin: int = 24
) -> tuple[float, float]:
    x, y = point
    return (
        min(max(x, margin), max(margin, width - margin)),
        min(max(y, margin), max(margin, height - margin)),
    )


def rotate_point_clockwise(point: tuple[float, float], original_height: int) -> tuple[float, float]:
    x, y = point
    return original_height - y, x


def load_depth_conf(image_path: Path):
    """ARKit depth (uint16 mm) + confidence maps that sit beside frame_<id>.jpg, if present.
    Returns (depth_map, conf_map) or (None, None) — the latter disables occlusion (so
    single-room / depth-less scans behave exactly as before)."""
    stem = image_path.stem.replace("frame_", "")
    dp = image_path.with_name(f"depth_{stem}.png")
    cp = image_path.with_name(f"conf_{stem}.png")
    if not dp.exists():
        return None, None
    try:
        depth = np.asarray(Image.open(dp))
        conf = np.asarray(Image.open(cp)) if cp.exists() else None
        return depth, conf
    except Exception:
        return None, None


def sample_wall_surface(
    points: np.ndarray, faces: Sequence[Sequence[int]], n: int = 12
) -> np.ndarray:
    """A regular n×n grid of world points across a wall's dominant (largest-area) face —
    enough samples to tell whether the wall is the front-most surface or hidden behind
    another room's wall."""
    if not faces:
        return points
    areas = [face_area_3d(points[f]) for f in faces]
    c = points[faces[int(np.argmax(areas))]]
    if len(c) < 4:
        return points
    u = np.linspace(0.0, 1.0, n)[:, None]
    v = np.linspace(0.0, 1.0, n)[None, :]
    top = c[0][None, :] * (1 - u) + c[1][None, :] * u  # (n,3) along one edge
    bot = c[3][None, :] * (1 - u) + c[2][None, :] * u  # (n,3) along the opposite edge
    grid = top[:, None, :] * (1 - v[..., None]) + bot[:, None, :] * v[..., None]
    return grid.reshape(-1, 3)


def wall_visible_fraction(
    world_points: np.ndarray,
    intrinsics: np.ndarray,
    camera_pose: np.ndarray,
    width: int,
    height: int,
    depth_map,
    conf_map,
    tol: float = OCCLUSION_TOL_M,
) -> float:
    """Fraction of a wall's in-frame, depth-known samples that are at/in-front-of the ARKit
    sensor depth (i.e. actually visible, not behind a nearer surface). Returns 1.0 when no
    depth is available (no occlusion judgement) so behaviour is unchanged without depth."""
    if depth_map is None:
        return 1.0
    cam = world_to_camera(world_points, camera_pose)
    d = -cam[:, 2]
    px = project_camera_points(cam, intrinsics)
    finite = np.all(np.isfinite(px), axis=1)
    inb = (
        finite
        & (d > NEAR_PLANE_METERS)
        & (px[:, 0] >= 0)
        & (px[:, 0] < width)
        & (px[:, 1] >= 0)
        & (px[:, 1] < height)
    )
    if not np.any(inb):
        return 1.0  # not in this frame — don't judge
    dh, dw = depth_map.shape[:2]
    xi = np.clip((px[:, 0] * dw / width).astype(int), 0, dw - 1)
    yi = np.clip((px[:, 1] * dh / height).astype(int), 0, dh - 1)
    sensor = depth_map[yi, xi].astype(float) / 1000.0  # uint16 mm -> m
    valid = inb & (sensor > 0)
    if conf_map is not None:
        valid &= conf_map.reshape(conf_map.shape[0], conf_map.shape[1])[yi, xi] > 0
    nb = int(np.count_nonzero(valid))
    if nb == 0:
        return 1.0  # no depth info here — don't occlude
    visible = valid & (d <= sensor + tol)
    return float(np.count_nonzero(visible)) / float(nb)


def mesh_coverage_percent(
    camera_points: np.ndarray,
    intrinsics: np.ndarray,
    width: int,
    height: int,
) -> float:
    """Percent of the image area covered by this mesh's projected footprint.

    Uses the convex hull of the near-visible projected points, clipped to the
    image rectangle, so the value is independent of the draw style (filled vs
    outline) and of how the mesh is split into faces. Rotation is area-preserving,
    so this is computed in the original (pre-rotation) image frame.
    """
    visible_mask = -camera_points[:, 2] > NEAR_PLANE_METERS
    if not np.any(visible_mask):
        return 0.0
    pixels = project_camera_points(camera_points[visible_mask], intrinsics)
    pixels = pixels[np.all(np.isfinite(pixels), axis=1)]
    if len(pixels) < 3:
        return 0.0
    hull = convex_hull(pixels)
    if len(hull) < 3:
        return 0.0
    clipped = clip_polygon_to_image(hull, width, height)
    if len(clipped) < 3:
        return 0.0
    return round(polygon_area(clipped) / (width * height) * 100.0, 1)


def render_overlay(
    image_path: Path,
    json_path: Path,
    output_path: Path,
    meshes: list[Mesh],
    line_width: int,
    draw_labels: bool,
    rotate_clockwise: bool,
    style: str,
    draw_panel: bool,
    outline_only: bool,
    label_font_size: int,
    highlight_openings: bool,
) -> dict:
    image = Image.open(image_path).convert("RGBA")
    width, height = image.size
    intrinsics, camera_pose = load_frame_meta(json_path)
    depth_map, conf_map = load_depth_conf(image_path)  # for multi-room wall occlusion

    fill_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    line_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    line_draw = ImageDraw.Draw(line_layer, "RGBA")

    label_candidates: list[tuple[str, tuple[float, float], tuple[int, int, int, int]]] = []
    visible_meshes: list[dict] = []

    for mesh in meshes:
        camera_points = world_to_camera(mesh.points, camera_pose)
        # multi-room occlusion: drop a wall hidden behind a nearer surface (e.g. another
        # room's wall), and scale a partially-occluded wall's coverage by its visible part.
        wall_visible = 1.0
        if mesh.category == "wall" and depth_map is not None:
            wall_visible = wall_visible_fraction(
                sample_wall_surface(mesh.points, mesh.faces),
                intrinsics,
                camera_pose,
                width,
                height,
                depth_map,
                conf_map,
            )
            if wall_visible < WALL_MIN_VISIBLE:
                continue
        if style == "colored":
            red, green, blue = semantic_color(mesh)
            face_color = (red, green, blue, 78 if mesh.category == "wall" else 64)
            line_color = (red, green, blue, 245)
        elif mesh.category == "floor":
            face_color = (0, 190, 255, 62)
            line_color = (0, 220, 255, 235)
        elif mesh.category == "ceiling":
            face_color = (200, 140, 240, 55)
            line_color = (210, 160, 245, 235)
        elif mesh.category == "door":
            face_color = (90, 255, 150, 60)
            line_color = (120, 255, 170, 240)
        elif mesh.category == "window":
            face_color = (80, 150, 255, 60)
            line_color = (120, 180, 255, 240)
        else:
            face_color = (255, 95, 45, 50)
            line_color = (255, 95, 45, 240)

        faces_by_depth: list[tuple[float, list[int]]] = []
        for face in mesh.faces:
            face_points = camera_points[face]
            if np.all(-face_points[:, 2] > NEAR_PLANE_METERS):
                faces_by_depth.append((float(np.mean(-face_points[:, 2])), face))

        visible_edges = 0
        visible_midpoints: list[tuple[float, float]] = []
        label_center: tuple[float, float] | None = None
        drawn_on_image = False
        for edge in mesh.edges:
            line = visible_line(camera_points, intrinsics, edge, width, height)
            if line is not None:
                visible_edges += 1
                visible_midpoints.append(
                    ((line[0][0] + line[1][0]) / 2, (line[0][1] + line[1][1]) / 2)
                )

        visible_faces = len(faces_by_depth)
        if (
            highlight_openings
            and mesh.category in {"door", "window"}
            and style in {"clean", "colored"}
        ):
            visible_point_mask = -camera_points[:, 2] > NEAR_PLANE_METERS
            if np.any(visible_point_mask):
                pixels = project_camera_points(camera_points[visible_point_mask], intrinsics)
                pixels = pixels[np.all(np.isfinite(pixels), axis=1)]
                hull = convex_hull(pixels)
            else:
                hull = []
            if len(hull) >= 3:
                clipped_hull = clip_polygon_to_image(hull, width, height)
                if (
                    len(clipped_hull) >= 3
                    and polygon_area(clipped_hull) >= width * height * 0.00025
                ):
                    shadow_color = (0, 0, 0, 185)
                    opening_color = (238, 238, 232, 245)
                    draw_dotted_polygon(line_draw, clipped_hull, shadow_color, line_width + 3)
                    draw_dotted_polygon(line_draw, clipped_hull, opening_color, max(2, line_width))
                    label_center = clamp_point(polygon_centroid(clipped_hull), width, height)
                    drawn_on_image = True
            elif len(hull) == 2:
                opening_color = (238, 238, 232, 245)
                draw_dotted_line(line_draw, hull[0], hull[1], (0, 0, 0, 185), line_width + 3)
                draw_dotted_line(line_draw, hull[0], hull[1], opening_color, max(2, line_width))
                label_center = clamp_point(
                    ((hull[0][0] + hull[1][0]) / 2, (hull[0][1] + hull[1][1]) / 2), width, height
                )
                drawn_on_image = True
        elif (
            mesh.category in {"floor", "ceiling"}
            and style in {"clean", "colored"}
            and mesh.outline_points is not None
            and len(mesh.outline_points) >= 3
        ):
            # Ray-cast the floor/ceiling plane so it is detected + labelled even
            # when part of it falls behind the camera (the usual indoor case).
            # Used for both the filled and outline sets.
            drawn_on_image, label_center = draw_floor_ray_outline(
                line_draw,
                intrinsics,
                camera_pose,
                mesh.outline_points,
                width,
                height,
                line_color,
                line_width,
                from_bottom=(mesh.category == "ceiling"),
            )
        elif style in {"clean", "colored"} and mesh.category == "wall":
            visible_wall_faces: list[
                tuple[float, list[tuple[float, float]], tuple[float, float], bool]
            ] = []
            world_face_areas = [face_area_3d(mesh.points[face]) for face in mesh.faces]
            max_world_face_area = max(world_face_areas) if world_face_areas else 0.0
            for face_index, face in enumerate(mesh.faces):
                if (
                    max_world_face_area <= 0
                    or world_face_areas[face_index] < max_world_face_area * 0.45
                ):
                    continue
                face_camera_points = camera_points[face]
                face_camera_points = clip_camera_polygon_to_near(face_camera_points)
                if len(face_camera_points) < 3:
                    continue
                pixels = project_camera_points(face_camera_points, intrinsics)
                if not np.all(np.isfinite(pixels)):
                    continue
                polygon = [tuple(point) for point in pixels]
                clipped_polygon = clip_polygon_to_image(polygon, width, height)
                area = polygon_area(clipped_polygon)
                draw_min_area = width * height * 0.00055
                if len(clipped_polygon) < 3 or area < draw_min_area:
                    continue
                center = polygon_centroid(clipped_polygon)
                label_min_area = width * height * 0.002
                label_ok = (
                    area >= label_min_area
                    and 70 <= center[0] <= width - 70
                    and 70 <= center[1] <= height - 70
                )
                visible_wall_faces.append((area, clipped_polygon, center, label_ok))

            for _, clipped_polygon, _, _ in sorted(visible_wall_faces, reverse=True):
                if not outline_only:
                    ImageDraw.Draw(fill_layer, "RGBA").polygon(clipped_polygon, fill=face_color)
                line_draw.line(
                    clipped_polygon + [clipped_polygon[0]], fill=line_color, width=line_width
                )
                drawn_on_image = True

            if visible_wall_faces:
                label_faces = [face for face in visible_wall_faces if face[3]]
                if label_faces:
                    _, _, center, _ = max(label_faces, key=lambda item: item[0])
                    label_center = clamp_point(center, width, height)
        elif style in {"clean", "colored"}:
            if (
                mesh.category == "floor"
                and mesh.outline_points is not None
                and len(mesh.outline_points) >= 3
            ):
                outline_camera_points = world_to_camera(mesh.outline_points, camera_pose)
                depth = -outline_camera_points[:, 2]
                if np.all(depth > NEAR_PLANE_METERS):
                    pixels = project_camera_points(outline_camera_points, intrinsics)
                    finite = np.all(np.isfinite(pixels), axis=1)
                    hull = [tuple(point) for point in pixels[finite]]
                else:
                    hull = []
            else:
                visible_point_mask = -camera_points[:, 2] > NEAR_PLANE_METERS
                if np.any(visible_point_mask):
                    pixels = project_camera_points(camera_points[visible_point_mask], intrinsics)
                    pixels = pixels[np.all(np.isfinite(pixels), axis=1)]
                    hull = convex_hull(pixels)
                else:
                    hull = []
            if hull:
                if len(hull) >= 3:
                    clipped_hull = clip_polygon_to_image(hull, width, height)
                    if mesh.category == "wall":
                        min_area = width * height * 0.004
                    elif mesh.category == "floor":
                        min_area = width * height * 0.003
                    else:
                        min_area = width * height * 0.001
                    if len(clipped_hull) >= 3 and polygon_area(clipped_hull) >= min_area:
                        candidate_center = polygon_centroid(clipped_hull)
                        border_margin = 90 if mesh.category == "wall" else 30
                        if not (
                            border_margin <= candidate_center[0] <= width - border_margin
                            and border_margin <= candidate_center[1] <= height - border_margin
                        ):
                            continue
                        if not outline_only:
                            ImageDraw.Draw(fill_layer, "RGBA").polygon(
                                clipped_hull, fill=face_color
                            )
                        line_draw.line(
                            clipped_hull + [clipped_hull[0]], fill=line_color, width=line_width
                        )
                        label_center = clamp_point(candidate_center, width, height)
                        drawn_on_image = True
                elif len(hull) == 2:
                    clipped_line = (
                        visible_line(camera_points, intrinsics, mesh.edges[0], width, height)
                        if mesh.edges
                        else None
                    )
                    if clipped_line is not None:
                        x0, y0 = clipped_line[0]
                        x1, y1 = clipped_line[1]
                        if math.hypot(x1 - x0, y1 - y0) >= 20:
                            line_draw.line(clipped_line, fill=line_color, width=line_width)
                            label_center = clamp_point(
                                ((x0 + x1) / 2, (y0 + y1) / 2), width, height
                            )
                            drawn_on_image = True
        else:
            for _, face in sorted(faces_by_depth, reverse=True):
                draw_face(fill_layer, camera_points, intrinsics, face, face_color)
            for edge in mesh.edges:
                line = visible_line(camera_points, intrinsics, edge, width, height)
                if line is not None:
                    line_draw.line(line, fill=line_color, width=line_width)
                    drawn_on_image = True

        if drawn_on_image:
            coverage_pct = mesh_coverage_percent(camera_points, intrinsics, width, height)
            coverage_pct = round(coverage_pct * wall_visible, 1)  # discount occluded part
            visible_meshes.append(
                {
                    "name": mesh.name,
                    "category": mesh.category,
                    "parent": mesh.parent,
                    "visible_edges": visible_edges,
                    "visible_faces": visible_faces,
                    "image_coverage_pct": coverage_pct,
                    "visible_fraction": round(wall_visible, 3),
                }
            )

        should_label = (
            draw_labels
            and drawn_on_image
            and not (style == "colored" and mesh.category in {"door", "window"})
        )
        if should_label:
            if label_center is not None:
                label_candidates.append((mesh_label(mesh), label_center, line_color))
            elif visible_midpoints:
                label_point = tuple(np.median(np.array(visible_midpoints), axis=0))
                label_candidates.append(
                    (mesh_label(mesh), clamp_point(label_point, width, height), line_color)
                )
            else:
                center_camera = world_to_camera(
                    np.mean(mesh.points, axis=0, keepdims=True), camera_pose
                )
                if -center_camera[0, 2] > NEAR_PLANE_METERS:
                    center_pixel = project_camera_points(center_camera, intrinsics)[0]
                    if (
                        -50 <= center_pixel[0] <= width + 50
                        and -50 <= center_pixel[1] <= height + 50
                    ):
                        label_candidates.append(
                            (
                                mesh_label(mesh),
                                clamp_point(tuple(center_pixel), width, height),
                                line_color,
                            )
                        )

    output = Image.alpha_composite(image, fill_layer)
    output = Image.alpha_composite(output, line_layer)

    if rotate_clockwise:
        output = output.transpose(Image.Transpose.ROTATE_270)
        rotated_labels = []
        for name, center, color in label_candidates:
            rotated_center = rotate_point_clockwise(center, height)
            if (
                90 <= rotated_center[0] <= output.width - 90
                and 90 <= rotated_center[1] <= output.height - 90
            ):
                rotated_labels.append(
                    (name, clamp_point(rotated_center, output.width, output.height), color)
                )
        label_candidates = rotated_labels

    if draw_labels:
        draw = ImageDraw.Draw(output, "RGBA")
        for name, center, color in label_candidates:
            draw_label(draw, name, center, color, output.size, label_font_size)

    wall_names = sorted(item["name"] for item in visible_meshes if item["category"] == "wall")
    floor_names = sorted(item["name"] for item in visible_meshes if item["category"] == "floor")
    door_names = sorted(
        f"{item['name']}@{item['parent']}" if item.get("parent") else item["name"]
        for item in visible_meshes
        if item["category"] == "door"
    )
    window_names = sorted(
        f"{item['name']}@{item['parent']}" if item.get("parent") else item["name"]
        for item in visible_meshes
        if item["category"] == "window"
    )
    ceiling_names = sorted(item["name"] for item in visible_meshes if item["category"] == "ceiling")

    def _coverage(category: str) -> dict:
        return {
            item["name"]: item.get("image_coverage_pct", 0.0)
            for item in sorted(visible_meshes, key=lambda item: item["name"])
            if item["category"] == category
        }

    wall_coverage_pct = _coverage("wall")
    floor_coverage_pct = _coverage("floor")
    ceiling_coverage_pct = _coverage("ceiling")
    if draw_panel:
        draw_stats_panel(output, wall_names, floor_names, ceiling_names)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.convert("RGB").save(output_path, quality=94)

    return {
        "source_image": str(image_path),
        "source_metadata": str(json_path),
        "output_image": str(output_path),
        "output_size": [output.width, output.height],
        "rotated_clockwise": rotate_clockwise,
        "visible_walls": wall_names,
        "wall_coverage_pct": wall_coverage_pct,
        "visible_floors": floor_names,
        "floor_coverage_pct": floor_coverage_pct,
        "visible_ceilings": ceiling_names,
        "ceiling_coverage_pct": ceiling_coverage_pct,
        "visible_doors": door_names,
        "visible_windows": window_names,
        "visible_wall_count": len(wall_names),
        "visible_floor_count": len(floor_names),
        "visible_ceiling_count": len(ceiling_names),
        "visible_door_count": len(door_names),
        "visible_window_count": len(window_names),
        "label_font_size": label_font_size,
        "highlight_openings": highlight_openings,
        "visible_elements": sorted(
            visible_meshes, key=lambda item: (item["category"], item["name"])
        ),
    }


def find_frame_pairs(scene_dir: Path) -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    for json_path in sorted(scene_dir.glob("frame_*.json")):
        image_path = json_path.with_suffix(".jpg")
        if image_path.exists():
            pairs.append((image_path, json_path))
            continue
        nested_image = scene_dir / "images" / image_path.name
        if nested_image.exists():
            pairs.append((nested_image, json_path))
    return pairs


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Project USDZ wall/floor geometry onto scene frame images.",
    )
    parser.add_argument(
        "scene_folder", type=Path, help="Folder containing room.usdz and frame_*.json files."
    )
    parser.add_argument(
        "--usdz",
        type=Path,
        default=None,
        help="Optional USDZ path. Defaults to <scene_folder>/room.usdz.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output folder. Defaults to <scene_folder>/overlays.",
    )
    parser.add_argument("--line-width", type=int, default=5, help="Overlay line width in pixels.")
    parser.add_argument(
        "--labels", action="store_true", help="Draw mesh labels, e.g. Wall0 and Floor0."
    )
    parser.add_argument(
        "--no-rotate-clockwise",
        action="store_true",
        help="Do not rotate the output. By default each output image is rotated "
        "90 degrees clockwise after projection so portrait-held captures look "
        "upright.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="JSON manifest path. Defaults to <output>/overlay_manifest.json.",
    )
    parser.add_argument(
        "--style",
        choices=["clean", "colored", "wireframe"],
        default="clean",
        help="Overlay style. colored gives each wall/opening a stable color and centered label.",
    )
    parser.add_argument(
        "--no-panel",
        action="store_true",
        help="Do not draw the visible wall/floor summary panel.",
    )
    parser.add_argument(
        "--outline-only",
        action="store_true",
        help="Draw colored outlines and labels without translucent fill/shadow.",
    )
    parser.add_argument(
        "--label-font-size", type=int, default=48, help="Label font size in pixels."
    )
    parser.add_argument(
        "--no-opening-highlights",
        action="store_true",
        help="Do not draw dotted gray outlines around detected doors/windows.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Process only the first N frames.")
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    scene_dir = args.scene_folder.expanduser().resolve()
    usdz_path = (args.usdz or scene_dir / "room.usdz").expanduser().resolve()
    output_dir = (args.output or scene_dir / "overlays").expanduser().resolve()
    manifest_path = (args.manifest or output_dir / "overlay_manifest.json").expanduser().resolve()

    if not scene_dir.is_dir():
        print(f"Scene folder does not exist: {scene_dir}", file=sys.stderr)
        return 2
    if not usdz_path.is_file():
        print(f"USDZ file does not exist: {usdz_path}", file=sys.stderr)
        return 2

    meshes = load_meshes(usdz_path)
    if not meshes:
        print(f"No wall/floor meshes found in: {usdz_path}", file=sys.stderr)
        return 2

    frame_pairs = find_frame_pairs(scene_dir)
    if args.limit is not None:
        frame_pairs = frame_pairs[: args.limit]
    if not frame_pairs:
        print(f"No frame_*.json + .jpg pairs found in: {scene_dir}", file=sys.stderr)
        return 2

    print(f"Loaded {len(meshes)} meshes from {usdz_path.name}")
    print(f"Writing {len(frame_pairs)} overlay images to {output_dir}")

    manifest = {
        "scene_folder": str(scene_dir),
        "usdz": str(usdz_path),
        "output_folder": str(output_dir),
        "mesh_totals": {
            "walls": sorted(mesh.name for mesh in meshes if mesh.category == "wall"),
            "floors": sorted(mesh.name for mesh in meshes if mesh.category == "floor"),
            "ceilings": sorted(mesh.name for mesh in meshes if mesh.category == "ceiling"),
            "doors": sorted(mesh_label(mesh) for mesh in meshes if mesh.category == "door"),
            "windows": sorted(mesh_label(mesh) for mesh in meshes if mesh.category == "window"),
            "wall_count": sum(1 for mesh in meshes if mesh.category == "wall"),
            "floor_count": sum(1 for mesh in meshes if mesh.category == "floor"),
            "ceiling_count": sum(1 for mesh in meshes if mesh.category == "ceiling"),
            "door_count": sum(1 for mesh in meshes if mesh.category == "door"),
            "window_count": sum(1 for mesh in meshes if mesh.category == "window"),
        },
        "settings": {
            "line_width": args.line_width,
            "labels": args.labels,
            "rotate_clockwise": not args.no_rotate_clockwise,
            "style": args.style,
            "panel": not args.no_panel,
            "outline_only": args.outline_only,
            "label_font_size": args.label_font_size,
            "highlight_openings": not args.no_opening_highlights,
        },
        "images": [],
    }

    for index, (image_path, json_path) in enumerate(frame_pairs, start=1):
        output_path = output_dir / f"{image_path.stem}_overlay.jpg"
        image_manifest = render_overlay(
            image_path,
            json_path,
            output_path,
            meshes,
            args.line_width,
            args.labels,
            not args.no_rotate_clockwise,
            args.style,
            not args.no_panel,
            args.outline_only,
            args.label_font_size,
            not args.no_opening_highlights,
        )
        manifest["images"].append(image_manifest)
        if index == 1 or index == len(frame_pairs) or index % 25 == 0:
            print(f"[{index}/{len(frame_pairs)}] {output_path.name}")

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"Wrote manifest: {manifest_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
