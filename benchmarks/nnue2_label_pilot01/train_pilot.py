"""Train one NNUE2_LABEL_PILOT_01 arm with the frozen train_config.json.

Arm H uses v1's HCE 2000 ms teacher score; arm N uses an NNUE label file
written by label.py.  Everything else is shared.  The output model uses the
v1 float-model format so the v1 exporter's functions can quantize it.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy  # noqa: E402
import torch  # noqa: E402
from torch.nn import functional  # noqa: E402

from makhos.core import parse_position  # noqa: E402
from makhos.nnue_features import (  # noqa: E402
    feature_spec_payload,
    ordered_accumulator_features,
)

CONFIG_PATH = Path(__file__).with_name("train_config.json")
PAD = 137
WIDTH = 17
NETWORK = {
    "architecture_count": 1,
    "perspective_accumulators": 2,
    "feature_width": 128,
    "concatenated_width": 256,
    "hidden_width": 32,
    "output_width": 1,
    "output_perspective": "side_to_move",
    "policy_head": False,
}
OUTCOME = {"loss": -1.0, "draw": 0.0, "win": 1.0}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def teacher_value(cp: int) -> float:
    return math.tanh(max(-2000, min(2000, cp)) / 600)


def load_label_file(path: Path, key: str) -> tuple[dict, dict]:
    with path.open(encoding="utf-8") as stream:
        lines = [json.loads(line) for line in stream if line.strip()]
    return lines[0], {line["canonical_position_id"]: line[key]["score"] for line in lines[1:]}


def build_tensors(rows: list[dict], labels: dict | None) -> dict:
    count = len(rows)
    stm = numpy.full((count, WIDTH), PAD, dtype=numpy.int64)
    opp = numpy.full((count, WIDTH), PAD, dtype=numpy.int64)
    teacher = numpy.zeros(count, dtype=numpy.float32)
    outcome = numpy.zeros(count, dtype=numpy.float32)
    has_outcome = numpy.zeros(count, dtype=numpy.float32)
    wdl = numpy.zeros(count, dtype=numpy.float32)
    has_wdl = numpy.zeros(count, dtype=numpy.float32)
    games = {}
    game_index = numpy.zeros(count, dtype=numpy.int64)
    for index, row in enumerate(rows):
        state = parse_position(
            row["position"], reversible_plies=row["reversible_plies"], ply=row["ply"]
        )
        features = ordered_accumulator_features(state)
        stm[index, : len(features.side_to_move)] = features.side_to_move
        opp[index, : len(features.opponent)] = features.opponent
        cp = row["teacher_score"] if labels is None else labels[row["canonical_position_id"]]
        teacher[index] = teacher_value(cp)
        value = OUTCOME.get(row["game_outcome_from_side_to_move"])
        if value is not None and not row["game_truncated"]:
            outcome[index], has_outcome[index] = value, 1.0
        value = OUTCOME.get(row["exact_wdl"])
        if value is not None:
            wdl[index], has_wdl[index] = value, 1.0
        game_index[index] = games.setdefault(row["game_id"], len(games))
    per_game = numpy.bincount(game_index).astype(numpy.float32)
    weight = 1.0 / per_game[game_index]
    return {
        name: torch.from_numpy(value)
        for name, value in dict(
            stm=stm, opp=opp, teacher=teacher, outcome=outcome,
            has_outcome=has_outcome, wdl=wdl, has_wdl=has_wdl, weight=weight,
        ).items()
    }


class Model(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.feature_weights = torch.nn.Parameter(torch.empty(PAD + 1, 128))
        self.feature_bias = torch.nn.Parameter(torch.zeros(128))
        self.hidden = torch.nn.Linear(256, 32)
        self.output = torch.nn.Linear(32, 1)
        torch.nn.init.uniform_(self.feature_weights, -1 / math.sqrt(137), 1 / math.sqrt(137))
        with torch.no_grad():
            self.feature_weights[PAD].zero_()

    def accumulator(self, indices):
        summed = functional.embedding_bag(
            indices, self.feature_weights, mode="sum", padding_idx=PAD
        )
        return torch.clamp(summed + self.feature_bias, 0.0, 1.0)

    def forward(self, stm, opp):
        combined = torch.cat((self.accumulator(stm), self.accumulator(opp)), dim=1)
        return self.output(torch.clamp(self.hidden(combined), 0.0, 1.0)).squeeze(1)


def loss_terms(model, data, index, config):
    target = config["target"]
    mix = target["loss_mix"]
    prediction = model(data["stm"][index], data["opp"][index])
    numerator = mix["teacher_score"] * functional.huber_loss(
        prediction, data["teacher"][index], reduction="none", delta=target["huber_delta"]
    )
    active = torch.full_like(prediction, mix["teacher_score"])
    for value, available, key in (("outcome", "has_outcome", "game_outcome"), ("wdl", "has_wdl", "exact_wdl")):
        weight = mix[key] * data[available][index]
        numerator = numerator + weight * (prediction - data[value][index]).square()
        active = active + weight
    per_sample = numerator / active
    weights = data["weight"][index]
    return (per_sample * weights).sum() / weights.sum()


def metrics(prediction, data):
    error = (prediction - data["teacher"]).abs()
    return {"teacher_mae": float(error.mean())}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--arm", choices=("H", "N"), required=True)
    parser.add_argument("--labels", type=Path, help="label.py output for arm N")
    parser.add_argument("--label-key", default="d12")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if args.seed not in config["seeds"]:
        raise SystemExit("seed is not in the frozen configuration")
    labels = None
    label_header = None
    if args.arm == "N":
        label_header, labels = load_label_file(args.labels, args.label_key)
    with gzip.open(args.rows, "rt", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream]
    train_rows = [row for row in rows if row["split"] == "train"]
    validation_rows = [row for row in rows if row["split"] == "validation"]

    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(args.seed)
    started = time.perf_counter()
    train = build_tensors(train_rows, labels)
    validation = build_tensors(validation_rows, labels)
    prepared = time.perf_counter() - started

    optimizer_config = config["optimizer"]
    model = Model()
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=optimizer_config["learning_rate"],
        weight_decay=optimizer_config["weight_decay"],
    )
    epochs = optimizer_config["epochs"]
    warmup = 2
    batch = optimizer_config["batch_size"]
    history = []
    for epoch in range(1, epochs + 1):
        if epoch <= warmup:
            rate = optimizer_config["learning_rate"] * epoch / warmup
        else:
            progress = (epoch - warmup) / (epochs - warmup)
            rate = optimizer_config["learning_rate"] * 0.5 * (1 + math.cos(math.pi * progress))
        for group in optimizer.param_groups:
            group["lr"] = rate
        generator = torch.Generator().manual_seed(args.seed + epoch)
        order = torch.randperm(len(train_rows), generator=generator)
        model.train()
        total = 0.0
        steps = 0
        for start in range(0, len(order), batch):
            index = order[start : start + batch]
            optimizer.zero_grad(set_to_none=True)
            loss = loss_terms(model, train, index, config)
            loss.backward()
            optimizer.step()
            with torch.no_grad():
                model.feature_weights[PAD].zero_()
            total += float(loss.detach())
            steps += 1
        model.eval()
        with torch.no_grad():
            everything = torch.arange(len(validation_rows))
            validation_loss = float(loss_terms(model, validation, everything, config))
        history.append({"epoch": epoch, "learning_rate": rate, "train_loss": total / steps, "validation_loss": validation_loss})
        print(json.dumps(history[-1]), flush=True)

    model.eval()
    with torch.no_grad():
        validation_prediction = model(validation["stm"], validation["opp"])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"arm{args.arm}_seed{args.seed}"
    state = {
        "feature_weights": model.feature_weights[:PAD].detach(),
        "feature_bias": model.feature_bias.detach(),
        "hidden.weight": model.hidden.weight.detach(),
        "hidden.bias": model.hidden.bias.detach(),
        "output.weight": model.output.weight.detach(),
        "output.bias": model.output.bias.detach(),
    }
    model_payload = {
        "format": "thai-makhos-float-nnue-model-v1",
        "kind": "float-nnue-checkpoint",
        "contract_sha256": sha256(CONFIG_PATH).upper(),
        "feature_spec": feature_spec_payload(),
        "network": NETWORK,
        "size": "all",
        "seed": args.seed,
        "best_epoch": epochs,
        "best_validation_loss": history[-1]["validation_loss"],
        "state": {
            name: {"shape": list(value.shape), "values": value.reshape(-1).tolist()}
            for name, value in sorted(state.items())
        },
    }
    model_path = args.output_dir / f"{stem}.model.json"
    model_path.write_text(json.dumps(model_payload, sort_keys=True) + "\n", encoding="utf-8")
    numpy.save(args.output_dir / f"{stem}.validation_prediction.npy", validation_prediction.numpy())
    run = {
        "format": "thai-makhos-nnue2-pilot-run-v1",
        "arm": args.arm,
        "seed": args.seed,
        "config_sha256": sha256(CONFIG_PATH),
        "rows_sha256": sha256(args.rows),
        "labels": None if labels is None else {
            "path": str(args.labels), "sha256": sha256(args.labels),
            "key": args.label_key, "header": label_header,
        },
        "train_rows": len(train_rows),
        "validation_rows": len(validation_rows),
        "python": platform.python_version(),
        "torch": torch.__version__,
        "numpy": numpy.__version__,
        "prepare_seconds": round(prepared, 1),
        "seconds": round(time.perf_counter() - started, 1),
        "history": history,
        "validation_teacher_mae_own_label": metrics(validation_prediction, validation)["teacher_mae"],
        "model_file": model_path.name,
        "model_sha256": sha256(model_path),
    }
    (args.output_dir / f"{stem}.run.json").write_text(json.dumps(run, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"model": str(model_path), "sha256": run["model_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
