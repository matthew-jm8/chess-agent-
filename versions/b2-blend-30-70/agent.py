"""The submission entrypoint. The platform imports this file and calls get_move."""

import math
import random
import time
from collections.abc import Hashable, Mapping, Sequence
from typing import NamedTuple

import chess
import numpy as np
from numba import njit

# Import time runs once per game, inside a 60 second budget, before your clock starts.
# Load weights and build tables out here, not inside get_move.

# Material values, unchanged since baselines/minimax (milestone A1). Piece-square tables
# (milestone A6, below) add a positional term on top of this; material itself stays as-is so
# the comparison isolates what positional understanding alone is worth.
PIECE_VALUE = {
    chess.PAWN: 100.0,
    chess.KNIGHT: 320.0,
    chess.BISHOP: 330.0,
    chess.ROOK: 500.0,
    chess.QUEEN: 900.0,
}
MOBILITY_WEIGHT = 4.0
MATE = 1e6

# For scoring the *attacker* side of a capture (order_moves, below). PIECE_VALUE has no entry
# for the king - it isn't material to count in the evaluation - but a king can capture, so
# ordering needs a value for it too. Giving it the largest value here (deliberately separate
# from PIECE_VALUE, not a real material worth) means "the king did the capturing" sorts last
# among captures of the same victim, which is what MVV-LVA intends: prefer capturing with the
# least valuable attacker.
ATTACKER_VALUE = {**PIECE_VALUE, chess.KING: 10_000.0}

# --- Time management (milestone A4) ---
#
# Milestones A1-A3 all used a fixed search depth and found the same problem three times over:
# a fixed depth has no idea how much clock is actually left, so it's either too shallow (wastes
# a generous clock) or too deep (flags on a tight one) - there's no single right answer, because
# the right answer changes every move. The fix is to stop guessing a depth up front and instead
# search iteratively deeper - depth 1, then 2, then 3, ... - keeping the best move found by the
# last depth that *finished*, and stopping the moment the clock says to. This is called
# "iterative deepening": each shallow pass is cheap compared to the deep ones, so re-doing that
# shallow work isn't wasted the way it sounds - what it buys is always having a good answer
# ready, however far deepening actually got before time ran out.
MAX_DEPTH = 40  # a generous, mostly symbolic cap - the clock is expected to bind first in almost
# every real position; this just bounds the pathological case (e.g. a near-empty endgame board
# where each depth is so cheap that dozens could complete) rather than depending on time alone.

# Budget this move gets, per docs/IDEAS.md's own starting formula: time_left_ms divided by an
# estimate of how many of our own moves remain. OWN_MOVES_PLAYED counts our moves so far this
# game (module state, persists between get_move calls, resets naturally each new process/game).
# Assume a "typical" game is roughly 40 of our own moves; the max(20, ...) floor means we never
# assume fewer than 20 remain even very late in a long game, so we never allocate more than
# time_left_ms / 20 to a single move just because the game has run long.
OWN_MOVES_PLAYED = 0
ASSUMED_GAME_LENGTH_PLIES = 40

# Real, measured margin, not a guess. Checking the clock on every node (see check_time, below)
# means overshoot past the deadline measured under 1ms across a range of budgets from 50ms to
# 1000ms in testing - there's no large "checking gap" to buy insurance against here. This value
# is deliberately just a healthy multiple of that measured overshoot, not the old (much
# larger, and it turned out actively harmful) guess: a bigger margin was silently starving the
# search of the ~150ms it usually takes to even finish depth 3, dropping real games all the way
# back down to depth 2 for the entire early game - measured directly, not assumed, by tracing
# a realistic fast-control move and finding it stopped at depth 2 with a 150ms margin in place.
SAFETY_MARGIN_MS = 50


class TimeUp(Exception):
    """Not an error - a control-flow signal to unwind the search the moment the deadline for
    this move passes. Caught once, at the top of the iterative deepening loop in get_move.
    """


DEADLINE = math.inf  # a time.monotonic() value; set fresh at the start of every get_move call

# Measured, not assumed: checking every node here costs about 1024x less than skipping 1024 of
# them saves. A "check every N nodes" interval only makes sense relative to how expensive a
# node actually is - in a fast, compiled engine doing millions of nodes/sec, skipping 1024 of
# them between checks is a rounding error; here, one node (move generation, an evaluation,
# maybe a TT lookup, all in Python) measured close to 0.1ms, so a 1024-node interval let a
# single tiny-budget move overshoot by ~100ms before ever getting a chance to bail out - the
# reasonable-sounding number turned out to be tuned for a completely different engine's speed.
# Checking every node costs a time.monotonic() call - a handful of nanoseconds - against a node
# that costs on the order of 100 microseconds; the overhead is negligible either way.


def check_time() -> None:
    """Raise TimeUp the moment our budget for this move is gone. Called from inside negamax,
    not just between iterative-deepening passes - a single depth can itself take too long
    (measured over a full second at depth 4 in earlier milestones), so waiting until a whole
    depth finishes to check the clock is not enough on its own.
    """
    if time.monotonic() >= DEADLINE:
        raise TimeUp

# --- Transposition table (milestone A3) ---
#
# The same position can be reached by more than one move order (a "transposition"), and
# because the process stays alive between get_move() calls, the *same* position can also come
# up again on a later move in this game. A transposition table remembers what a past search
# already worked out, so it doesn't get worked out again. TT persists across moves on purpose
# (docs/IDEAS.md: "a transposition table that survives across moves is a real gain") - a fresh
# process starts per game per the platform's rules, so it naturally starts empty each game.
#
# An alpha-beta score is only meaningful *within the (alpha, beta) window it was searched
# with* - reusing one blindly under a different window can return a wrong move, so each entry
# also records how the search that produced it ended relative to its own window:
#   EXACT      the true score (search finished normally, between alpha and beta)
#   LOWERBOUND the true score is *at least* this (search failed high: beta cutoff)
#   UPPERBOUND the true score is *at most* this (search failed low: never beat alpha)
EXACT, LOWERBOUND, UPPERBOUND = range(3)


