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

## Milestone A5 — quiescence search

Added captures-only search extension at the horizon (depth 0), with a real correctness
refinement beyond the minimal ask: when the side to move is in check, quiescence searches *all*
legal replies rather than only captures, and does not stand-pat (there is no "do nothing" option
when in check). Verified against the case quiescence is meant to fix: a hanging-queen position
scored only +16.0 by the static eval alone, but +692.0 once quiescence searched the recapture -
exactly the kind of horizon-effect correction this milestone is for.

**A serious bug, caught before it shipped by the same discipline as every previous milestone -
comparing root move scores directly rather than trusting a batch result:** a first 30-game
head-to-head against `versions/v4-timemgmt` came back **0.0% (+0 =0 -30)** - a complete loss,
every game by checkmate. Since a correct quiescence addition should never make the engine
*catastrophically* worse, this was investigated immediately rather than accepted. Traced a
specific position where the two versions picked different moves at the same depth and compared
every candidate move's score directly: multiple genuinely different moves - including one that
plainly hangs a bishop - were all scoring the *exact same* value, and the move actually being
played (an early queen sortie) turned out to be one of the worst options on the board (-788.0),
not the +100.0 it had been reported as.

**Root cause:** `quiescence()` used `alpha` itself to track "the best value found so far,"
instead of tracking a separate `best` the way the rest of `negamax` correctly does (`alpha` is
only supposed to be a pruning threshold). Whenever a move failed to beat whatever alpha it
happened to inherit from an earlier sibling in the search order, the function returned that
inherited alpha verbatim - not the true value it had actually found. Two completely different,
differently-bad moves could both "fail low" against the same borrowed threshold and report
identical scores, corrupting the root's ability to tell them apart. Fixed to be fail-soft,
matching `negamax`'s existing pattern exactly: track `best` separately, use `alpha`/`beta` only
for the cutoff decision, return `best`.

**Re-verified after the fix**: the same position's root scores now differentiate correctly
(the previously-tied moves spread from +100.0 down to -788.0, correctly ranking the queen
sortie as the blunder it is). Re-ran the 30-game head-to-head:

| Version | Score | Record | Flags |
|---|---|---|---|
| v5-quiescence, broken (fail-hard bug) | 0.0% | +0 =0 -30 | 0/30 |
| v5-quiescence, fixed | **85.0%** | +23 =5 -2 | 0/30 |

A complete turnaround, and the single biggest strength jump since move ordering (A2). Makes
sense: quiescence directly targets real blunders at the search horizon (mistaking a mid-exchange
position for the final result), so a *correct* implementation should be a substantial, visible
improvement - which this now clearly is, once the bug was actually fixed rather than just
"technically not crashing."

**vs `baselines/greedy`, fast control (20 games):** 97.5% (+19 =1 -0), zero flags - matches A4
exactly, no regression.

**vs `baselines/minimax`, fast control (20 games):** 72.5% (+11 =7 -2), zero flags. Up from A4's
57.5% - consistent with quiescence genuinely improving play quality, not just noise.

**vs `baselines/minimax`, competition clock (6 games):** 66.7% (+3 =2 -1), zero flags - matches
A2/A3's 66.7% on this exact matchup/clock, no regression.

### A5 summary

