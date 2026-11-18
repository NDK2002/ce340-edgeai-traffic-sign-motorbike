"""Evaluate one or more Ultralytics detection checkpoints and save comparable metrics.

Example:
    python 03_models_benchmark/evaluate_benchmark.py \
        --weights 03_models_benchmark/runs/week4-yolov8n-160/weights/best.pt \
        --data 01_dataset/mock_assets/data_mock.yaml --imgsz 160
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark detection models trên split validation.")
    parser.add_argument("--weights", nargs="+", required=True, help="Một hay nhiều file model .pt/.onnx.")
    parser.add_argument("--data", type=Path, required=True, help="YOLO data.yaml.")
    parser.add_argument("--split", choices=("val", "test"), default="val")
    parser.add_argument(
        "--conf",
        type=float,
        default=None,
        help="Operating threshold. Mặc định chọn ngưỡng tối đa macro-F1 trên validation.",
    )
    parser.add_argument("--imgsz", type=int, choices=(160, 192, 320), default=320)
    parser.add_argument("--device", default=None, help="Ví dụ: 0 hoặc cpu; mặc định để Ultralytics tự chọn.")
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--output", type=Path, default=SCRIPT_DIR / "runs" / "benchmark")
    return parser.parse_args()


def scalar(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def artifact_name(weights: str) -> str:
    path = Path(weights).expanduser()
    if path.parent.name.lower() == "weights":
        return path.parent.parent.name
    if path.suffix.lower() == ".keras" and path.parent.name:
        return path.parent.name
    return path.stem


def main() -> None:
    args = parse_args()
    data_path = args.data.expanduser().resolve()
    if not data_path.is_file():
        raise SystemExit(f"Không tìm thấy data.yaml: {data_path}")
    if args.split == "test" and args.conf is None:
        raise SystemExit("Khi dùng --split test, truyền --conf đã chọn trên validation để tránh tune trên test.")
    if args.conf is not None and not 0.0 <= args.conf <= 1.0:
        raise SystemExit("--conf phải nằm trong khoảng [0, 1].")
    missing_weights = [weight for weight in args.weights if not Path(weight).expanduser().is_file()]
    if missing_weights:
        raise SystemExit("Không tìm thấy checkpoint: " + ", ".join(missing_weights))

    output_dir = args.output.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []

    for weights in args.weights:
        checkpoint = str(Path(weights).expanduser().resolve())
        run_name = artifact_name(weights)
        if Path(weights).suffix.lower() == ".keras":
            try:
                from mobilenetv2_ssd import evaluate_model
            except ImportError as exc:
                raise SystemExit("Thiếu TensorFlow/Pillow/PyYAML/Matplotlib để đánh giá model Keras.") from exc
            row = evaluate_model(
                model_path=Path(checkpoint),
                data_yaml=data_path,
                output_dir=output_dir / run_name,
                imgsz=args.imgsz,
                split=args.split,
                confidence=args.conf,
            )
            rows.append(row)
            print(
                f"{row['model']} @conf={row['confidence']:.3f}: P={row['precision']}, "
                f"R={row['recall']}, F1={row['f1']}, "
                f"mAP@0.5={row['map50']}"
            )
            continue

        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise SystemExit(
                "Thiếu Ultralytics. Cài dependencies bằng: pip install -r requirements.txt"
            ) from exc
        model = YOLO(checkpoint)
        val_options: dict[str, Any] = {
            "data": str(data_path),
            "imgsz": args.imgsz,
            "batch": args.batch,
            "split": args.split,
            "project": str(output_dir),
            "name": run_name,
            "exist_ok": True,
            "plots": False,
        }
        if args.device is not None:
            val_options["device"] = args.device

        metrics = model.val(**val_options)
        box_metrics = metrics.box
        confidence_grid = np.asarray(box_metrics.px)
        if args.conf is None:
            confidence_index = int(np.argmax(np.mean(box_metrics.f1_curve, axis=0)))
        else:
            confidence_index = int(np.argmin(np.abs(confidence_grid - args.conf)))
        confidence = float(confidence_grid[confidence_index])
        precision = scalar(np.mean(box_metrics.p_curve[:, confidence_index]))
        recall = scalar(np.mean(box_metrics.r_curve[:, confidence_index]))
        f1 = scalar(np.mean(box_metrics.f1_curve[:, confidence_index]))
        confusion_options = {
            **val_options,
            "conf": confidence,
            "name": f"{run_name}-conf-{confidence:.3f}",
            "plots": True,
        }
        confusion_metrics = model.val(**confusion_options)
        save_dir = Path(confusion_metrics.save_dir).resolve()
        row = {
            "model": run_name,
            "weights": checkpoint,
            "data_yaml": str(data_path),
            "split": args.split,
            "imgsz": args.imgsz,
            "confidence": confidence,
            "metric_averaging": "macro over classes present in split",
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "map50": scalar(getattr(box_metrics, "map50", None)),
            "map50_95": scalar(getattr(box_metrics, "map", None)),
            "confusion_matrix": str(save_dir / "confusion_matrix.png"),
            "results_dir": str(save_dir),
        }
        (save_dir / "benchmark_metrics.json").write_text(
            json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        rows.append(row)
        print(
            f"{row['model']} @conf={confidence:.3f}: P={precision}, R={recall}, F1={f1}, "
            f"mAP@0.5={row['map50']}, mAP@0.5:0.95={row['map50_95']}"
        )

    summary_json = output_dir / "benchmark_summary.json"
    summary_csv = output_dir / "benchmark_summary.csv"
    summary_json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with summary_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Đã lưu bảng benchmark: {summary_csv}")


if __name__ == "__main__":
    main()
