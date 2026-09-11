# Roadmap & status

For the team. Not read by `harness/package.py` (only `agent.py` + declared weights get zipped
for submission), so nothing here ever reaches the competition upload regardless of where it
lives in the repo.

**Deadline:** submissions close **2026-09-11, 11:00 UTC**.
**Hardware:** development started on an Intel Mac, which cannot install `torch`, `onnxruntime`,
or `numba` at the platform's pinned versions (no wheels for that architecture at these
versions). A Silicon Mac was expected within a couple of days of starting; GitHub Actions CI
(Ubuntu + Apple Silicon `macos-latest` runners) covers the gap in the meantime.

The technical content of Phase A/B below comes directly from `docs/IDEAS.md` (the starter
repo's own "where the strength actually comes from" guide) and from what testing the existing
baselines (`baselines/minimax`, `baselines/numba`, `baselines/greedy`) revealed.

## What each package does

- **torch (PyTorch)** — the library for building and training neural networks. Needed for
  anything on the machine-learning side: the stretch-goal neural net evaluation function we've
  talked about.
- **onnxruntime** — a tool for running an already-trained neural network fast, in a portable
  format called ONNX. The idea from the roadmap: train the network with torch on a beefy setup,
  then export it to ONNX and use onnxruntime for the actual fast, lightweight inference during a
  game (since you don't want the heavier training library running during timed matches).
- **numba** — not about neural networks at all. It's a tool that speeds up ordinary Python code
  by compiling it into fast machine code just before it runs (a "JIT" — just-in-time compiler).
  This is used to make your board-evaluation function run much faster, so your search can go
  deeper in the same time budget — completely separate from ML.

## Status at a glance

| Milestone | What | Status |
|---|---|---|
| Setup | Fork starter, working random-mover, git/GitHub backup | ✅ done |
| A0 | GitHub Actions CI (Linux + Apple Silicon runners) | ✅ done, passing |
| A1 | Alpha-beta negamax search, fixed depth | ✅ done — see below |
| A2 | Move ordering (MVV-LVA) | ✅ done — see below |
| A3 | Transposition table | ✅ done — see below |
| A4 | Iterative deepening + real time management | ✅ done — see below |
| A5 | Quiescence search | ✅ done — see below |
| A6 | Evaluation upgrade: piece-square tables | ✅ done — see below |
| A7 | Static Exchange Evaluation (move ordering + quiescence pruning) | ⚠️ attempted, reverted — see below |
| A8 | Iterative-deepening root-move reordering | ✅ done — see below |
| A9 | Transposition-table best-move ordering hint | ✅ done — see below |
| A10 | Killer-move heuristic | ✅ done — see below |
| A11 | History heuristic | ⚠️ attempted, unresolved regression, reverted — see below |
| B0 | Full env parity (torch/numba/onnxruntime) | ✅ done on Windows — see below; Silicon Mac still pending |
| B1 | numba-jit the evaluation | ✅ done — see below |
| B2 | Neural-net evaluation (**stretch goal**, not required) | ✅ **PROMOTED to root `agent.py`** — see below |
| C | Submission safety buffer (gate, edge cases, zip, smoke games) | ✅ everything locally-checkable done — only the platform's own smoke-game upload remains, needs the team |

## How every milestone gets measured

Per `docs/IDEAS.md`: two games tell you nothing, and "better than my last one" is the only
comparison that matters. At the end of each milestone:
1. Snapshot the agent into `versions/<milestone-name>/agent.py` (mirrors `baselines/`'s layout,
   so it's directly usable as a harness opponent).
2. Run `tools/batch.py` (or `harness.arena`) against the previous snapshot and against
   `baselines/greedy` / `baselines/minimax`, saving PGNs + a written summary in `game-logs/`.
3. Record findings in `game-logs/FEEDBACK.md`.
4. Notable individual games get added to the **Scoresheet** board-viewer artifact for visual
   review (link shared separately per update — it's a private Claude artifact, not part of the
   repo).

Opening books are deliberately out of scope: rated games start from curated non-standard
positions, so a book keyed on move one is often already out of book (per `docs/IDEAS.md`)
— effort goes to search instead.

---

## Phase A — pure Python, no hardware blocker

**A0. GitHub Actions CI** — runs `make gate` on Ubuntu and a harness game on macOS (Apple
Silicon runner)/Windows, on every push. Validates torch/numba/onnxruntime-touching code without
needing local hardware that supports them.

**A1. Alpha-beta negamax, fixed depth** *(done)* — replaced the random-mover with negamax +
alpha-beta pruning, reusing `baselines/minimax`'s exact evaluation (material + mobility,
unchanged) so the comparison isolates what the search algorithm alone buys.

**A2. Move ordering (MVV-LVA)** *(done)* — order captures before quiet moves, captures sorted by
most-valuable-victim/least-valuable-attacker. Per `docs/IDEAS.md` this is the lever that makes
alpha-beta actually pay off ("the gap ... is mostly move ordering"). Hoped to let us push depth
back toward 4 safely — it didn't (still flagged at depth 4), but made depth 3 dramatically
stronger and safer instead. See below.

**A3. Transposition table** *(done)* — a dict keyed on `board._transposition_key()`, storing
depth + score + a bound-type flag (proper EXACT/LOWERBOUND/UPPERBOUND handling, not a naive
always-trust-the-cache version). Persists across moves within a game, since the process stays
alive between `get_move` calls. Strength-neutral at this fixed depth (as a correct TT should
be) — its value here is speed and cross-move memory, not different move choices. See below.

**A4. Iterative deepening + real time management** *(done)* — replaced fixed `DEPTH` with
iterative deepening (depth 1, 2, 3, ... keeping the best move from the last completed pass),
driven by a real budget from `time_left_ms`, checked on every single search node. Found two real
bugs by measuring rather than guessing (a too-coarse clock-check interval, and an oversized
safety margin that was silently capping the search at depth 2) — see below.

**A5. Quiescence search** *(done)* — captures-only extension at leaf nodes (all legal replies
when in check, not just captures - no "do nothing" option there), fixing the horizon effect
where the static eval is measured mid-exchange. Shipped with a real fail-hard/fail-soft bug
initially, caught by a 0.0% batch result before it went anywhere near a real submission - fixed,
this became the single biggest strength jump since move ordering (A2). See below.

**A6. Evaluation upgrade** *(done)* — material + piece-square tables on top of the now-solid
search (mobility deliberately left as-is, isolating what PST alone is worth). The strongest
single-milestone result yet, and the reference point for judging whether the stretch-goal
neural net (B2) is actually worth shipping later. See below.

## Phase B — once on Apple Silicon hardware

**B0. Full environment parity** *(done, on a Windows machine — see below)* — plain `uv sync`
(no exclusions); confirm torch, onnxruntime, numba install cleanly; run `make gate`.

**B1. numba-jit the evaluation** *(done — see below)* — ended up reading raw bitboards directly
rather than `baselines/numba/agent.py`'s array pattern (the array version's real speedup was too
small to matter); `@njit` decodes and evaluates in one compiled pass, warmed up once at import
(inside the init budget, not on the clock). The win is the extra depth the speed buys, not the
eval call itself — see below for why that didn't show up as a higher score in testing.

**B2. Neural-net evaluation — stretch goal only.** A solid classical engine (A0–A6, B1) is the
safe submission; this is attempted only with real time to spare. Train a small NNUE-style net
in torch offline (self-play / public games, labelled with a search-based signal — allowed, since
the restriction is on what ships in the zip, not what's learned from), export to ONNX, keep it
small (1–40 MB, per `docs/IDEAS.md`'s sizing guidance), run inference via `onnxruntime`. Ships
only if it actually beats the classical engine in an arena run.

## Phase C — submission safety buffer (last 1–2 days before Sept 11)

- ✅ `make gate` equivalent (`make` isn't installed in this dev environment - ran its three steps
  directly): `ruff check .` clean, `mypy` clean (9 source files), 2-game sanity arena vs.
  `baselines/random` completed with no flags/crashes (75.0%, +1=1-0).
- ✅ Stress-test edge cases: no legal moves, promotion, underpromotion, en passant, insufficient
  material — 22/22 checks pass against the real `agent.py`. One finding, not yet fixed (a real
  code edit, held for review rather than applied unilaterally): calling `get_move()` on an
  already-checkmated/stalemated position raises an uncaught `IndexError` (`best_move = moves[0]`
  on an empty legal-move list) — should never trigger in practice since the harness ends the
  game before calling `get_move()` again, but a one-line defensive guard would close it for free.
- ✅ `torch.set_num_threads(1)` at import — N/A currently, root `agent.py` doesn't import torch
  (classical eval only; B2's NNUE path uses onnxruntime for inference and is not shipped). Revisit
  this line if/when any torch-touching path is ever promoted into root `agent.py`.
- ✅ `make zip` equivalent (`python -m harness.package`): `submission.zip` is 16,753 bytes zipped
  (46,391 unzipped) — comfortably under the 50 MB cap — containing exactly `agent.py` at the
  archive root, confirmed via `unzip -l`.
- ⬜ **Run the platform's required two smoke games (one per color) — this is the one item that
  cannot be done from here.** It means uploading `submission.zip` to the actual AI Chessathon
  platform and letting its own validation pipeline play the two required games; that requires
  platform credentials/access this session doesn't have. Everything locally checkable is done and
  clean — this is the one remaining step for the team to do directly on the competition site,
  with days of margin left as the checklist recommends.

---

## Milestone details

### A0 — CI enabled
Re-added `.github/workflows/ci.yml` from the upstream starter (skipped during the initial fork).
First run passed: `make gate` on Ubuntu, harness games on macOS (Apple Silicon) and Windows
runners.

### A1 — Alpha-beta negamax search (fixed depth)

Same evaluation as `baselines/minimax` (material + mobility), search replaced with negamax +
alpha-beta pruning. Depth started at 4, but real testing found a serious issue:

- **Depth 4 flagged 20/20 games** at fast test control (10s+0.1s) — a single middlegame move
  measured ~2.2s with no move ordering yet, and that adds up fast with zero time awareness.
- **Depth 3** (~4x faster) fixed most, not all, of it:

| Opponent | Clock | Score | Record | Flags |
|---|---|---|---|---|
| `baselines/greedy` | fast (10s+0.1s) | 85.0% | +8 =1 -1 | 1/10 |
| `baselines/minimax` | fast (10s+0.1s) | 20.0% | +0 =4 -6 | 5/10 |
| `baselines/minimax` | competition (120s+0.5s) | 58.3% | +3 =1 -2 | 0/6 |

The flag risk turned out to be specific to the fast *test* clock, not the real 120s+0.5s
competition clock (zero flags there) — but it confirms time management (A4) is a hard
requirement before any version of this agent ships, and that fast-control volume testing isn't
safe to rely on until A4 lands. A 58.3% score against `minimax` (not a rout) also shows depth 3
alone hasn't fully recovered what we gave up dropping from depth 4 — move ordering (A2) is what
should buy that back. Full data: `game-logs/v1-alphabeta-vs-*/`, written up in
`game-logs/FEEDBACK.md`.

### A2 — Move ordering (MVV-LVA)

Added `order_moves()`: captures before quiet moves, captures ranked by MVV-LVA. Found and fixed
a real bug along the way — a king capturing something crashed the ordering function, since
`PIECE_VALUE` (reused from the evaluation) has no king entry; fixed with a separate
`ATTACKER_VALUE` table used only for ordering.

Re-tried depth 4 hoping the speedup would make it viable — it didn't (7/10 flags at fast
control, worse than depth 3 ever was) — so `DEPTH` stayed at 3. But ordering made depth 3 itself
dramatically better:

| Metric | A1 (no ordering) | A2 (with ordering) |
|---|---|---|
| vs `versions/v1-alphabeta`, head-to-head | — | 100.0% (+10 =0 -0) |
| vs `greedy`, fast clock | 85.0%, 1/10 flags | 95.0%, 0/10 flags |
| vs `minimax`, fast clock | 20.0%, 5/10 flags | 70.0%, 0/10 flags |
| vs `minimax`, competition clock | 58.3%, 0/6 flags | 66.7%, 0/6 flags |
| Middlegame move time (depth 3) | 1.014s | 0.209s (~5x faster) |

The head-to-head against `v1-alphabeta` is the cleanest signal: 100%, including 3 games where
v1 itself flagged at the *same* depth — direct evidence ordering buys real speed (better
pruning), not just better move choices. The minimax flag rate in particular, the worst problem
found in A1, dropped from 5/10 to 0/10. Full data: `game-logs/v2-ordering-vs-*/`, written up in
`game-logs/FEEDBACK.md`.

### A3 — Transposition table

Added a proper TT with EXACT/LOWERBOUND/UPPERBOUND flag handling (not a naive cache) — see the
code comments in `agent.py` for why that distinction matters for correctness, not just speed.
Depth 4 was re-tried a third time (ordering + TT together) hoping the combined speedup made it
safe: it didn't (6/10 flags at fast control, barely better than A2's 7/10) — `DEPTH` stays at 3.

**A real scare, resolved properly rather than assumed away:** a 10-game head-to-head against
`versions/v2-ordering` (identical depth, ordering unchanged, only the TT added) came back 25.0%
— alarming, since a *correct* TT should never make an engine play worse at a fixed depth, only
faster. Verified directly rather than guessing: computed every legal root move's score for both
versions on the position where their final choices diverged, and every score matched exactly
(all ~30 moves, including a 10-way tie for best) — proof the TT logic itself is sound. With that
many ties at this depth, small-sample tie-breaking noise was the real explanation. Re-ran at 40
games:

| Games | Score | Record |
|---|---|---|
| 10 | 25.0% | +1 =3 -6 |
| 40 | 47.5% | +13 =12 -15 |

47.5% at real sample size is a coin flip — confirms the TT is exactly what it should be:
strength-neutral at this fixed depth, a speed optimization only. Baseline results held steady
too (90.0%/0 flags vs `greedy`, 65.0%/1 flag and 66.7%/0 flags vs `minimax` at fast/competition
clock respectively — all within normal variance of A2's numbers). Full data:
`game-logs/v3-tt-vs-*/`, written up in `game-logs/FEEDBACK.md`.

### A4 — Iterative deepening + real time management

Replaced the fixed `DEPTH = 3` with iterative deepening: search 1 ply deep, then 2, then 3, ...,
keeping the best move from the last *fully completed* pass, driven by a real time budget
(`time_left_ms / max(20, expected_moves_left)`) checked on every single search node via a
`TimeUp` exception that unwinds the recursion immediately.

**Two real bugs, both caught by measuring instead of assuming:**

1. **Clock-check interval.** First version checked the deadline every 1024 nodes — measured
   directly, 1024 nodes cost ~110ms here (each node ~0.1ms in Python), so a request with
   essentially zero time budget still took 115ms to respond. Fixed by checking every single node
   instead (a `time.monotonic()` call costs nanoseconds against a ~100-microsecond node, so the
   overhead is negligible) — the same "no time left" case now responds in 0.4ms.
2. **Oversized safety margin.** `SAFETY_MARGIN_MS = 150` was an unverified guess. With per-node
   checking in place, directly measuring real overshoot past the deadline (bypassing the budget
   formula, testing exact deadlines from 50ms–1000ms) showed overshoot stayed under 1ms in every
   case — the margin was ~150x more conservative than needed, and it was actively harmful: it was
   silently capping the search at depth 2 for most of a real fast-control game, because a typical
   ~100ms-after-margin budget wasn't enough to finish depth 3 (which now takes ~150-200ms
   post-A2/A3). Reduced to `SAFETY_MARGIN_MS = 50`; a head-to-head against `versions/v3-tt` went
   from 40.0% back to exactly 50.0% once fixed, confirming the lost strength was fully recovered.

**Results (all after both fixes):**

| Opponent | Clock | Score | Record | Flags |
|---|---|---|---|---|
| `versions/v3-tt` | fast (10s+0.1s) | 50.0% | +10 =10 -10 | 0/30 |
| `baselines/greedy` | fast (10s+0.1s) | 97.5% | +19 =1 -0 | 0/20 |
| `baselines/minimax` | fast (10s+0.1s) | 57.5% | +6 =11 -3 | 0/20 |
| `baselines/minimax` | competition (120s+0.5s) | 58.3% | +1 =5 -0 | 0/6 |

Zero flags everywhere tested — the first milestone with that property across the board. The
strength numbers roughly match the fixed-depth predecessor (expected: same depth reached most of
the time, at this sample size and clock), but the real payoff is adaptivity and safety rather
than a visible strength jump here — going deeper when the clock allows, never gambling when it
doesn't. Full data: `game-logs/v4-timemgmt-vs-*/`, written up in `game-logs/FEEDBACK.md`.

### A5 — Quiescence search

Added a captures-only search extension at the horizon (`depth == 0`), with one correctness
refinement beyond the minimal ask: when the side to move is in check, quiescence searches *all*
legal replies, not just captures, and doesn't stand-pat — there is no "do nothing" option when in
check, and the only legal move might not even be a capture.

**A serious bug, caught the same way every previous one was — comparing scores directly rather
than trusting a batch result.** A first 30-game head-to-head against `versions/v4-timemgmt` came
back **0.0% (+0 =0 -30)**, every game lost by checkmate. Since a correct quiescence addition
should never make the engine catastrophically worse, this got investigated immediately: compared
every candidate move's score at the root of a specific diverging position, and found completely
different moves — including one that plainly hangs a bishop — all scoring the *exact same* value,
with the move actually being played (an early queen sortie) really one of the worst options on
the board (-788.0), not the +100.0 it had been reported as.

**Root cause**: `quiescence()` used `alpha` itself to hold "the best value found so far," instead
of tracking a separate `best` the way `negamax` already correctly does (`alpha`/`beta` are only
supposed to be pruning thresholds). Whenever a move failed to beat whatever alpha it happened to
inherit from an earlier sibling, the function returned that borrowed alpha verbatim rather than
the true value it had found — collapsing unrelated moves to identical scores. Fixed to be
fail-soft, matching the existing pattern exactly.

**After the fix — the single biggest strength jump since move ordering (A2):**

| Opponent | Clock | Score | Record | Flags |
|---|---|---|---|---|
| `versions/v4-timemgmt`, broken (before the fix) | fast | 0.0% | +0 =0 -30 | 0/30 |
| `versions/v4-timemgmt`, fixed | fast (10s+0.1s) | **85.0%** | +23 =5 -2 | 0/30 |
| `baselines/greedy` | fast (10s+0.1s) | 97.5% | +19 =1 -0 | 0/20 |
| `baselines/minimax` | fast (10s+0.1s) | 72.5% | +11 =7 -2 | 0/20 |
| `baselines/minimax` | competition (120s+0.5s) | 66.7% | +3 =2 -1 | 0/6 |

Verified directly that quiescence fixes the horizon effect it targets: a hanging-queen position
scored only +16.0 by static evaluation alone, and +692.0 once quiescence searched the recapture.
Full data: `game-logs/v5-quiescence-vs-*/`, written up in `game-logs/FEEDBACK.md`.

### A6 — Evaluation upgrade: piece-square tables

Added the widely-used "Simplified Evaluation Function" piece-square tables (Tomasz Michniewski,
an openly-published Chess Programming Wiki reference — not any engine's proprietary weights) on
top of the unchanged material + mobility terms. `MOBILITY_WEIGHT` deliberately left as-is
despite A5's finding that it can introduce real noise — changing two things in the evaluation at
once would make it impossible to isolate what PST alone buys; that finding remains an open
follow-up. King table is middlegame-only (no game-phase detection to blend in an endgame table
rewarding an active, centralized king) — a known, documented simplification.

Learned from A5's bug: verified the table transcription and square-mirroring *before* trusting
any batch result, not after. Spot-checked known reference squares against the published table
(pawn on d7 = +50, knight on a1 = -50, etc.) and confirmed a mirror pair — White knight on d4 vs
Black knight on d5 — scores identically from each side's own perspective.

**The strongest single-milestone result yet, and the first with zero losses in both the
head-to-head and a fast-control baseline batch:**

| Opponent | Clock | Score | Record | Flags |
|---|---|---|---|---|
| `versions/v5-quiescence` | fast (10s+0.1s) | 80.0% | +18 =12 -0 | 0/30 |
| `baselines/greedy` | fast (10s+0.1s) | 100.0% | +20 =0 -0 | 0/20 |
| `baselines/minimax` | fast (10s+0.1s) | 85.0% | +15 =4 -1 | 0/20 |
| `baselines/minimax` | competition (120s+0.5s) | 83.3% | +4 =2 -0 | 0/6 |

Full vs-minimax progression across every milestone, both clocks:

| Milestone | Fast clock | Competition clock |
|---|---|---|
| A1 (alpha-beta) | 20.0% (5/10 flags) | 58.3% |
| A2 (+ move ordering) | 70.0% (0 flags) | 66.7% |
| A3 (+ transposition table) | 65.0% (1 flag) | 66.7% |
| A4 (+ time management) | 57.5% (0 flags) | 58.3% |
| A5 (+ quiescence search) | 72.5% (0 flags) | 66.7% |
| A6 (+ piece-square tables) | **85.0%** (0 flags) | **83.3%** |

A6 is a clear new high on both clocks, and the first milestone to improve both simultaneously by
a wide margin rather than trading one off against the other. Directly confirms
`docs/IDEAS.md`'s own framing — "material plus piece-square tables is a real evaluation and it
beats both baselines" — with actual numbers rather than taking it on faith. **Phase A (the
classical engine) is now complete.** Full data: `game-logs/v6-pst-vs-*/`, written up in
`game-logs/FEEDBACK.md`.

### A7 — Static Exchange Evaluation (attempted, correct, reverted)

Prompted by a genuinely good question from a teammate: could the engine tell "this risks a
queen" from "this risks a pawn" and skip searching the worse branch? That's Static Exchange
Evaluation (SEE) - play the *whole* capture/recapture sequence on a square out, not just the
first trade. Built and hand-verified correct (four derived positions including an x-ray case,
all exact) before it touched any search behavior - the same discipline every milestone here uses.
Wired into `order_moves()` (replacing MVV-LVA's single-trade guess) and `quiescence()` (skip a
capture whose full exchange loses material - argued safe only there, never in the main search,
since a static judgment cutting a whole negamax branch could throw away a real combination).

**Batch-tested worse, not better: 46.7%, then 45.0% after fixing a real but not-the-cause
inefficiency (`see()` was being computed twice per capture).** Root cause measured directly: an
isolated benchmark found `see()` costs **~6.5x MVV-LVA per call** (18.4us vs. 2.8us) - a
`board.copy()` plus a simulated multi-step exchange vs. two dictionary lookups - paid on every
capture at every node across the whole tree, not just quiescence. The accuracy SEE buys in
ordering cost more search depth than it bought back.

**Reverted the wiring; kept `see()` itself in the file, unused**, as verified groundwork rather
than deleting real work - the parallel to B1 is direct (B1's first eval attempt was also correct
but too slow, and a bitboard rewrite fixed it with a real ~5-7x win instead of ~1.0-1.3x). The
same rewrite - work with raw bitboard integers instead of `board.copy()` - is the concrete next
step for `see()`, not attempted in this pass. Full data and numbers in `game-logs/FEEDBACK.md`.

### A8 — Iterative-deepening root-move reordering

A cheap, standard technique the A7 audit found completely absent: the previous depth's winning
root move gets no priority when the next depth starts. Fixed by moving it to the front of the
root move list after each completed depth - provably safe (order-only, never changes which move
search settles on) and cheap (list-length work, once per depth, not per node).

**Batch: 48.3% (+12 =5 -13) vs. the pre-A8 baseline** - close to neutral, and meaningfully
different in shape from the noisy 30.0% a same-code sanity check happened to show earlier the
same night, consistent with a genuinely small effect rather than a real swing either way. One
self-inflicted flag in the batch was investigated directly (reconstructed the exact position,
compared old vs. new code): the position itself had 2 legal moves and both versions answered it
in under 1ms even generously budgeted, ruling out A8's own logic as the cause - almost certainly
cumulative clock bleed over an unusually long (125-ply) game, the same underlying time-budget-
formula risk category B1's own flag investigation already found, not something new. Snapshot:
`versions/a8-rootorder/agent.py`. Full data in `game-logs/FEEDBACK.md`.

### A9 — Transposition-table best-move ordering hint

The same idea as A8 (a move known to be good here beats a static guess) applied everywhere A8
didn't reach: internal search nodes. `TTEntry` gained a `best_move` field; `negamax` records
whichever move produced its result and offers it as `order_moves`' top priority - ahead of every
capture - the next time that position comes up, including from a too-shallow entry whose score
isn't itself trustworthy yet.

Verified directly before batch-testing: confirmed `order_moves` actually promotes the given move
to the front even past a strong capture, and confirmed a real depth-4 search populates TT entries
with well-formed best moves (906 of 3,901 - depth-0 entries never get one, by design).

**Batch: 58.3% (+15 =5 -10) vs. the pre-A9 baseline** - the first clearly positive result among
this session's three search-improvement attempts, a real margin above 50% rather than a coin
flip. One flag in the batch belonged to the opponent, confirmed directly in the batch's own
summary data. Snapshot: `versions/a9-ttmove/agent.py`. Full data in `game-logs/FEEDBACK.md`.

### A10 — Killer-move heuristic

The cheaper, cross-branch complement to A9: a quiet move that caused a beta cutoff at a given
remaining-depth is disproportionately likely to be strong in a sibling branch at that same depth,
even without an exact transposition. A 2-slot-per-depth table records cutoff-causing quiet moves;
`order_moves` ranks a depth's killers right after every capture, ahead of any other quiet move.
Reset every `get_move()` call, deliberately unlike the TT's cross-game persistence - a killer is a
far more perishable signal than an actual transposition.

Verified with three direct checks before batch-testing: killer-first-after-captures ordering,
real-search population of the table (respecting the 2-slot cap, well-formed moves), and that
`get_move()` genuinely clears stale entries at the start of a call (not just "happens to look
empty" - checked with an entry planted at an unreachable depth).

**Batch: 71.7% (+16 =11 -3) vs. the pre-A10 baseline** - the strongest result of any
search-improvement attempt this session, clearly ahead of both A8 (48.3%) and A9 (58.3%). One
self-inflicted flag was investigated the same way as every other flag tonight: at the exact
position (46 legal moves, in a tactically sharp middlegame that grew out of another `3.Qg4`-trap
game), both the pre-A10 code and this version answered in 0.2ms even at a 150ms budget -
identical cost, ruling out A10's own logic and pointing instead to cumulative time pressure from
that game's earlier tactics, the same category of finding A8 had. Snapshot:
`versions/a10-killers/agent.py`. Full data in `game-logs/FEEDBACK.md`.

### A11 — History heuristic (attempted, unresolved regression, reverted)

The natural next step after A10: rank every OTHER quiet move (not a depth's killer) by a
whole-search, depth²-weighted cutoff count per `(from_square, to_square)`, instead of leaving
them all tied. Scored strictly below a killer and above nothing (a plain `-1.0` floor), so it
only ever refines the bottom of the order.

**Batch: 35.0% (+8 =5 -17, zero flags) vs. the pre-A11 baseline** - a real, clean regression.
Investigated harder than any other finding tonight because three separate checks all contradicted
it: 0/8 mismatched scores at fixed depth (ordering can't change a full-window result, only
efficiency - confirmed directly), ~10% fewer nodes and ~13% less time at fixed depth in every one
of 8 positions (ruling out an A7-shaped "just too slow" explanation), and a real `get_move()`
move-choice comparison that found the two versions agreed 6/8 of the time with the 2
disagreements splitting evenly (one clearly worse, one clearly better) - no systematic bias
toward worse moves in that sample either. **Root cause not found; reverted anyway, out of
caution.** The contradiction between "every targeted check says this is fine or good" and "a real
30-game batch says otherwise" is itself the finding - something compounds across a full real game
that none of tonight's smaller tests were shaped to catch, and this session ran out of time to
chase it further rather than ship an unexplained regression unsupervised, two days from the
deadline. `HISTORY`/`store_history` kept in the file, unwired - flagged for the team to revisit
with a larger sample and fresh eyes. No version snapshot (nothing shipped differs from
`a10-killers`). Full data in `game-logs/FEEDBACK.md`.

### B0 — Full environment parity (Windows machine)

A new team member joined partway through and, while getting set up, checked whether B0 could be
unblocked from a machine other than the pending Silicon Mac. Cloned the repo on Windows,
installed `uv`, and ran a plain `uv sync` (no `--no-install`/exclusion workaround) against the
locked `uv.lock`.

**Result:** all 24 locked packages installed cleanly, including the three previously blocked on
the Intel Mac — `torch==2.13.0+cpu`, `onnxruntime==1.29.0`, `numba==0.67.0` — alongside
`numpy==2.5.2` and `chess==1.11.2`. Verified they actually import and run, not just install
(`torch.zeros(3).sum().item()` returns `0.0`). `make gate` also passed cleanly: ruff clean,
mypy strict clean (9 source files), and 2/2 sanity games vs `baselines/random` finished by
checkmate with no flags. Full numbers in `game-logs/FEEDBACK.md`.

**Note:** this confirms the pinned versions install fine on at least one non-Mac architecture —
it does not by itself fix the Intel Mac (still no wheels for that arch at these versions) or
replace getting the Silicon Mac working, which remains the target dev machine per the hardware
note at the top of this doc. In the meantime, B1 and B2 work can proceed on this Windows
machine.

### B1 — numba-jit the evaluation

Two attempts, both fully measured rather than assumed. Full narrative and numbers in
`game-logs/FEEDBACK.md`; summary here.

**First attempt** followed `baselines/numba/agent.py`'s pattern literally (`board.piece_map()` →
three numpy arrays → jitted per-square loop). Correct (0 mismatches vs. the old pure-Python eval
across ~8,000 positions) but only **~1.0-1.3x faster** — a real board has ≤32 pieces, and
`piece_map()`'s dict construction plus numba's per-call array-argument marshaling was competing
with whatever the compiled loop saved. Batch-tested worse than pre-numba `v6-pst` against
`baselines/minimax` on both clocks, including one real flag on the competition clock.

**Second attempt** skipped `piece_map()`/arrays entirely: reads python-chess's raw per-piece-type
bitboards (plain 64-bit integers it already maintains) and jits the decode *and* the evaluation
together in one compiled call taking scalar arguments. Cast to `np.uint64` specifically, not
`int64` — a bitboard can have bit 63 set (h8 occupied), and signed right-shift on that would
sign-extend instead of zero-filling, corrupting every subsequent bit test. Re-verified correct
(0 mismatches, same ~8,000-position check) before trusting it. Real, repeatable speedup this
time: **~5.4x-7.0x faster per call** than the original pure-Python eval.

**The real speedup did not translate into a higher score against `baselines/minimax`** — if
anything it scored lower than both `v6-pst` and the marginal first attempt (fast clock 60.0% vs.
v6's 85.0%; competition clock 66.7% vs. v6's 83.3%). Looked at the actual games rather than just
the percentage: the drop is entirely from **more draws, not more losses** (zero losses on the
competition clock in both `v6-pst`'s testing and this version's; fast-clock draws roughly
doubled, 10/20 vs. 4/20). The faster eval provably buys deeper search, but in these matchups that
deeper search finds a repetition-safe draw more often than it converts to a win. Recorded as this
milestone's honest result, not smoothed into a claimed win — 20-26 games per matchup is still a
modest sample.

**Two things this testing surfaced, deliberately left as backlog, not fixed as part of B1** (same
discipline as A6 leaving `MOBILITY_WEIGHT` alone to isolate what PST bought): a reproducible
opening weakness where the evaluation can't tell a genuinely bad early queen sortie from a good
one (5 of 9 total losses across this milestone's batches trace to one of two such patterns,
several of them byte-identical games against different opponents — real evidence, not noise), and
a pre-existing iterative-deepening risk where `get_move()` starts a new search depth with no
forecast of whether it fits the remaining budget (confirmed present in `v6-pst` too, at equal
magnitude, via direct depth-by-depth timing — not something B1 introduced).

Snapshot: `versions/v7-numba-eval/agent.py`.

### B2 — neural-net evaluation (stretch goal) — ✅ PROMOTED to root `agent.py` (2026-09-11, ~07:35)

**Root `agent.py` now runs the blend+A11 candidate** (classical eval blended 50/50 with the NNUE
net, plus the A11 history heuristic) — promoted after the 250-game confirmed result (65.8% vs.
`a10-killers`) made it the best-evidenced candidate of the session. Promotion checklist, all
verified fresh against the actual promoted files, not assumed from the `versions/` copy:
- Cold-start import time: 3.6s (budget: 90s).
- `ruff`/`mypy` clean (one pre-existing `onnxruntime` stub warning, not a real defect).
- 22/22 edge-case checks pass.
- **Found and fixed a real packaging bug**: `harness/package.py`'s `DEFAULT_INCLUDES` only bundles
  `.py` files plus anything literally named `weights` — it silently produced a zip with only
  `agent.py`, missing both `.onnx` files, which would have crashed on the platform's first move.
  Fixed by passing `--include b2_model.onnx --include b2_model.onnx.data` explicitly. **Anyone
  re-running `python -m harness.package` for this build must pass those same two flags** or the
  zip will be broken again.
- Re-packaged zip verified by unzipping to a clean directory and running `evaluate()`/`get_move()`
  from that isolated location - exactly what the platform does - before trusting it.
  `submission.zip`: 754KB zipped / 843KB unzipped (agent.py + both `.onnx` files), comfortably
  under the 50MB cap.
  ~ 4-game live sanity batch vs. `minimax` run directly against the promoted file: 75.0%,
  no crashes/flags, consistent with the extensively-tested game-strength numbers below.

A small MLP (768 binary features → hidden layers → 1 score) trained on positions labeled by the
classical engine's own search, exported to ONNX, run via `onnxruntime`. Two rounds so far, full
narrative and exact numbers in `game-logs/FEEDBACK.md`; summary here.

**Round 1**: 12,000 positions, depth-2 labels. Lost badly to `a10-killers` (25.0%), traced to the
NNUE eval costing ~15.5x the classical eval per call.

**Round 2**: fixed the eval-speed problem for real (bitboard-jitted feature encoder, same trick
B1 used — verified byte-identical to the old encoder first; plus onnxruntime session tuning) —
cost dropped to 7.6x classical. Also generated a better dataset (20,000 positions, depth-3
labels, from `a10-killers`) and trained two architectures on it. Result was a genuine surprise:
the more-accurate, same-speed-as-round-1 model ("same", RMSE 235.0) scored *worse* (16.7%) than
round 1 did, while a smaller, *less* accurate but faster model ("small", RMSE 260.8, 5.6x
classical) scored better (26.7% vs. `a10-killers`, 87.5% vs. `greedy`, 77.5% vs. `minimax` fast
clock). Profiling (both `cProfile` and a clean unprofiled node-count comparison) found the real
cause: even at 7.6x classical cost, NNUE still reaches only 70-90% of the classical engine's
search nodes in the same time budget — a genuine depth handicap the accuracy gain doesn't yet pay
for. Also found, as a side effect of this profiling: `python-chess`'s own move-generation machinery
(not `evaluate()`) is ~70% of the *classical* engine's total search time — B1's eval speedup
already made classical eval a non-issue.

**Round 3 (2026-09-11)**: four requested follow-up experiments. Two dead ends, measured and
documented honestly: int8 quantization of `b2-nnue-small` is 1.22x *slower*, not faster (this
network is too small for int8's efficiency gains to pay off); a full leaf-batching integration
(a transposition-keyed eval cache, pre-warmed at the two natural batching points in the search)
was built and verified fully correct, but real search showed no net win (pre-warming trades away
alpha-beta's own pruning savings). Two real wins: A11 (history heuristic) re-tested at 50 games
scored 54.0%, reversing its original apparent regression (now believed to have been sample
noise); and **blending the classical eval with the NNUE net (50/50 weight) beats `a10-killers`
outright — 58.0% confirmed across two 50-game samples**, and **combined with A11's history
heuristic, 65.7% across three 50-game samples (150 games total)**. Both are the first NNUE-
adjacent results all session to actually beat the classical engine, not just approach it.

**Status: PROMOTED.** `versions/b2-blend-plus-a11` was the strongest tested candidate overall
(65.7-65.8% vs. `a10-killers` across 250 games, wins/sweeps against every other opponent tested)
and is now root `agent.py` itself, per the user's explicit instruction after reviewing this data
- see the promotion checklist at the top of this section for the fresh verification that ran
against the actual promoted files. `versions/b2-blend` (50/50, no A11) remains the next-best,
simpler alternative if this needs to be rolled back (58.0%, confirmed twice) -
`agent_classical_backup.py`-style rollback: the pre-promotion classical `agent.py` is recoverable
from git history (the commit immediately before this promotion) if needed. `versions/b2-nnue-small`
(pure NNUE, no blending) remains for reference but is superseded. Full numbers, the sample-
variance investigation behind the confirmed figures above, and the version-lineage audit that
motivated the repeated-sampling discipline are all in `game-logs/FEEDBACK.md`.