class TTEntry(NamedTuple):
    depth: int  # remaining depth the score was computed with - deeper is more trustworthy
    score: float
    flag: int  # EXACT, LOWERBOUND, or UPPERBOUND, above
    best_move: chess.Move | None  # milestone A9: the move that produced this score, if any -
    # used only as a move-ordering hint (try this first next time this position comes up, even
    # when depth is too shallow to trust the score itself), never as a substitute for actually
    # searching a node. Still meaningful on an UPPERBOUND (fail-low) entry, where it's the
    # least-bad move found rather than a proven-best one - a real hint either way, not a
    # guarantee, same spirit as reusing an EXACT/LOWERBOUND score under a different window.


TT: dict[Hashable, TTEntry] = {}
# Rough safety cap, not a precise benchmark: bounds memory over a long game (the platform caps
# the process at 2 GB and games at 300 plies) by clearing the table outright if it grows huge,
# rather than tracking per-entry age/eviction, which this milestone deliberately keeps simple.
TT_MAX_ENTRIES = 2_000_000

# Known simplification: MATE below is a flat constant, not adjusted for how many moves deep it
# was found. A mate score that bubbles up into a TT entry doesn't distinguish "mate in 2" from
# "mate in 5" the way a fully correct engine's TT does. MATE dwarfs every positional score, so
# this shouldn't change which move gets picked - it's a real, accepted trade-off, not a bug.


def store_tt(
    key: Hashable, depth: int, score: float, flag: int, best_move: chess.Move | None
) -> None:
    if len(TT) >= TT_MAX_ENTRIES:
        TT.clear()
    TT[key] = TTEntry(depth, score, flag, best_move)


# --- Killer moves (milestone A10) ---
#
# A9 gave the TT move top priority, but that only fires on an exact transposition (or the same
# position reached again, shallower, later in the game) - most nodes have no TT hint at all, and
# their quiet moves still had zero ranking beyond raw generation order (order_moves' score()
# giving every quiet move the same flat -1.0). Killer moves plug that gap with a much cheaper
# signal than a full transposition: a quiet move that caused a beta cutoff *at this same distance
# from the leaves* recently is disproportionately likely to be strong again in a sibling node -
# not because it's the same position, but because the same tactical idea (a check, a threat, an
# escape) often recurs across nearby branches of the tree.
#
# Indexed by remaining depth (the same "depth" negamax is already called with), not distance from
# the root - simpler, and standard practice in engines this size; it means a killer recorded in
# one branch of the tree can help order a sibling branch at the same depth, which is exactly the
# cross-branch reuse this heuristic is for.
KILLER_MOVES: list[list[chess.Move]] = [[] for _ in range(MAX_DEPTH + 1)]
KILLERS_PER_DEPTH = 2  # the standard slot count - enough to catch a second good idea without the
# list becoming stale as fast as a single slot would.


def store_killer(depth: int, move: chess.Move) -> None:
    """Record `move` as a cutoff-causing quiet move at `depth`, most-recent first. Only ever
    called for quiet moves (see negamax) - captures already have MVV-LVA/SEE-quality ordering of
    their own and don't need this.
    """
    killers = KILLER_MOVES[depth]
    if move in killers:
        return  # already recorded here; don't duplicate it into both slots
    killers.insert(0, move)
    del killers[KILLERS_PER_DEPTH:]


# --- History heuristic (milestone A11 - implemented, verified, NOT currently wired in) ---
#
# Killer moves (above) only rank the 1-2 most recent cutoffs *at one exact depth*. Every other
# quiet move - including a killer's own understudy from three plies ago, or a move that keeps
# causing cutoffs but never quite makes a depth's 2-slot cut - still had zero ranking among
# itself and every other non-killer quiet move. History fixes that with a cheaper, coarser, but
# much longer-memory signal: a running count, per (from_square, to_square) - not per full move,
# so a knight hopping the same two squares under different circumstances still shares one count -
# of how often that piece movement has caused a cutoff *anywhere in the whole search*, weighted
# by depth^2 (deeper cutoffs are rarer and a stronger signal than shallow ones, and squaring is
# the standard weighting - it separates a single deep cutoff from many shallow coincidental ones).
#
# Wired in, tested, and reverted: at a fixed depth with a full alpha-beta window, this measurably
# helps (0/8 mismatched scores vs. not having it, ~10% fewer nodes, ~13% less time - ordering
# changes efficiency, never correctness, and that held up under direct testing). But a 30-game batch
# against the pre-A11 baseline came back 35.0% (+8 =5 -17, no flags - a clean, real signal), and
# a real get_move() move-choice comparison (8 positions, generous shared time budget, an
# independent fixed-depth judge) found the two versions agreed 6/8 of the time and split evenly
# on the other 2 (one clearly worse, one clearly better) - nothing there explains a swing this
# large either. Root cause not found, not guessed at further - reverted out of caution rather
# than shipped on an unresolved contradiction between "the mechanism looks sound" and "the batch
# says otherwise." Kept here, unwired, as verified-but-unresolved groundwork - see
# game-logs/FEEDBACK.md's A11 section for the full investigation before touching this again.
HISTORY: dict[tuple[chess.Square, chess.Square], int] = {}
HISTORY_CAP = 10_000  # calibrated so even one very-deep cutoff (depth 40 -> 1,600) doesn't need
# many repeats to saturate the scaled range below - deliberately coarse, not finely tuned; this
# only has to distinguish "seen a lot" from "never seen," not rank precisely against itself.
_EMPTY_HISTORY: Mapping[tuple[chess.Square, chess.Square], int] = {}


def store_history(move: chess.Move, depth: int) -> None:
    """Bump the (from, to) pair's cutoff count. Same caller/scope restriction as store_killer:
    only quiet moves, only on an actual beta cutoff.
    """
    key = (move.from_square, move.to_square)
    HISTORY[key] = HISTORY.get(key, 0) + depth * depth


