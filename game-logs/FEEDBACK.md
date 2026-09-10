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

## Milestone A7 — Static Exchange Evaluation (attempted, correct, reverted)

A teammate asked a genuinely good question: could the engine recognize "this move risks a queen,
that one only risks a pawn" and skip searching the worse branch? That's Static Exchange
Evaluation (SEE) - playing the full capture/recapture sequence on a square out, not just the
first trade, to get the real net material result. `order_moves()`'s existing MVV-LVA score only
ever looked at one capture in isolation (victim value minus attacker value), with no idea whether
the capturing piece is itself then recaptured for a loss.

**Built and verified correct before touching any search behavior**, per this project's own
discipline: `see()` (a recursive "swap-off" - each side free to stop the exchange the instant
continuing would cost them material, mirroring quiescence's own stand-pat logic) checked against
four hand-derived positions - a simple winning capture, a losing capture, an even trade, and
critically an x-ray case (a rook behind another rook, revealed only once the front one trades
off) - all four matched exact hand calculations, including the x-ray one. `evaluate()` itself was
untouched, so the existing 8,000-position regression check still came back at 0 mismatches
throughout. `ruff`/`mypy --strict`/`make gate` all stayed clean the whole time.

**Wired into two places**: `order_moves()` (sort captures by real exchange value instead of the
MVV-LVA guess) and `quiescence()` (skip searching a capture further if its SEE is negative -
argued safe specifically there, never in the main search, since stand-pat is always the fallback
and quiescence only ever looks at captures anyway - a static judgment skipping a whole *negamax*
branch could throw away a real combination, which is why that boundary was deliberately kept).

**First batch (30 games, fast clock, head-to-head vs. the pre-A7 baseline `v7-numba-eval`):
46.7% (+9 =10 -11)** - worse, not better. Investigated rather than either shipped optimistically
or quietly dropped. Found and fixed a real inefficiency along the way: `see()` was being computed
*twice* per capture in quiescence (once inside `order_moves()`'s sort, once again in the filter) -
fixed by computing it once and reusing the result. **Re-ran the same batch: 45.0% (+6 =15 -9)** -
unchanged within noise. The dedup was a legitimate fix on its own terms but wasn't the actual
cause.

**Root cause, measured directly rather than guessed further**: an isolated benchmark (3,502 real
capture cases collected from random games, `see()` vs. the old MVV-LVA formula, no search
involved) found **`see()` costs ~6.5x what MVV-LVA costs per call - 18.4us vs. 2.8us**. Each
`see()` call does a `board.copy()` plus a simulated multi-step exchange (`board.attackers()`
queries, piece removal/placement); MVV-LVA is two dictionary lookups. `order_moves()` calls this
for *every capture at every node in the whole tree*, not just quiescence's leaf-adjacent nodes -
so the accuracy SEE genuinely buys in move ordering was being paid for with search depth lost
across the entire tree, and losing depth cost more than better-ordered captures bought back. A
third, independent measurement confirms it end-to-end: a fixed-depth-4 search across 240 random
positions took 1526ms/position with SEE wired in vs. 1098ms/position without it - a real ~39%
slower search overall, not just a slower per-call number in isolation.

**Reverted the wiring, kept the (correct, verified) `see()` implementation in the file, unused,**
as groundwork for a lighter reimplementation rather than deleting verified-correct work. The
parallel to milestone B1 is direct: B1's first (array-based) eval attempt was also correct but
too slow to pay for itself (~1.0-1.3x), and a bitboard rewrite (reading python-chess's raw
per-piece bitboards instead of building a Python object per square) got a real ~5-7x win instead
of a marginal one. The same rewrite is the natural next step for `see()` - avoid `board.copy()`
and work directly with bitboard integers the way `_evaluate_bitboards_jit` already does. Not
attempted in this pass; flagged as the concrete next move rather than a vague "optimize later."

No version snapshot for this milestone (nothing shipped differs from `v7-numba-eval`). Verified
two ways, not just asserted: a direct `diff` against `versions/v7-numba-eval/agent.py` confirms
every remaining difference is either the dormant (unused) SEE code or a docstring - zero changes
to `order_moves()`'s scoring, `quiescence()`'s candidate-building, `negamax()`, `search_root()`,
or `get_move()`. A 10-game sanity batch came back 30.0% (+1 =4 -5) against `v7-numba-eval` -
*not* evidence of a real difference, since the diff already proves the algorithms are
byte-identical; it's the same small-sample noise the project already learned to expect from A3's
TT scare (25% at 10 games, 47.5% once re-run at 40) - included here for completeness, not as
supporting evidence, since the diff is the stronger proof. Full data: `game-logs/a7-see-vs-v7/`
(30 games - the *second*, post-dedup-fix attempt only; both batches reused the same label, so the
first attempt's PGNs/summary.json were overwritten on disk - its 46.7% record is preserved here
in writing, not as replayable game files) and `game-logs/a7-reverted-vs-v7-sanity/` (the
noisy-but-superseded-by-the-diff sanity batch).

## Milestone A8 — iterative-deepening root-move reordering

A cheap, standard idea the A7 audit flagged as completely absent: `get_move()`'s iterative
deepening reused the same MVV-LVA-ordered root move list at every depth, unchanged - the move
that won at depth 3 got no priority when depth 4 started, despite being very likely still strong.
After each completed depth, `get_move()` now moves that depth's winning move to the front of the
list before starting the next one. Provably safe by construction: this only ever changes which
order root moves are *tried* in, never which one search settles on - `search_root` still scores
every move at the new depth regardless of where it sits in the list.

**Batch (30 games, fast clock, vs. pre-A8 baseline): 48.3% (+12 =5 -13)** - close to neutral, not
a clear win, but the real signal is the *shape* of the result, not just the percentage: this is
much closer to 50% than the 30.0% a same-code sanity check happened to show for A7's revert,
consistent with a genuinely small, order-only effect rather than either a real regression or a
dramatic improvement at this sample size.

**One real self-inflicted flag in the batch (game 8, 125 plies) - investigated properly, not
dismissed.** This is the first fast-clock self-flag across any of tonight's batches, so it got
the same treatment as B1's competition-clock flag: reconstruct the exact position, compare old
vs. new code directly. The position where it happened (FEN
`8/4k3/5N2/4P3/2Q5/P3B2P/8/6K1 b - - 10 63`) had **exactly 2 legal moves**, and both the pre-A8
code and this version answered it in **under 1ms even given a 400ms budget** - nowhere close to
expensive enough to explain a flag on its own. A8's own added work (`list.remove()` +
`list.insert()` once per completed depth, on a legal-move-count-sized list) is microseconds, not
something that compounds into a flag either. The far more likely explanation: 125 plies is an
unusually long game, and slow, cumulative clock bleed across that many decisions - not any single
expensive node - is a pre-existing, generic risk in the time budget formula
(`time_left_ms / max(20, 40 - moves_played)`) that predates A8 and wasn't changed by it. Distinct
from B1's depth-cliff flag (one expensive node) but the same underlying theme: the time-budget
formula doesn't guarantee flag-safety in every scenario, and this milestone doesn't fix that
either - noted, not solved, same as B1's version of this finding.

Snapshot: `versions/a8-rootorder/agent.py`. Full data: `game-logs/a8-rootorder-vs-v7/`; the flag
diagnosis's position/timing comparison is recorded here rather than as a separate saved file,
matching how B1's own flag investigation was written up.

## Milestone A9 — transposition-table best-move ordering hint

A8 fixed root-move ordering across iterative-deepening depths; the same idea was still completely
missing everywhere else in the tree. `TTEntry` stored only `depth, score, flag` - even a TT hit
too shallow to trust the score outright carried no information at all about which move was good
here. Added a `best_move` field: `negamax` now records whichever move produced its returned
score, and on the next visit to that position (an exact transposition, or the same position
reached one ply shallower on a later move) `order_moves` tries that move before anything else -
ahead of every capture, not just ahead of other quiet moves. Kept meaningful even for an
UPPERBOUND (fail-low) entry, where it's the least-bad move found rather than a proven-best one -
still a real hint, the same spirit the code already used for reusing a bound score under a
different window.

**Verified two ways before batch-testing, not just "it runs":** `order_moves(board, moves,
tt_move=X)` puts `X` first even when the list also contains a strong capture (checked directly -
a quiet developing move moved from index 6 to index 0 out of 31 legal moves). A real depth-4
search from the starting position was then checked to confirm TT entries actually end up with a
populated, well-formed `best_move` (906 of 3,901 entries did - the rest are depth-0/quiescence
entries, which by design never get one).

**Batch (30 games, fast clock, vs. the pre-A9 baseline `a8-rootorder`): 58.3% (+15 =5 -10)** - the
first clearly positive result among tonight's three search-improvement attempts (A7/SEE was a
regression, A8 was close to neutral at 48.3%). One flag in the batch belonged to the *opponent*
(`a8-rootorder`, checked directly in `summary.json`), not this version - a clean win, no
self-inflicted issue.

