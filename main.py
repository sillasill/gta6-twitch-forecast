"""Forecast GTA VI's launch-day Twitch viewers, hour by hour, as quantiles.

The program reads one case file per run (schema makefun/twitch-ccu-case/v1):
everything recorded up to the end of the release day's first hour, that hour's
print included, plus the hourly curves of past big game launches (the
comparables). It writes one forecast file per case: for each of hours 2 to 24,
five quantiles of that hour's concurrent-viewer count.

How the forecast is made
-------------------------
Every launch's day has the same shape in outline -- a quiet dip in the small
hours, a jump when the US east coast unlocks, a long rise to an evening peak
-- but the *size* of that shape, measured against the first hour's print,
depends on what hour 1 already contains. A launch whose first hour is already
huge (a whole continent playing since its midnight) grows only a little more
by the evening; a launch whose first hour is still small (most regions not
unlocked yet) can grow many-fold. So the forecast is built from the
comparables' own curves, re-weighted for each case:

* For every comparable we take its release-day curve and express each hour as
  a log ratio against its own hour-1 print, ln(viewers_h / viewers_1).
* Two numbers describe how similar a comparable is to this case, and both
  are computed from the case file at run time, never hard-coded:
    - the *unlock ratio*: hour-1 print divided by the category's median
      hourly viewers over the three days before release. A high ratio means
      the launch was already in full swing by hour 1; a ratio near 1 means
      hour 1 was still the quiet pre-release level (early access, or an
      unlock that falls later in the day).
    - the *scale*: the hour-1 print itself. Big launches flatten out
      (their hour 1 already holds most of the day's audience); small ones
      climb further.
* Each comparable gets a weight from Gaussian kernels on the log unlock
  ratio and the log hour-1 print, plus a small floor weight so no launch is
  ever fully ignored. For each hour, the five forecast quantiles are the
  weighted empirical quantiles of the comparables' log ratios at that hour,
  multiplied back by this case's hour-1 print.
* The spread is shrunk slightly toward the median (a factor of 0.9 in log
  space): the raw empirical tails are a touch wider than the truth on the
  practice launches, and the pinball loss pays for needless width.
* The upper tail gets extra room when the first hour's print is small.
  Across the comparables, log(peak / hour-1 print) falls almost one-for-one
  with log(hour-1 print) -- a small print can grow many-fold by the
  evening, while a big one barely grows at all. So for prints below a
  reference size, the distance from the median to each upper quantile is
  stretched, in proportion to how far below the reference the print sits
  (capped at a factor of two). The lower quantiles are left alone: the
  cost of overshooting them is paid in full, while an upper quantile that
  sits too low is the expensive mistake.

Everything is deterministic: the input files are read in name order, the
weights are pure arithmetic on the case data, and there is no randomness, no
clock, and no network. Standard library only.

What the case must not contain
------------------------------
The comparables include the target game's own pre-release category history
(under its own name); it is skipped, because it holds no launch day. A
comparable missing hour 1, or with fewer than 20 of the day's 24 hours, is
skipped too. An hour no comparable covers falls back to a persistence
forecast with a widening spread, so the output is always a valid 23 rows.
"""

import json
import math
import os
import statistics
from datetime import datetime, timedelta
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# Standard normal quantiles at the five levels, used only by the fallback.
Z = [-1.6448536269514722, -0.6744897501960817, 0.0,
     0.6744897501960817, 1.6448536269514722]

# Kernel widths (in natural-log units) for the two similarity measures.
BW_UNLOCK_RATIO = 0.5
BW_SCALE = 1.5
# Every comparable keeps at least this much weight, so the tails of the
# distribution never rest on one or two launches alone.
FLOOR_WEIGHT = 0.02
# Spread shrink: quantiles are pulled this far toward the median in log space.
SPREAD_SHRINK = 0.9
# Anchor-dependent upside spread. Prints below UPSIDE_REF_PRINT get their
# upper quantiles stretched by 1 + UPSIDE_SLOPE * ln(UPSIDE_REF_PRINT /
# print), capped at UPSIDE_CAP: a small first hour may still climb a long
# way by the evening, a big one will not.
UPSIDE_REF_PRINT = 100000.0
UPSIDE_SLOPE = 0.5
UPSIDE_CAP = 2.0
# An hour is only trusted when at least this many hours of the release day
# are present in a comparable's curve.
MIN_DAY_HOURS = 20
# How far back the pre-release median is taken, in days.
PRE_DAYS = 3


def parse_time(text):
    """An ISO-8601 UTC timestamp as a datetime."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def release_day_curve(hourly, day_start):
    """Map hour (1..24) to viewers for the UTC release day of one launch."""
    curve = {}
    for point in hourly or []:
        try:
            when = parse_time(point["from"])
        except (KeyError, TypeError, ValueError):
            continue
        hour = int((when - day_start).total_seconds() // 3600) + 1
        viewers = point.get("viewers")
        if 1 <= hour <= 24 and viewers and viewers > 0:
            curve[hour] = float(viewers)
    return curve


def pre_release_median(hourly, day_start):
    """Median hourly viewers in the days just before a launch's release day."""
    start = day_start - timedelta(days=PRE_DAYS)
    values = []
    for point in hourly or []:
        try:
            when = parse_time(point["from"])
        except (KeyError, TypeError, ValueError):
            continue
        viewers = point.get("viewers")
        if start <= when < day_start and viewers and viewers > 0:
            values.append(float(viewers))
    return statistics.median(values) if values else None


