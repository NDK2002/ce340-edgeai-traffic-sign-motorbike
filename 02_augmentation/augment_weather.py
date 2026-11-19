"""Sinh dữ liệu biển báo trong điều kiện thời tiết phức tạp cho đồ án CE340 ([K2]).

Bốn kịch bản (đều là biến đổi mức pixel, KHÔNG dịch/xoay ảnh nên tọa độ bbox giữ nguyên):
    rain         RandomRain (drizzle/heavy) + Spatter giọt nước đọng ống kính
    motion_blur  MotionBlur, kernel tỉ lệ theo kích thước ảnh (xe chạy 30–50 km/h)
    occlusion    ConstrainedCoarseDropout — 1 mảng che nằm trong mỗi bbox, che < 40% diện tích biển
    night        RandomBrightnessContrast + RandomGamma + GaussNoise (thiếu sáng ban đêm, nhiễu cảm biến)

Mỗi ảnh đầu ra đều được kiểm tra: không mất nhãn, bbox không lệch, tỉ lệ che của từng biển < 40%.
Mẫu không đạt sẽ được sinh lại (tối đa --max-attempts lần) rồi bỏ qua và ghi vào báo cáo.

QUAN TRỌNG: tăng cường SAU khi đã chia train/val/test (remap_and_split.py), chạy riêng cho từng split,
để ảnh tăng cường không bao giờ rò rỉ sang split khác.

Chạy từ thư mục gốc repo, ví dụ smoke-test trên bộ mock 5 ảnh:
    python 02_augmentation/augment_weather.py --preview 20

Tăng cường split train của dataset thật (ảnh trên Drive):
    python 02_augmentation/augment_weather.py \
        --images /content/drive/MyDrive/ce340/dataset/train/images \
        --out /content/drive/MyDrive/ce340/dataset_aug/train --copies 1 --preview 0
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import albumentations as A
import cv2
import numpy as np
import yaml


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_CLASSES = REPO_ROOT / "01_dataset" / "classes.yaml"
DEFAULT_IMAGES = REPO_ROOT / "01_dataset" / "mock_assets" / "images"
DEFAULT_OUT = SCRIPT_DIR / "outputs" / "mock"
DEFAULT_PREVIEW = SCRIPT_DIR / "preview_samples"

# Kịch bản mức pixel không biến đổi bbox nên Albumentations cảnh báo thừa; bbox vẫn được kiểm tra riêng.
warnings.filterwarnings("ignore", message="Got processor for bboxes, but no transform to process it")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
SCENARIOS = ("rain", "motion_blur", "occlusion", "night")
MIN_VISIBILITY = 0.4  # theo yêu cầu [K2]: A.BboxParams(..., min_visibility=0.4)
MAX_OCCLUSION = 0.4  # che khuất mỗi biển phải < 40% diện tích bbox
# Sai số cho phép khi so bbox trước/sau, tính theo pixel: Albumentations 2.x làm tròn bbox về lưới
# pixel trong CoarseDropout (lệch ~1px). Nhãn ghi ra luôn là nhãn gốc nên không bị ảnh hưởng.
BBOX_TOL_PX = 1.5
JPEG_QUALITY = 92
PREVIEW_MAX_SIDE = 480
GRID_THUMB = 160


# ----------------------------------------------------------------------------- I/O


def load_class_names(classes_path: Path) -> dict[int, str]:
    with classes_path.open("r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    names = config.get("names") if isinstance(config, dict) else None
    if isinstance(names, list):
        names = dict(enumerate(names))
    if not isinstance(names, dict) or not names:
        raise ValueError(f"{classes_path} không có khóa 'names' hợp lệ")
    return {int(k): str(v) for k, v in names.items()}


def read_image(path: Path) -> np.ndarray:
    # np.fromfile + imdecode thay cho cv2.imread để đọc được đường dẫn tiếng Việt trên Windows.
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Không đọc được ảnh: {path}")
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def write_image(path: Path, image_rgb: np.ndarray, quality: int = JPEG_QUALITY) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buffer = cv2.imencode(path.suffix or ".jpg", cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR),
                              [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError(f"Không ghi được ảnh: {path}")
    buffer.tofile(str(path))


def read_yolo_labels(path: Path, num_classes: int) -> tuple[list[list[float]], list[int], list[str]]:
    """Đọc file nhãn YOLO, cắt bbox về [0, 1]; trả về (bboxes, labels, warnings)."""
    bboxes: list[list[float]] = []
    labels: list[int] = []
    warnings: list[str] = []
    if not path.is_file():
        return bboxes, labels, warnings  # ảnh nền (không có biển) là hợp lệ

    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        parts = raw.split()
        if not parts:
            continue
        if len(parts) != 5:
            raise ValueError(f"{path}:{line_no}: cần 5 giá trị 'class cx cy w h', nhận '{raw}'")
        class_id = int(float(parts[0]))
        if not 0 <= class_id < num_classes:
            raise ValueError(f"{path}:{line_no}: class_id {class_id} ngoài khoảng 0..{num_classes - 1}")
        cx, cy, w, h = map(float, parts[1:])
        x1, y1 = max(0.0, cx - w / 2), max(0.0, cy - h / 2)
        x2, y2 = min(1.0, cx + w / 2), min(1.0, cy + h / 2)
        if x2 <= x1 or y2 <= y1:
            warnings.append(f"{path}:{line_no}: bbox rỗng sau khi cắt về [0,1] — bỏ qua")
            continue
        clipped = [(x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1]
        if not np.allclose(clipped, [cx, cy, w, h], atol=1e-6):
            warnings.append(f"{path}:{line_no}: bbox vượt biên ảnh — đã cắt về [0,1]")
        bboxes.append(clipped)
        labels.append(class_id)
    return bboxes, labels, warnings


def write_yolo_labels(path: Path, bboxes: list[list[float]], labels: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{int(c)} {x:.6f} {y:.6f} {w:.6f} {h:.6f}" for (x, y, w, h), c in zip(bboxes, labels)]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def infer_labels_dir(images_dir: Path) -> Path:
    """Quy ước YOLO: .../images -> .../labels (cùng cấp)."""
    if images_dir.name == "images":
        return images_dir.parent / "labels"
    return images_dir


def list_images(images_dir: Path) -> list[Path]:
    return sorted(p for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS)


# ----------------------------------------------------------------------- transforms


def _odd(value: float) -> int:
    n = max(3, int(round(value)))
    return n if n % 2 else n + 1


def build_transform(scenario: str, image_shape: tuple[int, ...], num_classes: int, seed: int) -> A.Compose:
    """Pipeline Albumentations cho 1 kịch bản; tham số tỉ lệ theo cạnh ngắn của ảnh."""
    short_side = min(image_shape[:2])

    if scenario == "rain":
        # Mặc định Albumentations dùng vệt mưa dài height/8 (quá dài với ảnh 160–320px);
        # 'torrential' (2×height giọt) che gần hết biển nên không dùng.
        drop_length = max(4, round(short_side * 0.04))
        transforms: list[Any] = [
            A.OneOf(
                [A.RandomRain(rain_type=kind, drop_length=drop_length, blur_value=3,
                              brightness_coefficient=0.8, p=1.0)
                 for kind in ("drizzle", "heavy")],
                p=1.0,
            ),
            A.Spatter(mode="rain", p=0.6),  # giọt nước đọng trên ống kính
        ]
    elif scenario == "motion_blur":
        k_min = _odd(short_side * 0.02)
        k_max = max(k_min + 2, _odd(short_side * 0.045))
        transforms = [A.MotionBlur(blur_limit=(k_min, k_max), p=1.0)]
    elif scenario == "occlusion":
        # 1 lỗ/biển, mỗi chiều 30–60% kích thước bbox -> diện tích che 9–36% (< 40%).
        transforms = [
            A.ConstrainedCoarseDropout(
                num_holes_range=(1, 1),
                hole_height_range=(0.3, 0.6),
                hole_width_range=(0.3, 0.6),
                fill="random_uniform",
                fill_mask=255,  # đánh dấu vùng che trên mask để đo tỉ lệ che từng biển
                bbox_labels=list(range(num_classes)),
                p=1.0,
            )
        ]
    elif scenario == "night":
        transforms = [
            # Biển báo phản quang vẫn còn đọc được ban đêm -> tối vừa phải, không về đen.
            A.RandomBrightnessContrast(brightness_limit=(-0.35, -0.2), contrast_limit=(-0.2, 0.0), p=1.0),
            A.RandomGamma(gamma_limit=(105, 135), p=0.5),
            A.GaussNoise(std_range=(0.02, 0.05), p=0.7),
        ]
    else:
        raise ValueError(f"Kịch bản không hỗ trợ: {scenario} (chọn trong {SCENARIOS})")

    return A.Compose(
        transforms,
        bbox_params=A.BboxParams(format="yolo", label_fields=["class_labels"], min_visibility=MIN_VISIBILITY),
        seed=seed,
    )


# ------------------------------------------------------------------------ validation


def occlusion_fractions(occlusion_mask: np.ndarray, bboxes: list[list[float]]) -> list[float]:
    """Tỉ lệ diện tích mỗi bbox (YOLO chuẩn hóa) bị che theo mask (>0 là bị che)."""
    h, w = occlusion_mask.shape[:2]
    fractions = []
    for cx, cy, bw, bh in bboxes:
        x1, x2 = int(round((cx - bw / 2) * w)), int(round((cx + bw / 2) * w))
        y1, y2 = int(round((cy - bh / 2) * h)), int(round((cy + bh / 2) * h))
        region = occlusion_mask[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
        fractions.append(float((region > 0).mean()) if region.size else 0.0)
    return fractions


def validate_output(
    src_bboxes: list[list[float]],
    src_labels: list[int],
    out_bboxes: Any,
    out_labels: Any,
    occlusion_mask: np.ndarray,
) -> str | None:
    """Trả về None nếu đạt, ngược lại là lý do lỗi."""
    if len(out_bboxes) != len(src_bboxes) or [int(c) for c in out_labels] != list(src_labels):
        return f"mất nhãn ({len(src_bboxes)} -> {len(out_bboxes)} bbox)"
    if src_bboxes:
        h, w = occlusion_mask.shape[:2]
        tolerance = np.array([BBOX_TOL_PX / w, BBOX_TOL_PX / h, BBOX_TOL_PX / w, BBOX_TOL_PX / h])
        if (np.abs(np.asarray(out_bboxes, dtype=float) - np.asarray(src_bboxes)) > tolerance).any():
            return "bbox bị lệch so với ảnh gốc"
    worst = max(occlusion_fractions(occlusion_mask, src_bboxes), default=0.0)
    if worst >= MAX_OCCLUSION:
        return f"biển bị che {worst:.0%} (>= {MAX_OCCLUSION:.0%})"
    return None


# --------------------------------------------------------------------------- engine


@dataclass
class AugmentReport:
    source_images: int = 0
    generated: Counter = field(default_factory=Counter)
    skipped: list[dict[str, str]] = field(default_factory=list)
    retries: Counter = field(default_factory=Counter)
    max_occlusion: dict[str, float] = field(default_factory=dict)
    class_instances: Counter = field(default_factory=Counter)
    label_warnings: list[str] = field(default_factory=list)


class WeatherAugmenter:
    def __init__(self, num_classes: int, seed: int = 42, max_attempts: int = 10) -> None:
        self.num_classes = num_classes
        self.seed = seed
        self.max_attempts = max_attempts
        self._cache: dict[tuple[str, tuple[int, ...]], A.Compose] = {}

    def _transform(self, scenario: str, shape: tuple[int, ...]) -> A.Compose:
        key = (scenario, tuple(shape[:2]))
        if key not in self._cache:
            offset = SCENARIOS.index(scenario) * 1_000_003 + len(self._cache)
            self._cache[key] = build_transform(scenario, shape, self.num_classes, self.seed + offset)
        return self._cache[key]

    def augment(
        self, image: np.ndarray, bboxes: list[list[float]], labels: list[int], scenario: str
    ) -> tuple[np.ndarray | None, int, float, str | None]:
        """Trả về (ảnh, số lần thử, tỉ lệ che lớn nhất, lỗi cuối) — ảnh None nếu hết lượt thử."""
        transform = self._transform(scenario, image.shape)
        empty_mask = np.zeros(image.shape[:2], dtype=np.uint8)
        error = None
        for attempt in range(1, self.max_attempts + 1):
            out = transform(image=image, mask=empty_mask, bboxes=bboxes, class_labels=labels)
            error = validate_output(bboxes, labels, out["bboxes"], out["class_labels"], out["mask"])
            if error is None:
                worst = max(occlusion_fractions(out["mask"], bboxes), default=0.0)
                return out["image"], attempt, worst, None
        return None, self.max_attempts, 0.0, error


def run(args: argparse.Namespace) -> AugmentReport:
    class_names = load_class_names(args.classes)
    num_classes = len(class_names)
    images_dir = args.images.resolve()
    labels_dir = (args.labels or infer_labels_dir(images_dir)).resolve()
    out_images, out_labels = args.out / "images", args.out / "labels"

    image_paths = list_images(images_dir)
    if not image_paths:
        raise FileNotFoundError(f"Không có ảnh trong {images_dir}")

    augmenter = WeatherAugmenter(num_classes, seed=args.seed, max_attempts=args.max_attempts)
    report = AugmentReport(source_images=len(image_paths))
    preview_pool: dict[str, list[tuple[Path, np.ndarray, list[list[float]], list[int]]]] = {s: [] for s in args.scenarios}
    grid_rows: list[list[np.ndarray]] = []

    for index, image_path in enumerate(image_paths, start=1):
        image = read_image(image_path)
        bboxes, labels, warnings = read_yolo_labels(labels_dir / f"{image_path.stem}.txt", num_classes)
        report.label_warnings.extend(warnings)
        grid_row = [draw_boxes(image, bboxes, labels, class_names, "original")] if len(grid_rows) < args.grid_rows else None

        for scenario in args.scenarios:
            for copy in range(args.copies):
                result, attempts, worst, error = augmenter.augment(image, bboxes, labels, scenario)
                if result is None:
                    report.skipped.append({"image": image_path.name, "scenario": scenario, "reason": error or ""})
                    continue
                stem = f"{image_path.stem}__{scenario}{copy}"
                write_image(out_images / f"{stem}.jpg", result)
                write_yolo_labels(out_labels / f"{stem}.txt", bboxes, labels)
                report.generated[scenario] += 1
                report.retries[scenario] += attempts - 1
                report.max_occlusion[scenario] = max(report.max_occlusion.get(scenario, 0.0), worst)
                report.class_instances.update(class_names[c] for c in labels)
                if len(preview_pool[scenario]) < args.preview:
                    preview_pool[scenario].append((out_images / f"{stem}.jpg", result, bboxes, labels))
                if grid_row is not None and copy == 0:
                    grid_row.append(draw_boxes(result, bboxes, labels, class_names, scenario))

        if grid_row is not None:
            grid_rows.append(grid_row)
        if index % 100 == 0 or index == len(image_paths):
            print(f"[{index}/{len(image_paths)}] đã xử lý", flush=True)

    if args.preview > 0:
        write_previews(args.preview_dir, preview_pool, args.preview, class_names, grid_rows)
    write_summary(args, report, images_dir, labels_dir)
    return report


# --------------------------------------------------------------------------- preview


def _color(class_id: int) -> tuple[int, int, int]:
    hue = int(class_id * 180 / 12) % 180
    bgr = cv2.cvtColor(np.uint8([[[hue, 220, 255]]]), cv2.COLOR_HSV2RGB)[0, 0]
    return int(bgr[0]), int(bgr[1]), int(bgr[2])


def draw_boxes(
    image: np.ndarray, bboxes: list[list[float]], labels: list[int], class_names: dict[int, str], title: str = ""
) -> np.ndarray:
    canvas = image.copy()
    h, w = canvas.shape[:2]
    thickness = max(1, round(min(h, w) / 200))
    scale = max(0.35, min(h, w) / 800)
    for (cx, cy, bw, bh), c in zip(bboxes, labels):
        x1, y1 = int((cx - bw / 2) * w), int((cy - bh / 2) * h)
        x2, y2 = int((cx + bw / 2) * w), int((cy + bh / 2) * h)
        color = _color(c)
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, thickness)
        text = f"{c}:{class_names.get(c, '?')}"
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
        ty = y1 - 3 if y1 - th - 6 > 0 else y2 + th + 3
        cv2.rectangle(canvas, (x1, ty - th - 3), (x1 + tw + 4, ty + 3), color, -1)
        cv2.putText(canvas, text, (x1 + 2, ty), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 1, cv2.LINE_AA)
    if title:
        cv2.putText(canvas, title, (6, int(22 * scale / 0.4)), cv2.FONT_HERSHEY_SIMPLEX, scale * 1.2,
                    (255, 255, 255), 2, cv2.LINE_AA)
    return canvas


def _fit(image: np.ndarray, max_side: int) -> np.ndarray:
    h, w = image.shape[:2]
    ratio = max_side / max(h, w)
    if ratio >= 1:
        return image
    return cv2.resize(image, (round(w * ratio), round(h * ratio)), interpolation=cv2.INTER_AREA)


def write_previews(
    preview_dir: Path,
    pool: dict[str, list[tuple[Path, np.ndarray, list[list[float]], list[int]]]],
    limit: int,
    class_names: dict[int, str],
    grid_rows: list[list[np.ndarray]],
) -> None:
    preview_dir.mkdir(parents=True, exist_ok=True)
    for old in preview_dir.glob("*.jpg"):
        old.unlink()

    # Lấy xen kẽ giữa các kịch bản để preview phủ đủ cả 4 loại thời tiết.
    chosen = []
    queues = [list(items) for items in pool.values()]
    while len(chosen) < limit and any(queues):
        for queue in queues:
            if queue and len(chosen) < limit:
                chosen.append(queue.pop(0))
    for out_path, image, bboxes, labels in chosen:
        drawn = draw_boxes(image, bboxes, labels, class_names)
        write_image(preview_dir / out_path.name, _fit(drawn, PREVIEW_MAX_SIDE), quality=85)

    if grid_rows:
        columns = max(len(row) for row in grid_rows)
        tiles = []
        for row in grid_rows:
            thumbs = [cv2.resize(_fit(t, GRID_THUMB), (GRID_THUMB, GRID_THUMB)) for t in row]
            thumbs += [np.zeros((GRID_THUMB, GRID_THUMB, 3), np.uint8)] * (columns - len(thumbs))
            tiles.append(np.hstack(thumbs))
        write_image(preview_dir / "_grid_overview.jpg", np.vstack(tiles), quality=85)
    print(f"Preview: {len(chosen)} ảnh + _grid_overview.jpg -> {preview_dir}")


def write_summary(args: argparse.Namespace, report: AugmentReport, images_dir: Path, labels_dir: Path) -> None:
    summary = {
        "source_images": report.source_images,
        "images_dir": str(images_dir),
        "labels_dir": str(labels_dir),
        "out_dir": str(args.out.resolve()),
        "scenarios": list(args.scenarios),
        "copies_per_scenario": args.copies,
        "seed": args.seed,
        "albumentations_version": A.__version__,
        "generated": dict(report.generated),
        "generated_total": sum(report.generated.values()),
        "retries": dict(report.retries),
        "max_bbox_occlusion": {k: round(v, 4) for k, v in report.max_occlusion.items()},
        "class_instances": dict(sorted(report.class_instances.items())),
        "skipped": report.skipped,
        "label_warnings": report.label_warnings,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "augment_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("generated", "generated_total", "max_bbox_occlusion")}, ensure_ascii=False))
    if report.skipped:
        print(f"CẢNH BÁO: bỏ qua {len(report.skipped)} mẫu — xem augment_summary.json", file=sys.stderr)
    for warning in report.label_warnings:
        print(f"CẢNH BÁO: {warning}", file=sys.stderr)


# ------------------------------------------------------------------------------ CLI


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tăng cường ảnh thời tiết phức tạp (mưa, mờ, che khuất, đêm) cho CE340.")
    parser.add_argument("--images", type=Path, default=DEFAULT_IMAGES, help="Thư mục ảnh nguồn (1 split).")
    parser.add_argument("--labels", type=Path, help="Thư mục nhãn YOLO; mặc định suy ra images -> labels.")
    parser.add_argument("--classes", type=Path, default=DEFAULT_CLASSES, help="Data contract 12 lớp.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Thư mục xuất (tạo images/ và labels/).")
    parser.add_argument("--scenarios", nargs="+", choices=SCENARIOS, default=list(SCENARIOS))
    parser.add_argument("--copies", type=int, default=1, help="Số bản sinh cho mỗi ảnh × mỗi kịch bản.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-attempts", type=int, default=10, help="Số lần sinh lại khi mẫu không đạt kiểm tra.")
    parser.add_argument("--preview", type=int, default=20, help="Số ảnh vẽ bbox kiểm chứng (0 = tắt).")
    parser.add_argument("--preview-dir", type=Path, default=DEFAULT_PREVIEW)
    parser.add_argument("--grid-rows", type=int, default=5, help="Số ảnh nguồn đưa vào _grid_overview.jpg.")
    args = parser.parse_args(argv)
    if args.copies < 1 or args.max_attempts < 1 or args.preview < 0:
        parser.error("--copies, --max-attempts phải >= 1 và --preview >= 0")
    return args


def main(argv: list[str] | None = None) -> int:
    # Console Windows mặc định cp1252 không in được tiếng Việt.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    report = run(parse_args(argv))
    return 1 if report.skipped else 0


if __name__ == "__main__":
    raise SystemExit(main())