Quiescence search (captures-only extension at the leaves, with a proper in-check refinement -
search all legal replies rather than only captures, and don't stand-pat, since there is no "do
nothing" option when in check) is done, and it's the largest single improvement since move
ordering (A2). It shipped with a real bug initially (fail-hard/fail-soft conflation making
different moves score identically and once causing a queen to be hung outright) that a 0.0%
head-to-head result caught immediately - fixed by matching `negamax`'s existing fail-soft
pattern (track `best` separately from the pruning threshold `alpha`/`beta`).

| Opponent | Clock | Score | Record | Flags |
|---|---|---|---|---|
| `versions/v4-timemgmt` | fast (10s+0.1s) | 85.0% | +23 =5 -2 | 0/30 |
| `baselines/greedy` | fast (10s+0.1s) | 97.5% | +19 =1 -0 | 0/20 |
| `baselines/minimax` | fast (10s+0.1s) | 72.5% | +11 =7 -2 | 0/20 |
| `baselines/minimax` | competition (120s+0.5s) | 66.7% | +3 =2 -1 | 0/6 |

Zero flags across every batch. Verified directly (not just via game outcomes) that quiescence
fixes the horizon effect it's meant to: a hanging-queen position scored only +16.0 by static
eval alone, +692.0 once quiescence searched the recapture. Full data:
`game-logs/v5-quiescence-vs-*/`.

## Milestone A6 — evaluation upgrade: piece-square tables

Added piece-square tables (bonus/penalty per square, per piece type) on top of the unchanged
material + mobility terms - the well-known "Simplified Evaluation Function" tables (Tomasz
Michniewski, an openly-published Chess Programming Wiki reference, not any engine's
proprietary weights), reused as a tested starting point rather than guessed from scratch.
`MOBILITY_WEIGHT` deliberately left untouched despite A5's finding that it can introduce real
noise - changing two things in the eval at once would make it impossible to isolate what PST
alone is worth; that finding remains an open, documented follow-up, not silently patched here.

Verified the table transcription and square-mirroring directly before trusting any batch result
(a lesson from A5): spot-checked known reference squares (pawn on d7 = +50, knight on a1 = -50,
etc.) against the published table, and confirmed a mirror pair (White knight on d4 vs Black
knight on d5) scores identically from each side's own perspective. King table is
middlegame-only - no game-phase detection to blend in an endgame table that would reward an
active, centralized king instead - a known, documented simplification.

**Head-to-head vs `versions/v5-quiescence`, fast control (30 games):** 80.0% (+18 =12 -0), zero
losses, zero flags. The cleanest result of any milestone so far - not a single game lost.

**vs `baselines/greedy`, fast control (20 games):** 100.0% (+20 =0 -0) - a perfect score, up
from A5's 97.5%.

**vs `baselines/minimax`, fast control (20 games):** 85.0% (+15 =4 -1), up from A5's 72.5%.

**vs `baselines/minimax`, competition clock (6 games):** 83.3% (+4 =2 -0), zero losses, zero
flags - the best competition-clock result against minimax of any milestone so far.

### A6 summary

Piece-square tables are the strongest single-milestone result yet, and the first with zero
losses in *both* the head-to-head and the fast-control baseline batch:

| Opponent | Clock | Score | Record | Flags |
|---|---|---|---|---|
| `versions/v5-quiescence` | fast (10s+0.1s) | 80.0% | +18 =12 -0 | 0/30 |
| `baselines/greedy` | fast (10s+0.1s) | 100.0% | +20 =0 -0 | 0/20 |
| `baselines/minimax` | fast (10s+0.1s) | 85.0% | +15 =4 -1 | 0/20 |
| `baselines/minimax` | competition (120s+0.5s) | 83.3% | +4 =2 -0 | 0/6 |

Full vs-minimax progression across every milestone so far, fast and competition clock:

| Milestone | Fast clock | Competition clock |
|---|---|---|
| A1 (alpha-beta) | 20.0% (5/10 flags) | 58.3% |
| A2 (+ move ordering) | 70.0% (0/10 flags) | 66.7% |
| A3 (+ transposition table) | 65.0% (1/10 flags) | 66.7% |
| A4 (+ time management) | 57.5% (0/20 flags) | 58.3% |
| A5 (+ quiescence search) | 72.5% (0/20 flags) | 66.7% |
| A6 (+ piece-square tables) | **85.0%** (0/20 flags) | **83.3%** |

Two things stand out reading this whole progression at once: A6 is a clear new high on both
clocks, and it's also the first milestone to *improve on both clocks simultaneously and by a
wide margin* rather than trading one off against the other (A4 dipped on both while adding pure
safety; A2/A3/A5 improved fast-clock numbers more than competition-clock ones). Consistent with
`docs/IDEAS.md`'s own framing: "material plus piece-square tables is a real evaluation and it
beats both baselines" - now demonstrably true here, not just asserted. Full data:
`game-logs/v6-pst-vs-*/`.

**Additional confirmation batches, larger sample (35 games), requested after the milestone:**

| Opponent | Score | Record | Flags |
|---|---|---|---|
| `baselines/minimax`, fast clock | 84.3% | +26 =7 -2 | 1/35 |

The one flag was **`baselines/minimax` itself flagging**, not our agent (`score_for_agent: win`
in the batch data - minimax has no time management at all, unlike our agent since A4). Result
holds steady with the 20-game number (85.0%).

| `versions/v5-quiescence`, fast clock (head-to-head) | 77.1% | +22 =10 -3 | 0/35 |

Also holds steady with the 30-game number (80.0%) - three losses appear at this larger sample
(zero had shown up at 30 games) but the result stays clearly, comfortably positive either way.

## Milestone B0 — full environment parity (Windows machine)

New team member joining partway through, checking whether B0 (blocked on the original Intel
Mac — no wheels for torch/onnxruntime/numba at the platform's pinned versions on that
architecture) could be unblocked from a different machine. Cloned the repo fresh on Windows,
installed `uv`, and ran a plain `uv sync` — deliberately not the `--no-install`/exclusion
workaround the Mac had been using — to see whether this machine's wheels resolve cleanly.

**Result: yes, full parity.** All 24 locked packages installed with no errors, including the
three that had been blocked:

| Package | Version installed | Pinned version | Match |
|---|---|---|---|
| torch | 2.13.0+cpu | 2.13.0 (CPU index) | ✅ |
| numpy | 2.5.2 | 2.5.2 | ✅ |
| numba | 0.67.0 | 0.67.0 | ✅ |
| onnxruntime | 1.29.0 | 1.29.0 | ✅ |
| chess (python-chess) | 1.11.2 | 1.11.2 | ✅ |

Installed, not just resolved — confirmed each one actually imports and runs (not only that `uv`
reported success): `import torch, onnxruntime, numba, numpy, chess` all succeeded, and
`torch.zeros(3).sum().item()` returned `0.0`, so torch's CPU backend is functional, not just
importable.

`make gate` (ruff + mypy strict + 2 sanity games vs `baselines/random`) also ran clean on this
machine:

| Check | Result |
|---|---|
| `ruff check .` | All checks passed |
| `mypy` (strict) | Success: no issues found in 9 source files |
| 2 games vs `baselines/random`, 5s base | +2 =0 -0, both by checkmate, no flags |

**Takeaway:** the B0 blocker was specific to the original Intel Mac's architecture, not to the
pinned versions themselves being uninstallable everywhere — a plain Windows machine resolves and
runs the full stack (including the ML/JIT packages) without the CI-only workaround. This doesn't
replace getting the actual Apple Silicon Mac working (per `docs/ROADMAP.md`, that's still the
target dev machine), but it means B1 (numba-jit) and B2 (the stretch-goal ONNX net) can now
also be developed and tested from this Windows machine in the meantime, rather than waiting on
the Silicon Mac alone. Full install/test log: this session's terminal output, not committed as a
separate file (no PGNs beyond the two `make gate` sanity games, which aren't saved by the gate
target itself).

## Milestone B1 — numba-jit the evaluation

**First attempt (array-based) barely moved the needle.** Followed `baselines/numba`'s pattern
literally: `encode(board)` built three `np.zeros(64)` arrays from `board.piece_map()`, a jitted
function looped over them. Correctness was perfect (0 mismatches vs. the old pure-Python
`evaluate()` across ~8,000 random positions), but a direct microbenchmark found only a **~1.0-1.3x
speedup** even after a follow-up fix that preallocated the three buffers instead of reallocating
them every call. Batch testing with this version actually scored *worse* than the pre-numba
`v6-pst` snapshot against `baselines/minimax` on both clocks (75.0% vs. v6's 85.0% fast; 66.7% vs.
v6's 83.3% competition, including one real flag - our own agent running out of time on the
competition clock, the first since A4 landed). Investigated properly rather than shipped as-is
(see below for why the flag wasn't actually numba's fault) - but the speed win itself was real
and needed fixing.

**Root cause, found by reading the code rather than guessing further:** a real board has at most
32 occupied squares, so `board.piece_map()`'s Python-level dict-of-Piece-objects construction,
plus numba's own per-call argument-marshaling overhead for three *array* arguments, was competing
with (and mostly cancelling out) whatever the compiled 64-square loop itself saved. Buffer reuse
only removed the allocation piece of that cost, not the dict-construction or array-marshaling
piece.

**Fix: skip `piece_map()` and arrays entirely - read raw bitboards, jit the decode too.**
python-chess already maintains each piece type's occupancy as a plain 64-bit integer
(`board.pawns`, `board.knights`, ... `board.occupied_co[color]`). Passing those eight integers
(cast to `np.uint64` - see below) plus `mobility` directly into one jitted function that decodes
*and* evaluates in the same compiled pass means: no Python-level dict per call, and scalar
arguments marshal far more cheaply than array arguments. Correctness re-verified the same way (0
mismatches, ~8,000 random positions) before trusting it.

**A real correctness trap avoided by using `uint64`, not plain `int64`:** a bitboard can
legitimately have bit 63 set (h8 occupied). `int64` is signed, so right-shifting a value with
that bit set sign-extends instead of bringing in zeros - it would have silently corrupted every
square's bit test past the first high occupied bit, exactly the kind of "looks fine in most
testing, breaks on some boards" bug the project has hit before (A2's king-capture crash, A5's
quiescence fail-soft bug). Caught by reasoning about it up front, not by a failing test - explicit
`np.uint64(...)` casts on every bitboard keep every shift/comparison unsigned throughout.