# --- Piece-square tables (milestone A6) ---
#
# Material alone treats every knight as worth the same 320 points regardless of where it
# stands, but a knight in the corner covers 2 squares and one in the center covers 8 - they
# are not actually equal. A piece-square table is just a lookup of a bonus/penalty per square
# for a given piece type, added on top of material. These are the widely-used "Simplified
# Evaluation Function" tables (Tomasz Michniewski, published on the Chess Programming Wiki as
# an openly-shared educational reference, not any engine's proprietary weights) - a real,
# well-tested starting point rather than a from-scratch guess at 384 numbers.
#
# Written below in the usual published form: 8 rows of a8..h8 down to a1..h1, White's
# perspective. That's the opposite order from how python-chess numbers squares (0=a1 up to
# 63=h8), so _to_square_indexed reverses the row order once at import time rather than
# hand-transcribing every table into an unfamiliar order (error-prone for 6 tables of 64
# numbers each, and much harder to check by eye against the published version).

def _to_square_indexed(rank8_to_rank1: list[float]) -> list[float]:
    rows = [rank8_to_rank1[i : i + 8] for i in range(0, 64, 8)]
    return [value for row in reversed(rows) for value in row]


_PAWN_PST = _to_square_indexed(
    [
        0, 0, 0, 0, 0, 0, 0, 0,
        50, 50, 50, 50, 50, 50, 50, 50,
        10, 10, 20, 30, 30, 20, 10, 10,
        5, 5, 10, 25, 25, 10, 5, 5,
        0, 0, 0, 20, 20, 0, 0, 0,
        5, -5, -10, 0, 0, -10, -5, 5,
        5, 10, 10, -20, -20, 10, 10, 5,
        0, 0, 0, 0, 0, 0, 0, 0,
    ]
)
_KNIGHT_PST = _to_square_indexed(
    [
        -50, -40, -30, -30, -30, -30, -40, -50,
        -40, -20, 0, 0, 0, 0, -20, -40,
        -30, 0, 10, 15, 15, 10, 0, -30,
        -30, 5, 15, 20, 20, 15, 5, -30,
        -30, 0, 15, 20, 20, 15, 0, -30,
        -30, 5, 10, 15, 15, 10, 5, -30,
        -40, -20, 0, 5, 5, 0, -20, -40,
        -50, -40, -30, -30, -30, -30, -40, -50,
    ]
)
_BISHOP_PST = _to_square_indexed(
    [
        -20, -10, -10, -10, -10, -10, -10, -20,
        -10, 0, 0, 0, 0, 0, 0, -10,
        -10, 0, 5, 10, 10, 5, 0, -10,
        -10, 5, 5, 10, 10, 5, 5, -10,
        -10, 0, 10, 10, 10, 10, 0, -10,
        -10, 10, 10, 10, 10, 10, 10, -10,
        -10, 5, 0, 0, 0, 0, 5, -10,
        -20, -10, -10, -10, -10, -10, -10, -20,
    ]
)
_ROOK_PST = _to_square_indexed(
    [
        0, 0, 0, 0, 0, 0, 0, 0,
        5, 10, 10, 10, 10, 10, 10, 5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        0, 0, 0, 5, 5, 0, 0, 0,
    ]
)
_QUEEN_PST = _to_square_indexed(
    [
        -20, -10, -10, -5, -5, -10, -10, -20,
        -10, 0, 0, 0, 0, 0, 0, -10,
        -10, 0, 5, 5, 5, 5, 0, -10,
        -5, 0, 5, 5, 5, 5, 0, -5,
        0, 0, 5, 5, 5, 5, 0, -5,
        -10, 5, 5, 5, 5, 5, 0, -10,
        -10, 0, 5, 0, 0, 0, 0, -10,
        -20, -10, -10, -5, -5, -10, -10, -20,
    ]
)
# Middlegame-shaped only (rewards staying tucked behind pawns): a fully correct engine blends
# this with a separate endgame table that instead rewards an active, centralized king once
# material thins out. Not doing that game-phase detection is a deliberate simplification for
# this milestone - the king table below is used for the whole game, not just the middlegame.
_KING_PST = _to_square_indexed(
    [
        -30, -40, -40, -50, -50, -40, -40, -30,
        -30, -40, -40, -50, -50, -40, -40, -30,
        -30, -40, -40, -50, -50, -40, -40, -30,
        -30, -40, -40, -50, -50, -40, -40, -30,
        -20, -30, -30, -40, -40, -30, -30, -20,
        -10, -20, -20, -20, -20, -20, -20, -10,
        20, 20, 0, 0, 0, 0, 20, 20,
        20, 30, 10, 0, 0, 10, 30, 20,
    ]
)

PST = {
    chess.PAWN: _PAWN_PST,
    chess.KNIGHT: _KNIGHT_PST,
    chess.BISHOP: _BISHOP_PST,
    chess.ROOK: _ROOK_PST,
    chess.QUEEN: _QUEEN_PST,
    chess.KING: _KING_PST,
}


# --- numba-jit the evaluation (milestone B1) ---
#
# Per docs/IDEAS.md: "numba closes most of that gap ... warm every jitted function once at
# import ... baselines/numba shows the pattern." The win isn't the eval call itself; it's the
# extra search depth the freed-up time budget buys.
#
# First attempt encoded the board into three numpy arrays via board.piece_map() (a Python-level
# dict of Piece objects) and passed those arrays into a jitted per-square loop. Measured directly:
# that was only ~1.0-1.3x faster than the original pure-Python eval, even after removing the
# arrays' own allocation cost - a real board has at most 32 occupied squares, so the fixed cost
# of piece_map()'s dict construction plus numba's own per-call argument marshaling for three array
# arguments was competing with (and mostly cancelling out) whatever the compiled loop itself won.
#
# This version instead reads the board's raw bitboards - plain Python ints python-chess already
# maintains (board.pawns, board.knights, ..., board.occupied_co[color]) - and hands them straight
# into ONE jitted function that does the decoding *and* the evaluation together, in compiled code.
# Scalar arguments marshal far more cheaply than array arguments, and there's no Python-side
# piece_map() dict to build at all. Measured directly: ~8x faster than the array version above,
# i.e. roughly an order of magnitude faster than the original pure-Python eval - confirmed
# numerically identical to it across ~8,000 random positions before being adopted.

# PST as one (7, 64) array: row 0 unused (no piece there), rows 1-6 match chess.PAWN..chess.KING
# and come straight from the PST dict above, so the published table values stay the single
# source of truth - this is a reshaping of them for numba, not a second transcription.
_PST_ARR = np.zeros((7, 64), dtype=np.float64)
for _pt, _table in PST.items():
    _PST_ARR[_pt] = _table

