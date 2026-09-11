"""Shared helpers for CLI commands in Thai Makhos Engine."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..core import DEFAULT_RULES, Rules, initial_state, parse_position
from ..exact import ExactSolver
from ..native import NativeSearch
from ..native_tablebase import NativeTablebase
from ..policy_value import EmpiricalPolicyValueModel
from ..proof import EndgameOracle, load_proof_strategy
from ..ranked_tablebase import RankedTablebase
from ..search import Engine


def _verify_requested_provenance(
    tablebase: RankedTablebase,
    args: argparse.Namespace,
) -> None:
    if getattr(args, "verify_tablebase_provenance", False):
        tablebase.verify_provenance(
            getattr(args, "tablebase_provenance_manifest", None)
        )


def _open_proof_oracle(
    args: argparse.Namespace,
    no_progress_plies: int,
) -> tuple[EndgameOracle, NativeTablebase | None, list[RankedTablebase]]:
    ranked_paths = args.ranked_tablebase or []
    if isinstance(ranked_paths, str):
        ranked_paths = [ranked_paths]
    ranked: list[RankedTablebase] = []
    try:
        for path in ranked_paths:
            tablebase = RankedTablebase(path)
            try:
                _verify_requested_provenance(tablebase, args)
                if tablebase.no_progress_plies != no_progress_plies:
                    raise ValueError(
                        "ranked tablebase no-progress rule mismatch"
                    )
            except Exception:
                tablebase.close()
                raise
            ranked.append(tablebase)
    except Exception:
        for tablebase in ranked:
            tablebase.close()
        raise
    native = None
    if args.native_tablebase or ranked:
        native = NativeTablebase(
            args.native_library,
            no_progress_plies=no_progress_plies,
            hash_power=args.native_hash_power,
        )
    return (
        EndgameOracle(native=native, ranked_tablebases=ranked),
        native,
        ranked,
    )


def _get_state(args: argparse.Namespace):
    if getattr(args, "position", None):
        return parse_position(args.position, reversible_plies=getattr(args, "clock", 0))
    return initial_state(args.first)


def _get_engine(args: argparse.Namespace) -> Engine:
    rules = Rules(
        name=DEFAULT_RULES.name,
        starting_player=DEFAULT_RULES.starting_player,
        repetition_limit=DEFAULT_RULES.repetition_limit,
        no_progress_plies=getattr(
            args, "no_progress", DEFAULT_RULES.no_progress_plies
        ),
    )
    native = None
    native_search = None
    ranked: list[RankedTablebase] = []
    ranked_paths = getattr(args, "ranked_tablebase", None) or []
    if isinstance(ranked_paths, str):
        ranked_paths = [ranked_paths]
    try:
        for ranked_path in ranked_paths:
            tablebase = RankedTablebase(
                ranked_path,
                verify_checksum=getattr(
                    args, "verify_tablebase_checksum", False
                ),
            )
            try:
                _verify_requested_provenance(tablebase, args)
            except Exception:
                tablebase.close()
                raise
            ranked.append(tablebase)
            print(
                f"ranked {tablebase.piece_count}-piece tablebase ready: "
                f"{tablebase.total_states:,} states"
            )
    except Exception:
        for tablebase in ranked:
            tablebase.close()
        raise
    if (
        getattr(args, "native_tablebase", False) or
        ranked or
        getattr(args, "proof_strategy", None)
    ):
        native = NativeTablebase(
            args.native_library,
            no_progress_plies=rules.no_progress_plies,
            hash_power=args.native_hash_power,
        )
        print(
            f"native 3-piece tablebase ready: {native.state_count:,} states, "
            f"{native.root_count:,} roots"
        )
    if not getattr(args, "python_search", False):
        native_library = Path(args.native_library)
        if native_library.is_file():
            native_search = NativeSearch(
                native_library,
                hash_power=getattr(args, "search_hash_power", 20),
            )
    model_path = getattr(args, "policy_model", None)
    if model_path:
        model = EmpiricalPolicyValueModel.load(model_path)
        print(
            f"policy-value model ready: {model.games} games, "
            f"{model.samples} samples"
        )
    else:
        model = EmpiricalPolicyValueModel()
    proof_strategy = None
    proof_path = getattr(args, "proof_strategy", None)
    if proof_path:
        proof_strategy = load_proof_strategy(
            proof_path,
            EndgameOracle(native=native, ranked_tablebases=ranked),
        )
        print(
            f"proof strategy ready: {proof_strategy.checked_nodes:,} "
            "verified nodes"
        )
    return Engine(
        rules=rules,
        exact_piece_limit=args.exact_pieces,
        exact_max_states=args.max_states,
        native_tablebase=native,
        ranked_tablebases=ranked,
        policy_value_model=model,
        distance_max_nodes=getattr(args, "distance_nodes", 0),
        proof_strategy=proof_strategy,
        native_search=native_search,
    )
