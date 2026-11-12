#!/usr/bin/env python3
"""Forecast Roblox's Up-and-Coming chart top 10 for the next 72 hours.

Reads /input/history.ndjson + /input/task.json, writes /output/forecast.json
(one object: {"probabilities": [...], "top10": [...]}), exactly as the
roblox-up-and-coming-forecast-01 rules describe.

Method (see METHOD.md for the full write-up):
  Per game, fit a time-weighted regression of rank on time (recent reads weigh
  more) and of log(player count) on time. The chart is sorted by user growth,
  so a game's rank drift is its rank velocity plus a term from its player
  growth, blended lightly with its climb rate since it first entered the
  chart (a game that surged into the chart keeps some of that surge).
  Each game's rank at hour h is a Gaussian around its projected mean; per
  place, probabilities are the density shares across games, averaged over the
  72 window hours. Games leave the chart ~28-30 days after creation, so a
  soft age-out factor (from details.created when present, else from the
  first-seen date) fades them out. Mass left unnamed at each place grows with
  horizon: brand-new games can enter the chart and win, and the unnamed share
  is the only cover for them.

Standard library only. No network, no clock, no randomness: two runs on the
same history write the same file byte for byte.
"""

import json
import math
import os
from datetime import datetime, timezone

# Tuned on walk-forward backtests over the public chart archive
# (19 cuts, Oct 30 - Nov 7 2026; mean log score -38.00 vs -43.51 baseline).
PARAMS = {
    "candidate_days": 10,    # how long a game stays a candidate after last seen
    "vel_lookback_h": 36,    # rank/player regression window (hours)
    "vel_halflife_h": 24,    # exponential weight half-life (hours)
    "beta_play": 0.5,         # player-growth weight in rank drift (ranks/hour)
    "w_long": 0.2,           # weight of the since-first-seen climb rate in drift
    "tau_v": 12.0,           # momentum decay time constant (hours)
    "s0": 2.0,               # rank spread at h=0
    "s1": 0.6,               # rank spread growth per sqrt(hour)
    "u0": 0.05,              # unnamed mass at h=0
    "umax": 0.30,            # unnamed mass late in the window
    "tau_u": 24.0,           # unnamed-mass growth time constant (hours)
    "tt_bonus": 0.5,         # boost for games also in Top Trending
    "age_limit_days": 29.0,  # chart age-out (days after creation)
    "max_rows": 30,          # named games per place
}


def parse_time(s):
    # ISO 8601 UTC, with or without fractional seconds.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).timestamp()


def wlinreg(xs, ys, ws):
    """Weighted least-squares slope and intercept of y on x."""
    sw = sum(ws)
    if sw <= 0 or len(xs) < 2:
        return 0.0, (ys[0] if ys else 0.0)
    mx = sum(w * x for w, x in zip(ws, xs)) / sw
    my = sum(w * y for w, y in zip(ws, ys)) / sw
    sxx = sum(w * (x - mx) ** 2 for w, x in zip(ws, xs))
    if sxx <= 0:
        return 0.0, my
    sxy = sum(w * (x - mx) * (y - my) for w, x, y in zip(ws, xs, ys))
    b = sxy / sxx
    return b, my - b * mx


def norm_pdf(z):
    return math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)


def load_history(input_dir):
    snaps = []
    path = os.path.join(input_dir, "history.ndjson")
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                snaps.append(json.loads(line))
    snaps.sort(key=lambda s: s["at"])
    return snaps


def build_series(snaps):
    """Per-game time series from the snapshots."""
    series = {}
    tt_best = {}
    for s in snaps:
        t = parse_time(s["at"])
        for r in s.get("up_and_coming") or []:
            uid = r["universe_id"]
            g = series.setdefault(uid, {"times": [], "ranks": [], "plays": [],
                                        "name": r.get("name") or "",
                                        "first": t, "created": None})
            g["times"].append(t)
            g["ranks"].append(r["rank"])
            g["plays"].append(max(r.get("playing") or 0, 1))
            if r.get("name"):
                g["name"] = r["name"]
        for r in s.get("top_trending") or []:
            uid = r["universe_id"]
            if uid not in tt_best or r["rank"] < tt_best[uid]:
                tt_best[uid] = r["rank"]
        det = s.get("details") or {}
        for uid_s, d in det.items():
            try:
                uid = int(uid_s)
            except (TypeError, ValueError):
                continue
            if uid in series and d and d.get("created"):
                series[uid]["created"] = parse_time(d["created"])
    return series, tt_best