# Same idea for material. PIECE_VALUE has no king entry (it isn't material to count), so row 6
# stays 0.0 - a king contributes nothing to the material term, matching the old dict-based sum.
_PIECE_VALUE_ARR = np.zeros(7, dtype=np.float64)
for _pt, _value in PIECE_VALUE.items():
    _PIECE_VALUE_ARR[_pt] = _value


@njit(cache=False)
def _evaluate_bitboards_jit(
    pawns: np.uint64,
    knights: np.uint64,
    bishops: np.uint64,
    rooks: np.uint64,
    queens: np.uint64,
    kings: np.uint64,
    white_occ: np.uint64,
    black_occ: np.uint64,
    white_to_move: bool,
    mobility: int,
) -> float:
    """Decode each of python-chess's per-piece-type bitboards (one uint64, one bit per square,
    all six sharing the same 64 squares) and evaluate in the same pass - the per-square loop
    evaluate() has always done, just no longer needing a Python object per occupied square first.

    uint64 specifically (not a plain Python/numba int64): a bitboard can legitimately have bit 63
    set (h8 occupied), and int64 is signed - shifting a negative two's-complement value right
    sign-extends instead of bringing in zeros, which would corrupt every square's bit test past
    the first occupied high bit. uint64 keeps every shift and comparison here unsigned throughout.
    """
    material = 0.0
    positional_score = 0.0
    one = np.uint64(1)
    for square in range(64):
        bit = one << np.uint64(square)
        is_white = (white_occ & bit) != np.uint64(0)
        is_black = (black_occ & bit) != np.uint64(0)
        if not is_white and not is_black:
            continue
        if pawns & bit:
            piece_type = 1
        elif knights & bit:
            piece_type = 2
        elif bishops & bit:
            piece_type = 3
        elif rooks & bit:
            piece_type = 4
        elif queens & bit:
            piece_type = 5
        else:
            piece_type = 6  # king - no bitboard check needed, it's the only piece type left
        value = _PIECE_VALUE_ARR[piece_type]
        # Mirroring a square vertically (White's PST perspective -> Black's) is XOR 56 in bitboard
        # terms (0=a1..63=h8, 8 files/rank): flips the rank triplet of bits, keeps the file as-is
        # - the same mirror chess.square_mirror() does, done here without a function call per hit.
        table_square = square if is_white else (square ^ 56)
        bonus = _PST_ARR[piece_type, table_square]
        if is_white == white_to_move:
            material += value
            positional_score += bonus
        else:
            material -= value
            positional_score -= bonus
    return material + MOBILITY_WEIGHT * mobility + positional_score


def _classical_evaluate(board: chess.Board, mobility: int) -> float:
    """The B1/A-series material+mobility+PST evaluation - kept, renamed, for reference and as
    what this B2 experiment is measured against. Not called by quiescence() in this variant;
    see evaluate(), below.
    """
    return _evaluate_bitboards_jit(
        np.uint64(board.pawns),
        np.uint64(board.knights),
        np.uint64(board.bishops),
        np.uint64(board.rooks),
        np.uint64(board.queens),
        np.uint64(board.kings),
        np.uint64(board.occupied_co[chess.WHITE]),
        np.uint64(board.occupied_co[chess.BLACK]),
        board.turn == chess.WHITE,
        mobility,
    )


# Compile now, at import (inside the 90 second budget), not on the first real move. numba
# compiles per argument signature, so this has to call with the exact types get_move's calls
# will really use - an int32 warm-up would not help a call that later shows up as int64.
_classical_evaluate(chess.Board(), 20)


# --- B2: NNUE-style neural net evaluation (experimental - replaces the classical eval above) ---
#
# Trained offline (see training-data/ and game-logs/FEEDBACK.md's B2 section for the full
# pipeline): a small MLP over 768 binary features (12 planes - 6 "my piece type" + 6 "opponent
# piece type" - x 64 squares each), labeled by this engine's own depth-2 search on ~12,000 real
# positions from tonight's own games (per AGENTS.md: "training it on positions an engine labelled
# is a normal way to do that"). Exported to ONNX, verified to match the raw torch model's output
# within floating-point tolerance before being trusted here.
#
# A pure A/B replacement, not a blend: evaluate() below returns ONLY the net's output, nothing
# from _classical_evaluate() - the cleanest way to directly test the roadmap's own question
# ("does this beat the classical engine"), without conflating the two signals.
import os as _os  # noqa: E402

import onnxruntime as _ort  # noqa: E402

_NNUE_PIECE_TYPE_INDEX = {
    chess.PAWN: 0,
    chess.KNIGHT: 1,
    chess.BISHOP: 2,
    chess.ROOK: 3,
    chess.QUEEN: 4,
    chess.KING: 5,
}
_nnue_model_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "b2_model.onnx")
# Session tuning (measured, see game-logs/FEEDBACK.md B2 section): the platform contract gives
# us one CPU core, so ORT's default multi-thread pool setup is pure overhead - it spins up
# threads it can never actually parallelize across. Pinning to 1 thread and disabling the
# memory-pattern arena (which optimizes for varying batch sizes; we only ever call batch=1)
# measured ~10% faster per call (63.2us -> 57.6us) with byte-identical output.
_nnue_opts = _ort.SessionOptions()
_nnue_opts.intra_op_num_threads = 1
_nnue_opts.inter_op_num_threads = 1
_nnue_opts.graph_optimization_level = _ort.GraphOptimizationLevel.ORT_ENABLE_ALL
_nnue_opts.enable_mem_pattern = False
_nnue_opts.execution_mode = _ort.ExecutionMode.ORT_SEQUENTIAL
_nnue_session = _ort.InferenceSession(
    _nnue_model_path, sess_options=_nnue_opts, providers=["CPUExecutionProvider"]
)


