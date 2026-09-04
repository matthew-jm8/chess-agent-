"""The submission entrypoint. The platform imports this file and calls get_move."""

import math
import random
from collections.abc import Hashable
from typing import NamedTuple

import chess

# Import time runs once per game, inside a 60 second budget, before your clock starts.
# Load weights and build tables out here, not inside get_move.

# Same evaluation as baselines/minimax, unchanged on purpose: this milestone is about the
# search algorithm (alpha-beta pruning, extra depth), not the evaluation. Comparing this
# agent to baselines/minimax in an arena isolates exactly what alpha-beta buys us.
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

# Total plies searched from the root. baselines/minimax searches 2 (fixed, no pruning).
#
# History: depth 4 with no move ordering took ~2.2s on an ordinary middlegame move and lost
# 20/20 fast-control games by flagging (milestone A1). Adding MVV-LVA move ordering (A2) cut
# that to ~1.4s but still flagged 7/10 at fast control. Adding a transposition table on top
# (this milestone, A3) cut it further to ~1.0s (cold cache) - still not enough: a depth-4 batch
# with both ordering and TT still flagged 6/10 games at fast control. Depth 3 stays for now.
# This is still a stopgap, not a fix - there is still no time management (milestone A4), so
# this number goes back up once that lands and the clock itself decides how deep to search
# instead of a fixed constant guessing at it.
DEPTH = 3

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


def evaluate(board: chess.Board, mobility: int) -> float:
    """Score a position from the side-to-move's perspective: positive is good for them."""
    mover = board.turn
    material = sum(
        value * (len(board.pieces(piece, mover)) - len(board.pieces(piece, not mover)))
        for piece, value in PIECE_VALUE.items()
    )
    return material + MOBILITY_WEIGHT * mobility


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
        score = evaluate(board, len(moves))
        store_tt(key, depth, score, EXACT)  # a static eval is exactly correct for its depth
        return score

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
    board = chess.Board(fen)

    # Root loop: try every legal move, score the resulting position with negamax, and keep
    # whichever move(s) score best. This has no time management yet (fixed DEPTH) - that
    # comes in a later milestone once iterative deepening is in place.
    best_score = -math.inf
    best_moves: list[chess.Move] = []
    alpha, beta = -math.inf, math.inf
    for move in order_moves(board, list(board.legal_moves)):
        board.push(move)
        score = -negamax(board, DEPTH - 1, -beta, -alpha)
        board.pop()
        if score > best_score:
            best_score = score
            best_moves = [move]
            alpha = max(alpha, best_score)
        elif score == best_score:
            best_moves.append(move)
    return random.choice(best_moves).uci()
