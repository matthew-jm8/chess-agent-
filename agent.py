"""The submission entrypoint. The platform imports this file and calls get_move."""

import math
import random
import time
from collections.abc import Hashable
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


TT: dict[Hashable, TTEntry] = {}
# Rough safety cap, not a precise benchmark: bounds memory over a long game (the platform caps
# the process at 2 GB and games at 300 plies) by clearing the table outright if it grows huge,
# rather than tracking per-entry age/eviction, which this milestone deliberately keeps simple.
TT_MAX_ENTRIES = 2_000_000

# Known simplification: MATE below is a flat constant, not adjusted for how many moves deep it
# was found. A mate score that bubbles up into a TT entry doesn't distinguish "mate in 2" from
# "mate in 5" the way a fully correct engine's TT does. MATE dwarfs every positional score, so
# this shouldn't change which move gets picked - it's a real, accepted trade-off, not a bug.


def store_tt(key: Hashable, depth: int, score: float, flag: int) -> None:
    if len(TT) >= TT_MAX_ENTRIES:
        TT.clear()
    TT[key] = TTEntry(depth, score, flag)


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


def evaluate(board: chess.Board, mobility: int) -> float:
    """Score a position from the side-to-move's perspective: positive is good for them."""
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
evaluate(chess.Board(), 20)


def order_moves(board: chess.Board, moves: list[chess.Move]) -> list[chess.Move]:
    """Captures first, best captures first (MVV-LVA); quiet moves keep their given order.

    Alpha-beta only prunes once it has already found a move good enough to trigger a cutoff -
    so the earlier a strong move is tried, the more of the tree gets skipped. Captures are the
    moves most likely to be strong, and MVV-LVA (most-valuable-victim, least-valuable-attacker)
    orders them the way a human would scan a position first: capturing a queen with a pawn
    before capturing a pawn with a queen. See docs/IDEAS.md: "the gap between the minimax
    baseline and something respectable is mostly move ordering."
    """

    def score(move: chess.Move) -> float:
        if not board.is_capture(move):
            return -1.0  # quiet moves sort after every capture
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
    if cached is not None and cached.depth >= depth:
        if cached.flag == EXACT:
            return cached.score
        if cached.flag == LOWERBOUND:
            alpha = max(alpha, cached.score)
        elif cached.flag == UPPERBOUND:
            beta = min(beta, cached.score)
        if alpha >= beta:
            return cached.score

    if depth == 0:
        # quiescence does its own windowed sub-search (milestone A5), so its result carries the
        # same fail-high/fail-low ambiguity as a regular node's - it's classified by the same
        # flag logic below, not treated as unconditionally exact the way a bare static eval was.
        best = quiescence(board, alpha, beta)
    else:
        best = -math.inf
        for move in order_moves(board, moves):
            board.push(move)
            score = -negamax(board, depth - 1, -beta, -alpha)
            board.pop()
            if score > best:
                best = score
            if best > alpha:
                alpha = best
            if alpha >= beta:
                break  # beta cutoff: the opponent already has a better option upstream

    flag = EXACT
    if best <= original_alpha:
        flag = UPPERBOUND  # never beat the window we came in with - a "failed low" bound
    elif best >= beta:
        flag = LOWERBOUND  # cut off on a beta break - the true score is at least this good
    store_tt(key, depth, best, flag)
    return best


def search_root(board: chess.Board, depth: int, moves: list[chess.Move]) -> chess.Move:
    """One complete root search at a fixed depth: score every legal move, return one of the
    best (ties broken randomly). `moves` is precomputed once by the caller and reused across
    every depth - MVV-LVA ordering doesn't depend on search depth, so there's no need to
    recompute it each pass. May raise TimeUp partway through; get_move handles that by simply
    not using this depth's result at all, not by salvaging whichever root moves it did finish -
    a plain, easy-to-verify rule, at the cost of a little wasted work right at the moment the
    clock runs out.
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
            depth += 1
    except TimeUp:
        pass  # keep whatever the last fully-completed depth found; see search_root's docstring

    return best_move.uci()