def _nnue_features_pure_python(board: chess.Board) -> np.ndarray:
    """Original feature encoder, kept for reference/verification only - see _nnue_features below
    for the version actually used. Same 768-dim encoding used to build the training set (see
    training-data/b2_train.py): white-oriented, mirror-for-the-non-mover's-pieces squares,
    exactly matching the convention _PST_ARR/_evaluate_bitboards_jit already use, so a knight on
    d4 for the White mover and a knight on d5 for the Black mover land on the identical feature.
    """
    features = np.zeros((1, 768), dtype=np.float32)
    mover = board.turn
    for square, piece in board.piece_map().items():
        table_square = square if piece.color == chess.WHITE else chess.square_mirror(square)
        plane = _NNUE_PIECE_TYPE_INDEX[piece.piece_type] + (0 if piece.color == mover else 6)
        features[0, plane * 64 + table_square] = 1.0
    return features


# Speed fix (measured, see game-logs/FEEDBACK.md B2 section): the pure-Python version above cost
# 27.3us/call, MORE than the entire onnxruntime inference call (19.5us/call) - the exact same
# piece_map()-dict-loop cost B1 found and fixed for the classical eval, applied here. This
# version reads the board's raw bitboards directly (no per-square Piece object, no dict) and
# writes the 768 one-hot features in one jitted pass, same technique as
# _evaluate_bitboards_jit above.
@njit(cache=False)
def _encode_nnue_features_jit(
    pawns: np.uint64,
    knights: np.uint64,
    bishops: np.uint64,
    rooks: np.uint64,
    queens: np.uint64,
    kings: np.uint64,
    white_occ: np.uint64,
    black_occ: np.uint64,
    white_to_move: bool,
    out: np.ndarray,
) -> None:
    out[:] = 0.0
    one = np.uint64(1)
    for square in range(64):
        bit = one << np.uint64(square)
        is_white = (white_occ & bit) != np.uint64(0)
        is_black = (black_occ & bit) != np.uint64(0)
        if not is_white and not is_black:
            continue
        if pawns & bit:
            type_index = 0
        elif knights & bit:
            type_index = 1
        elif bishops & bit:
            type_index = 2
        elif rooks & bit:
            type_index = 3
        elif queens & bit:
            type_index = 4
        else:
            type_index = 5  # king
        table_square = square if is_white else (square ^ 56)
        plane = type_index + (0 if is_white == white_to_move else 6)
        out[plane * 64 + table_square] = 1.0


_nnue_feature_buffer = np.zeros((1, 768), dtype=np.float32)


def _nnue_features(board: chess.Board) -> np.ndarray:
    """Bitboard-jitted feature encoder - see _nnue_features_pure_python above for the reference
    version this is verified against. Reuses one buffer array across calls (also measured
    faster than allocating a fresh np.zeros every call) - safe because onnxruntime's session.run
    reads the array synchronously and nothing here holds a reference to a past call's contents.
    """
    _encode_nnue_features_jit(
        np.uint64(board.pawns),
        np.uint64(board.knights),
        np.uint64(board.bishops),
        np.uint64(board.rooks),
        np.uint64(board.queens),
        np.uint64(board.kings),
        np.uint64(board.occupied_co[chess.WHITE]),
        np.uint64(board.occupied_co[chess.BLACK]),
        board.turn == chess.WHITE,
        _nnue_feature_buffer[0],
    )
    return _nnue_feature_buffer


BLEND_CLASSICAL_WEIGHT = 0.3
BLEND_NNUE_WEIGHT = 0.7


def evaluate(board: chess.Board, mobility: int) -> float:
    """Score a position from the side-to-move's perspective: positive is good for them.
    B2 blend experiment (2026-09-11, requested test - not a proven improvement, not shipped):
    a 50/50 weighted combination of the classical static eval (material+mobility+PST, cheap,
    proven) and the NNUE net's output (trained on depth-3 search labels - a rough, learned proxy
    for deeper lookahead the classical eval doesn't have). Hypothesis: the two carry genuinely
    different signal (a static heuristic vs. a compressed deeper-search approximation), so a
    blend might hedge against the NNUE's own inaccuracy while adding *some* of what it learned -
    at the cost of paying BOTH evals' time every call, on top of an already-too-slow NNUE path.
    Weight is an untuned, symmetric starting point, not searched/optimized - see
    game-logs/FEEDBACK.md for the real batch result before treating this as validated either way.
    """
    classical_score = _classical_evaluate(board, mobility)
    features = _nnue_features(board)
    nnue_score = float(_nnue_session.run(["eval"], {"features": features})[0].item())
    return BLEND_CLASSICAL_WEIGHT * classical_score + BLEND_NNUE_WEIGHT * nnue_score


# Warm up the ONNX Runtime session now, at import, same reasoning as numba's own warm-up above -
# first-call overhead (session/kernel setup) belongs in the init budget, not on the clock.
evaluate(chess.Board(), 20)


# --- Static Exchange Evaluation (milestone A7 - implemented, verified, NOT currently wired in) ---
#
# order_moves' MVV-LVA score (below) looks at exactly one capture in isolation - victim value
# minus attacker value - with no idea whether the capturing piece is itself then recaptured. SEE
# instead plays the *whole* exchange out - every attacker and defender of the target square,
# taking turns with their cheapest piece, each side free to stop the instant continuing would
# cost them material - and returns the real net result. It's correct (hand-verified against
# several positions, including an x-ray case) and was wired into order_moves/quiescence for a
# real attempt, but measured out as a net loss: see() costs ~6.5x MVV-LVA per call (18.4us vs
# 2.8us, isolated benchmark), paid on every capture at every node across the *whole* tree (not
# just quiescence, since order_moves is called from negamax too) - two independent 30-game
# batches against the pre-A7 baseline both came back under 50% (46.7%, then 45.0% after fixing an
# unrelated double-call inefficiency, which didn't move the number). The per-call cost, not the
# pruning, is the bottleneck. Left in the file, unwired, as correct groundwork for a lighter
# bitboard-based reimplementation (following milestone B1's own array->bitboard rewrite, which
# fixed an analogous cost problem) - see game-logs/FEEDBACK.md's A7 section for the full numbers.
SEE_PRUNE_THRESHOLD = 0.0  # unused while see() is unwired; kept so a future rewrite doesn't need
# to re-derive this from scratch - see the comment above quiescence()'s (currently plain MVV-LVA
# ordered, no SEE filter) capture handling.


