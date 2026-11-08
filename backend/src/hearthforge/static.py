"""Phase 18: serve the built frontend (`vite build` → dist/) from the API process when HF_STATIC_DIR is set.

One origin for the page, `/api` and `/ws` means httpOnly session cookies work in every browser (Safari
blocks cross-site ones, PLAN B2) with no CORS at all. Hashed bundles are cached for a year; the
generated art and fonts for an hour; index.html never (so a deploy shows up on the next load)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

YEAR = "public, max-age=31536000, immutable"
HOUR = "public, max-age=3600"


def mount_frontend(app: FastAPI, root: Path) -> None:
    root = root.resolve()
    index = root / "index.html"
    if not index.is_file():
        raise RuntimeError(f"HF_STATIC_DIR={root} has no index.html (run `npm run build` in frontend/)")

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str) -> FileResponse:
        if path.startswith(("api/", "ws")):
            raise HTTPException(404)
        f = (root / path).resolve()
        if path and f.is_file() and root in f.parents:
            # Vite's hashed bundles sit directly in assets/; generated art and fonts live in subfolders
            hashed = path.startswith("assets/") and path.count("/") == 1
            return FileResponse(f, headers={"Cache-Control": YEAR if hashed else HOUR})
        return FileResponse(index, headers={"Cache-Control": "no-cache"})  # the app routes /play etc.
