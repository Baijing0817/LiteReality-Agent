"""Editable-region helpers for scaffolded files (ported from articraft).

A tool may want to let the agent edit only the *user* section of a file, leaving a deterministic
header/footer frozen. That section is delimited by the two markers below. If they're absent (LR's
`Room.py` has none today), the WHOLE file is treated as editable — so this is a no-op until/unless
we add markers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

USER_CODE_START_MARKER = "# >>> USER_CODE_START"
USER_CODE_END_MARKER = "# >>> USER_CODE_END"


@dataclass(frozen=True)
class CodeRegion:
    has_region: bool
    content_start: int = 0
    content_end: int = 0
    start_line: int = 1
    end_line: int = 1


def find_code_region(full_code: str) -> CodeRegion:
    """Locate the editable region; if markers are missing/malformed, the whole file is editable."""
    start_idx = full_code.find(USER_CODE_START_MARKER)
    if start_idx < 0:
        return CodeRegion(has_region=False, content_start=0, content_end=len(full_code))
    start_line_end = full_code.find("\n", start_idx)
    if start_line_end < 0:
        return CodeRegion(has_region=False, content_start=0, content_end=len(full_code))
    content_start = start_line_end + 1
    end_idx = full_code.find(USER_CODE_END_MARKER, content_start)
    if end_idx < 0:
        return CodeRegion(has_region=False, content_start=0, content_end=len(full_code))
    start_line = full_code.count("\n", 0, content_start) + 1
    end_line = full_code.count("\n", 0, end_idx) + 1
    return CodeRegion(True, content_start, end_idx, start_line, end_line)


def extract_editable_code(full_code: str) -> str:
    r = find_code_region(full_code)
    return full_code[r.content_start : r.content_end]


def replace_editable_code(full_code: str, new_code: str) -> str:
    r = find_code_region(full_code)
    if r.has_region:
        normalized = new_code if (not new_code or new_code.endswith("\n")) else new_code + "\n"
        return full_code[: r.content_start] + normalized + full_code[r.content_end :]
    return new_code


def map_syntax_error_line_to_editable(full_code: str, line_no: Optional[int]) -> Optional[int]:
    """Full-file syntax-error line → editable-region line (None if outside the region)."""
    if line_no is None:
        return None
    r = find_code_region(full_code)
    if not r.has_region:
        return line_no
    if line_no < r.start_line or line_no >= r.end_line:
        return None
    return line_no - r.start_line + 1
