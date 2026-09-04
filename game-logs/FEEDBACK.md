# Test feedback log

Running notes on what testing reveals, milestone by milestone. Personal review only — never
read by `harness/package.py`, so nothing here reaches `submission.zip` (only `agent.py` and
declared weights do). Committed to the repo for backup/reference; see the sibling `.pgn` files
and `summary.json` per batch for the underlying games.

## Milestone A1 — alpha-beta negamax (fixed depth)

**Depth 4 → 3, and why:** at depth 4 with no move ordering, a single middlegame move measured
~2.2s locally. An arena batch at fast control (10s + 0.1s) lost all 20/20 games by flagging —
the search was simply too slow to survive that clock, let alone leave room for actual play.
Dropping to depth 3 (~4x faster per the same measurement) fixed most, not all, of it.

**Depth 3 results (fast control, 10s + 0.1s):**

| Opponent | Games | Score | Record | Flags |
|---|---|---|---|---|
| `baselines/greedy` | 10 | 85.0% | +8 =1 -1 | 1/10 |
| `baselines/minimax` | 10 | 20.0% | +0 =4 -6 | 5/10 |

Two things stand out:
- Against `greedy`, depth-3 alpha-beta is clearly much stronger (85% vs. a baseline greedy
  itself beats random ~90%+ of the time) — this is the expected win from real search depth.
- Against `minimax`, it's *losing* overall, and half the games end in a flag, not a real loss.
  minimax's play (material + mobility eval) seems to keep positions more open/complex for
  longer than greedy's play does, and our search — still with zero move ordering — is far more
  expensive in those positions. This isn't "minimax outplays us"; it's "we run out of clock
  against it more often than not."

**Resolved: it's specific to the fast test clock.** At the real 120s+0.5s competition clock,
depth-3 alpha-beta had zero flags across 7 games (1 single game + a 6-game batch):

| Opponent | Clock | Games | Score | Record | Flags |
|---|---|---|---|---|---|
| `baselines/minimax` | competition (120s+0.5s) | 6 | 58.3% | +3 =1 -2 | 0/6 |

So the fast 10s+0.1s control the plan intended to use for high-volume testing (per
`docs/IDEAS.md`: "a change worth 3% needs hundreds of games to see") is currently **not safe to
use** for this agent — the flag risk it exposes is a test-harness artifact of an unmanaged fixed
depth, not a reflection of real competition risk. Until milestone A4 (time management) lands:
volume testing should run at the real 120s+0.5s clock, at real wall-clock cost per batch, or
depth should be dropped further for fast-control testing specifically.

Either way this confirms `docs/IDEAS.md`'s own warning that flagging is "the most common
self-inflicted" loss, and moves real time management from "do it eventually" (milestone A4) to
"don't consider any version of this agent safe to submit without it," even though depth 3
survives the competition clock today. A 58.3% score against minimax (not a rout) also suggests
depth 3 alone isn't yet a decisive improvement over minimax's own depth-2 - move ordering
(milestone A2) is what's supposed to buy back the depth we gave up going from 4 to 3.

Representative games from all of the above are viewable on the Scoresheet board-viewer
artifact (link shared separately - republish it with updated GAMES entries after future
batches).
