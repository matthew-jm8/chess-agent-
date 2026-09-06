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
| B0 | Full env parity on Silicon Mac (torch/numba/onnxruntime) | ⬜ blocked on hardware |
| B1 | numba-jit the evaluation | ⬜ planned |
| B2 | Neural-net evaluation (**stretch goal**, not required) | ⬜ optional |
| C | Submission safety buffer (gate, edge cases, zip, smoke games) | ⬜ last 1-2 days |

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

**B0. Full environment parity** — plain `uv sync` (no exclusions); confirm torch, onnxruntime,
numba install cleanly; run `make gate`.

**B1. numba-jit the evaluation** — following `baselines/numba/agent.py`'s pattern exactly:
encode board state into numpy arrays, `@njit` the hot evaluation function, warm it up once at
import (inside the init budget, not on the clock). The win is the extra depth the speed buys,
not the eval call itself.

**B2. Neural-net evaluation — stretch goal only.** A solid classical engine (A0–A6, B1) is the
safe submission; this is attempted only with real time to spare. Train a small NNUE-style net
in torch offline (self-play / public games, labelled with a search-based signal — allowed, since
the restriction is on what ships in the zip, not what's learned from), export to ONNX, keep it
small (1–40 MB, per `docs/IDEAS.md`'s sizing guidance), run inference via `onnxruntime`. Ships
only if it actually beats the classical engine in an arena run.

## Phase C — submission safety buffer (last 1–2 days before Sept 11)

- `make gate` (ruff + mypy strict + quick sanity games) clean.
- Stress-test edge cases: no legal moves, promotion, underpromotion, en passant, insufficient
  material.
- If torch is used anywhere: `torch.set_num_threads(1)` at import.
- `make zip`; confirm `submission.zip` is under the 50 MB cap with `agent.py` at the root.
- Run the platform's required two smoke games (one per color) with days of margin left.

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
