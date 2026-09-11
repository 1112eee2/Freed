"""Tablebase and proof verification CLI command handlers."""

from __future__ import annotations

import argparse

from ..audit_rules import IndependentRulesAuditor
from ..core import DEFAULT_RULES, Rules, parse_position
from ..proof import (
    NonLossProver,
    ProofBudgetExceeded,
    load_proof_strategy,
    proof_no_progress_plies,
    write_certificate,
)
from ..ranked_tablebase import RankedTablebase
from ..tb4_verify import verify_ranked_tablebase
from ..verify import verify_one_vs_one
from .common import _open_proof_oracle


def command_verify_endgames(args: argparse.Namespace) -> int:
    result = verify_one_vs_one(
        no_progress_plies=args.no_progress,
        max_states=args.max_states,
    )
    print("verified material: one piece vs one piece")
    print(f"root positions: {result.positions}")
    print(f"side-to-move W/D/L: {result.wins}/{result.draws}/{result.losses}")
    print(f"unique solved states: {result.solved_states}")
    print(f"time: {result.elapsed_ms} ms")
    return 0


def command_verify_tablebase(args: argparse.Namespace) -> int:
    result = verify_ranked_tablebase(
        args.tablebase,
        no_progress_plies=args.no_progress,
        samples=args.samples,
        seed=args.seed,
        max_states=args.max_states,
        tactical=args.tactical,
        captures_only=args.captures_only,
        min_captures=args.min_captures,
    )
    print(f"{result.piece_count}-piece positions compared: {result.samples}")
    print(f"sample W/D/L: {result.wins}/{result.draws}/{result.losses}")
    print(f"unique Python oracle states: {result.oracle_states}")
    print("ranked tablebase differential verification: PASS")
    return 0


def command_verify_tablebase_provenance(args: argparse.Namespace) -> int:
    for path in args.tablebase:
        with RankedTablebase(path) as tablebase:
            binding = tablebase.verify_provenance(args.manifest)
            print(
                f"{binding.piece_count}-piece tablebase provenance: PASS "
                f"({binding.sha256})"
            )
    print("ruleset, generator source, and tablebase SHA-256 bindings: PASS")
    return 0


def command_prove_nonloss(args: argparse.Namespace) -> int:
    state = parse_position(args.position, reversible_plies=args.clock)
    rules = Rules(
        name="thai-makhos-proof",
        starting_player=DEFAULT_RULES.starting_player,
        repetition_limit=None,
        no_progress_plies=args.no_progress,
    )
    oracle, native, ranked = _open_proof_oracle(args, args.no_progress)
    try:
        prover = NonLossProver(
            rules,
            oracle,
            node_budget=args.node_budget,
            collect_all_choices=args.all_safe_choices,
        )
        try:
            certificate, stats = prover.prove(state, args.root_player)
        except (ProofBudgetExceeded, RecursionError) as error:
            print("result: UNKNOWN")
            print(str(error))
            return 2
        if certificate is None:
            print("result: FORCED LOSS")
            print(f"expanded nodes: {stats.expanded}")
            return 1
        print("result: PROVEN NON-LOSS")
        print(f"expanded nodes: {stats.expanded}")
        print(f"certificate nodes: {stats.certificate_nodes}")
        if args.certificate:
            write_certificate(certificate, args.certificate)
            print(f"certificate: {args.certificate}")
        return 0
    finally:
        for tablebase in ranked:
            tablebase.close()
        if native is not None:
            native.close()


def command_check_proof(args: argparse.Namespace) -> int:
    no_progress = proof_no_progress_plies(args.certificate)
    oracle, native, ranked = _open_proof_oracle(args, no_progress)
    try:
        rules_auditor = (
            IndependentRulesAuditor() if args.independent_rules_audit else None
        )
        strategy = load_proof_strategy(
            args.certificate,
            oracle,
            rules_auditor=rules_auditor,
        )
        checked = strategy.checked_nodes
        print(f"certificate nodes checked: {checked}")
        if rules_auditor is not None:
            print("independent rules audit: PASS")
        print("non-loss proof certificate: PASS")
        close = getattr(strategy, "close", None)
        if close is not None:
            close()
        return 0
    finally:
        for tablebase in ranked:
            tablebase.close()
        if native is not None:
            native.close()
