import pytest

# name → result line, filled by tests/synthetic/test_accuracy.py and tests/test_real_photos.py.
ACCURACY_REPORT: dict[str, str] = {}
REAL_PHOTO_REPORT: dict[str, str] = {}


@pytest.fixture
def accuracy_report() -> dict[str, str]:
    return ACCURACY_REPORT


@pytest.fixture
def real_photo_report() -> dict[str, str]:
    return REAL_PHOTO_REPORT


def pytest_terminal_summary(terminalreporter):
    for title, report in (("synthetic", ACCURACY_REPORT), ("real photos", REAL_PHOTO_REPORT)):
        if not report:
            continue
        terminalreporter.section(f"dial reading accuracy ({title})")
        for name, line in report.items():
            terminalreporter.write_line(f"{name:34s} {line}")