def forecast(snaps, task, p):
    places = int(task.get("places", 10))
    window = task.get("window") or {}
    horizon = int(window.get("slots", 72)) * int(window.get("slot_minutes", 60)) // 60
    horizon = max(horizon, 1)
    t0 = parse_time(snaps[-1]["at"])
    series, tt_best = build_series(snaps)
    last = snaps[-1].get("up_and_coming") or []
    last_rank = {r["universe_id"]: r["rank"] for r in last}

    # Candidate pool: games seen recently enough to still matter.
    cand = {}
    for uid, g in series.items():
        if (t0 - g["times"][-1]) / 3600.0 <= p["candidate_days"] * 24:
            cand[uid] = g

    # Features per candidate.
    feats = {}
    for uid in sorted(cand):
        g = cand[uid]
        times, ranks, plays = g["times"], g["ranks"], g["plays"]
        idx = [i for i, t in enumerate(times)
               if (t0 - t) / 3600.0 <= p["vel_lookback_h"]]
        if len(idx) >= 2:
            xs = [(times[i] - t0) / 3600.0 for i in idx]
            ws = [math.exp((times[i] - t0) / 3600.0 / p["vel_halflife_h"]
                           * math.log(2)) for i in idx]
            v_rank, _ = wlinreg(xs, [ranks[i] for i in idx], ws)
            v_play, _ = wlinreg(xs, [math.log(plays[i]) for i in idx], ws)
            npts = len(idx)
        else:
            v_rank, v_play, npts = 0.0, 0.0, len(idx)
        r0 = last_rank.get(uid)
        if r0 is None:
            r0 = ranks[-1] + 5 + 0.5 * ((t0 - times[-1]) / 3600.0)
        v = v_rank - p["beta_play"] * v_play * 30.0
        if npts < 3:
            v = -p["beta_play"] * v_play * 30.0
        # Long-window climb rate since first seen: a game that climbed a long
        # way since it entered the chart keeps some of that surge. Blended in
        # lightly: it helps the two most recent windows, costs little on the
        # 19-cut walk-forward, and is measured on dense hourly data in the
        # final. (A heavier blend won the practice window but lost on average,
        # so it was rejected as a one-window overfit.)
        span_h = max((t0 - g["first"]) / 3600.0, 1.0)
        v_long = (ranks[0] - r0) / span_h
        v = (1.0 - p["w_long"]) * v + p["w_long"] * v_long
        feats[uid] = {"r0": r0, "v": v, "first": g["first"],
                      "created": g["created"], "name": g["name"],
                      "tt": tt_best.get(uid)}

    # Hourly projection, averaged over the window.
    acc = {k: {} for k in range(1, places + 1)}
    exp_rank = {}
    for h in range(1, horizon + 1):
        u = p["u0"] + (p["umax"] - p["u0"]) * (1.0 - math.exp(-h / p["tau_u"]))
        sigma = p["s0"] + p["s1"] * math.sqrt(h)
        dens = {}
        for uid in sorted(feats):
            f = feats[uid]
            disp = f["v"] * p["tau_v"] * (1.0 - math.exp(-h / p["tau_v"]))
            mu = f["r0"] + disp
            mu = 1.0 if mu < 1.0 else (110.0 if mu > 110.0 else mu)
            pres = 1.0
            if f["created"] is not None:
                rem = f["created"] + p["age_limit_days"] * 86400.0 - (t0 + h * 3600.0)
                if rem <= 0:
                    pres = 0.0
                elif rem < 86400.0:
                    pres = rem / 86400.0
            else:
                rem = f["first"] + 28.0 * 86400.0 - (t0 + h * 3600.0)
                if rem <= 0:
                    pres = 0.0
                else:
                    pres = min(1.0, rem / (28.0 * 86400.0) * 2.0)
            boost = 1.0
            if f["tt"] is not None and f["tt"] <= 20:
                boost = 1.0 + p["tt_bonus"] * (21 - f["tt"]) / 20.0
            dens[uid] = (mu, sigma, pres, boost)
            exp_rank[uid] = exp_rank.get(uid, 0.0) + mu * pres / horizon
        for k in range(1, places + 1):
            tot = 0.0
            vals = {}
            for uid in sorted(dens):
                mu, sig, pres, boost = dens[uid]
                if pres <= 0:
                    continue
                d = norm_pdf((k - mu) / sig) / sig * pres * boost
                vals[uid] = d
                tot += d
            if tot <= 0:
                continue
            for uid, d in vals.items():
                acc[k][uid] = acc[k].get(uid, 0.0) + (d / tot) * (1.0 - u) / horizon

    # Rows: top max_rows games per place; keep each place's sum <= 1.
    probs = []
    for k in range(1, places + 1):
        items = sorted(acc[k].items(), key=lambda kv: (-kv[1], kv[0]))[: p["max_rows"]]
        rows = [(uid, round(v, 6)) for uid, v in items if v > 1e-6]
        s = sum(v for _, v in rows)
        if s > 1.0:
            rows = [(uid, round(v * (1.0 - 1e-6) / s, 6)) for uid, v in rows]
        for uid, v in rows:
            probs.append({"universe_id": uid, "place": k, "p": v})

    # top10: lowest expected rank first, tie-broken by total named probability.
    tot_p = {}
    for row in probs:
        tot_p[row["universe_id"]] = tot_p.get(row["universe_id"], 0.0) + row["p"]
    order = sorted(feats, key=lambda u: (exp_rank.get(u, 999.0), -tot_p.get(u, 0.0), u))
    top10 = [u for u in order if tot_p.get(u, 0.0) > 0][:places]
    if len(top10) < places:  # fallback: fill from the last chart's order
        for r in sorted(last, key=lambda r: r["rank"]):
            if r["universe_id"] not in top10:
                top10.append(r["universe_id"])
            if len(top10) >= places:
                break
    return {"probabilities": probs, "top10": top10[:places]}


def main():
    input_dir = os.environ.get("MAKEFUN_INPUT_DIR") or "/input"
    output_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    with open(os.path.join(input_dir, "task.json"), "r", encoding="utf-8") as f:
        task = json.load(f)
    snaps = load_history(input_dir)
    result = forecast(snaps, task, PARAMS)
    out_path = os.path.join(output_dir, task.get("output", "forecast.json"))
    os.makedirs(output_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(result, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
