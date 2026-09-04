"""The submission entrypoint. The platform imports this file and calls get_move."""

import math
import random

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

# Total plies searched from the root. baselines/minimax searches 2 (fixed, no pruning).
#
# Measured on this machine: depth 4 took ~2.2s on a fairly ordinary middlegame position
# (no move ordering yet, so alpha-beta prunes far less than it eventually will - see
# docs/IDEAS.md: "alpha-beta only pays off when good moves come first"). A handful of moves
# like that blows a 10s fast-control clock entirely, which is exactly what happened: an
# arena run at depth 4 lost all 20 games by flagging. Depth 3 measured ~4x faster and
# survives fast-control testing. This is a stopgap, not a fix - there is still no time
# management (milestone A4) or move ordering (milestone A2) to make depth 4+ safe, so this
# number goes back up once those land.
DEPTH = 3


def evaluate(board: chess.Board, mobility: int) -> float:
    """Score a position from the side-to-move's perspective: positive is good for them."""
    mover = board.turn
    material = sum(
        value * (len(board.pieces(piece, mover)) - len(board.pieces(piece, not mover)))
        for piece, value in PIECE_VALUE.items()
    )
    return material + MOBILITY_WEIGHT * mobility


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
        # No legal moves: checkmate (bad for the side to move) or stalemate (a draw).
        return -MATE if board.is_check() else 0.0
    if depth == 0:
        return evaluate(board, len(moves))

    best = -math.inf
    for move in moves:
        board.push(move)
        score = -negamax(board, depth - 1, -beta, -alpha)
        board.pop()
        if score > best:
            best = score
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break  # beta cutoff: the opponent already has a better option upstream
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
    for move in board.legal_moves:
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
