"""Sketchfab Download-API client.

Auth is a personal API token (Settings → Password & API on sketchfab.com). Read from the
`token=` arg or the `SKETCHFAB_API_TOKEN` env var; the header is `Authorization: Token <tok>`.

The download endpoint (`GET /v3/models/{uid}/download`) returns short-lived signed URLs for
several formats — typically `glb`, `gltf`, `usdz`, `source`. Each is a ZIP archive (occasionally
a bare file). We fetch the best available mesh format, extract it, locate the mesh, and — when
`pack_glb` is set and we didn't already get a `.glb` — pack glTF → GLB with trimesh so the rest
of the pipeline gets a single self-contained `.glb`.

Downloads are md5-cached under ~/.litereality_sketchfab_cache (keyed by uid+format) so repeated
pulls of the same asset don't re-hit the API.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, Optional

API = "https://api.sketchfab.com/v3"
_MESH_EXT = (".glb", ".gltf")
_CACHE = Path(os.path.expanduser("~")) / ".litereality_sketchfab_cache"


class SketchfabError(RuntimeError):
    """Any Sketchfab API / download failure (auth, not-downloadable, network, extract)."""


def parse_uid(url_or_uid: str) -> str:
    """Accept a bare 32-hex uid OR any Sketchfab model URL and return the uid.

    Handles `https://sketchfab.com/3d-models/some-name-<uid>`, `.../models/<uid>`, trailing
    `/embed`, and query strings. A bare uid passes straight through.
    """
    s = (url_or_uid or "").strip()
    if re.fullmatch(r"[0-9a-fA-F]{32}", s):
        return s.lower()
    # the uid is the last 32-hex token anywhere in the URL (usually the slug suffix after '-')
    hexes = re.findall(r"[0-9a-fA-F]{32}", s)
    if hexes:
        return hexes[-1].lower()
    raise SketchfabError(f"could not find a 32-hex model uid in {url_or_uid!r}")


class SketchfabClient:
    def __init__(self, token: Optional[str] = None, timeout: int = 60) -> None:
        self.token = (token or os.environ.get("SKETCHFAB_API_TOKEN", "")).strip()
        if not self.token:
            raise SketchfabError(
                "no Sketchfab token — set $SKETCHFAB_API_TOKEN (Settings → Password & API) "
                "or pass token=..."
            )
        self.timeout = timeout

    # ---- low-level ---------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Token {self.token}"}

    def _get(self, path: str, **params) -> dict:
        import requests

        url = path if path.startswith("http") else f"{API}{path}"
        r = requests.get(url, headers=self._headers(), params=params or None, timeout=self.timeout)
        if r.status_code == 401:
            raise SketchfabError("401 unauthorized — the Sketchfab token is invalid or expired.")
        if not r.ok:
            raise SketchfabError(f"GET {url} → {r.status_code}: {r.text[:300]}")
        return r.json()

    # ---- public API --------------------------------------------------------
    def whoami(self) -> str:
        return self._get("/me").get("username", "?")

    def search(
        self,
        query: str,
        count: int = 12,
        downloadable: bool = True,
        categories: Optional[str] = None,
        min_face_count: Optional[int] = None,
        max_face_count: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Search models. Returns compact dicts (uid, name, author, license, faces, url, thumb).

        `downloadable=True` is the default because a non-downloadable hit is useless here.
        """
        params: dict[str, Any] = {"type": "models", "q": query, "count": count}
        if downloadable:
            params["downloadable"] = "true"
        if categories:
            params["categories"] = categories
        if min_face_count:
            params["min_face_count"] = min_face_count
        if max_face_count:
            params["max_face_count"] = max_face_count
        results = self._get("/search", **params).get("results", [])
        return [self._compact(m) for m in results]

    def info(self, uid_or_url: str) -> dict[str, Any]:
        uid = parse_uid(uid_or_url)
        return self._compact(self._get(f"/models/{uid}"))

    def download(
        self,
        uid_or_url: str,
        out_dir: str | Path,
        name: Optional[str] = None,
        prefer: str = "glb",
        pack_glb: bool = True,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """Download a model to `out_dir/<name>.glb` (+ its attribution JSON).

        `prefer` picks the archive format ('glb' if offered, else 'gltf'). When the model isn't
        downloadable, or offers no mesh format, a SketchfabError is raised. Returns a dict with
        `glb` (path), `format`, `attribution`, and `dir`.
        """
        uid = parse_uid(uid_or_url)
        meta = self.info(uid)
        if not meta.get("isDownloadable", True):
            raise SketchfabError(
                f"model {uid} ({meta.get('name')!r}) is not downloadable on Sketchfab."
            )

        links = self._get(f"/models/{uid}/download")
        fmt, link = self._pick_format(links, prefer)
        slug = _slugify(name or meta.get("name") or uid)
        dest_dir = Path(out_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        raw = self._fetch_archive(uid, fmt, link["url"], use_cache=use_cache)
        mesh_path = self._extract_mesh(raw, dest_dir / f"_{slug}_src", fmt)

        # normalise to a single .glb next to the extracted source
        glb_out = dest_dir / f"{slug}.glb"
        if mesh_path.suffix.lower() == ".glb":
            shutil.copyfile(mesh_path, glb_out)
            out_format = "glb"
        elif pack_glb:
            self._pack_gltf_to_glb(mesh_path, glb_out)
            out_format = "glb(packed)"
        else:
            glb_out = mesh_path  # leave as extracted .gltf tree
            out_format = "gltf"

        attribution = self._attribution(meta)
        (dest_dir / f"{slug}.attribution.json").write_text(json.dumps(attribution, indent=2))
        return {
            "uid": uid,
            "name": meta.get("name"),
            "glb": str(glb_out),
            "format": out_format,
            "src_format": fmt,
            "dir": str(dest_dir),
            "attribution": attribution,
        }

    # ---- internals ---------------------------------------------------------
    @staticmethod
    def _compact(m: dict) -> dict[str, Any]:
        lic = m.get("license") or {}
        user = m.get("user") or {}
        thumbs = ((m.get("thumbnails") or {}).get("images") or [])
        thumb = max(thumbs, key=lambda t: t.get("width", 0)).get("url") if thumbs else None
        return {
            "uid": m.get("uid"),
            "name": m.get("name"),
            "author": user.get("displayName") or user.get("username"),
            "author_url": user.get("profileUrl"),
            "license": lic.get("label") or lic.get("slug"),
            "license_url": lic.get("url"),
            "faces": m.get("faceCount"),
            "isDownloadable": m.get("isDownloadable"),
            "url": m.get("viewerUrl"),
            "thumb": thumb,
        }

    @staticmethod
    def _pick_format(links: dict, prefer: str) -> tuple[str, dict]:
        order = [prefer] + [f for f in ("glb", "gltf") if f != prefer]
        for fmt in order:
            link = links.get(fmt)
            if link and link.get("url"):
                return fmt, link
        offered = ", ".join(k for k, v in links.items() if isinstance(v, dict) and v.get("url"))
        raise SketchfabError(f"no glb/gltf download offered (only: {offered or 'none'}).")

    def _fetch_archive(self, uid: str, fmt: str, url: str, use_cache: bool) -> bytes:
        import requests

        cache_file = _CACHE / f"{uid}.{fmt}.bin"
        if use_cache and cache_file.is_file():
            return cache_file.read_bytes()
        r = requests.get(url, timeout=max(self.timeout, 120))
        if not r.ok:
            raise SketchfabError(f"archive download failed → {r.status_code}")
        data = r.content
        if use_cache:
            _CACHE.mkdir(parents=True, exist_ok=True)
            cache_file.write_bytes(data)
        return data

    @staticmethod
    def _extract_mesh(raw: bytes, into: Path, fmt: str) -> Path:
        """Sketchfab archives are ZIPs; extract and return the mesh entry. Bare files pass through."""
        if into.exists():
            shutil.rmtree(into)
        into.mkdir(parents=True, exist_ok=True)
        if zipfile.is_zipfile(io.BytesIO(raw)):
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                z.extractall(into)
            meshes = [p for p in into.rglob("*") if p.suffix.lower() in _MESH_EXT]
            if not meshes:
                raise SketchfabError(f"archive had no {'/'.join(_MESH_EXT)} inside {into}")
            # prefer .glb, then the shallowest .gltf (top-level scene.gltf)
            meshes.sort(key=lambda p: (p.suffix.lower() != ".glb", len(p.parts)))
            return meshes[0]
        # not a zip — a bare glb/gltf
        bare = into / f"model.{fmt if fmt in ('glb', 'gltf') else 'glb'}"
        bare.write_bytes(raw)
        return bare

    @staticmethod
    def _pack_gltf_to_glb(gltf_path: Path, glb_out: Path) -> None:
        try:
            import trimesh
        except ImportError as e:  # noqa: BLE001
            raise SketchfabError(
                "glTF→GLB packing needs trimesh (`uv add trimesh`), or pass pack_glb=False."
            ) from e
        scene = trimesh.load(str(gltf_path), process=False)
        scene.export(str(glb_out))

    @staticmethod
    def _attribution(meta: dict) -> dict[str, Any]:
        lic = meta.get("license") or "?"
        author = meta.get("author") or "?"
        text = (
            f"\"{meta.get('name')}\" by {author} ({meta.get('author_url') or 'sketchfab'}) "
            f"licensed under {lic}. Source: {meta.get('url')}"
        )
        return {
            "name": meta.get("name"),
            "author": author,
            "author_url": meta.get("author_url"),
            "license": lic,
            "license_url": meta.get("license_url"),
            "source": meta.get("url"),
            "credit": text,
        }


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_") or "sketchfab_model"