def _capture_value(board: chess.Board, move: chess.Move) -> float:
    """Value of whatever `move` immediately captures. Mirrors the en-passant handling
    order_moves has always needed: the captured pawn isn't on move.to_square in that one case,
    so piece_at there would wrongly see an empty square.
    """
    if board.is_en_passant(move):
        return PIECE_VALUE[chess.PAWN]
    victim = board.piece_at(move.to_square)
    assert victim is not None
    return PIECE_VALUE[victim.piece_type]


def _least_valuable_attacker(
    board: chess.Board, color: chess.Color, square: chess.Square
) -> chess.Square | None:
    """The cheapest piece of `color` currently attacking `square`, or None if there isn't one.

    Called fresh at every step of see()'s simulated exchange (board.attackers() only ever
    reflects the board as it currently stands, with no memory of earlier steps), so x-ray
    attacks - a rook behind another rook on the same file, revealed the instant the piece in
    front of it is removed - are picked up automatically, without any special-case code for them.

    Known simplification: doesn't check whether the attacking piece is pinned, or whether a king
    "attacker" would actually be moving into check - both illegal in a real game. This is the
    standard approximation heuristic SEE implementations accept; board.attackers() is a raw
    geometric attack computation, not a legal-move filter, and modeling real legality here would
    cost far more than the rare mispriced exchange it would fix.
    """
    attackers = board.attackers(color, square)
    if not attackers:
        return None

    def attacker_value(attacker_square: chess.Square) -> float:
        piece = board.piece_at(attacker_square)
        assert piece is not None
        return ATTACKER_VALUE[piece.piece_type]

    return min(attackers, key=attacker_value)


def _see_exchange(
    board: chess.Board, square: chess.Square, side: chess.Color, hanging_value: float
) -> float:
    """The value `side` can win by recapturing on `square`, where `hanging_value` is what's
    currently sitting there. Mirrors quiescence()'s own "always free to stop" logic: recapturing
    only makes sense if it doesn't lose material once the opponent's best reply is accounted for
    - `max(0.0, ...)` is what lets a side that would come out behind simply decline to capture,
    exactly the choice a real player has at every point in a real exchange.

    Known simplification: doesn't handle a pawn promoting mid-exchange (recapturing onto the
    back rank) - a further, rarer edge case than the top-level move's own promotion (handled in
    see(), below) that the existing MVV-LVA code never handled either; left out to keep this
    addition easy to verify, the same trade-off A5's quiescence made for its own scope.
    """
    attacker_square = _least_valuable_attacker(board, side, square)
    if attacker_square is None:
        return 0.0
    attacker = board.piece_at(attacker_square)
    assert attacker is not None
    attacker_value = PIECE_VALUE.get(attacker.piece_type, 0.0)

    board.remove_piece_at(attacker_square)
    board.set_piece_at(square, attacker)
    gain = hanging_value - _see_exchange(board, square, not side, attacker_value)
    return max(0.0, gain)


def see(board: chess.Board, move: chess.Move) -> float:
    """Static Exchange Evaluation: the net material result of the *entire* capture/recapture
    sequence a capture at move.to_square touches off, not just the first trade - positive means
    the side playing `move` comes out ahead once the whole exchange plays out optimally for both
    sides.

    Simulated on a scratch copy (board.copy(stack=False)) by mutating piece placement directly
    rather than board.push() - move legality, castling rights, and en passant rights don't matter
    for anything past the first capture, only which pieces still attack the target square.

    A capturing promotion leaves the *promoted* piece sitting on the target square, not the pawn
    that moved there - what the opponent could recapture has to reflect that. The value returned
    still only scores the capture itself, not the promotion's own separate material gain,
    matching the scope order_moves' old MVV-LVA score already had (it never special-cased
    promotions either).
    """
    target = move.to_square
    mover = board.piece_at(move.from_square)
    assert mover is not None
    first_victim_value = _capture_value(board, move)

    placed_piece_type = move.promotion if move.promotion is not None else mover.piece_type
    placed_piece = chess.Piece(placed_piece_type, mover.color)

    scratch = board.copy(stack=False)
    if board.is_en_passant(move):
        captured_pawn_square = target + (-8 if mover.color == chess.WHITE else 8)
        scratch.remove_piece_at(captured_pawn_square)
    scratch.remove_piece_at(move.from_square)
    scratch.set_piece_at(target, placed_piece)

    hanging_value = PIECE_VALUE.get(placed_piece_type, 0.0)
    return first_victim_value - _see_exchange(scratch, target, not mover.color, hanging_value)


