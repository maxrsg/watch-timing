"""Malformed images must fail with InvalidImageError (a clean 4xx), never anything else."""

import contextlib
import io
import random
from pathlib import Path

import pytest
from PIL import Image

from tests.helpers import make_image
from watchtiming.dial import preprocess
from watchtiming.exif import read_capture_exif
from watchtiming.imaging import InvalidImageError

# Inputs found by fuzzing that used to crash preprocess with struct.error, TypeError or
# AttributeError (Pillow re-serializing malformed EXIF inside ImageOps.exif_transpose).
# Pillow warns about corrupt metadata on these inputs; that is expected.
pytestmark = pytest.mark.filterwarnings("ignore::UserWarning")

MALFORMED = sorted((Path(__file__).parent / "malformed").glob("*.jpg"))


def readers():
    return [preprocess, read_capture_exif]


@pytest.mark.parametrize("path", MALFORMED, ids=lambda p: p.stem)
@pytest.mark.parametrize("reader", readers(), ids=lambda f: f.__name__)
def test_known_malformed_exif(path, reader):
    # Rejecting is fine; crashing with anything else is not.
    with contextlib.suppress(InvalidImageError):
        reader(path.read_bytes())


def _mutations(seed: int, count: int):
    exif = Image.Exif()
    exif[0x0112] = 6
    exif[0x011A] = (72, 1)
    exif[0x0110] = "Model"
    buf = io.BytesIO()
    Image.new("RGB", (64, 48)).save(buf, "JPEG", exif=exif)
    data = buf.getvalue()
    start = data.index(b"Exif\x00\x00") + 6
    rng = random.Random(seed)
    for _ in range(count):
        b = bytearray(data)
        for _ in range(rng.randint(1, 6)):
            b[rng.randrange(start, start + 60)] = rng.randrange(256)
        yield bytes(b)


@pytest.mark.parametrize("reader", readers(), ids=lambda f: f.__name__)
def test_fuzzed_exif_never_escapes(reader):
    for data in [*_mutations(seed=1, count=500), make_image()]:
        with contextlib.suppress(InvalidImageError):
            reader(data)
