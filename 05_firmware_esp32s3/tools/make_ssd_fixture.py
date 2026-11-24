"""Sinh dữ liệu đối chiếu cho host_tests/test_model_output.cpp.

Lấy shape 6 feature map từ model Keras thật (03_models_benchmark/mobilenetv2_ssd.py), sinh anchor bằng
build_anchors() của dự án, tạo đầu ra INT8 giả lập có 1 biển được cài sẵn, rồi giải mã bằng numpy theo
đúng công thức _decode_predictions(). File C header đầu ra là kết quả tham chiếu cho bản giải mã C++.

Chạy từ gốc repo (cần tensorflow + tf-keras như requirements.txt):
    python 05_firmware_esp32s3/tools/make_ssd_fixture.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "03_models_benchmark"))
import mobilenetv2_ssd as ssd  # noqa: E402

NUM_CLASSES = 12
SIZES = (96, 128, 160, 192, 320)


def feature_shapes(model) -> list[tuple[int, int]]:
    return [tuple(int(v) for v in model.get_layer(f"ssd_class_{i}").output.shape[1:3]) for i in range(6)]


def c_floats(values) -> str:
    return ", ".join(f"{float(v):.9g}f" for v in values)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--imgsz", type=int, default=96)
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO / "05_firmware_esp32s3/traffic_sign_alert/host_tests/ssd_fixture.h",
    )
    args = parser.parse_args()

    counts = {}
    for s in SIZES:
        model, anchors, _ = ssd.build_model(NUM_CLASSES, s, None)
        counts[s] = (feature_shapes(model), anchors)
    shapes, anchors = counts[args.imgsz]
    A, C = len(anchors), NUM_CLASSES + 1

    rng = np.random.default_rng(7)
    cls_scale, cls_zp = 0.0625, -12
    box_scale, box_zp = 0.03125, 3
    cls_q = rng.integers(-128, 60, size=(A, C), dtype=np.int16)
    cls_q[:, NUM_CLASSES] = rng.integers(40, 128, size=A)  # nền thắng ở hầu hết anchor, như model thật
    planted_anchor, planted_class = A // 3 + 5, 7
    cls_q[planted_anchor, :] = -100
    cls_q[planted_anchor, planted_class] = 110
    cls_q[planted_anchor, NUM_CLASSES] = 70
    cls_q = cls_q.clip(-128, 127).astype(np.int8)
    box_q = rng.integers(-128, 128, size=(A, 4), dtype=np.int16).astype(np.int8)

    logits = ((cls_q.astype(np.float32) - cls_zp) * np.float32(cls_scale)).astype(np.float32)
    offsets = ((box_q.astype(np.float32) - box_zp) * np.float32(box_scale)).astype(np.float32)
    e = np.exp(logits - logits.max(axis=1, keepdims=True))
    probs = e / e.sum(axis=1, keepdims=True)
    scores = probs[:, :NUM_CLASSES]
    best_anchor, best_class = np.unravel_index(np.argmax(scores), scores.shape)
    prior = anchors[best_anchor]
    center = offsets[best_anchor, :2] * prior[2:] * ssd.CENTER_VARIANCE + prior[:2]
    size = np.exp(np.clip(offsets[best_anchor, 2:] * ssd.SIZE_VARIANCE, -10.0, 10.0)) * prior[2:]
    box = np.clip(np.concatenate((center - size / 2, center + size / 2)), 0.0, 1.0)

    # Bản float32 (model FP32): cùng giá trị logits / offsets để kiểm tra nhánh không lượng tử hoá.
    lines = [
        "// Sinh bởi 05_firmware_esp32s3/tools/make_ssd_fixture.py — không sửa tay.",
        "// Anchor từ build_anchors() + shape feature map của model Keras thật; giải mã tham chiếu bằng numpy.",
        "#pragma once",
        "#include <cstdint>",
        "namespace fx {",
        f"constexpr int kImgsz = {args.imgsz};",
        f"constexpr int kAnchors = {A};",
        f"constexpr int kSizes[] = {{{', '.join(str(s) for s in SIZES)}}};",
        f"constexpr int kCounts[] = {{{', '.join(str(len(counts[s][1])) for s in SIZES)}}};",
        f"constexpr int kShapes[] = {{{', '.join(str(h) for h, _ in shapes)}}};",
        f"constexpr float kClsScale = {cls_scale}f;",
        f"constexpr int kClsZp = {cls_zp};",
        f"constexpr float kBoxScale = {box_scale}f;",
        f"constexpr int kBoxZp = {box_zp};",
        f"const int8_t kCls[] = {{{', '.join(map(str, cls_q.flatten().tolist()))}}};",
        f"const int8_t kBox[] = {{{', '.join(map(str, box_q.flatten().tolist()))}}};",
        f"const float kAnchorsRef[] = {{{c_floats(anchors.flatten())}}};",
        f"constexpr int kBestAnchor = {int(best_anchor)};",
        f"constexpr int kBestClass = {int(best_class)};",
        f"constexpr float kBestScore = {float(scores[best_anchor, best_class]):.9g}f;",
        f"constexpr float kBestBox[4] = {{{c_floats(box)}}};",
        f"constexpr int kPlantedAnchor = {planted_anchor};",
        f"constexpr int kPlantedClass = {planted_class};",
        "}  // namespace fx",
        "",
    ]
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(f"imgsz={args.imgsz} anchors={A} shapes={shapes} best=(anchor {best_anchor}, class {best_class}, "
          f"score {scores[best_anchor, best_class]:.4f}) → {args.out}")
    for s in SIZES:
        print(f"  {s}: {len(counts[s][1])} anchor, feature {[h for h, _ in counts[s][0]]}")


if __name__ == "__main__":
    main()
