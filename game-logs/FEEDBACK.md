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

## Milestone A2 — move ordering (MVV-LVA)

**Bug found during timing re-check:** `order_moves` crashed (`KeyError: 6`) the first time a
king was the *attacker* in a capture — `PIECE_VALUE` deliberately has no entry for the king
(it isn't material to count in the evaluation), but a king capturing something is a completely
normal legal move. Fixed by adding a separate `ATTACKER_VALUE` table (`PIECE_VALUE` plus a
large placeholder for the king) used only for ordering, not evaluation. Exactly the kind of edge
case `docs/IDEAS.md` warns about ("crashing on an edge case... the rare paths show up") — caught
by testing before it ever reached a real game.

**Timing, same two reference positions as A1 (opening move, and the busier middlegame FEN
`r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 4 4`):**

| Depth | Opening move | Middlegame move |
|---|---|---|
| 3, no ordering (A1) | 0.204s | 1.014s |
| 4, no ordering (A1) | 0.768s | 2.173s |
| 3, **with ordering** | 0.131s | 0.209s |
| 4, **with ordering** | 0.407s | 1.427s |

Ordering cut the depth-3 middlegame move by ~5x. Depth 4 also improved (2.17s → 1.43s) but
tested it anyway to be sure rather than trust the estimate:

| Depth | Opponent | Clock | Score | Record | Flags |
|---|---|---|---|---|---|
| 4 + ordering | `baselines/greedy` | fast (10s+0.1s) | 30.0% | +3 =0 -7 | 7/10 |

**Depth 4 is still not safe**, even with ordering — worse flag rate than depth 3 had *without*
ordering in A1 (1/10). Kept `DEPTH = 3`.

**Depth 3 + ordering results (fast control, 10s+0.1s):**

| Opponent | Score | Record | Flags |
|---|---|---|---|
| `versions/v1-alphabeta` (this milestone's own predecessor, head-to-head) | 100.0% | +10 =0 -0 | 3/10 (all on v1's side) |
| `baselines/greedy` | 95.0% | +9 =1 -0 | 0/10 |

Beating `v1-alphabeta` 10/10 is the clean "did this change help" signal `docs/IDEAS.md` asks
for — 7 wins by actually outplaying it, and notably the other 3 came from **v1 itself flagging**,
not us: at the *same* depth (3), v1's unordered search is slow enough to lose on time against
v2's ordered one, direct evidence ordering buys real speed, not just move quality. Score against
`greedy` also improved (85.0%→95.0%) with zero flags this time (down from 1/10 in A1).

| `baselines/minimax` | 70.0% | +5 =4 -1 | 0/10 |

Against `minimax`, ordering is the single biggest jump of this milestone: **20.0% → 70.0%**,
and the flag rate that dominated A1's minimax result (5/10) dropped to **0/10**. Four of the ten
games ended in threefold repetition, not a decisive result — consistent with `docs/IDEAS.md`'s
note that the referee auto-claims repetition, so a level position can safely resolve as a draw
rather than risk something worse.

**Competition-clock sanity check (120s+0.5s), same as A1's methodology:**

| Opponent | Score | Record | Flags |
|---|---|---|---|
| `baselines/minimax` | 66.7% | +2 =4 -0 | 0/6 |

Up from A1's 58.3% with the same opponent/clock, still zero flags. No losses at all this time
(4 draws, 2 wins) — consistent with the fast-control picture: ordering made the engine both
faster and stronger, not a speed/strength trade-off.

### A2 summary

Move ordering (MVV-LVA) was worth doing on every axis measured:

| Metric | A1 (no ordering, depth 3) | A2 (ordering, depth 3) |
|---|---|---|
| vs `versions/v1-alphabeta` | — | 100.0% (+10 =0 -0) |
| vs `greedy`, fast clock | 85.0%, 1/10 flags | 95.0%, 0/10 flags |
| vs `minimax`, fast clock | 20.0%, 5/10 flags | 70.0%, 0/10 flags |
| vs `minimax`, competition clock | 58.3%, 0/6 flags | 66.7%, 0/6 flags |
| Middlegame move time (depth 3) | 1.014s | 0.209s |

Depth 4 was re-tried with ordering in place (hoping the speedup would make it safe) but still
flagged 7/10 games at fast control — worse than depth 3 ever was — so it stays out until real
time management (A4) exists. `DEPTH = 3` remains the setting, but is now meaningfully stronger
and safer at the same depth than before this milestone.

## Milestone A3 — transposition table

Added a proper TT (`EXACT`/`LOWERBOUND`/`UPPERBOUND` flags, not a naive "always trust the
cache" version — see the code comment block in `agent.py` for why that distinction matters for
correctness, not just speed). Sanity-checked first: still returns only legal moves across a
mainline position, a busy middlegame position, and a bare king+pawn endgame; TT populated with
1,234 / 1,787 / 46 entries respectively on those single calls.

**Depth 4, third attempt** (previously ruled out in A1 without ordering, and in A2 with ordering
alone):

| Depth | Middlegame move time (cold TT) |
|---|---|
| 3 | 0.193s |
| 4 | 0.973s (down from 1.427s in A2 - ordering + TT together, real improvement) |

| Depth | Opponent | Clock | Score | Record | Flags |
|---|---|---|---|---|---|
| 4 + ordering + TT | `baselines/greedy` | fast (10s+0.1s) | 30.0% | +3 =0 -7 | 6/10 |

**Still not safe.** Better than A2's depth-4 attempt in raw timing, but the flag rate barely
moved (7/10 → 6/10) — `DEPTH` stays at 3. Real time management (A4) remains the actual fix; no
depth increase is going to be safe against a clock the search doesn't check.

**Head-to-head vs `versions/v2-ordering`, depth 3 (both versions) — a real scare, then a lesson:**

A first batch of 10 games came back **25.0%** (+1 =3 -6) — alarming, since a *correctly*
implemented TT should never make an engine play worse at a fixed, equal depth, only faster (it
doesn't change what gets searched, only how much redundant work is skipped). Before accepting
that number, verified directly: computed every one of the ~30 legal root moves' scores for both
versions on the exact position where their final move choices had diverged. **Every score
matched exactly** between v2 and v3, including the full set of moves tied for best (10 different
moves tied at the same score in that position) — proof the TT logic itself is correct, not
subtly corrupting the search.

With move-scoring ties that common at this depth/evaluation coarseness, the *actual* move played
among tied options comes down to random tie-breaking, which is independent per process/game —
meaning two functionally-identical engines can produce a lopsided-looking small-sample record
purely by chance. Re-ran at 40 games to check:

| Games | Score | Record |
|---|---|---|
| 10 | 25.0% | +1 =3 -6 |
| 40 | **47.5%** | +13 =12 -15 |

47.5% at 40 games is a statistical coin flip — confirms the TT is exactly what it should be:
**strength-neutral, purely a speed optimization at this fixed depth.** This is `docs/IDEAS.md`'s
"two games tell you nothing" warning realized directly: the 10-game sample alone would have
wrongly suggested shipping a regression.

**vs baselines, fast control (10s+0.1s):**

| Opponent | Score | Record | Flags |
|---|---|---|---|
| `baselines/greedy` | 90.0% | +9 =0 -1 | 0/10 |
| `baselines/minimax` | 65.0% | +4 =5 -1 | 1/10 |

Both within normal sample-to-sample variance of A2's numbers (95.0%/0 flags and 70.0%/0 flags
respectively) — consistent with the head-to-head finding above: TT isn't meaningfully changing
strength at this fixed depth, small-sample noise explains the wobble either way.

**Competition-clock sanity check (120s+0.5s):**

| Opponent | Score | Record | Flags |
|---|---|---|---|
| `baselines/minimax` | 66.7% | +2 =4 -0 | 0/6 |

Identical to A2's result on this exact matchup/clock (66.7%, +2 =4 -0, 0/6 flags) — about as
clean a confirmation as it gets that this milestone changed speed and safety margin, not
playing strength.

### A3 summary

Depth 4 remains unsafe even with TT added on top of ordering (6/10 flags, barely better than
A2's 7/10) — `DEPTH` stays at 3. The TT itself is implemented correctly (verified by direct
move-by-move score comparison against v2, not just game outcomes) and is strength-neutral at
this fixed depth, exactly as a correct transposition table should be — its value is real but
currently invisible in these numbers: faster computation per position (freeing up time-budget
headroom for milestone A4) and cross-move memory that will matter more once search gets deeper
or slower components (like B1's numba evaluation) are added. The 10-vs-40-game discrepancy in
the head-to-head (25.0% → 47.5%) is this milestone's best concrete lesson in why
`docs/IDEAS.md` insists on real sample sizes before trusting a result.

## Milestone A4 — iterative deepening + real time management

**A real bug caught before it ever reached a game:** the first version checked the clock only
every 1024 nodes searched (a number that "sounded reasonable"). Measured directly: 1024 nodes
took ~110ms here, because each node (move generation, an evaluation, a TT lookup, all in
Python) costs roughly 0.1ms. That 1024-node interval was tuned for a completely different
engine's speed - a compiled engine doing millions of nodes/sec would treat 1024 nodes as
imperceptible; ours doesn't. Concretely, a call with `time_left_ms=1` (i.e. essentially no
budget at all) still took **115ms** to return, because it ran to the first checkpoint at node
1024 regardless of the deadline already being in the past. Fixed by checking every single node
instead - a `time.monotonic()` call costs a handful of nanoseconds against a ~100-microsecond
node, so the overhead is negligible, and it closes the gap entirely.

**Before/after, same reference position, across a range of budgets:**

| `time_left_ms` | Actual time (before fix) | Actual time (after fix) |
|---|---|---|
| 1 | 115.57ms | 0.42ms |
| 10,000 | 195.33ms | 107.12ms (target ~100ms) |
| 60,000 | 1391.87ms | 1389.38ms (target ~1350ms) |

This is exactly the kind of thing docs/IDEAS.md means by "leave a margin... the watchdog does
not forgive": a plausible-sounding constant, unverified, would have meant the agent could
overshoot a tight remaining clock by ~100ms with no way to notice — small in isolation, but
exactly the failure mode that causes a flag in a genuinely close-on-time endgame.

**Second bug, caught by the same discipline of measuring instead of assuming:** the initial
`SAFETY_MARGIN_MS = 150` was itself an unverified guess, and it was actively harmful. A 30-game
head-to-head against `versions/v3-tt` (fixed depth 3, no time awareness) came back a real
40.0% (+6 =12 -12) — zero flags either side, but a genuine strength gap this time, not sampling
noise. Traced why directly: under realistic fast-control budgets (~100-170ms after the 150ms
margin), the search only ever completed **depth 2**, never depth 3, because depth 3 (now
~150-200ms post-A2/A3 optimisation) looked too risky to attempt under such a thin allowance.
Meanwhile v3 always searches to depth 3 unconditionally - so v4 was playing a full ply shallower
than v3 for most of every game, a real weakness, not a bug in the time-management logic itself.

Measured the *actual* overshoot past the deadline with per-node checking directly (bypassing the
budget formula, setting exact deadlines from 50ms to 1000ms): overshoot stayed under 1ms in
every case. The 150ms margin was roughly 150x more conservative than the real risk it was meant
to cover. Reduced to `SAFETY_MARGIN_MS = 50` (still a healthy ~50x buffer over the measured
overshoot) and re-checked: depth 3 now completes in most realistic early/mid-game fast-control
positions (2 of 3 traced cases, versus 0 of 3 before), with the remaining case a genuinely
borderline position rather than a systemic problem - exactly the adaptive behaviour time
management is supposed to produce, unlike v3's blind fixed-depth gamble.

**Re-run with `SAFETY_MARGIN_MS = 50`, 30 games vs `versions/v3-tt`:** 50.0% exactly (+10 =10
-10), zero flags either side. Confirms the fix: v4 now matches v3's strength precisely at fast
control, while adding the safety of adapting depth to the actual clock instead of gambling on a
fixed one - the real payoff shows up in positions where v3's fixed depth-3 gamble would fail
(deeper into a long, complex game) rather than in this average-case matchup.

**vs `baselines/greedy`, fast control (20 games):** 97.5% (+19 =1 -0), zero flags — matches
A2/A3's numbers on this matchup (95.0%/90.0%), confirming no regression there either.

**vs `baselines/minimax`, fast control (20 games):** 57.5% (+6 =11 -3), zero flags. A little
lower than A2/A3 (70.0%/65.0%) but within normal variance for a match this heavy on draws (11 of
20 by threefold repetition) - no flags either way is the number that actually matters here.

**vs `baselines/minimax`, competition clock (6 games):** 58.3% (+1 =5 -0), zero flags, **zero
losses** (5 draws, 1 win). In line with A2/A3's 66.7% on this exact matchup/clock.

### A4 summary

Iterative deepening + real time management replaces the fixed `DEPTH = 3` with a search that
adapts to the actual clock, checked on every single node rather than periodically. Two real bugs
were found and fixed purely by measuring instead of guessing - a check-interval bug (1024 nodes
between clock checks, when each node costs ~0.1ms, meant a near-zero time budget could still take
~115ms) and an oversized safety margin (150ms reserved "just in case," when the real measured
overshoot with per-node checking is under 1ms) that was silently capping the search at depth 2
for most of every game. Fixing both recovered a head-to-head score against `versions/v3-tt` from
40.0% back to exactly 50.0% - full parity with a fixed-depth-3 engine, while adding the safety of
never gambling on a depth the clock can't afford:

| Opponent | Clock | Score | Record | Flags |
|---|---|---|---|---|
| `versions/v3-tt` | fast (10s+0.1s) | 50.0% | +10 =10 -10 | 0/30 |
| `baselines/greedy` | fast (10s+0.1s) | 97.5% | +19 =1 -0 | 0/20 |
| `baselines/minimax` | fast (10s+0.1s) | 57.5% | +6 =11 -3 | 0/20 |
| `baselines/minimax` | competition (120s+0.5s) | 58.3% | +1 =5 -0 | 0/6 |

Zero flags across every batch, on both clocks, against both baselines and its own predecessor -
the first milestone where that's true everywhere it's been tested. This doesn't yet show up as a
strength jump (matching, not beating, the fixed-depth version at this sample size/clock), because
this milestone's actual payoff is safety and adaptivity - going deeper when the clock allows,
never gambling when it doesn't - which the numbers above don't fully capture at only 76 games and
no fixed-depth agent ever actually flagging in this batch to demonstrate the difference against.