Snapshot: `versions/a9-ttmove/agent.py`. Full data: `game-logs/a9-ttmove-vs-a8/`.

## Milestone A10 — killer-move heuristic

A9 gave the TT move top priority, but a TT hint only fires on an exact transposition - most
nodes never get one, and their quiet moves still had zero ranking beyond raw generation order
(`order_moves`'s flat `-1.0` for every non-capture). Killer moves are the standard, cheaper
complement: a quiet move that caused a beta cutoff at a given remaining-depth recently is
disproportionately likely to be strong again in a *sibling* branch at that same depth - not
because it's the same position, but because the same tactical idea (a check, a threat, an escape)
often recurs nearby in the tree. Added a 2-slot-per-depth table (`KILLER_MOVES`, indexed by
remaining depth, the same value `negamax` is already called with); a quiet move that causes a
cutoff gets recorded there, and `order_moves` ranks a depth's killers right after every capture,
ahead of any other quiet move. Reset at the start of every `get_move()` call - deliberately unlike
the TT, which persists across the whole game on purpose (see its own comment); a killer only
claims a move was strong *recently, near this depth*, a far more perishable signal than an actual
transposition.

**Verified directly before batch-testing, three separate checks:** `order_moves` puts a given
killer right after a real capture and ahead of an ordinary quiet move (checked with an actual
capture available in the test position, not assumed). A real depth-4 search from the starting
position populates `KILLER_MOVES` with well-formed legal moves, respecting the 2-slot cap.
`get_move()` actually clears stale entries at the start of a call - checked by injecting a killer
at `MAX_DEPTH` (a depth an ~0-budget search has no way to reach) and confirming it's gone
afterward, so the only way it could disappear is the reset itself, not that call's own search
overwriting it.

**Batch (30 games, fast clock, vs. the pre-A10 baseline `a9-ttmove`): 71.7% (+16 =11 -3)** - the
strongest result of any search-improvement attempt tonight, a real margin well above both A8's
near-neutral 48.3% and A9's already-positive 58.3%.

**One real self-inflicted flag (game 6, 41 plies) - investigated the same way as every other flag
tonight, not waved off just because the headline number is good.** This game is itself another
instance of the `3.Qg4` opening trap (documented since B1) that spiraled into a tactically sharp
middlegame (two captures and several piece jumps between moves 14-20). At the exact position
where black flagged (FEN `r3rk2/pppb2pp/8/6R1/nbBnp3/1P6/P2P1PPP/1RB3K1 b - - 0 21`, 46 legal
moves), both the pre-A10 code and this version answered in **0.2ms even at a 150ms budget** -
identical, negligible cost for both, ruling out A10's own logic as directly responsible (a killer
lookup is a membership check against at most 2 moves; there's no plausible mechanism for it to
cost real time). Most likely cumulative time pressure from the tactically demanding stretch
earlier in this specific game, the same category of finding as A8's flag - not exhaustively
traced move-by-move here, since the two versions' actual games diverge from very early on and
aren't directly comparable position-by-position beyond the flagging position itself.

