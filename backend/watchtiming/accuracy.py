"""A watch's rate from its measurements: deviation against reference time, per session.

Pure functions, no I/O. The rate is the slope of a linear regression, never the difference
between two points. Each reference source (EXIF, or the device clock per platform and frame
timing) can carry its own constant offset, so the fit has one slope and a separate intercept
per source: a step between sources then can't turn into a rate error.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

DAY_S = 86400.0
# Below this span the rate is shown but flagged: a few tenths of a second of reading noise
# over a few hours is a large error in s/d.
MIN_SPAN = timedelta(hours=24)


def source_key(source: str, platform: str | None, frame_timing: str | None) -> str:
    """The group a measurement's constant offset belongs to: "exif", or the device clock per
    platform and frame timing ("device_clock:ios:capture_time")."""
    if source == "exif":
        return "exif"
    return f"{source}:{platform}:{frame_timing}"


@dataclass(frozen=True)
class RatePoint:
    time: datetime  # reference time, timezone-aware
    deviation_s: float  # dial − reference, positive = fast
    source: str  # source_key()


@dataclass(frozen=True)
class RateFit:
    rate_s_per_day: float  # positive = gains time
    # Each source's deviation at `epoch` (the first measurement's time).
    intercepts: dict[str, float]
    epoch: datetime
    n: int
    span_hours: float
    # Spread of the points around the fit; None when there are no degrees of freedom left.
    residual_std_s: float | None
    short_span: bool  # the points span less than MIN_SPAN
    mixed_sources: bool  # more than one source: each got its own intercept


def fit_rate(points: list[RatePoint]) -> RateFit | None:
    """One slope with a separate intercept per source (least squares). None when no source
    has two points at different times: there's no slope to see yet."""
    if len(points) < 2:
        return None
    epoch = min(p.time for p in points)
    groups: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for p in points:
        groups[p.source].append(((p.time - epoch).total_seconds() / DAY_S, p.deviation_s))

    sxx = sxy = 0.0
    means: dict[str, tuple[float, float]] = {}
    for source, pairs in groups.items():
        t, d = np.array(pairs).T
        means[source] = (float(t.mean()), float(d.mean()))
        sxx += float(((t - t.mean()) ** 2).sum())
        sxy += float(((t - t.mean()) * (d - d.mean())).sum())
    if sxx <= 1e-12:
        return None
    slope = sxy / sxx
    intercepts = {s: d_mean - slope * t_mean for s, (t_mean, d_mean) in means.items()}

    residuals = [d - (intercepts[s] + slope * t) for s, pairs in groups.items() for t, d in pairs]
    dof = len(points) - len(groups) - 1
    residual_std = float(np.sqrt(np.sum(np.square(residuals)) / dof)) if dof > 0 else None
    span = max(p.time for p in points) - epoch
    return RateFit(
        rate_s_per_day=slope,
        intercepts=intercepts,
        epoch=epoch,
        n=len(points),
        span_hours=span.total_seconds() / 3600,
        residual_std_s=residual_std,
        short_span=span < MIN_SPAN,
        mixed_sources=len(groups) > 1,
    )


def predict(fit: RateFit, time: datetime, source: str) -> float:
    """The deviation the fit expects at `time` for a measurement from `source`. A source the fit
    hasn't seen gets the mean of the others' intercepts."""
    intercept = fit.intercepts.get(source)
    if intercept is None:
        intercept = sum(fit.intercepts.values()) / len(fit.intercepts)
    return intercept + fit.rate_s_per_day * (time - fit.epoch).total_seconds() / DAY_S


def expected_deviation(points: list[RatePoint], time: datetime, source: str) -> float | None:
    """The deviation to expect for a new measurement: from the fit when there is one, else the
    latest measurement's deviation (the rate isn't known yet). None without measurements."""
    if not points:
        return None
    fit = fit_rate(points)
    if fit is not None:
        return predict(fit, time, source)
    return max(points, key=lambda p: p.time).deviation_s
