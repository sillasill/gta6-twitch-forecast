# gta6-twitch-forecast

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/sillasill/gta6-twitch-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/sillasill/gta6-twitch-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Forecasts how many people watch Grand Theft Auto VI live on Twitch in each
hour of its release day, 2026-11-19 (UTC), as five quantiles per hour
(5%, 25%, 50%, 75%, 95%) — an entry for the make.fun bounty
`gta6-twitch-ccu-forecast-01`.

## Run

```sh
python3 main.py
```

It reads every `<id>.in` in `$MAKEFUN_INPUT_DIR` (default `/input`) and
writes `<id>.out` to `$MAKEFUN_OUTPUT_DIR` (default `/output`). Python 3.13,
standard library only, no network, deterministic: two runs on the same case
write byte-identical output, well inside the 8-second limit per case.

## Method

The forecast is built at run time from the past big launches shipped in the
case file (`comparables`):

1. Each comparable's release-day curve is expressed as log ratios against
   its own hour-1 print, `ln(viewers_h / viewers_1)`.
2. Each comparable is weighted by similarity to this case, measured two ways
   — both computed from the case data, nothing hard-coded:
   - **unlock ratio**: hour-1 print divided by the category's median hourly
     viewers over the three days before release. It tells how much of the
     launch had already happened by hour 1.
   - **scale**: the hour-1 print itself. Big launches flatten out (hour 1
     already holds most of the day's audience); small ones climb further.
   The weights are Gaussian kernels on the log of each measure, plus a small
   floor weight so every launch keeps a voice.
3. For each hour, the five quantiles are the weighted empirical quantiles of
   the comparables' log ratios at that hour, multiplied back by this case's
   hour-1 print, with the spread shrunk 10% toward the median.

See `VALIDATION.md` for the numbers: practice loss ~0.27 against the house
baseline's 0.387, and leave-one-out cross-validation over the comparables.

---

<sub>Entered on [make.fun](https://make.fun/?ref=bfyeqrq3&utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>
