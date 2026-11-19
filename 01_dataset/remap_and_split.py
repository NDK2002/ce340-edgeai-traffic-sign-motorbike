"""Gộp dataset biển báo công khai về 12 lớp CE340 và chia Train/Val/Test theo nhóm ([K1]).

Quy trình:
    1. Khai báo nguồn trong 01_dataset/sources.yaml (YOLO/Roboflow hoặc COCO JSON như Zalo AI).
    2. Xem tên lớp thật của từng nguồn và sinh khung ánh xạ:
           python 01_dataset/remap_and_split.py --inspect
    3. Điền ánh xạ "tên lớp nguồn -> tên lớp đích" theo Ý NGHĨA biển (xem 01_dataset/classes.yaml),
       rồi chạy gộp & chia:
           python 01_dataset/remap_and_split.py --out 01_dataset/processed

Đặc điểm:
    * Lớp nguồn không có trong ánh xạ bị bỏ (đếm trong báo cáo); ảnh chỉ còn nền được giữ tối đa
      --background-ratio để làm mẫu âm.
    * Chia 70/20/10 theo NHÓM (cùng clip / cùng ảnh gốc Roboflow) để chống rò rỉ frame,
      gán nhóm tham lam cân bằng số biển từng lớp giữa các split.
    * Loại ảnh trùng byte-by-byte (Roboflow hay chép cùng 1 ảnh vào nhiều split).
    * Xuất YOLO chuẩn Ultralytics: <out>/images/{train,val,test}, <out>/labels/{train,val,test},
      <out>/data.yaml (không có 'path' -> dùng được khi copy cả thư mục lên Drive/Colab),
      kèm 01_dataset/data.yaml (có 'path' tuyệt đối) và 01_dataset/dataset_summary.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any, Iterable

import cv2
import numpy as np
import yaml


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CLASSES = SCRIPT_DIR / "classes.yaml"
DEFAULT_SOURCES = SCRIPT_DIR / "sources.yaml"
DEFAULT_OUT = SCRIPT_DIR / "processed"
SPLITS = ("train", "val", "test")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

# Roboflow: "<goc>_jpg.rf.<hash>.jpg". Frame video:
#   "<clip>_mp4-0012"      (Roboflow tự cắt video)
#   "<clip>-MOV_out0012"   (ffmpeg "out%04d" — dataset Vietnam-Traffic-Sign-Detection v6)
#   "<clip>_frame_0012"
ROBOFLOW_SUFFIX = re.compile(r"_(jpe?g|png|bmp|webp)\.rf\.[0-9a-f]+$", re.IGNORECASE)
VIDEO_FRAME = re.compile(
    r"([-_.](mp4|avi|mov|mkv)([-_]?(out|frame))?[-_]?\d+|[-_]frame[-_]?\d+)$", re.IGNORECASE
)


# ------------------------------------------------------------------------- data model


@dataclass
class Box:
    class_id: int
    cx: float
    cy: float
    w: float
    h: float


@dataclass
class Sample:
    source: str
    image_path: Path
    group: str
    boxes: list[Box] = field(default_factory=list)  # đã ánh xạ sang 12 lớp đích
    dropped: Counter = field(default_factory=Counter)  # tên lớp nguồn bị bỏ -> số biển
    digest: str = ""

    @property
    def class_counts(self) -> Counter:
        return Counter(b.class_id for b in self.boxes)


@dataclass
class SourceStats:
    images: int = 0
    kept_images: int = 0
    background_images: int = 0
    duplicates: int = 0
    excluded: Counter = field(default_factory=Counter)  # lớp nguồn gây loại ảnh -> số ảnh
    scene_merges: int = 0
    overrides_applied: int = 0
    mapped: Counter = field(default_factory=Counter)  # "nguồn -> đích" -> số biển
    dropped: Counter = field(default_factory=Counter)
    warnings: list[str] = field(default_factory=list)


# ----------------------------------------------------------------------- config / IO


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def load_class_names(classes_path: Path) -> dict[int, str]:
    names = (load_yaml(classes_path) or {}).get("names")
    if isinstance(names, list):
        names = dict(enumerate(names))
    if not isinstance(names, dict) or not names:
        raise ValueError(f"{classes_path} không có khóa 'names' hợp lệ")
    return {int(k): str(v) for k, v in names.items()}


def resolve_target(value: Any, class_names: dict[int, str]) -> int | None:
    """Đích ánh xạ: tên lớp, class_id, hoặc null/'drop' để bỏ."""
    if value is None or (isinstance(value, str) and value.strip().lower() in {"", "drop", "null", "none"}):
        return None
    if isinstance(value, int) or (isinstance(value, str) and value.strip().isdigit()):
        class_id = int(value)
        if class_id not in class_names:
            raise ValueError(f"class_id đích {class_id} không có trong classes.yaml")
        return class_id
    by_name = {name: cid for cid, name in class_names.items()}
    if value not in by_name:
        raise ValueError(f"Lớp đích '{value}' không có trong classes.yaml (chọn: {', '.join(by_name)})")
    return by_name[value]


def group_key(stem: str, rule: str) -> str:
    """Khóa nhóm chống rò rỉ: ảnh cùng khóa luôn nằm chung 1 split."""
    if rule == "stem":
        return stem
    if rule.startswith("regex:"):
        match = re.search(rule[len("regex:"):], stem)
        return (match.group(1) if match and match.groups() else match.group(0)) if match else stem
    if rule != "auto":
        raise ValueError(f"group không hợp lệ: '{rule}' (dùng auto | stem | regex:<pattern>)")
    base = ROBOFLOW_SUFFIX.sub("", stem)
    clip = VIDEO_FRAME.sub("", base)
    return clip or base


def file_digest(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_size(path: Path) -> tuple[int, int]:
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError(f"Không đọc được ảnh: {path}")
    return image.shape[1], image.shape[0]


def clip_box(class_id: int, x1: float, y1: float, x2: float, y2: float) -> Box | None:
    x1, y1, x2, y2 = max(0.0, x1), max(0.0, y1), min(1.0, x2), min(1.0, y2)
    if x2 <= x1 or y2 <= y1:
        return None
    return Box(class_id, (x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1)


# ----------------------------------------------------------------------------- readers
# Mỗi reader trả về iterator (ảnh, [(tên lớp nguồn, x1, y1, x2, y2 chuẩn hóa 0..1)]).

RawAnn = tuple[str, float, float, float, float]


def read_yolo_source(root: Path, yaml_name: str | None = None) -> Iterable[tuple[Path, list[RawAnn]]]:
    candidates = [root / yaml_name] if yaml_name else [root / "data.yaml", root / "data.yml"]
    yaml_path = next((p for p in candidates if p.is_file()), None)
    if yaml_path is None:
        raise FileNotFoundError(f"Nguồn YOLO cần file {candidates[0]} chứa 'names'")
    names = (load_yaml(yaml_path) or {}).get("names")
    if isinstance(names, list):
        names = dict(enumerate(names))
    names = {int(k): str(v) for k, v in names.items()}

    image_dirs = sorted({p for p in root.rglob("images") if p.is_dir()})
    if not image_dirs:
        raise FileNotFoundError(f"Không tìm thấy thư mục images/ trong {root}")
    for image_dir in image_dirs:
        label_dir = image_dir.parent / "labels"
        for image_path in sorted(p for p in image_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS):
            anns: list[RawAnn] = []
            label_path = label_dir / f"{image_path.stem}.txt"
            if label_path.is_file():
                for line in label_path.read_text(encoding="utf-8").splitlines():
                    parts = line.split()
                    if len(parts) < 5:
                        continue
                    if len(parts) > 5:  # nhãn polygon/segment của Roboflow -> lấy bbox bao
                        coords = np.array(parts[1:], dtype=float).reshape(-1, 2)
                        x1, y1 = coords.min(axis=0)
                        x2, y2 = coords.max(axis=0)
                    else:
                        cx, cy, w, h = map(float, parts[1:5])
                        x1, y1, x2, y2 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
                    source_id = int(float(parts[0]))
                    anns.append((names.get(source_id, str(source_id)), x1, y1, x2, y2))
            yield image_path, anns


def read_coco_source(images_dir: Path, annotations: Path) -> Iterable[tuple[Path, list[RawAnn]]]:
    data = json.loads(annotations.read_text(encoding="utf-8"))
    categories = {c["id"]: str(c.get("name", c["id"])) for c in data.get("categories", [])}
    per_image: dict[Any, list[dict]] = defaultdict(list)
    for ann in data.get("annotations", []):
        per_image[ann["image_id"]].append(ann)
    for info in sorted(data.get("images", []), key=lambda i: str(i["file_name"])):
        image_path = images_dir / info["file_name"]
        if not image_path.is_file():
            continue
        width, height = info.get("width"), info.get("height")
        if not width or not height:
            width, height = image_size(image_path)
        anns: list[RawAnn] = []
        for ann in per_image.get(info["id"], []):
            x, y, w, h = ann["bbox"]
            name = categories.get(ann["category_id"], str(ann["category_id"]))
            anns.append((name, x / width, y / height, (x + w) / width, (y + h) / height))
        yield image_path, anns


def iter_source(spec: dict, base: Path) -> Iterable[tuple[Path, list[RawAnn]]]:
    fmt = spec.get("format", "yolo")
    if fmt == "yolo":
        return read_yolo_source((base / spec["root"]).resolve(), spec.get("data_yaml"))
    if fmt == "coco":
        return read_coco_source((base / spec["images"]).resolve(), (base / spec["annotations"]).resolve())
    raise ValueError(f"Nguồn '{spec.get('name')}': format '{fmt}' không hỗ trợ (yolo | coco)")


# ------------------------------------------------------------------ scene / overrides


def natural_key(text: str) -> list[Any]:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", text)]


def scene_feature(path: Path) -> np.ndarray:
    """Vector đặc trưng phần trên ảnh (bỏ 45% dưới — tay lái/gương xe giống nhau ở mọi cảnh)."""
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"Không đọc được ảnh: {path}")
    top = image[: max(1, int(image.shape[0] * 0.55))]
    small = cv2.GaussianBlur(cv2.resize(top, (48, 32), interpolation=cv2.INTER_AREA).astype(np.float32), (3, 3), 0)
    centered = small - small.mean()
    return centered / (np.linalg.norm(centered) + 1e-6)


def merge_scenes(paths: list[Path], groups: dict[Path, str], threshold: float) -> tuple[dict[Path, str], int]:
    """Gộp nhóm của các ảnh liền kề (theo thứ tự tên tự nhiên) có nội dung giống nhau >= threshold.
    Bắt các cảnh bị cắt thành nhiều clip/ảnh rời — nguồn rò rỉ mà quy tắc theo tên file không thấy."""
    ordered = sorted(paths, key=lambda p: natural_key(p.stem))
    parent = {g: g for g in set(groups.values())}

    def find(g: str) -> str:
        while parent[g] != g:
            parent[g] = parent[parent[g]]
            g = parent[g]
        return g

    merges = 0
    previous = None
    for path in ordered:
        feature = scene_feature(path)
        if previous is not None:
            a, b = find(groups[previous[0]]), find(groups[path])
            if a != b and float((previous[1] * feature).sum()) >= threshold:
                parent[b] = a
                merges += 1
        previous = (path, feature)
    return {p: find(g) for p, g in groups.items()}, merges


def load_overrides(path: Path) -> dict[tuple[str, int], tuple[str, str]]:
    """CSV image_stem,box_index,source_class,new_class -> {(stem, index): (lớp gốc, lớp mới)}."""
    import csv

    overrides: dict[tuple[str, int], tuple[str, str]] = {}
    with path.open("r", encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(line for line in stream if not line.startswith("#")):
            overrides[(row["image_stem"], int(row["box_index"]))] = (row["source_class"], row["new_class"])
    return overrides


# ----------------------------------------------------------------------------- collect


def collect(
    sources: list[dict], base: Path, class_names: dict[int, str], sources_dir: Path | None = None
) -> tuple[list[Sample], dict[str, SourceStats]]:
    sources_dir = sources_dir or base
    samples: list[Sample] = []
    stats: dict[str, SourceStats] = {}
    seen_digests: set[str] = set()

    for spec in sources:
        name = spec["name"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise ValueError(f"Tên nguồn '{name}' chỉ được chứa chữ, số, '_' hoặc '-' (dùng làm tiền tố tên file)")
        mapping = {str(k): resolve_target(v, class_names) for k, v in (spec.get("map") or {}).items()}
        if not any(v is not None for v in mapping.values()):
            raise ValueError(f"Nguồn '{name}' chưa ánh xạ lớp nào — chạy --inspect rồi điền 'map'")
        rule = spec.get("group", "auto")
        # Lớp nguồn chứa biển thuộc 12 lớp nhưng chưa tách được nhãn (VD P.127 gộp mọi tốc độ):
        # bỏ cả ảnh, vì giữ ảnh mà bỏ nhãn sẽ dạy model coi biển đó là nền.
        exclude = {str(c) for c in spec.get("exclude_if_present") or []}
        conflict = exclude & {k for k, v in mapping.items() if v is not None}
        if conflict:
            raise ValueError(f"Nguồn '{name}': {sorted(conflict)} vừa được ánh xạ vừa nằm trong exclude_if_present")
        st = stats[name] = SourceStats()

        records = list(iter_source(spec, base))
        groups = {p: f"{name}/{group_key(p.stem, rule)}" for p, _ in records}
        if spec.get("scene_merge"):
            groups, st.scene_merges = merge_scenes([p for p, _ in records], groups, float(spec["scene_merge"]))

        overrides: dict[tuple[str, int], tuple[str, str]] = {}
        if spec.get("label_overrides"):
            # Đường dẫn override tính từ thư mục chứa sources.yaml (file CSV được commit trong repo).
            overrides = load_overrides((sources_dir / spec["label_overrides"]).resolve())
        applied = 0

        for image_path, anns in records:
            st.images += 1
            if overrides:
                anns = list(anns)
                for index, (source_class, *coords) in enumerate(anns):
                    override = overrides.get((image_path.stem, index))
                    if override is None:
                        continue
                    if override[0] != source_class:
                        raise ValueError(f"label_overrides lệch dataset: {image_path.stem}#{index} là "
                                         f"'{source_class}', CSV ghi '{override[0]}'")
                    anns[index] = (override[1], *coords)
                    applied += 1
            blocking = {a[0] for a in anns} & exclude
            if blocking:
                st.excluded.update(blocking)
                continue
            digest = file_digest(image_path)
            if digest in seen_digests:
                st.duplicates += 1
                continue
            seen_digests.add(digest)
            sample = Sample(name, image_path, groups[image_path], digest=digest)
            for source_class, x1, y1, x2, y2 in anns:
                target = mapping.get(source_class)
                if target is None:
                    sample.dropped[source_class] += 1
                    continue
                box = clip_box(target, x1, y1, x2, y2)
                if box is None:
                    st.warnings.append(f"{image_path.name}: bbox '{source_class}' rỗng sau khi cắt biên")
                    continue
                sample.boxes.append(box)
                st.mapped[f"{source_class} -> {class_names[target]}"] += 1
            st.dropped.update(sample.dropped)
            samples.append(sample)
        st.overrides_applied = applied
        if applied != len(overrides):
            st.warnings.append(f"label_overrides: chỉ áp dụng {applied}/{len(overrides)} dòng — "
                               "kiểm tra tên ảnh/box_index có khớp phiên bản dataset")
    return samples, stats


def select_backgrounds(samples: list[Sample], ratio: float, seed: int, stats: dict[str, SourceStats]) -> list[Sample]:
    positives = [s for s in samples if s.boxes]
    backgrounds = [s for s in samples if not s.boxes]
    rng = random.Random(seed)
    rng.shuffle(backgrounds)
    keep = int(len(positives) * ratio / (1 - ratio)) if ratio < 1 else len(backgrounds)
    kept = backgrounds[:keep]
    for s in positives:
        stats[s.source].kept_images += 1
    for s in kept:
        stats[s.source].kept_images += 1
        stats[s.source].background_images += 1
    return positives + kept


# ------------------------------------------------------------------------------- split


def _sq_error_delta(n: float, current: float, target: float) -> float:
    """Mức tăng của (current - target)^2 / target khi thêm n — chuẩn hóa theo mục tiêu để split nhỏ
    (test 10%) cũng được phủ đủ lớp hiếm, đồng thời phạt việc dồn cả nhóm lớn vào split nhỏ."""
    return (n * n + 2 * n * (current - target)) / target


def split_groups(samples: list[Sample], ratios: tuple[float, float, float], seed: int) -> dict[str, list[Sample]]:
    """Gán tham lam từng nhóm vào split làm giảm nhiều nhất sai lệch so với mục tiêu
    (số biển từng lớp + số ảnh), xử lý nhóm chứa lớp hiếm trước."""
    groups: dict[str, list[Sample]] = defaultdict(list)
    for s in samples:
        groups[s.group].append(s)

    group_classes = {g: sum((s.class_counts for s in items), Counter()) for g, items in groups.items()}
    total_classes = sum(group_classes.values(), Counter())
    total_images = len(samples)

    order = list(groups)
    random.Random(seed).shuffle(order)
    # Nhóm chứa lớp hiếm & nhóm lớn được xếp trước để chia đều chúng.
    rarity = {g: sum(n / total_classes[c] for c, n in group_classes[g].items()) for g in order}
    order.sort(key=lambda g: (rarity[g], len(groups[g])), reverse=True)

    cur_classes = {sp: Counter() for sp in SPLITS}
    cur_images = Counter()
    assignment: dict[str, list[Sample]] = {sp: [] for sp in SPLITS}
    for g in order:
        best, best_cost = None, None
        for sp, ratio in zip(SPLITS, ratios):
            if ratio <= 0:
                continue
            cost = sum(
                _sq_error_delta(n, cur_classes[sp][c], ratio * total_classes[c])
                for c, n in group_classes[g].items()
            )
            cost += _sq_error_delta(len(groups[g]), cur_images[sp], ratio * total_images)
            if best_cost is None or cost < best_cost:
                best, best_cost = sp, cost
        assignment[best].extend(groups[g])
        cur_classes[best] += group_classes[g]
        cur_images[best] += len(groups[g])
    return assignment


# ------------------------------------------------------------------------------ export


def export(assignment: dict[str, list[Sample]], out: Path) -> None:
    for sp in SPLITS:
        image_dir, label_dir = out / "images" / sp, out / "labels" / sp
        for directory in (image_dir, label_dir):
            if directory.exists():
                shutil.rmtree(directory)  # tránh lẫn file cũ của lần chạy trước sang split khác
            directory.mkdir(parents=True)
        used: Counter = Counter()
        for s in sorted(assignment[sp], key=lambda x: (x.source, x.image_path.name)):
            stem = f"{s.source}__{s.image_path.stem}"
            used[stem] += 1
            if used[stem] > 1:
                stem = f"{stem}__{used[stem]}"
            shutil.copy2(s.image_path, image_dir / f"{stem}{s.image_path.suffix.lower()}")
            lines = [f"{b.class_id} {b.cx:.6f} {b.cy:.6f} {b.w:.6f} {b.h:.6f}" for b in s.boxes]
            (label_dir / f"{stem}.txt").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def data_yaml_text(class_names: dict[int, str], dataset_path: str | None) -> str:
    header = "# Sinh tự động bởi 01_dataset/remap_and_split.py — KHÔNG sửa tay, chạy lại script.\n"
    config: dict[str, Any] = {}
    if dataset_path:
        config["path"] = dataset_path
    config.update({"train": "images/train", "val": "images/val", "test": "images/test",
                   "nc": len(class_names), "names": dict(sorted(class_names.items()))})
    return header + yaml.safe_dump(config, allow_unicode=True, sort_keys=False)


def write_summary(
    path: Path,
    assignment: dict[str, list[Sample]],
    stats: dict[str, SourceStats],
    class_names: dict[int, str],
    args: argparse.Namespace,
) -> list[str]:
    warnings: list[str] = []
    per_split = {sp: sum((s.class_counts for s in assignment[sp]), Counter()) for sp in SPLITS}
    total = sum(per_split.values(), Counter())
    n_images = {sp: len(assignment[sp]) for sp in SPLITS}
    n_groups = {sp: len({s.group for s in assignment[sp]}) for sp in SPLITS}
    all_images = sum(n_images.values())
    widths: dict[int, list[float]] = defaultdict(list)
    for sp in SPLITS:
        for s in assignment[sp]:
            for b in s.boxes:
                widths[b.class_id].append(b.w)

    lines = [
        "# BÁO CÁO PHÂN BỐ DATASET 12 LỚP — CE340 ([K1])",
        "",
        "> Sinh tự động bởi `01_dataset/remap_and_split.py`. Ảnh lưu trên Drive/Roboflow, không đưa lên GitHub.",
        "",
        f"* **Thư mục dataset:** `{args.out.resolve()}`",
        f"* **Tỉ lệ chia (theo nhóm chống rò rỉ frame):** "
        f"{' / '.join(f'{r:.0%}' for r in args.ratios)} — seed `{args.seed}`",
        f"* **Tổng:** `{all_images}` ảnh, `{sum(total.values())}` biển, "
        f"`{sum(n_groups.values())}` nhóm",
        "",
        "## 1. Số ảnh theo split",
        "",
        "| Split | Ảnh | Tỉ lệ thực | Nhóm | Ảnh nền (không biển) |",
        "| :--- | ---: | ---: | ---: | ---: |",
    ]
    for sp in SPLITS:
        background = sum(1 for s in assignment[sp] if not s.boxes)
        share = n_images[sp] / all_images if all_images else 0
        lines.append(f"| {sp} | {n_images[sp]} | {share:.1%} | {n_groups[sp]} | {background} |")

    lines += [
        "",
        "## 2. Số biển báo theo lớp",
        "",
        "`bbox_w` = trung vị bề rộng bbox / bề rộng ảnh; nhân với `imgsz` (160/320) để ước lượng số pixel "
        "của biển khi đưa vào model.",
        "",
        "| ID | Lớp | Train | Val | Test | Tổng | bbox_w | ≈px @160 |",
        "| ---: | :--- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for cid, cname in sorted(class_names.items()):
        med = median(widths[cid]) if widths[cid] else 0.0
        lines.append(
            f"| {cid} | `{cname}` | {per_split['train'][cid]} | {per_split['val'][cid]} | "
            f"{per_split['test'][cid]} | {total[cid]} | {med:.3f} | {med * 160:.0f} |"
        )
        if total[cid] == 0:
            warnings.append(f"Lớp {cid} '{cname}' KHÔNG có mẫu nào")
        elif total[cid] < args.min_instances:
            warnings.append(f"Lớp {cid} '{cname}' chỉ có {total[cid]} biển (< {args.min_instances})")
        for sp, ratio in zip(SPLITS, args.ratios):
            if ratio > 0 and total[cid] > 0 and per_split[sp][cid] == 0:
                warnings.append(f"Lớp {cid} '{cname}' không có mẫu trong split {sp}")

    lines += ["", "## 3. Theo nguồn dữ liệu", ""]
    for name, st in stats.items():
        lines += [
            f"### `{name}`",
            "",
            f"* Ảnh đọc được: `{st.images}` — giữ `{st.kept_images}` (trong đó `{st.background_images}` ảnh nền), "
            f"trùng lặp bị loại `{st.duplicates}`",
            f"* Gộp cảnh liền kề giống nhau (`scene_merge`): `{st.scene_merges}` lần; "
            f"nhãn sửa tay (`label_overrides`): `{st.overrides_applied}` biển",
            "* Ảnh bị loại do chứa lớp chưa tách nhãn (`exclude_if_present`): "
            + (", ".join(f"`{k}`: {v} ảnh" for k, v in st.excluded.most_common()) or "—"),
            "* Ánh xạ: " + (", ".join(f"`{k}`: {v}" for k, v in sorted(st.mapped.items())) or "—"),
            "* Lớp nguồn bị bỏ (không thuộc 12 lớp): "
            + (", ".join(f"`{k}`: {v}" for k, v in st.dropped.most_common()) or "—"),
            "",
        ]
        warnings.extend(f"[{name}] {w}" for w in st.warnings[:20])

    group_sizes = Counter(s.group for sp in SPLITS for s in assignment[sp])
    if group_sizes:
        group, size = group_sizes.most_common(1)[0]
        if size > 0.15 * all_images:
            warnings.append(f"Nhóm '{group}' chiếm {size}/{all_images} ảnh — split có thể lệch, "
                            "xem lại quy tắc 'group' của nguồn")

    lines += ["## 4. Cảnh báo", ""] + ([f"* ⚠️ {w}" for w in warnings] or ["* Không có."]) + [""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return warnings


# ----------------------------------------------------------------------------- inspect


def inspect_sources(sources: list[dict], base: Path) -> str:
    """In tên lớp nguồn + số biển, kèm khung 'map' để điền."""
    out = []
    for spec in sources:
        counter: Counter = Counter()
        images = 0
        for _, anns in iter_source(spec, base):
            images += 1
            counter.update(a[0] for a in anns)
        out.append(f"# Nguồn '{spec['name']}': {images} ảnh, {sum(counter.values())} biển, {len(counter)} lớp")
        out.append(f"- name: {spec['name']}")
        out.append("  map:")
        for cls, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])):
            current = (spec.get("map") or {}).get(cls)
            out.append(f"    {json.dumps(cls, ensure_ascii=False)}: {current if current else 'drop'}  # {n} biển")
        out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------------- CLI


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gộp & chia dataset 12 lớp biển báo CE340 theo nhóm.")
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES, help="File khai báo nguồn & ánh xạ.")
    parser.add_argument("--raw-root", type=Path,
                        help="Gốc của đường dẫn trong sources.yaml (mặc định: thư mục chứa sources.yaml).")
    parser.add_argument("--only", nargs="+", help="Chỉ xử lý các nguồn có tên này.")
    parser.add_argument("--classes", type=Path, default=DEFAULT_CLASSES)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Thư mục dataset đầu ra (để trên Drive).")
    parser.add_argument("--ratios", type=float, nargs=3, default=(0.7, 0.2, 0.1), metavar=("TRAIN", "VAL", "TEST"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--background-ratio", type=float, default=0.1,
                        help="Tỉ lệ tối đa ảnh nền (không còn biển nào sau ánh xạ) trong dataset.")
    parser.add_argument("--min-instances", type=int, default=50, help="Cảnh báo khi lớp có ít biển hơn.")
    parser.add_argument("--data-yaml", type=Path, default=SCRIPT_DIR / "data.yaml",
                        help="data.yaml có 'path' tuyệt đối cho Ultralytics (mặc định 01_dataset/data.yaml).")
    parser.add_argument("--dataset-path", default="/content/ce340_v1",
                        help="Giá trị 'path' ghi vào --data-yaml (nơi giải nén dataset khi train, VD Colab). "
                             "'local' = đường dẫn tuyệt đối của --out.")
    parser.add_argument("--summary", type=Path, default=SCRIPT_DIR / "dataset_summary.md")
    parser.add_argument("--inspect", action="store_true", help="Chỉ liệt kê lớp nguồn & sinh khung ánh xạ.")
    args = parser.parse_args(argv)
    if abs(sum(args.ratios) - 1.0) > 1e-6 or min(args.ratios) < 0:
        parser.error("--ratios phải không âm và cộng lại bằng 1")
    if not 0 <= args.background_ratio < 1:
        parser.error("--background-ratio phải trong [0, 1)")
    return args


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # console Windows cp1252 không in được tiếng Việt
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args(argv)
    config = load_yaml(args.sources) or {}
    sources = config.get("sources") or []
    if args.only:
        sources = [s for s in sources if s.get("name") in set(args.only)]
    else:
        sources = [s for s in sources if s.get("enabled", True)]
    if not sources:
        raise SystemExit(f"Không có nguồn nào đang bật trong {args.sources} — đặt 'enabled: true' "
                         "cho nguồn đã tải về (hoặc dùng --only <tên>)")
    base = (args.raw_root or args.sources.parent).resolve()

    if args.inspect:
        print(inspect_sources(sources, base))
        return 0

    class_names = load_class_names(args.classes)
    samples, stats = collect(sources, base, class_names, sources_dir=args.sources.parent.resolve())
    samples = select_backgrounds(samples, args.background_ratio, args.seed, stats)
    if not any(s.boxes for s in samples):
        raise SystemExit("Không còn biển nào sau ánh xạ — kiểm tra lại 'map' trong sources.yaml")
    assignment = split_groups(samples, tuple(args.ratios), args.seed)

    export(assignment, args.out)
    (args.out / "data.yaml").write_text(data_yaml_text(class_names, None), encoding="utf-8")
    args.data_yaml.parent.mkdir(parents=True, exist_ok=True)
    dataset_path = args.out.resolve().as_posix() if args.dataset_path == "local" else args.dataset_path
    args.data_yaml.write_text(data_yaml_text(class_names, dataset_path), encoding="utf-8")
    warnings = write_summary(args.summary, assignment, stats, class_names, args)
    shutil.copy2(args.summary, args.out / "dataset_summary.md")

    print({sp: len(assignment[sp]) for sp in SPLITS}, "->", args.out.resolve())
    print(f"Báo cáo: {args.summary}  |  data.yaml: {args.data_yaml}")
    for w in warnings:
        print(f"CẢNH BÁO: {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