def order_moves(
    board: chess.Board,
    moves: list[chess.Move],
    tt_move: chess.Move | None = None,
    killers: Sequence[chess.Move] = (),
    history: Mapping[tuple[chess.Square, chess.Square], int] = _EMPTY_HISTORY,
) -> list[chess.Move]:
    """Captures first, best captures first (MVV-LVA); quiet moves keep their given order.
    `tt_move`, when given, is tried before everything else, captures included. `killers`, when
    given, are tried after every capture but before any other quiet move.

    Alpha-beta only prunes once it has already found a move good enough to trigger a cutoff -
    so the earlier a strong move is tried, the more of the tree gets skipped. Captures are the
    moves most likely to be strong, and MVV-LVA (most-valuable-victim, least-valuable-attacker)
    orders them the way a human would scan a position first: capturing a queen with a pawn
    before capturing a pawn with a queen. See docs/IDEAS.md: "the gap between the minimax
    baseline and something respectable is mostly move ordering."

    Milestone A7 tried replacing this with see() (above) - strictly more accurate, since it plays
    the whole exchange out instead of guessing from one victim/attacker pair - but see()'s real
    per-call cost measured too high to pay for itself here; see the comment above
    SEE_PRUNE_THRESHOLD for the numbers. Reverted to plain MVV-LVA, which is what every prior
    milestone's own results (through B1) were actually measured against.

    Milestone A9 adds `tt_move`: a move a past search already found good here (see negamax's TT
    probe) is a far stronger ordering signal than any static guess about it, MVV-LVA included -
    it beats even a queen-takes-queen capture to the front of the list.

    Milestone A10 adds `killers`: quiet moves that caused a cutoff at this same depth recently
    (see store_killer) - a cheaper, cross-branch cousin of the TT move. Scored strictly between
    "worst real capture" (0.0 - a king recapturing a pawn, ATTACKER_VALUE's own extreme) and
    "ordinary quiet move" (-1.0), so a killer always sorts after every capture but ahead of every
    other quiet move.

    Milestone A11 adds `history`: every OTHER quiet move (not this depth's killer) used to tie at
    a flat -1.0 with zero ranking among them - history breaks that tie using each move's
    whole-search cutoff count (see store_history), scaled into (-1.0, -0.6] so it can never reach
    a killer's -0.5 or any real capture's >= 0.0 - it only ever refines the bottom of the order,
    never jumps the queue past a stronger signal. No caller currently passes one (defaults to
    `_EMPTY_HISTORY`) - verified correct and even faster/more-efficient at a fixed depth, but
    reverted after a real batch regression neither that nor a real-game move-choice comparison
    could explain; see the comment above HISTORY's definition and game-logs/FEEDBACK.md's A11
    section for the full, unresolved investigation.
    """

    def score(move: chess.Move) -> float:
        if move == tt_move:
            return math.inf  # milestone A9: known-good beats every static guess about a move
        if not board.is_capture(move):
            if move in killers:
                return -0.5  # milestone A10: between "quiet" (-1.0) and any real capture (>= 0.0)
            history_count = history.get((move.from_square, move.to_square), 0)
            return -1.0 + 0.4 * min(history_count, HISTORY_CAP) / HISTORY_CAP  # milestone A11
        attacker = board.piece_at(move.from_square)
        assert attacker is not None
        if board.is_en_passant(move):
            # The captured pawn isn't on move.to_square in this one case, so piece_at there
            # would wrongly see an empty square - the victim is always a pawn here regardless.
            victim_value = PIECE_VALUE[chess.PAWN]
        else:
            victim = board.piece_at(move.to_square)
            assert victim is not None
            victim_value = PIECE_VALUE[victim.piece_type]
        return victim_value * 100 - ATTACKER_VALUE[attacker.piece_type]

    return sorted(moves, key=score, reverse=True)


def quiescence(board: chess.Board, alpha: float, beta: float) -> float:
    """Extend the search at the horizon through captures only, until the position "calms down"
    (milestone A5). Without this, the main search's leaf evaluation can land exactly mid-trade -
    right after losing a piece but before recapturing it - and the static eval would see "I just
    lost a queen" and panic, when the position is actually fine once the exchange finishes.

    "Stand pat": the side to move can always choose to make no more captures and accept the
    current static score, so that score is a valid lower bound on this position's true value -
    unless the side to move is in check. In check there is no "do nothing": every legal reply
    must address the check, so standing pat is meaningless and captures-only is wrong (the only
    legal move might not be a capture at all) - the correct move there is to search every legal
    reply, not just captures, exactly as the main search would.

    Fail-soft, matching negamax: `best` (the actual best value found) is tracked separately from
    `alpha` (only a pruning threshold). A first version conflated the two - using alpha itself to
    hold "the best value so far" - which meant that whenever a move failed to beat the *incoming*
    alpha (set by whatever sibling was searched first, not by this move's own quality), the
    function returned that alpha verbatim instead of the true value it had actually found. Two
    completely different, differently-bad moves could then both fail low against the same
    inherited alpha and come back reporting the identical score - caught directly by comparing
    root move scores and finding a hung piece scored identically to a normal developing move.

    Deliberately not using the transposition table here: quiescence "depth" isn't comparable to
    the main search's remaining-depth counter, and giving it a fair place in the same table is a
    refinement this milestone leaves out to keep the addition easy to verify on its own.

    Milestone A7 tried also skipping captures here whose see() came back negative (loses material
    once the full exchange plays out) - safe in principle (stand-pat is always the fallback, and
    quiescence only ever looks at captures anyway) but reverted along with order_moves' use of
    see(), for the same real per-call-cost reason documented above SEE_PRUNE_THRESHOLD.
    """
    check_time()

    moves = list(board.legal_moves)
    if not moves:
        return -MATE if board.is_check() else 0.0

    if board.is_check():
        # No stand-pat option: every legal reply must address the check, so there is no "value
        # of doing nothing" to fall back on - best starts unset until a real reply is searched.
        best = -math.inf
        candidates = order_moves(board, moves)
    else:
        best = evaluate(board, len(moves))
        if best >= beta:
            return best
        if best > alpha:
            alpha = best
        candidates = [move for move in order_moves(board, moves) if board.is_capture(move)]

    for move in candidates:
        board.push(move)
        score = -quiescence(board, -beta, -alpha)
        board.pop()
        if score > best:
            best = score
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break
    return best


