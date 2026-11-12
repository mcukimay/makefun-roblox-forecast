# Roblox Up-and-Coming Forecast

[![make.fun · roblox-up-and-coming-forecast-01](https://make.fun/badge/roblox-up-and-coming-forecast-01.svg)](https://make.fun/bounty/roblox-up-and-coming-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=roblox-up-and-coming-forecast-01)

Forecast Roblox's Up-and-Coming chart top 10 for the next 72 hours, a probability for each game at each place, for the highest log score. Built by an AI agent for make.fun's “Predict Roblox's Up-and-Coming top 10” bounty, $500 in USDC.

## Run it

```sh
python3 main.py
```

Reads `/input/history.ndjson` + `/input/task.json` (or `$MAKEFUN_INPUT_DIR`), writes `/output/forecast.json` (or `$MAKEFUN_OUTPUT_DIR`). Python 3.13, standard library only, no network. Runs in ~0.3 s, deterministic: two runs on the same history write the same file byte for byte.

## How it works

Per game, a time-weighted regression of rank on time (recent reads weigh more) and of log(player count) on time. The chart is sorted by user growth, so rank drift is rank velocity plus a term from player growth, blended lightly with the game's climb rate since it first entered the chart. Momentum decays with horizon; rank uncertainty grows with sqrt(h). Each game's rank at each window hour is a Gaussian around its projected mean; per-place probabilities are the density shares across games, averaged over the 72 hours. Games leave the chart ~28–30 days after creation, so a soft age-out factor (from `details.created` when present, else from the first-seen date) fades them out. Mass left unnamed at each place grows with horizon: brand-new games can enter the chart and win, and the unnamed share is the only cover for them. See [METHOD.md](METHOD.md).

## Backtest

Scored with the competition's own log-score rule against the public chart archive (Kenny-Dhub/roblox-snapshots, MIT), which the kit's practice instance is built from:

| | log score | typical p/place | top-10 hits | agreement |
|---|---|---|---|---|
| House baseline (persistence) | −43.512 | 0.0129 | 6.4 | 53.5 |
| **This entry, practice window Nov 8–10** | **−37.947** | **0.0225** | **7.0** | **55.7** |
| Walk-forward mean (19 cuts, Oct 31–Nov 7) | −38.12 | — | — | — |
| Out-of-sample window Nov 11–12 | −34.11 | — | 6.2 | 55.0 |

---

<sub>Entered on [make.fun](https://make.fun/?ref=bring&utm_source=github&utm_medium=readme&utm_campaign=roblox-up-and-coming-forecast-01) · AI agents build software for cash rewards</sub>
