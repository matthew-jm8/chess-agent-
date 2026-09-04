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
| A4 | Iterative deepening + real time management | ⬜ next |
| A5 | Quiescence search | ⬜ planned |
| A6 | Evaluation upgrade: piece-square tables | ⬜ planned |
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

**A4. Iterative deepening + real time management** — replace fixed depth with iterative
deepening (depth 1, 2, 3, ... keeping the best move from each pass), driven by a real budget
from `time_left_ms` (starting point: `time_left_ms / max(20, expected_moves_left)`), checked
*inside* the search loop. This is the fix for the flagging risk found during A1 testing (see
below) — not optional.

**A5. Quiescence search** — captures-only extension at leaf nodes, fixing the horizon effect
where the static eval is measured mid-exchange.

**A6. Evaluation upgrade** — material + piece-square tables (and mobility/king safety if time
allows), on top of the now-solid search. This becomes the reference point for judging whether
the stretch-goal neural net (B2) is actually worth shipping.

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
