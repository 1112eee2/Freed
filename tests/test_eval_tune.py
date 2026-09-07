import unittest

import numpy as np

from makhos.eval_tune import _metrics, fit_logistic_weights


class EvaluationTuneTests(unittest.TestCase):
    def test_logistic_fit_improves_synthetic_soft_label_loss(self) -> None:
        features = np.asarray([
            [-2.0, 0.0],
            [-1.0, 1.0],
            [0.0, -1.0],
            [0.0, 1.0],
            [1.0, -1.0],
            [2.0, 0.0],
        ])
        targets = np.asarray([0.0, 0.0, 0.5, 0.5, 1.0, 1.0])
        initial = np.asarray([0.05, 0.0])
        fitted, iterations = fit_logistic_weights(
            features, targets, initial, ridge=0.01
        )
        self.assertLess(
            _metrics(features, targets, fitted)["cross_entropy"],
            _metrics(features, targets, initial)["cross_entropy"],
        )
        self.assertLess(iterations, 100)


if __name__ == "__main__":
    unittest.main()
