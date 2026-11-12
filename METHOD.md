# Method

## Data sources

- The only input is what the grader gives the program: `/input/history.ndjson`
  (hourly snapshots of Roblox's Up-and-Coming chart — rank, universe id, name,
  player count — plus the Top Trending and Top Playing Now charts of the same
  reads and the up-and-coming games' `games/v1` details where the recorder
  read them) and `/input/task.json` (places, window, output file).
- Tuning used the public archive the kit's practice instance is built from,
  [Kenny-Dhub/roblox-snapshots](https://github.com/Kenny-Dhub/roblox-snapshots)
  (MIT, `data/discover/latest.json` at each commit): 50 reads, Oct 30 – Nov 12
  2026. The first 34 reads are the practice history; the next 10 are the
  practice window. The local scorer was validated by reproducing the house
  baseline's published practice score exactly (−43.512039, 6.4 hits, 53.5
  agreement).

## What the chart does

Up-and-Coming lists games published in the last 28 days, sorted by user
growth. It churns fast: in the archive's 44 consecutive read pairs, the top 10
changed in 42 (median 6 places). The #1 at the close of the practice history
was #1 in none of the 10 window reads; the window's later #1s were a game
ranked #29 at close (Sweep The Moon) and a game nowhere in the history at all
(Do Not Stop.). Two facts drive the design:

1. The top games are sticky for the first ~24 h, then climbers and brand-new
   games take over. The score is the mean over all window reads, so the
   forecast must be the average of the hourly distributions, not a snapshot.
2. Brand-new winners are unpredictable from the history. The only cover for
   them is the unnamed share: what a place leaves unnamed is spread equally
   over every game on that read's chart the forecast did not name at that
   place — including games that were not on the chart at all when the
   forecast was written.

## Features per game

- **Rank velocity**: weighted least-squares slope of rank on time over the
  last 36 h, weights decaying with a 24 h half-life. Negative = climbing.
- **Player growth**: slope of log(player count) on time over the same window.
  The sort is by user growth, so this enters the drift as
  `v = v_rank − 0.5 · v_play · 30`.
- **Climb since first seen**: `(rank at first appearance − rank now) / hours
  since first appearance`, blended at weight 0.2. A game that surged into the
  chart keeps some of that surge.
- **Top Trending presence**: games also in the Top Trending top 20 get a
  small density boost (they are stickier).
- **Age**: games leave the chart ~28–30 days after creation (verified against
  the games that vanished from the chart in the window). With
  `details.created` present the fade starts at creation + 29 days; without it
  the first-seen date is the proxy (a game first seen F exits uniformly in
  [F, F + 28 d]).

## Ranking logic

For each window hour h (1–72): projected mean rank
`μ = clamp(r0 + v · 12 · (1 − exp(−h/12)), 1, 110)`, spread
`σ = 2.0 + 0.6 · √h`, presence from the age factor. The density of game i at
place k is the Gaussian density at k, times presence and the trending boost.
Per place, densities are normalized to sum to `1 − u(h)`, where the unnamed
mass `u(h)` grows from 0.05 to 0.30 with a 24 h time constant — early hours
are mostly the games already on the chart, late hours leave room for games
nobody has seen yet. The forecast averages the hourly distributions. Each
place names its top 30 games; each place's sum stays ≤ 1 (the rest is the
unnamed share). `top10` orders games by expected rank (presence-weighted mean
μ), tie-broken by total named probability.

## Predicted top 10 (practice window, history to Nov 7 23:00 UTC)

1. Survive Your Ideas — #1 at close, 57.5k playing; stayed top 6 all window.
2. South Hell [HORROR] — #2 at close; #1 in 4 of the 10 window reads.
3. [🎩] Ragdoll Research — #4 at close with strong momentum; #1 once.
4. Ragdoll Physics 🩸 — #3 at close, very sticky at #3–5.
5. [HIPPO🦛] FERAL 🐺 Animal Survival — #9 at close, climbed to #5.
6. [MULTIPLAYER] Ragdoll Realism — #12 at close, held #9–11 all window.
7. 13 Days to Escape [ALPHA] — #7 at close, stayed #6–7.
8. 🍦Cozy Lucky Scoop Order — #5 at close, held #5–7.
9. WRECKED [Realistic Crashes] — #11 at close; persistence pick, faded late.
10. Tesla Roadster Chase — #6 at close; persistence pick, faded late.

The `top10` is only the tie-break. The log score comes from the
probabilities: they give real mass to climbers the top 10 ordering misses
(e.g. Impact Lab, first seen 4 h before the close at #75, gets ~0.02 at place
10) and leave ~22% of every place unnamed for brand-new entrants.

## What was tried and rejected

- **Heavier surge blend (weight 0.5)**: practice window −35.22, but
  walk-forward mean −39.32 — a one-window overfit driven by a single climber.
  Rejected; weight 0.2 was kept (−37.95 practice, −38.12 walk-forward).
- **More named rows per place (40–50)**: worse on both walk-forward and
  practice; the extra rows dilute the places that matter. Kept at 30.
- **Pure persistence** (the house baseline): −43.51. The momentum + growth
  model beats it by 5.6 nats on the practice window.

## Final run

In the final, the history is the archive's 45 reads plus the house recorder's
hourly reads to the deadline, with `details` (including `created`) present —
the age-out factor then uses exact creation dates, and velocities are measured
on dense hourly data. The program reads the window (72 hourly slots) from
`task.json` rather than hard-coding it.
