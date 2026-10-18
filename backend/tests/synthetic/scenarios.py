"""Named synthetic dials covering the variations the CV pipeline must handle (CLAUDE.md:
rotation, tilt, noise, glare, dial/hand polarity, overlapping hands, seconds-hand tail).

Use with `pytest.mark.parametrize("name,spec", SCENARIOS.items())` and report the reading
error in seconds per scenario, not just pass/fail.
"""

from tests.synthetic.render import DialSpec

SCENARIOS: dict[str, DialSpec] = {
    "flat": DialSpec(),
    "rotated": DialSpec(rotation_deg=37),
    "upside_down": DialSpec(rotation_deg=180),
    "tilt_mild": DialSpec(tilt_deg=15, tilt_axis_deg=30),
    "tilt_strong": DialSpec(tilt_deg=40, tilt_axis_deg=110, rotation_deg=-20),
    "close_camera": DialSpec(tilt_deg=25, camera_distance=1.2),
    "pivot_offset": DialSpec(pivot_offset=(0.03, -0.02)),
    "dark_dial": DialSpec(dark_dial=True),
    "noise": DialSpec(noise_sigma=15, seed=1),
    "blur": DialSpec(blur_sigma=2.0),
    "glare": DialSpec(glare=0.6, glare_center=(0.45, 0.4)),
    "no_markers": DialSpec(markers=False),
    "no_seconds_tail": DialSpec(seconds_tail=0.0),
    # Overlapping hands: fewer peaks than hands.
    "overlap_all": DialSpec(hours=12, minutes=0, seconds=0),
    "near_overlap_all": DialSpec(hours=12, minutes=0, seconds=0.5),  # seconds ~3° apart
    "overlap_hour_minute": DialSpec(hours=3, minutes=16, seconds=22),
    "overlap_minute_second": DialSpec(hours=7, minutes=41, seconds=41.5),
    "seconds_tail_on_hour": DialSpec(hours=9, minutes=0, seconds=15),
    "everything": DialSpec(
        hours=4,
        minutes=41,
        seconds=12.4,
        rotation_deg=30,
        tilt_deg=30,
        tilt_axis_deg=20,
        dark_dial=True,
        glare=0.4,
        blur_sigma=1.0,
        noise_sigma=8,
        seed=2,
    ),
}
