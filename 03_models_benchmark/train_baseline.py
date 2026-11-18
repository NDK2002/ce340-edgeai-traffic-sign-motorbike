"""Train a CE340 traffic-sign detection baseline with Ultralytics YOLO.

Run from the repository root, for example:
    python 03_models_benchmark/train_baseline.py --data 01_dataset/mock_assets/data_mock.yaml \
        --model yolov8n --imgsz 160 --epochs 3 --batch 4 --device cpu --export onnx
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


SCRIPT_DIR = Path(__file__).resolve().parent
MODEL_WEIGHTS = {
    "yolov8n": "yolov8n.pt",
    # Ultralytics' maintained YOLOv5 implementation is the anchor-free YOLOv5u
    # nano checkpoint. Supply --weights to use another compatible checkpoint.
    "yolov5-tiny": "yolov5nu.pt",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Huấn luyện baseline nhận diện biển báo cho đồ án CE340."
    )
    parser.add_argument(
        "--model",
        choices=("yolov8n", "yolov5-tiny", "mobilenetv2-ssd"),
        default="yolov8n",
        help="Kiến trúc cần chạy.",
    )
    parser.add_argument(
        "--weights",
        help="YOLO checkpoint/YAML hoặc file weights MobileNetV2 Keras; mặc định là checkpoint pretrained.",
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=Path("01_dataset/mock_assets/data_mock.yaml"),
        help="YOLO data.yaml; mặc định là bộ mock 5 ảnh trong repo.",
    )
    parser.add_argument("--imgsz", type=int, choices=(160, 192, 320), default=320)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--seed", type=int, default=42, help="Seed để tái lập lần chạy.")
    parser.add_argument("--freeze-backbone", action="store_true", help="Đóng băng backbone MobileNetV2.")
    parser.add_argument("--device", default=None, help="YOLO: ví dụ 0 hoặc cpu; TensorFlow tự chọn thiết bị khả dụng.")
    parser.add_argument("--workers", type=int, default=0, help="Mặc định 0 để chạy ổn định trên Windows.")
    parser.add_argument("--project", type=Path, default=SCRIPT_DIR / "runs")
    parser.add_argument("--name", help="Tên thư mục kết quả; mặc định tự tạo theo model và kích thước ảnh.")
    parser.add_argument("--export", choices=("none", "onnx", "saved_model", "both"), default="none")
    parser.add_argument("--exist-ok", action="store_true", help="Cho phép ghi vào thư mục kết quả cùng tên đã có.")
    return parser.parse_args()


def validate_data_config(data_path: Path) -> dict[str, Any]:
    data_path = data_path.expanduser().resolve()
    if not data_path.is_file():
        raise FileNotFoundError(f"Không tìm thấy cấu hình dữ liệu: {data_path}")

    with data_path.open("r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if not isinstance(config, dict):
        raise ValueError(f"Cấu hình dữ liệu phải là YAML object: {data_path}")
    if not config.get("train") or not config.get("val"):
        raise ValueError("data.yaml cần khai báo cả hai split 'train' và 'val'.")
    if not config.get("nc") or not config.get("names"):
        raise ValueError("data.yaml cần khai báo 'nc' và 'names' theo Data Contract.")
    nc = int(config["nc"])
    if nc < 1 or len(config["names"]) != nc:
        raise ValueError("'nc' phải khớp số lớp trong 'names'.")
    return config


def main() -> None:
    args = parse_args()
    data_path = args.data.expanduser().resolve()
    data_config = validate_data_config(data_path)

    run_name = args.name or f"week4-{args.model}-{args.imgsz}"
    project_dir = args.project.expanduser().resolve()
    if args.model == "mobilenetv2-ssd":
        output_dir = project_dir / run_name
        if output_dir.exists() and any(output_dir.iterdir()):
            raise SystemExit(
                f"Thư mục run đã có artifacts: {output_dir}. Chọn --name mới để không ghi đè kết quả cũ."
            )
        try:
            from mobilenetv2_ssd import train_model
        except ImportError as exc:
            raise SystemExit(
                "Thiếu TensorFlow/Pillow/PyYAML. Cài dependencies bằng: pip install -r requirements.txt"
            ) from exc
        keras_path = train_model(
            data_yaml=data_path,
            output_dir=output_dir,
            imgsz=args.imgsz,
            epochs=args.epochs,
            batch=args.batch,
            seed=args.seed,
            backbone_weights=args.weights or "imagenet",
            freeze_backbone=args.freeze_backbone,
        )
        print(f"Training xong. Keras model: {keras_path}")
        print(f"SavedModel: {output_dir / 'saved_model'}")
        return

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise SystemExit(
            "Thiếu Ultralytics. Cài dependencies bằng: pip install -r requirements.txt"
        ) from exc

    weights = args.weights or MODEL_WEIGHTS[args.model]
    project_dir.mkdir(parents=True, exist_ok=True)

    model = YOLO(weights)
    train_options: dict[str, Any] = {
        "data": str(data_path),
        "imgsz": args.imgsz,
        "epochs": args.epochs,
        "batch": args.batch,
        "workers": args.workers,
        "project": str(project_dir),
        "name": run_name,
        "exist_ok": args.exist_ok,
        "plots": True,
        "seed": args.seed,
        "deterministic": True,
    }
    if args.device is not None:
        train_options["device"] = args.device

    result = model.train(**train_options)
    save_dir = Path(result.save_dir).resolve()
    best_weights = save_dir / "weights" / "best.pt"
    run_info = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "requested_model": args.model,
        "checkpoint": weights,
        "data_yaml": str(data_path),
        "num_classes": data_config["nc"],
        "class_names": data_config["names"],
        "imgsz": args.imgsz,
        "epochs": args.epochs,
        "batch": args.batch,
        "seed": args.seed,
        "device": args.device or "auto",
        "versions": {
            package: importlib.metadata.version(package)
            for package in ("ultralytics", "torch", "torchvision")
        },
        "best_weights": str(best_weights),
    }
    (save_dir / "ce340_run_config.json").write_text(
        json.dumps(run_info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Training xong. Kết quả: {save_dir}")
    print(f"Best checkpoint: {best_weights}")

    if args.export != "none":
        if not best_weights.is_file():
            raise FileNotFoundError(f"Không thấy best checkpoint để export: {best_weights}")
        trained_model = YOLO(str(best_weights))
        formats = ("onnx", "saved_model") if args.export == "both" else (args.export,)
        for export_format in formats:
            exported = trained_model.export(format=export_format, imgsz=args.imgsz)
            print(f"Đã export {export_format}: {exported}")


if __name__ == "__main__":
    main()
