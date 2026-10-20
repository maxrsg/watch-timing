import cv2

from tests.synthetic.render import DialSpec, render
from watchtiming.debug import main


def test_without_tap_stops_before_dial_detection(tmp_path):
    image = tmp_path / "dial.png"
    cv2.imwrite(str(image), render(DialSpec(size=1600)).image)
    out = tmp_path / "out"

    assert main([str(image), "-o", str(out)]) == 0

    written = cv2.imread(str(out / "01_preprocessed.png"), cv2.IMREAD_GRAYSCALE)
    assert written.shape == (1000, 1000)
    assert {p.stem for p in out.iterdir()} == {"00_grid", "01_preprocessed", "02_edges", "03_dial"}


def test_with_tap_writes_every_stage(tmp_path, capsys):
    dial = render(DialSpec(size=1600, tilt_deg=20))
    image = tmp_path / "dial.png"
    cv2.imwrite(str(image), dial.image)
    out = tmp_path / "out"
    tap = f"{dial.truth.twelve[0]:.1f},{dial.truth.twelve[1]:.1f}"  # photo pixels

    assert main([str(image), "--tap", tap, "-o", str(out)]) == 0

    stems = {p.stem for p in out.iterdir()}
    assert {"03_dial", "04_rectified", "05_polar", "06_bars", "07_traces"} <= stems
    assert "time: 10:08:37.0" in capsys.readouterr().out


def test_unreadable_image_fails_cleanly(tmp_path, capsys):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    assert main([str(bad), "-o", str(tmp_path / "out")]) == 1
    assert "error" in capsys.readouterr().err
