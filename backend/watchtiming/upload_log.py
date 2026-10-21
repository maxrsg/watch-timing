"""Dev-only: keep /api/read uploads for debugging real photos.

Off unless the WATCHTIMING_SAVE_UPLOADS environment variable names a directory. The product
stores no images (CLAUDE.md); this exists so photos taken in the app can be inspected with the
debug stages afterwards. Each upload gets its own folder: the original file, the request, the
result and the debug stage images, drawn from the very measurement the app was sent.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from watchtiming.dial import Preprocessed
from watchtiming.measure import Measurement

ENV_VAR = "WATCHTIMING_SAVE_UPLOADS"

_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/heic": ".heic",
    "image/heif": ".heic",
    "image/png": ".png",
}


def upload_dir() -> Path | None:
    value = os.environ.get(ENV_VAR)
    return Path(value) if value else None


def save_upload(
    root: Path,
    data: bytes,
    content_type: str | None,
    request: dict,
    pre: Preprocessed,
    measurement: Measurement,
    result_json: str,
) -> Path:
    """Write one upload with its debug stages; returns its folder."""
    # Imported here: the drawing code is only needed when uploads are kept.
    import cv2

    from watchtiming.debug import draw_stages

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    folder = root / stamp
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"photo{_EXTENSIONS.get(content_type or '', '.bin')}").write_bytes(data)
    (folder / "request.json").write_text(json.dumps(request, indent=2, default=str))
    (folder / "result.json").write_text(result_json)
    stages, info = draw_stages(pre, measurement)
    for name, image in stages:
        cv2.imwrite(str(folder / f"{name}.png"), image)
    (folder / "info.txt").write_text("\n".join(info) + "\n")
    return folder