def weighted_quantile(pairs, level):
    """Weighted quantile of (value, weight) pairs, linearly interpolated."""
    ordered = sorted(pairs)
    total = sum(weight for _, weight in ordered)
    if total <= 0 or not ordered:
        return None
    target = level * total
    seen = 0.0
    prev_value, prev_seen = ordered[0][0], 0.0
    for value, weight in ordered:
        seen += weight
        if seen >= target:
            if seen == weight or seen == prev_seen:
                return value
            frac = (target - prev_seen) / (seen - prev_seen)
            return prev_value + frac * (value - prev_value)
        prev_value, prev_seen = value, seen
    return ordered[-1][0]


def collect_comparables(case):
    """The usable past launches: each with its day curve and similarity data."""
    pool = []
    for comp in case.get("comparables") or []:
        name = comp.get("name") or ""
        if "Grand Theft Auto VI" in name:
            # The target's own pre-release category history: no launch day.
            continue
        try:
            day_start = parse_time(comp["day_start"])
        except (KeyError, TypeError, ValueError):
            continue
        hourly = comp.get("hourly") or []
        curve = release_day_curve(hourly, day_start)
        if 1 not in curve or len(curve) < MIN_DAY_HOURS:
            continue
        before = pre_release_median(hourly, day_start)
        unlock_ratio = curve[1] / before if before and before > 0 else None
        pool.append({"curve": curve, "first": curve[1],
                     "unlock_ratio": unlock_ratio})
    return pool


def case_anchor(case):
    """This case's hour-1 print and its unlock ratio, from the case file."""
    known = case.get("known") or []
    first_row = next((k for k in known if k.get("hour") == 1), None)
    if first_row and first_row.get("viewers"):
        first = max(1.0, float(first_row["viewers"]))
    else:
        # No hour-1 print: fall back to the last recorded point, then to 1.
        history = case.get("history") or []
        first = 1.0
        for point in reversed(history):
            if point.get("viewers"):
                first = max(1.0, float(point["viewers"]))
                break
    try:
        day_start = parse_time(case["day_start"])
    except (KeyError, TypeError, ValueError):
        day_start = None
    before = None
    if day_start is not None:
        before = pre_release_median(case.get("history_hourly") or [],
                                    day_start)
    unlock_ratio = first / before if before and before > 0 else None
    return first, unlock_ratio


def similarity_weight(comp, first, unlock_ratio):
    """How much one past launch should count for this case."""
    weight = FLOOR_WEIGHT
    if unlock_ratio and comp["unlock_ratio"]:
        gap = (math.log(comp["unlock_ratio"]) - math.log(unlock_ratio))
        weight += math.exp(-(gap / BW_UNLOCK_RATIO) ** 2)
    gap = math.log(comp["first"]) - math.log(first)
    weight += math.exp(-(gap / BW_SCALE) ** 2)
    return weight


def upside_spread_factor(first):
    """Extra width for the upper quantiles when the hour-1 print is small.

    Across the comparables the evening peak is almost unrelated to the
    hour-1 print in absolute terms, so the ratio peak / print grows as
    the print shrinks. The factor is 1 for prints at or above the
    reference size and grows logarithmically below it, capped so that a
    print of a few hundred viewers cannot stretch the tail without bound.
    """
    if first >= UPSIDE_REF_PRINT:
        return 1.0
    return min(UPSIDE_CAP,
               1.0 + UPSIDE_SLOPE * math.log(UPSIDE_REF_PRINT / first))


def fallback_quantiles(first, hour, upside=1.0):
    """Persistence with a widening spread, for an hour no comparable covers.

    The upside factor applies here too: with no comparable to learn from,
    a small print's evening hours are just as uncertain upwards.
    """
    spread = 0.15 * math.sqrt(hour - 1)
    return [first * math.exp(z * spread * (upside if z > 0 else 1.0))
            for z in Z]


def forecast_case(case):
    first, unlock_ratio = case_anchor(case)
    pool = collect_comparables(case)
    upside = upside_spread_factor(first)
    rows = []
    for row in case["forecast"]:
        hour = row["hour"]
        pairs = []
        for comp in pool:
            if hour not in comp["curve"]:
                continue
            ratio = math.log(comp["curve"][hour] / comp["first"])
            pairs.append((ratio, similarity_weight(comp, first,
                                                   unlock_ratio)))
        if pairs:
            median_log = weighted_quantile(pairs, 0.5)
            quantiles = []
            for level in LEVELS:
                log_ratio = weighted_quantile(pairs, level)
                # Pull the spread toward the median in log space.
                shrunk = median_log + SPREAD_SHRINK * (log_ratio - median_log)
                if level > 0.5:
                    # A small first print can still climb a long way, so
                    # give the upper quantiles extra room above the median.
                    shrunk = median_log + (shrunk - median_log) * upside
                quantiles.append(first * math.exp(shrunk))
        else:
            quantiles = fallback_quantiles(first, hour, upside)
        # Keep the quantiles ordered, positive and within the contest's cap.
        cleaned = []
        for value in quantiles:
            value = min(max(value, 1.0), 1e9)
            if cleaned:
                value = max(value, cleaned[-1])
            cleaned.append(round(value, 2))
        rows.append({"hour": hour, "q": cleaned})
    return {"hours": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case)
        out_path = OUTPUT_DIR / f"{path.stem}.out"
        out_path.write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n",
            encoding="utf-8")


if __name__ == "__main__":
    main()