Snapshot: `versions/a10-killers/agent.py`. Full data: `game-logs/a10-killers-vs-a9/`.

## Milestone A11 — history heuristic (attempted, unresolved regression, reverted)

The natural next step after killer moves: A10 only ranks the 1-2 most recent cutoffs *at one
exact depth*, so every other quiet move - including a killer's own understudy, or a move that
keeps causing cutoffs without ever making a depth's 2-slot cut - still tied at a flat `-1.0` with
zero ranking among them. History adds a coarser, longer-memory signal: a running count per
`(from_square, to_square)`, weighted by depth² (deeper cutoffs are rarer, stronger evidence),
accumulated across the *whole* search rather than one depth. Scored into `(-1.0, -0.6]` in
`order_moves` - strictly below a killer's `-0.5` and any real capture's `>= 0.0`, so it can only
ever refine the bottom of the order, never jump ahead of a stronger signal. Reset every
`get_move()` call, same reasoning as killers.

**Batch (30 games, fast clock, vs. the pre-A11 baseline `a10-killers`): 35.0% (+8 =5 -17, zero
flags)** - a real, clean regression, not a timing artifact. Investigated with more rigor than any
prior finding tonight, because the mechanism itself looked sound and the result contradicted it:

1. **Not a correctness bug.** Move ordering can only change alpha-beta's *efficiency*, never its
   *result*, under a full window - checked directly: 0/8 mismatched scores between old and new at
   a fixed depth across 8 random positions.
2. **Not a speed problem** (ruling out an A7-shaped explanation). At the same fixed depth, history
   consistently searched *fewer* nodes and finished *faster* - about 10% fewer nodes, 13% less
   wall time, across all 8 positions, never worse in a single one.
