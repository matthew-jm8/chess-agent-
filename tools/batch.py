"""Run a batch of games, saving one PGN plus metadata per game for visual review.

Our own tooling, not part of the platform's harness (harness/ is left untouched, per
docs/IDEAS.md - "changing it makes local results meaningless"). Reuses harness.referee's
play_match and harness.sandbox's local() exactly the way harness/arena.py does; arena.py only
prints a running score, this also keeps each game's PGN.

Output goes under game-logs/<label>/: game-NN.pgn per game plus a summary.json. Never read by
harness/package.py, so none of it reaches submission.zip - only agent.py (+ declared weights)
does. Committed to git (see the .gitignore exception for game-logs/) purely for our own
before/after review, e.g. via the Scoresheet game-viewer artifact.
"""

import argparse
import io
import json
from pathlib import Path

import chess.pgn

from harness.referee import FAILED_TERMINATIONS, play_match
from harness.rules import PLY_CAP
from harness.sandbox import local

FAST_BASE_MS = 10_000
FAST_INCREMENT_MS = 100


def count_plies(pgn_text: str) -> int:
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    return 0 if game is None else sum(1 for _ in game.mainline_moves())


def clock_label(base_ms: int, increment_ms: int) -> str:
    """Human-readable, unambiguous label for which clock a batch used."""
    if base_ms == 120_000 and increment_ms == 500:
        return "competition clock (120s+0.5s)"
    if base_ms == FAST_BASE_MS and increment_ms == FAST_INCREMENT_MS:
        return "fast test clock (10s+0.1s)"
    return f"custom clock ({base_ms / 1000:g}s+{increment_ms / 1000:g}s)"


def main() -> None:
    parser = argparse.ArgumentParser(description="Play a batch of games, saving PGN + metadata.")
    parser.add_argument("--agent", type=Path, default=Path("."))
    parser.add_argument("--opponent", type=Path, default=Path("baselines/greedy"))
    parser.add_argument("--games", type=int, default=10)
    parser.add_argument("--base-ms", type=int, default=FAST_BASE_MS)
    parser.add_argument("--increment-ms", type=int, default=FAST_INCREMENT_MS)
    parser.add_argument("--ply-cap", type=int, default=PLY_CAP)
    parser.add_argument("--label", required=True, help="Name for this batch, e.g. v1-vs-greedy")
    arguments = parser.parse_args()

    agent = arguments.agent.resolve()
    opponent = arguments.opponent.resolve()
    out_dir = Path("game-logs") / arguments.label
    out_dir.mkdir(parents=True, exist_ok=True)

    wins = draws = losses = 0
    terminations: dict[str, int] = {}
    games: list[dict[str, object]] = []

    for game in range(arguments.games):
        plays_white = game % 2 == 0
        white, black = (agent, opponent) if plays_white else (opponent, agent)
        outcome = play_match(
            local(white),
            local(black),
            arguments.base_ms,
            arguments.increment_ms,
            ply_cap=arguments.ply_cap,
        )
        terminations[outcome.termination] = terminations.get(outcome.termination, 0) + 1
        if outcome.result in ("draw", "void"):
            draws += 1
            score_for_agent = "draw"
        elif (outcome.result == "white") == plays_white:
            wins += 1
            score_for_agent = "win"
        else:
            losses += 1
            score_for_agent = "loss"

        pgn_name = f"game-{game + 1:02d}.pgn"
        (out_dir / pgn_name).write_text(outcome.pgn + "\n")
        games.append(
            {
                "index": game + 1,
                "pgn_file": pgn_name,
                "agent_color": "white" if plays_white else "black",
                "result": outcome.result,
                "termination": outcome.termination,
                "score_for_agent": score_for_agent,
                "plies": count_plies(outcome.pgn),
            }
        )
        print(f"game {game + 1}/{arguments.games}: {outcome.result} by {outcome.termination}")

    score = (wins + draws / 2) / arguments.games
    summary = {
        "label": arguments.label,
        "agent": str(arguments.agent),
        "opponent": str(arguments.opponent),
        "clock": clock_label(arguments.base_ms, arguments.increment_ms),
        "base_ms": arguments.base_ms,
        "increment_ms": arguments.increment_ms,
        "games": arguments.games,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "score": score,
        "terminations": terminations,
        "results": games,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    print(f"\n{arguments.agent} vs {arguments.opponent} over {arguments.games} games "
          f"[{clock_label(arguments.base_ms, arguments.increment_ms)}]")
    print(f"+{wins} ={draws} -{losses}, score {score:.1%}")
    print("terminations: " + ", ".join(f"{name} {count}" for name, count in terminations.items()))
    print(f"saved to {out_dir}/")

    # A termination in FAILED_TERMINATIONS (crash/illegal/flag/init) always names the side that
    # erred as the *loser* (harness/referee.py's _opponent_wins) - so it's only actually our
    # agent's problem when score_for_agent is a loss, not whenever the label shows up at all.
    # Otherwise a batch where the *opponent* flagged (a real, good result for our agent) reports
    # a false "your agent failed" and exits non-zero over nothing. both_failed is the one
    # ambiguous case - both sides errored at once - so it's still treated as a real failure.
    broken = [
        game
        for game in games
        if game["termination"] in FAILED_TERMINATIONS
        and (game["score_for_agent"] == "loss" or game["termination"] == "both_failed")
    ]
    if broken:
        raise SystemExit(
            "your agent failed to finish a game: "
            + ", ".join(f"game {g['index']} ({g['termination']})" for g in broken)
        )


if __name__ == "__main__":
    main()
