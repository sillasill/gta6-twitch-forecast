# Validation — gta6-twitch-ccu-forecast-01

Entry: `main.py` (Python 3.13, stdlib only) + `README.md` + `LICENSE` (MIT) +
`.makefun/owner.json`. No `main.ts` — one entrypoint only.

## Model

Weighted empirical quantiles of comparables' log ratios `ln(viewers_h /
viewers_1)`, per hour. Each comparable is weighted by Gaussian kernels on
two similarity measures computed at run time from the case file:

- **unlock ratio** — hour-1 print / median hourly viewers in the 3 days
  before release (bandwidth 0.5 in log space). Tells how much of the launch
  had already happened by hour 1.
- **scale** — the hour-1 print itself (bandwidth 1.5 in log space). Big
  launches flatten out; small ones climb further.

Plus a 0.02 floor weight per comparable and a 0.9 spread shrink toward the
median. The target's own pre-release GTA VI history is skipped (no launch
day); comparables missing hour 1 or with < 20 of the day's 24 hours are
skipped; an hour no comparable covers falls back to persistence with a
widening spread.

**Revision (17 Nov 2026): anchor-dependent upside spread.** The upper
quantiles (τ > 0.5) are stretched away from the median by a factor of
1 + 0.5 · ln(100,000 / hour-1 print) when the print is below 100,000,
capped at 2.0; the median and lower quantiles are untouched, and the same
factor widens the upper half of the persistence fallback. The evidence:
across the 37 comparables, log(peak / hour-1) = 11.66 − 0.93 · log(hour-1),
so the evening peak is nearly unrelated to the hour-1 print in absolute
terms — a small print can grow many-fold, a big one barely grows. The
cap matters: without it, prints of a few hundred viewers stretch the tail
without bound and LOO on all targets gets worse (0.463 vs 0.449 baseline).

Key finding from the data: log(hour-1 print) correlates −0.94 with
log(peak / hour-1) across the 37 usable comparables — the anchor matters as
much as the shape. All four practice launches share one shape: a dip at
hours 2–4, a jump at hours 5–6 (US East unlock), a midday lull, and an
evening peak at hours 18–22, 1.7×–9.1× the hour-1 print.

## Practice cases (answers fetched from SullyGnome, 4 requests, one per game)

| case | game | loss | typical miss | 90% coverage |
|------|------|------|--------------|--------------|
| p00 | Marvel's Wolverine | 0.392 | 111.3% | 1.000 |
| p01 | Red Dead Redemption 2 | 0.247 | 54.6% | 0.957 |
| p02 | God of War Ragnarök | 0.152 | 25.3% | 1.000 |
| p03 | Marvel's Spider-Man 2 | 0.244 | 35.0% | 0.826 |
| **overall** | | **0.259** | | **0.946** |

Before the revision the overall loss was 0.270 (p00 0.438, coverage 0.935);
the revision improves only p00 — the one small-anchor case (print 23,357,
factor 1.73× on its upper quantiles) — and leaves the other three cases
byte-identical. House baseline on the same answers: **0.387** loss, 82.8% typical miss,
0.783 coverage (reproduced exactly by the local scorer, which validates the
answers and the pinball implementation). The entry beats the baseline on
every practice case. Wolverine is the hardest: its evening peak is 9.1× its
small hour-1 print (23,357), an outlier no comparable predicts; the honest
spread still covers most of its hours.

## Leave-one-out cross-validation over comparables

Each of the 37 usable comparables in turn was treated as the target (its
hour-1 print as the anchor), forecast from the other 36, and scored with
pinball loss against its real release-day curve:

| model | LOO loss, GTA-like targets (n=21) | LOO loss, all targets (n=37) |
|-------|----------------------------------|------------------------------|
| house baseline (persistence) | 0.844 | 0.930 |
| empirical quantiles, all comparables | 0.686 | 0.714 |
| kernel on unlock ratio only | 0.621 | 0.626 |
| **this entry (both kernels, α=0.9)** | **0.433** | **0.450** |

GTA-like = clean launch (unlock ratio > 20), not free-to-play / live-service.
LOO is pessimistic — it includes idiosyncratic launches (simultaneous global
unlocks, early-access contamination) that a rolling-midnight console launch
like GTA VI will not resemble — but the ranking of the variants is the same
as on the practice cases, and the chosen bandwidths (0.5 / 1.5) sit on a flat
plateau: every nearby combination scores 0.273–0.279 on the practice, so the
model is not tuned to a knife edge. Effective sample size for a GTA-sized
target (hour-1 print 270k–1M) is 14–21 of 37 comparables.

After the revision, LOO re-run with the entry's own `forecast_case`:
baseline (no upside spread) 0.433 GTA-like / 0.449 all; revised
0.412 GTA-like / 0.444 all, coverage 0.876→0.915 GTA-like and 0.867→0.913
all. The gain is not just the one practice case — it holds across the 21
GTA-like LOO targets. Note the revision is inert for a GTA-sized anchor
(print ≥ 100,000 → factor 1.0), so the final case forecast is unchanged
by it; it only protects small-anchor cases like Wolverine.

Variants tried and rejected: empirical quantiles without similarity weights
(0.714 LOO / 0.686 GTA-like), unlock-ratio kernel alone (fails p03: 1.174 —
Spider-Man 2's unlock ratio of 47 sits in the contaminated range, so the
scale kernel is essential), median + normal spread (0.80 LOO), no spread
shrink (practice 0.275 vs 0.270 at α=0.9). For the upside-spread revision
itself: reference print 200,000 with slope 0.3 (practice 0.261, but p03
worsens 0.244→0.257); slope 0.8 at reference 100,000 (practice 0.257, but
LOO-all 0.446 vs 0.444 at slope 0.5); no cap (LOO-all 0.463, worse than
baseline). Chosen: reference 100,000, slope 0.5, cap 2.0 — best LOO-all,
near-best practice (0.259) and LOO GTA-like (0.412), and no practice case
worse than before.

## Format / determinism / runtime

- All four practice outputs: 23 rows, hours 2–24 each once, five
  non-decreasing quantiles per row, all > 0 and ≤ 1e9, files 1,456–1,565
  bytes (limit 65,536).
- Two full runs byte-identical (`diff -r` clean); a single-case run
  produces the same bytes as the batch run.
- Runtime: ~0.20 s for all four cases together (~0.05 s per case), limit
  8 s per case.
- Edge case re-tested after the revision: no comparables, no history,
  hour-1 print 850 → valid fallback output (persistence with widening
  spread, upper half stretched by the capped factor 2.0: q95 at hour 24
  9,061 vs 2,775 before), no crash.

## Remaining

- Not submitted (by design): needs a public GitHub repo created by Ram
  first, then the main agent submits with the transcript bundle.
- The final case (h00) cannot be scored until the release day is recorded;
  the practice score is no guide to the final, per the rules.