3. **Not an obvious move-quality problem either**, at least not in a small, targeted sample: a
   real `get_move()` comparison (same generous time budget, both versions, 8 positions) found
   old and new agreed on the move 6 of 8 times; the 2 disagreements split evenly - one where
   history's choice was judged clearly worse by an independent fixed-depth search (607 -> 551,
   about half a pawn), one where it was judged clearly *better* (89 -> 115) - no systematic bias
   toward worse moves showed up here.

**Root cause not found - reverted anyway, out of caution rather than confidence in an
explanation.** Three separate, reasonably thorough checks all came back "this looks fine or even
good," yet the one measurement that actually matters (a real 30-game batch) says otherwise
clearly. That contradiction itself is the finding: something about history's effect compounds
across a full real game (many real moves, `HISTORY` persisting and accumulating across every
iterative-deepening pass within each one) in a way none of tonight's smaller, more targeted tests
were shaped to catch - and this session ran out of time to chase it further rather than ship an
unexplained regression on an unattended machine two days before the deadline. Reverted
`order_moves`/`negamax`/`get_move`'s use of it; kept `HISTORY`/`store_history` in the file,
unwired, as verified-but-unresolved groundwork - not deleted, since the mechanism itself passed
every check thrown at it except the one that counts. **Flagged for the team: worth a fresh look
with a larger sample and fresh eyes, not a rabbit hole for 4am alone.**

No version snapshot (nothing shipped differs from `a10-killers` - `order_moves`/`negamax`/
`get_move` reverted to that version's exact logic; `ruff`/`mypy`/the eval regression check/gate
sanity games all still clean). Full data: `game-logs/a11-history-vs-a10/` (the batch), this
session's own diagnostic scripts' output recorded here rather than as separate files (matching
how every other same-night flag/regression investigation was written up).

## Milestone B2, round 2 — deeper/denser training data, a real speed fix, and a genuine puzzle

Round 1 (12,000 positions, depth-2 labels) lost badly to `a10-killers` (25.0%), traced to the
NNUE eval costing ~15.5x the classical eval per call - not an accuracy problem. Round 2 attacked
both halves of that at once: a real speed fix, and a real data-quality upgrade. The two didn't
combine the way the numbers alone predicted, and chasing down why is the most useful thing this
section has to say - a case study in "measure the actual outcome, not the inputs you expect to
produce it."