def negamax(board: chess.Board, depth: int, alpha: float, beta: float) -> float:
    """Negamax search with alpha-beta pruning.

    Negamax is minimax written so both sides use the same code: at every level we pick the
    move that is best for whoever is to move, and a child's score is negated before use,
    because "good for my opponent" is exactly "bad for me".

    alpha is the best score the side to move can already guarantee somewhere else in the
    search; beta is the best score the *other* side can already guarantee. Once we find a
    move so good it exceeds beta, the opponent would never let us reach this position in the
    first place (they had a better alternative earlier) - so we stop looking at this branch's
    remaining moves. That cutoff is what lets us search deeper than plain minimax in the same
    time: we skip branches whose outcome can't change the final decision.

    Milestone A9: the TT probe below now also pulls a move-ordering hint (see order_moves) even
    when the entry's depth is too shallow to trust its score - a move that was good here before,
    at any depth, is still a far better first guess than a static heuristic. Whatever move this
    call itself finds best gets stored back, so the hint improves the more a position is
    revisited (transpositions, or the same position one ply shallower on a later move).
    """
    check_time()  # may raise TimeUp - see get_move for how an unfinished depth is handled

    moves = list(board.legal_moves)
    if not moves:
        # No legal moves: checkmate (bad for the side to move) or stalemate (a draw). Not
        # cached - this result is valid at any depth (there are no legal moves regardless of
        # how much budget remains), and giving it a depth-independent cache entry correctly
        # needs a sentinel this milestone deliberately keeps out of scope; it's cheap to just
        # recompute (checking for an empty move list is fast).
        return -MATE if board.is_check() else 0.0

    original_alpha = alpha
    key = board._transposition_key()
    cached = TT.get(key)
    tt_move = cached.best_move if cached is not None else None
    if cached is not None and cached.depth >= depth:
        if cached.flag == EXACT:
            return cached.score
        if cached.flag == LOWERBOUND:
            alpha = max(alpha, cached.score)
        elif cached.flag == UPPERBOUND:
            beta = min(beta, cached.score)
        if alpha >= beta:
            return cached.score

    best_move: chess.Move | None = None
    if depth == 0:
        # quiescence does its own windowed sub-search (milestone A5), so its result carries the
        # same fail-high/fail-low ambiguity as a regular node's - it's classified by the same
        # flag logic below, not treated as unconditionally exact the way a bare static eval was.
        # No best_move out of quiescence - it's never stored at depth 0 (see store_tt call below
        # only running for depth > 0 nodes' own moves; a depth-0 TT entry keeps best_move=None).
        best = quiescence(board, alpha, beta)
    else:
        best = -math.inf
        for move in order_moves(board, moves, tt_move, KILLER_MOVES[depth]):
            board.push(move)
            score = -negamax(board, depth - 1, -beta, -alpha)
            board.pop()
            if score > best:
                best = score
                best_move = move
            if best > alpha:
                alpha = best
            if alpha >= beta:
                # milestones A10/A11: only quiet moves are worth remembering as killers/history -
                # a capture that causes a cutoff is already found again next time via MVV-LVA/SEE
                # ordering, which ranks captures far more precisely than either table could.
                if not board.is_capture(move):
                    store_killer(depth, move)
                break  # beta cutoff: the opponent already has a better option upstream

    flag = EXACT
    if best <= original_alpha:
        flag = UPPERBOUND  # never beat the window we came in with - a "failed low" bound
    elif best >= beta:
        flag = LOWERBOUND  # cut off on a beta break - the true score is at least this good
    store_tt(key, depth, best, flag, best_move)
    return best


def search_root(board: chess.Board, depth: int, moves: list[chess.Move]) -> chess.Move:
    """One complete root search at a fixed depth: score every legal move, return one of the
    best (ties broken randomly). `moves`'s MVV-LVA ordering is computed once by the caller and
    reused across every depth - that ordering doesn't depend on search depth, so there's no need
    to recompute it each pass. get_move does mutate `moves` between depths, though (milestone A8:
    moving the previous depth's winner to the front - see its own comment) - a genuinely
    different move can end up tried first at the next depth, which is the whole point of it.

    May raise TimeUp partway through; get_move handles that by simply not using this depth's
    result at all, not by salvaging whichever root moves it did finish - a plain, easy-to-verify
    rule, at the cost of a little wasted work right at the moment the clock runs out.
    """
    best_score = -math.inf
    best_moves: list[chess.Move] = []
    alpha, beta = -math.inf, math.inf
    for move in moves:
        board.push(move)
        score = -negamax(board, depth - 1, -beta, -alpha)
        board.pop()
        if score > best_score:
            best_score = score
            best_moves = [move]
            alpha = max(alpha, best_score)
        elif score == best_score:
            best_moves.append(move)
    return random.choice(best_moves)


def get_move(fen: str, time_left_ms: int) -> str:
    """Return a legal move in UCI notation.

    fen           the position to move in; your colour is the side to move
    time_left_ms  your clock before this move, in milliseconds
    returns       "e2e4", or "e7e8q" for a promotion

    The process stays alive between your moves, so state you keep on a module or in a
    closure survives to the next call. It does not survive to the next game.

    print() is safe. Your stdout is redirected away from the protocol stream, discarded
    during rated games and shown back to you in the validation log.
    """
    global DEADLINE, OWN_MOVES_PLAYED
    # Milestone A10: killer moves reset every real move, unlike TT (which deliberately persists
    # across the whole game - see its own comment). A killer only claims a quiet move was strong
    # *recently, near this depth* - a much weaker, more perishable signal than an actual
    # transposition, and standard practice resets it fresh per search rather than letting it
    # accumulate get_move calls that may have nothing to do with the position at hand now.
    for killers in KILLER_MOVES:
        killers.clear()
    # Note: HISTORY (milestone A11) is deliberately NOT reset/used here - it's currently unwired,
    # see the comment above its definition for why.
    board = chess.Board(fen)
    moves = order_moves(board, list(board.legal_moves))

    # Ready instantly, before any real searching happens: the answer if the clock is so tight
    # we can't even finish a depth-1 pass. docs/IDEAS.md is explicit that a flag - not a bad
    # move - is the most common self-inflicted loss, so there must always be *something* legal
    # to return, however little time is left.
    best_move = moves[0]

    OWN_MOVES_PLAYED += 1
    expected_moves_left = max(20, ASSUMED_GAME_LENGTH_PLIES - OWN_MOVES_PLAYED)
    budget_ms = time_left_ms / expected_moves_left
    DEADLINE = time.monotonic() + max(0.0, budget_ms - SAFETY_MARGIN_MS) / 1000

    depth = 1
    try:
        while depth <= MAX_DEPTH:
            best_move = search_root(board, depth, moves)
            # Iterative-deepening move ordering (milestone A8): the move that just won at this
            # depth is very likely still strong at the next one - trying it first there gives
            # alpha-beta the earliest, tightest bound it can get before searching every other
            # root move, so more of them cut off sooner. Cheap and safe: this only ever changes
            # which order root moves are tried in, never which one ultimately gets returned -
            # search_root still scores every move at the new depth regardless of where it sits
            # in `moves`. moves.remove() matches by value (chess.Move defines equality on
            # from/to/promotion), not object identity, and is O(legal move count) - a few dozen
            # at most, negligible next to an actual search node.
            moves.remove(best_move)
            moves.insert(0, best_move)
            depth += 1
    except TimeUp:
        pass  # keep whatever the last fully-completed depth found; see search_root's docstring

    return best_move.uci()
