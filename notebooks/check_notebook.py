"""Validate catalog try-on notebooks before Colab users open them.

Stdlib only. Run from repo root:

  python notebooks/check_notebook.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
NOTEBOOKS = (
    HERE / "fashn_vton_colab.ipynb",
)

MUST_CONTAIN = (
    "TryOnPipeline",
    "fashn-AI/fashn-vton-1.5",
    "T4",
    "one-pieces",
    "flat-lay",
    "colab_worker.py",
)
MUST_NOT_CONTAIN = (
    "FASHN_API_KEY",
    "FASHN_KEY",
    "BEGIN PRIVATE KEY",
    "sk-proj-",
    "hf_write_",
)


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def check(path: Path) -> None:
    if not path.is_file():
        fail(f"missing {path.relative_to(ROOT)}")
    try:
        nb = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        fail(f"{path.name} is not valid JSON: {e}")
    if nb.get("nbformat") != 4:
        fail(f"{path.name} nbformat must be 4")
    cells = nb.get("cells")
    if not isinstance(cells, list) or not cells:
        fail(f"{path.name} has no cells")
    src = "\n".join("".join(c.get("source") or []) for c in cells)
    for needle in MUST_CONTAIN:
        if needle not in src:
            fail(f"{path.name} missing required text: {needle!r}")
    for needle in MUST_NOT_CONTAIN:
        if needle in src:
            fail(f"{path.name} must not contain {needle!r}")
    print(f"ok  {path.relative_to(ROOT)}  cells={len(cells)}")


def main() -> int:
    for p in NOTEBOOKS:
        check(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
