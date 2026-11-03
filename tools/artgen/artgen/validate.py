"""CI check: generated art only uses palette colours, and the generator is deterministic.

Run from tools/artgen: `uv run python -m artgen.validate`
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

from PIL import Image

from artgen.palette import all_colors

ROOT = Path(__file__).resolve().parents[3]
GEN = ROOT / "frontend" / "public" / "assets" / "gen"
SKIP = {"title.png"}  # composed scene with blended shadows


def digest() -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(GEN.rglob("*.png"))}


def main() -> None:
    allowed = all_colors()
    bad: list[str] = []
    for p in sorted(GEN.rglob("*.png")):
        if p.name in SKIP:
            continue
        img = Image.open(p).convert("RGBA")
        off = {px[:3] for px in img.get_flattened_data() if px[3] == 255 and px[:3] not in allowed and px[:3] != (255, 255, 255)}
        if off:
            bad.append(f"{p.relative_to(ROOT)}: {len(off)} off-palette colours, e.g. {sorted(off)[:3]}")
    before = digest()
    subprocess.run([sys.executable, "-m", "artgen"], check=True, cwd=Path(__file__).resolve().parents[1],
                   stdout=subprocess.DEVNULL)
    after = digest()
    changed = [k for k in before if before[k] != after.get(k)]
    if changed:
        bad.append(f"non-deterministic output: {changed[:5]}")
    if bad:
        print("\n".join(bad))
        sys.exit(1)
    print(f"artgen OK: {len(after)} PNGs, palette-clean and deterministic")


if __name__ == "__main__":
    main()
