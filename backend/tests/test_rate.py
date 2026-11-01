"""accuracy.py: the rate from deviations against reference time (positive = fast)."""

from datetime import UTC, datetime, timedelta

import pytest

from watchtiming.accuracy import (
    RatePoint,
    expected_deviation,
    fit_rate,
    predict,
    source_key,
)

T0 = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)


def at(days: float, deviation: float, source: str = "exif") -> RatePoint:
    return RatePoint(T0 + timedelta(days=days), deviation, source)


def test_a_watch_gaining_time_has_a_positive_rate():
    fit = fit_rate([at(0, 1.0), at(1, 4.0), at(2, 7.0)])
    assert fit is not None
    assert fit.rate_s_per_day == pytest.approx(3.0)
    assert fit.intercepts == {"exif": pytest.approx(1.0)}
    assert fit.n == 3
    assert fit.span_hours == pytest.approx(48)
    assert not fit.short_span
    assert not fit.mixed_sources


def test_a_watch_losing_time_has_a_negative_rate():
    fit = fit_rate([at(0, -2.0), at(3, -8.0)])
    assert fit is not None
    assert fit.rate_s_per_day == pytest.approx(-2.0)
    assert fit.residual_std_s is None  # two points, two parameters


def test_the_rate_is_a_regression_not_the_last_two_points():
    # The last point is 1 s high; a regression dampens it, a two-point difference wouldn't.
    fit = fit_rate([at(0, 0.0), at(1, 5.0), at(2, 10.0), at(3, 16.0)])
    assert fit is not None
    assert fit.rate_s_per_day == pytest.approx(5.3)
    assert fit.residual_std_s == pytest.approx(
        (0.30 / 2) ** 0.5
    )  # residuals +0.2, −0.1, −0.4, +0.3


def test_no_rate_without_two_points_in_time():
    assert fit_rate([]) is None
    assert fit_rate([at(0, 1.0)]) is None
    assert fit_rate([at(1, 1.0), at(1, 1.4)]) is None
    # One point per source: each source's offset is unknown, so there's no slope either.
    assert fit_rate([at(0, 1.0, "exif"), at(1, 3.0, "device_clock:ios:capture_time")]) is None


def test_a_short_span_is_flagged():
    fit = fit_rate([at(0, 0.0), at(0.5, 2.0)])
    assert fit is not None
    assert fit.short_span
    assert fit.rate_s_per_day == pytest.approx(4.0)


def test_mixed_sources_get_their_own_offset():
    # True rate +2 s/d. The device clock reads 0.8 s higher than EXIF throughout.
    device = source_key("device_clock", "ios", "capture_time")
    points = [
        at(0, 0.0),
        at(1, 2.0),
        at(2, 4.0 + 0.8, device),
        at(3, 6.0 + 0.8, device),
        at(4, 8.0),
    ]
    fit = fit_rate(points)
    assert fit is not None
    assert fit.rate_s_per_day == pytest.approx(2.0)
    assert fit.intercepts["exif"] == pytest.approx(0.0)
    assert fit.intercepts[device] == pytest.approx(0.8)
    assert fit.mixed_sources
    # A plain regression over the mixed points would have turned the step into a rate error.
    plain = fit_rate([RatePoint(p.time, p.deviation_s, "one") for p in points])
    assert plain is not None
    assert plain.rate_s_per_day != pytest.approx(2.0, abs=0.05)


def test_source_keys():
    assert source_key("exif", None, None) == "exif"
    assert source_key("device_clock", "ios", "capture_time") == "device_clock:ios:capture_time"


def test_prediction_follows_the_fit_and_the_source():
    device = source_key("device_clock", "ios", "capture_time")
    fit = fit_rate([at(0, 0.0), at(1, 2.0), at(0, 1.0, device), at(2, 5.0, device)])
    assert fit is not None
    assert predict(fit, T0 + timedelta(days=3), "exif") == pytest.approx(6.0)
    assert predict(fit, T0 + timedelta(days=3), device) == pytest.approx(7.0)
    # An unseen source: the mean intercept.
    assert predict(fit, T0 + timedelta(days=3), "other") == pytest.approx(6.5)


def test_expected_deviation():
    assert expected_deviation([], T0, "exif") is None
    # One measurement: no rate yet, the last deviation is the best guess.
    assert expected_deviation([at(0, 3.0)], T0 + timedelta(days=1), "exif") == 3.0
    points = [at(0, 0.0), at(1, 2.0)]
    assert expected_deviation(points, T0 + timedelta(days=2), "exif") == pytest.approx(4.0)
