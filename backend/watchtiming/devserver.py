"""Dev server: the FastAPI app with auto-reload, plus dev-only switches.

uv run watchtiming-dev                      # same as `fastapi dev watchtiming/api.py`
uv run watchtiming-dev --save-uploads       # also keep each /api/read upload
uv run watchtiming-dev --save-uploads DIR   # ... in DIR (default: debug-out/uploads)
"""

import argparse
import os
from pathlib import Path

import uvicorn

from watchtiming.upload_log import ENV_VAR

DEFAULT_UPLOAD_DIR = Path("debug-out/uploads")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="watchtiming-dev", description=__doc__.splitlines()[0])
    parser.add_argument(
        "--save-uploads",
        nargs="?",
        const=DEFAULT_UPLOAD_DIR,
        type=Path,
        metavar="DIR",
        help=f"keep each /api/read upload with debug images (default: {DEFAULT_UPLOAD_DIR})",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-reload", action="store_true")
    args = parser.parse_args(argv)

    if args.save_uploads is not None:
        # Through the environment, so the reloading worker processes inherit it.
        folder = args.save_uploads.resolve()
        os.environ[ENV_VAR] = str(folder)
        print(f"Saving uploads to {folder}", flush=True)
    else:
        os.environ.pop(ENV_VAR, None)
    uvicorn.run("watchtiming.api:app", host=args.host, port=args.port, reload=not args.no_reload)


if __name__ == "__main__":
    main()
