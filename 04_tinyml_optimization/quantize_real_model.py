"""[S3][S4] Official TinyML Post-Training Quantization (Full INT8) & C-array export.

Hỗ trợ cả 2 nhánh mô hình thật từ `[T4]` (Phạm Thành Trung) và tập ảnh calibration từ `[K1]` (Nguyễn Duy Khang):
  - Nhánh `tf` (MobileNetV2-SSD SavedModel/.keras): chuẩn hóa calibration RGB float32 [-1, 1].
  - Nhánh `onnx` (YOLOv8n / YOLOv5u nano .onnx): chuyển đổi qua `onnx2tf` (-oiqt) với calibration RGB float32 [0, 1].

Khuyến nghị chạy trên Google Colab (Linux) sau khi cài `requirements.txt` + `onnx2tf`.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Bắt buộc đặt trước khi nạp TensorFlow để tương thích legacy Keras 2 / TFMOT
os.environ.setdefault("TF_USE_LEGACY_KERAS", "1")

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from quantize_int8_mock import export_tflite_to_c_header  # noqa: E402

# Tập toán tử phổ biến được tflite-micro (ESP-NN trên ESP32-S3) hỗ trợ tốt ở INT8
TFLM_SUPPORTED_OPS = frozenset(
    {
        "ADD",
        "AVERAGE_POOL_2D",
        "CONCATENATION",
        "CONV_2D",
        "DEPTHWISE_CONV_2D",
        "DEQUANTIZE",
        "FULLY_CONNECTED",
        "LOGISTIC",
        "MAX_POOL_2D",
        "MEAN",
        "MUL",
        "PAD",
        "QUANTIZE",
        "RELU",
        "RELU6",
        "RESHAPE",
        "RESIZE_BILINEAR",
        "RESIZE_NEAREST_NEIGHBOR",
        "SOFTMAX",
        "STRIDED_SLICE",
        "SUB",
        "TRANSPOSE",
    }
)


def _collect_image_paths(calib_dir: Path, max_samples: int) -> list[Path]:
    """Thu thập danh sách ảnh calibration (.jpg/.jpeg/.png) theo thứ tự ổn định."""
    extensions = {".jpg", ".jpeg", ".png"}
    paths = sorted(p for p in calib_dir.rglob("*") if p.suffix.lower() in extensions)
    if not paths:
        raise FileNotFoundError(f"Không tìm thấy ảnh calibration trong: {calib_dir}")
    return paths[:max_samples]


def _load_calibration_batch(image_paths: list[Path], imgsz: int, norm_mode: str) -> "np.ndarray":
    """Đọc ảnh calibration và chuẩn hóa theo đúng dải của từng nhánh mô hình."""
    import numpy as np
    from PIL import Image

    batch = []
    for path in image_paths:
        with Image.open(path) as img:
            arr = np.asarray(img.convert("RGB").resize((imgsz, imgsz)), dtype=np.float32)
            if norm_mode == "minus_one_to_one":
                arr = (arr / 127.5) - 1.0
            elif norm_mode == "zero_to_one":
                arr = arr / 255.0
            else:
                raise ValueError(f"Unsupported norm_mode: {norm_mode}")
            batch.append(arr)
    return np.stack(batch, axis=0)


def _convert_tf_branch(model_path: Path, calib_batch: "np.ndarray") -> tuple[bytes, bytes]:
    """Convert SavedModel hoặc .keras sang FP32 baseline và Full Integer INT8."""
    import tensorflow as tf

    def make_converter():
        if model_path.is_dir():
            return tf.lite.TFLiteConverter.from_saved_model(str(model_path))
        model = tf.keras.models.load_model(str(model_path), compile=False)
        return tf.lite.TFLiteConverter.from_keras_model(model)

    fp32_bytes = make_converter().convert()

    def representative_dataset():
        for i in range(len(calib_batch)):
            yield [calib_batch[i : i + 1]]

    int8_converter = make_converter()
    int8_converter.optimizations = [tf.lite.Optimize.DEFAULT]
    int8_converter.representative_dataset = representative_dataset
    int8_converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    int8_converter.inference_input_type = tf.int8
    int8_converter.inference_output_type = tf.int8
    int8_bytes = int8_converter.convert()
    return fp32_bytes, int8_bytes


def _convert_onnx_branch(onnx_path: Path, calib_batch: "np.ndarray") -> tuple[bytes, bytes]:
    """Convert ONNX (YOLOv8n / YOLOv5u) sang FP32 & Full INT8 TFLite qua onnx2tf."""
    import numpy as np

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        calib_npy = tmp_path / "calib_rgb_01.npy"
        np.save(calib_npy, calib_batch)

        out_dir = tmp_path / "onnx2tf_out"
        cmd = [
            "onnx2tf",
            "-i",
            str(onnx_path),
            "-o",
            str(out_dir),
            "-oiqt",
            "-qt",
            "per-tensor",
            "-cind",
            "images",
            str(calib_npy),
            "[[[[0,0,0]]]]",
            "[[[[1,1,1]]]]",
        ]
        subprocess.run(cmd, check=True)

        fp32_candidates = sorted(out_dir.glob("*_float32.tflite"))
        int8_candidates = sorted(out_dir.glob("*_full_integer_quant.tflite"))
        if not int8_candidates:
            int8_candidates = sorted(out_dir.glob("*_integer_quant.tflite"))
        if not fp32_candidates or not int8_candidates:
            raise FileNotFoundError(
                f"Không tìm thấy đủ file float32/full_integer_quant .tflite trong {out_dir}"
            )
        return fp32_candidates[0].read_bytes(), int8_candidates[0].read_bytes()


def _inspect_tflite_model(int8_bytes: bytes) -> tuple[list[str], list[str]]:
    """Kiểm tra I/O dtype=int8 và đối chiếu danh sách ops với TFLM (ESP-NN)."""
    import numpy as np
    import tensorflow as tf

    interpreter = tf.lite.Interpreter(model_content=int8_bytes)
    interpreter.allocate_tensors()

    inputs = interpreter.get_input_details()
    outputs = interpreter.get_output_details()
    for detail in inputs:
        print(f"[Input]  {detail['name']}: shape={tuple(detail['shape'])}, dtype={detail['dtype'].__name__}")
        if detail["dtype"] != np.int8:
            raise AssertionError(f"Input {detail['name']} chưa phải int8 ({detail['dtype']})")
    for detail in outputs:
        print(f"[Output] {detail['name']}: shape={tuple(detail['shape'])}, dtype={detail['dtype'].__name__}")

    ops = sorted({op["op_name"] for op in interpreter._get_ops_details()})
    unsupported = [op for op in ops if op not in TFLM_SUPPORTED_OPS]
    return ops, unsupported


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="[S3][S4] Full Integer INT8 Quantization & C-array export cho model thật (CE340)"
    )
    parser.add_argument(
        "--branch",
        choices=["tf", "onnx"],
        required=True,
        help="Nhánh model đầu vào: 'tf' (MobileNetV2-SSD SavedModel/.keras) hoặc 'onnx' (YOLOv8n/v5u)",
    )
    parser.add_argument("--model", type=Path, required=True, help="Đường dẫn SavedModel/, .keras hoặc .onnx")
    parser.add_argument("--calib-dir", type=Path, required=True, help="Thư mục ảnh calibration từ [K1]")
    parser.add_argument("--imgsz", type=int, default=160, help="Kích thước ảnh đầu vào (mặc định: 160)")
    parser.add_argument("--max-calib", type=int, default=150, help="Số ảnh calibration tối đa (100-200)")
    parser.add_argument(
        "--output-tflite",
        type=Path,
        default=Path("04_tinyml_optimization/traffic_sign_model_int8.tflite"),
        help="Đường dẫn file .tflite INT8 đầu ra",
    )
    parser.add_argument(
        "--output-header",
        type=Path,
        default=Path("04_tinyml_optimization/traffic_sign_model_int8.h"),
        help="Đường dẫn file C-array .h đầu ra",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    norm_mode = "minus_one_to_one" if args.branch == "tf" else "zero_to_one"

    image_paths = _collect_image_paths(args.calib_dir, args.max_calib)
    print(f"[Calib] Loaded {len(image_paths)} images | imgsz={args.imgsz} | norm={norm_mode}")
    calib_batch = _load_calibration_batch(image_paths, args.imgsz, norm_mode)

    if args.branch == "tf":
        fp32_bytes, int8_bytes = _convert_tf_branch(args.model, calib_batch)
    else:
        fp32_bytes, int8_bytes = _convert_onnx_branch(args.model, calib_batch)

    reduction_pct = (1.0 - len(int8_bytes) / len(fp32_bytes)) * 100.0
    print(f"[Size] FP32: {len(fp32_bytes):,} bytes ({len(fp32_bytes) / 1024:.1f} KB)")
    print(f"[Size] INT8: {len(int8_bytes):,} bytes ({len(int8_bytes) / 1024:.1f} KB)")
    print(f"[Size] Reduction: {reduction_pct:.2f}% (target >= 70%)")

    ops, unsupported = _inspect_tflite_model(int8_bytes)
    print(f"[Ops] Total unique ops ({len(ops)}): {ops}")
    if unsupported:
        print(f"[WARN] Ops ngoài danh sách TFLM cơ bản: {unsupported}")
    else:
        print("[Ops] 100% ops nằm trong tập hỗ trợ TFLM / ESP-NN.")

    args.output_tflite.parent.mkdir(parents=True, exist_ok=True)
    args.output_tflite.write_bytes(int8_bytes)
    export_tflite_to_c_header(
        int8_bytes,
        args.output_header,
        array_name="traffic_sign_model_int8",
        guard_name="CE340_TRAFFIC_SIGN_MODEL_INT8_H_",
    )
    print(f"[Done] Saved TFLite: {args.output_tflite}")
    print(f"[Done] Saved Header: {args.output_header}")


if __name__ == "__main__":
    main()
