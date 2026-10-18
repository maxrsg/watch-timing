import cv2

from tests.synthetic.render import DialSpec, render
from watchtiming.debug import main


def test_writes_stage_images(tmp_path):
    image = tmp_path / "dial.png"
    cv2.imwrite(str(image), render(DialSpec(size=1600)).image)
    out = tmp_path / "out"

    assert main([str(image), "-o", str(out)]) == 0

    written = cv2.imread(str(out / "01_preprocessed.png"), cv2.IMREAD_GRAYSCALE)
    assert written.shape == (1000, 1000)


def test_unreadable_image_fails_cleanly(tmp_path, capsys):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    assert main([str(bad), "-o", str(tmp_path / "out")]) == 1
    assert "error" in capsys.readouterr().err
