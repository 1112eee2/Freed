"""Unit tests for makhos.cli modularization and handler routing."""

import unittest

import makhos.cli as cli
import makhos.cli_handlers.analysis_handler as analysis_h
import makhos.cli_handlers.common as common_h
import makhos.cli_handlers.play_handler as play_h
import makhos.cli_handlers.proof_handler as proof_h
import makhos.cli_handlers.sprt_handler as sprt_h


class CLIModularizationTests(unittest.TestCase):

    def test_cli_exports_all_handlers_and_helpers(self) -> None:
        self.assertIs(cli.command_sprt, sprt_h.command_sprt)
        self.assertIs(cli._set_batch_process_priority, sprt_h._set_batch_process_priority)
        self.assertIs(cli._set_windows_process_priority, sprt_h._set_windows_process_priority)
        self.assertIs(cli._write_sprt_checkpoint, sprt_h._write_sprt_checkpoint)
        self.assertIs(cli._load_sprt_checkpoint, sprt_h._load_sprt_checkpoint)

        self.assertIs(cli.command_bestmove, play_h.command_bestmove)
        self.assertIs(cli.command_play, play_h.command_play)
        self.assertIs(cli.command_solve, play_h.command_solve)
        self.assertIs(cli.command_arena, play_h.command_arena)
        self.assertIs(cli.command_train_selfplay, play_h.command_train_selfplay)
        self.assertIs(cli.command_gauntlet, play_h.command_gauntlet)
        self.assertIs(cli.command_gui, play_h.command_gui)
        self.assertIs(cli.command_uci, play_h.command_uci)

        self.assertIs(cli.command_verify_endgames, proof_h.command_verify_endgames)
        self.assertIs(cli.command_verify_tablebase, proof_h.command_verify_tablebase)
        self.assertIs(cli.command_verify_tablebase_provenance, proof_h.command_verify_tablebase_provenance)
        self.assertIs(cli.command_prove_nonloss, proof_h.command_prove_nonloss)
        self.assertIs(cli.command_check_proof, proof_h.command_check_proof)

        self.assertIs(cli.command_perft, analysis_h.command_perft)
        self.assertIs(cli.command_verify_native, analysis_h.command_verify_native)
        self.assertIs(cli.command_bench_native, analysis_h.command_bench_native)
        self.assertIs(cli.command_profile_native, analysis_h.command_profile_native)
        self.assertIs(cli.command_analyze_game, analysis_h.command_analyze_game)
        self.assertIs(cli.command_build_middlegame_corpus, analysis_h.command_build_middlegame_corpus)
        self.assertIs(cli.command_build_eval_corpus, analysis_h.command_build_eval_corpus)
        self.assertIs(cli.command_fit_eval, analysis_h.command_fit_eval)

        self.assertIs(cli._get_engine, common_h._get_engine)
        self.assertIs(cli._get_state, common_h._get_state)
        self.assertIs(cli._open_proof_oracle, common_h._open_proof_oracle)
        self.assertIs(cli._verify_requested_provenance, common_h._verify_requested_provenance)

    def test_parser_subcommands_dispatch_to_respective_handlers(self) -> None:
        parser = cli.build_parser()

        commands_to_test = [
            (["perft", "--depth", "1"], cli.command_perft),
            (["bestmove", "--depth", "1"], cli.command_bestmove),
            (["solve", "--position", "B:BM25:RM1"], cli.command_solve),
            (["arena", "--pairs", "1"], cli.command_arena),
            (["verify-endgames"], cli.command_verify_endgames),
            (["gauntlet", "--pairs", "1"], cli.command_gauntlet),
            (["verify-native"], cli.command_verify_native),
            (["bench-native", "--cases", "1"], cli.command_bench_native),
            (["fit-eval"], cli.command_fit_eval),
            (["gui", "--no-browser"], cli.command_gui),
            (["uci"], cli.command_uci),
            (["check-proof", "--certificate", "cert.json"], cli.command_check_proof),
        ]

        for argv, expected_func in commands_to_test:
            with self.subTest(command=argv[0]):
                args = parser.parse_args(argv)
                self.assertIs(args.func, expected_func)


if __name__ == "__main__":
    unittest.main()
