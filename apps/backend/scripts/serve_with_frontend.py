import os
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(SCRIPTS_DIR)
REPO_ROOT = os.path.dirname(os.path.dirname(BACKEND_DIR))
DIST_DIR = os.environ.get("FRONTEND_DIST_DIR") or os.path.join(REPO_ROOT, "apps", "frontend", "dist")

sys.path.insert(0, BACKEND_DIR)

import uvicorn
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from app.main import app

BASE_PREFIX = sys.argv[2].strip("/") if len(sys.argv) > 2 else ""
INDEX_HTML = os.path.join(DIST_DIR, "index.html")

if not os.path.isdir(DIST_DIR):
    raise SystemExit(f"dist 不存在：{DIST_DIR}（先在 apps/frontend 执行 npm run build）")

ASSETS_URL = f"/{BASE_PREFIX}/assets" if BASE_PREFIX else "/assets"
app.mount(ASSETS_URL, StaticFiles(directory=os.path.join(DIST_DIR, "assets")), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    relative_path = full_path
    if BASE_PREFIX:
        prefix = f"{BASE_PREFIX}/"
        if not full_path.startswith(prefix):
            return FileResponse(INDEX_HTML)
        relative_path = full_path[len(prefix):]
    candidate = os.path.join(DIST_DIR, relative_path) if relative_path else ""
    if relative_path and os.path.isfile(candidate):
        return FileResponse(candidate)
    return FileResponse(INDEX_HTML)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8020
    host = os.environ.get("CONSOLE_HOST", "127.0.0.1")
    location = f"http://127.0.0.1:{port}/{BASE_PREFIX}" if BASE_PREFIX else f"http://127.0.0.1:{port}"
    print(f"serving frontend({DIST_DIR}) base='/{BASE_PREFIX}' + api on {location}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