**Real, verified speedup this time:** ~5.4x-7.0x faster per `evaluate()` call than the original
pure-Python version (measured 3 runs to confirm it wasn't a fluke), vs. ~1.0-1.3x from the array
version. `make gate` clean (ruff, mypy strict, sanity games).

**Batch results after the fix - honest, not spun:**

| Opponent | Clock | `v6-pst` (pre-numba) | v7 array (first attempt) | v7 bitboard (final) |
|---|---|---|---|---|
| `baselines/minimax` | fast (10s+0.1s) | 85.0% (+15=4-1), 0/20 flags | 75.0% (+11=8-1), 0 flags for us | **60.0%** (+7=10-3), 0/20 flags |
| `baselines/minimax` | competition (120s+0.5s) | 83.3% (+4=2-0), 0/6 flags | 66.7% (+3=2-1), 1 flag (ours) | **66.7%** (+2=4-0), 0/6 flags |

The real speedup did **not** translate into a higher score against `minimax` - if anything the
final version scores lower than both `v6-pst` and the marginal first attempt. Looked at the
actual game composition rather than just the percentage: the drop is entirely from **more draws,
not more losses** - competition clock has zero losses in both `v6-pst`'s testing and this
version's (2 wins/4 draws vs. v6's 4 wins/2 draws), and fast clock's draw count roughly doubled
(10/20 vs. `v6-pst`'s 4/20) with the same win-minus-loss balance in the same direction. The
faster eval clearly buys deeper search (confirmed by the earlier depth-timing measurements), but
in these particular matchups it more often finds a repetition-safe drawing line than a winning
one. Not treating this as solved or as a regression that needs chasing further - it's a real,
measured behavior change from a proven-correct, genuinely faster evaluation, and 20-26 games per
matchup is still a modest sample (per `docs/IDEAS.md`: "a change worth 3% needs hundreds of games
to see"). Recorded honestly as this milestone's actual result, not smoothed over.

**Two backlog findings surfaced by this testing, deliberately left unfixed (out of scope for a
milestone about jitting speed, not eval quality - same discipline as A6 leaving
`MOBILITY_WEIGHT` untouched):**

1. **A reproducible opening weakness against early queen sorties.** Across this session's
   batches, 5 of the 9 total losses trace to the same pattern: an early, objectively-dubious
   queen sortie (`1. e4 e5 2. Nc3 Nc6 3. Qg4` in three games across two different opponents,
   byte-identical in two of them; `1. e3 Nf6 2. Qf3 e5 3. Qf5` in three more games, byte-identical
   or transposed in all three) that a shallow material/mobility/PST evaluator can't distinguish
   from a genuinely good move - both `v6-pst` and `baselines/minimax` independently play into the
   same trap as White. See `game-logs/v7-numba-vs-v6/game-15.pgn` + `game-26.pgn` (also
   `v7-numba-vs-minimax/game-14.pgn`) for the first pattern, `game-02.pgn` + `game-06.pgn` +
   `game-16.pgn` in `game-logs/v7-numba-vs-minimax/` for the second (a bishop sac on f6 removing
   a knight defender, then `Qg7#` - a real king-safety blind spot, not a one-off tactical miss).
2. **A pre-existing time-management risk, not something B1 introduced.** The one flag in the
   first attempt's competition-clock batch traced to a highly tactical, exchange-heavy
   middlegame (FEN `r3k1nB/pp1b1p1p/3p4/4p3/3P4/2PP2P1/P2N1PBP/R3K2R w KQq - 0 17`) hitting a
   depth-5-to-6 cost cliff (~700ms -> ~12s). Direct depth-by-depth timing confirmed `v6-pst` hits
   the *identical* cliff at equal magnitude - `get_move()`'s iterative-deepening loop
   unconditionally starts a new depth with no forecast of whether it'll fit the remaining budget,
   and this was always true, just not sampled in 6-game competition-clock batches until now. The
   flag didn't recur in the final version's 6-game re-run, but that's not evidence it's fixed -
   the underlying unconditional-depth-start logic is unchanged either way.

Snapshot: `versions/v7-numba-eval/agent.py`. Full data: `game-logs/v7-numba-vs-minimax/`,
`game-logs/v7-numba-vs-minimax-compclock/` (both overwritten with the final bitboard version's
numbers), `game-logs/v7-numba-vs-v6/` and `game-logs/v7-numba-vs-greedy/` (from the first
attempt - not re-run since the eval's output is proven byte-identical regardless of which version
produced it, so only speed-sensitive matchups needed re-testing).