**The speed fix (kept - a proven, unambiguous improvement, same bar as B1's own eval speedup):**
`_nnue_features` (turns a `chess.Board` into the net's 768 input numbers) was a pure-Python loop
over `board.piece_map()` - exactly the dict-construction cost B1 found and fixed for the classical
eval, just not yet applied here. Rewrote it as one `@njit` pass over the board's raw bitboards
(same technique as `_evaluate_bitboards_jit`), verified byte-identical to the old encoder across
~8,000 real-game positions before trusting it. Measured: encoding dropped from 27.3us to
5.2us/call. Combined with tuning onnxruntime's `SessionOptions` (single-threaded - the platform
gives us one core, so ORT's default multi-thread pool is pure overhead; disabled the memory-
pattern arena, which optimizes for varying batch sizes we never use) for another ~10%, the whole
NNUE eval call dropped from **15.5x to 7.6x the classical eval's cost**, verified via the same
isolated-benchmark technique as every other speed claim tonight.

**The data upgrade:** generated a new dataset - 20,000 positions (up from 12,000), sampled every
2nd ply instead of every 4th, labeled at depth 3 instead of depth 2 (using `a10-killers`, the
strongest classical engine, as the labeling teacher - directly the "use a10-killers to improve
B2" idea raised earlier), drawn from all 824 games played so far tonight. Generation itself hit a
real problem worth recording: the first attempt only wrote output once, at the very end, with no
progress visibility - after 32 minutes and zero sign of life (vs. ~7.5 min expected from a quick
benchmark), it was killed and rewritten to checkpoint every single position to disk immediately
and log progress every 100 - a real design flaw caught before it could cost hours of unrecoverable
overnight compute, not just a speed tweak. The rewritten version completed cleanly: 20,000
positions in 4,001s (~5.0 pos/s, real games take longer per position than the random-move
benchmark predicted, confirming the concern).

Trained two architectures on it, 500 epochs, tracking the best validation checkpoint rather than
trusting the final epoch (the "same" architecture visibly overfits past epoch 225 - train RMSE
kept falling to 58 while validation rose back to 254; best-checkpoint tracking caught this
automatically):

| Model | Shape | Best epoch | Val RMSE | Eval cost vs. classical |
|---|---|---|---|---|
| Round 1 (reference) | 768-256-32-1 | - | 264.7 (depth-2 labels) | 15.5x |
| Round 2 "same" | 768-256-32-1 | 225 | **235.0** (depth-3 labels) | 7.6x |
| Round 2 "small" | 768-128-1 | 498 | 260.8 (depth-3 labels) | 5.6x |

Both exported to ONNX and reverified against raw torch output (max diff 0.0002-0.0003). One real
bug found and fixed along the way: renaming an exported `.onnx` file after the fact breaks it,
because the external-weights filename is embedded *inside* the file's own metadata, not derived
from its actual name on disk - fixed by using `onnx.load_model_from_string` + `onnx.save(...,
location=...)` to properly rewrite that reference when relocating into each version folder,
rather than a plain file copy/rename.

**The batch results were a genuine surprise:**

| Agent | vs. `a10-killers` (30 games, fast) | vs. `greedy` (20, fast) | vs. `minimax` (20, fast) |
|---|---|---|---|
| Round 1 | 25.0% (+4=7-19) | - | 60.0% (+7=10-3) |
| Round 2 "same" | **16.7%** (+2=6-22) | - | - |
| Round 2 "small" | 26.7% (+2=12-16) | 87.5% (+16=3-1) | 77.5% (+12=7-1) |

"Same" - strictly faster AND more accurate than round 1 by every number measured before the
batch ran - scored *worse* against `a10-killers` than round 1 did. That's not noise to shrug off;
it directly contradicts what every prior metric predicted, and deserved the same investigation
rigor as A11's regression rather than a shrug.

**Investigation.** Profiled a real `get_move()` call (`cProfile`, competition-clock-equivalent
budget, three representative positions) for both `a10-killers` and "same". First finding, and
useful on its own: for the classical engine, `evaluate()` doesn't even make the top 15 functions
by cumulative time - `python-chess`'s own move-generation machinery (`generate_legal_moves`,
`generate_pseudo_legal_moves`, `_is_safe`, `scan_reversed`) is ~70% of total search time. B1's
eval speedup years ago already made classical eval a non-issue; it was never the bottleneck this
session assumed it might still be.

For "same", `evaluate()` consumed 34-59% of total search time - and its own reported cost per
call (100-190us, extracted precisely via `pstats`, not eyeballed) was 3-5x higher than the
34.49us/call the isolated tight-loop benchmark predicted. Cross-checked this against the
classical eval's own profiled-vs-isolated numbers (15.9us profiled vs. ~4.5us isolated - also
inflated, just less dramatically) and concluded `cProfile`'s own per-call instrumentation
overhead (this search makes 5-7 million function calls per move) was distorting the *absolute*
numbers for both agents - a real caveat, not a reason to distrust the *relative* comparison
between them under identical instrumentation.

To get a clean, non-distorted number, re-measured with a plain call-counter (monkeypatching
`evaluate()` at runtime, zero profiling overhead) instead of `cProfile`, across the same three
positions, same simulated competition-clock budget:

| Position | `a10-killers` nodes | "same" nodes | "small" nodes |
|---|---|---|---|
| Opening | 26,437 | 18,373 (70%) | 20,191 (76%) |
| Middlegame (tactical) | 24,916 | 20,836 (84%) | 22,679 (91%) |
| Endgame | 20,796 | 18,683 (90%) | 18,540 (89%) |

**Conclusion: even at 7.6x the classical eval's cost, NNUE still reaches only 70-90% of the
classical engine's node count in the same time budget** - a real, meaningful search-depth
handicap that the accuracy improvement (RMSE 235.0 vs. 264.7) wasn't enough to pay for. "Small" -
less accurate but reaching more nodes than "same" in 2 of 3 positions - backs this up directly:
it beat "same" head-to-head in every comparison run (26.7% vs. 16.7% vs. `a10-killers`), despite
being the *less accurate* of the two nets. Depth is currently worth more than the accuracy gained
this round, at least at the search depths a 120s-class clock reaches.

**Kept as the front-running NNUE candidate**: `versions/b2-nnue-small`, not `versions/b2-nnue`
("same") - one open question worth the team's attention: "small" drew by threefold repetition in
12/30 games against `a10-killers`, exactly double "same"'s 6/30, not yet explained (possibly a
less decisive evaluation signal steering it into repeated positions more often - not confirmed).
Neither variant is close to `a10-killers` yet; both remain experimental, un-promoted candidates,
not a replacement for the shipped classical path.
