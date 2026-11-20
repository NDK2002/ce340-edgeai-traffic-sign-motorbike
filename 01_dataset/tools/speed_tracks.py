"""Tách lớp gộp P.127 (biển tốc độ tối đa) thành 40/50/60 theo track — hỗ trợ [K1].

Dataset Roboflow VN gộp mọi tốc độ vào một lớp P.127, và nhiều frame có 2–5 biển tốc độ cạnh nhau,
nên không gán theo clip được. Công cụ này:

  build  Ghép bbox P.127 qua các frame liên tiếp của cùng cảnh thành "track" (Hungarian theo khoảng
         cách tâm / kích thước bbox), xuất tracks.csv + bảng ảnh review (mỗi hàng 1 track, ảnh lớn
         nhất đầu hàng) để người gán đọc số tốc độ MỘT lần cho cả track.
  apply  Đọc track_labels.yaml (track_id -> 30/40/50/60/80/... | unknown | mixed) và sinh
         label_overrides CSV cho remap_and_split.py (P.127 -> P.127_<tốc độ>).

Ví dụ (từ thư mục gốc repo):
    python 01_dataset/tools/speed_tracks.py build --root 01_dataset/raw/roboflow_vn --out 01_dataset/overrides/p127
    python 01_dataset/tools/speed_tracks.py apply --out 01_dataset/overrides/p127 \
        --csv 01_dataset/overrides/roboflow_vn_p127.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
import yaml
from scipy.optimize import linear_sum_assignment

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import remap_and_split as rs  # noqa: E402

MAX_MATCH_COST = 1.5  # dịch tâm tối đa (đơn vị: kích thước bbox) giữa 2 frame liên tiếp
MAX_SIZE_RATIO = 2.0
TILE = 64
TILES_PER_ROW = 10
ROWS_PER_SHEET = 16


def load_boxes(root: Path, class_name: str, scene_threshold: float):
    """[(stem, box_index, (cx, cy, w, h), image_path)] theo cảnh, đã sắp theo thứ tự frame."""
    records = list(rs.read_yolo_source(root))
    groups = {p: rs.group_key(p.stem, "auto") for p, _ in records}
    groups, _ = rs.merge_scenes([p for p, _ in records], groups, scene_threshold)
    per_scene: dict[str, list] = defaultdict(list)
    for path, anns in records:
        frame = []
        for index, (name, x1, y1, x2, y2) in enumerate(anns):
            if name == class_name:
                frame.append((path.stem, index, ((x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1), path))
        if frame:
            per_scene[groups[path]].append(frame)
    for frames in per_scene.values():
        frames.sort(key=lambda f: rs.natural_key(f[0][0]))
    return per_scene


def link_tracks(per_scene) -> list[list]:
    tracks: list[list] = []
    for frames in per_scene.values():
        active: list[int] = []  # chỉ số track đang mở, khớp với các box của frame trước
        previous: list = []
        for frame in frames:
            assigned = [-1] * len(frame)
            if previous:
                cost = np.full((len(previous), len(frame)), 1e6)
                for i, (_, _, (px, py, pw, ph), _) in enumerate(previous):
                    for j, (_, _, (cx, cy, cw, ch), _) in enumerate(frame):
                        size = (pw + ph + cw + ch) / 4
                        ratio = max(pw * ph, cw * ch) / max(1e-9, min(pw * ph, cw * ch))
                        if ratio <= MAX_SIZE_RATIO ** 2:
                            cost[i, j] = np.hypot(px - cx, py - cy) / max(size, 1e-6)
                rows, cols = linear_sum_assignment(cost)
                for i, j in zip(rows, cols):
                    if cost[i, j] <= MAX_MATCH_COST:
                        assigned[j] = active[i]
            new_active = []
            for j, box in enumerate(frame):
                if assigned[j] < 0:
                    tracks.append([])
                    assigned[j] = len(tracks) - 1
                tracks[assigned[j]].append(box)
                new_active.append(assigned[j])
            active, previous = new_active, frame
    return tracks


def crop(path: Path, box) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    h, w = image.shape[:2]
    cx, cy, bw, bh = box
    x1, y1 = max(0, int((cx - bw / 2) * w)), max(0, int((cy - bh / 2) * h))
    x2, y2 = min(w, int((cx + bw / 2) * w) + 1), min(h, int((cy + bh / 2) * h) + 1)
    return cv2.resize(image[y1:y2, x1:x2], (TILE, TILE), interpolation=cv2.INTER_CUBIC)


def build(args: argparse.Namespace) -> None:
    per_scene = load_boxes(args.root, args.class_name, args.scene_merge)
    tracks = link_tracks(per_scene)
    # Track có ảnh lớn nhất lên trước -> dễ đọc số
    tracks.sort(key=lambda t: -max(b[2][2] * b[2][3] for b in t))
    args.out.mkdir(parents=True, exist_ok=True)

    with (args.out / "tracks.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["track_id", "image_stem", "box_index", "width"])
        for tid, track in enumerate(tracks):
            for stem, index, box, _ in track:
                writer.writerow([tid, stem, index, f"{box[2]:.4f}"])

    labels_path = args.out / "track_labels.yaml"
    if not labels_path.exists():
        labels_path.write_text(
            "# Tốc độ đọc được cho từng track (30/40/50/60/80/...), 'unknown' nếu không đọc được,\n"
            "# 'mixed' nếu 1 hàng chứa nhiều số khác nhau (track ghép nhầm).\n"
            + "".join(f"{tid}: \n" for tid in range(len(tracks))), encoding="utf-8")

    for sheet_start in range(0, len(tracks), ROWS_PER_SHEET):
        rows = []
        for tid in range(sheet_start, min(len(tracks), sheet_start + ROWS_PER_SHEET)):
            track = sorted(tracks[tid], key=lambda b: -b[2][2] * b[2][3])
            # Ảnh lớn nhất + rải đều phần còn lại để thấy cả đầu lẫn cuối track
            picks = np.unique(np.linspace(0, len(track) - 1, min(TILES_PER_ROW, len(track))).round().astype(int))
            tiles = [crop(track[i][3], track[i][2]) for i in picks]
            tiles += [np.zeros((TILE, TILE, 3), np.uint8)] * (TILES_PER_ROW - len(tiles))
            label = np.full((TILE, 96, 3), 40, np.uint8)
            cv2.putText(label, f"#{tid}", (4, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 255), 2)
            cv2.putText(label, f"n={len(track)}", (4, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
            rows.append(np.hstack([label, *tiles]))
        sheet = np.vstack(rows)
        cv2.imwrite(str(args.out / f"sheet_{sheet_start // ROWS_PER_SHEET:02d}.jpg"), sheet,
                    [cv2.IMWRITE_JPEG_QUALITY, 90])
    boxes = sum(len(t) for t in tracks)
    print(f"{len(tracks)} track, {boxes} bbox '{args.class_name}' -> {args.out}")


def apply(args: argparse.Namespace) -> None:
    labels = yaml.safe_load((args.out / "track_labels.yaml").read_text(encoding="utf-8")) or {}
    missing = [tid for tid, v in labels.items() if v in (None, "")]
    if missing:
        raise SystemExit(f"Còn {len(missing)} track chưa gán nhãn, VD {missing[:10]}")
    rows = []
    with (args.out / "tracks.csv").open("r", encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            value = str(labels[int(row["track_id"])]).strip()
            rows.append((row["image_stem"], int(row["box_index"]), args.class_name, f"{args.class_name}_{value}"))
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    with args.csv.open("w", encoding="utf-8", newline="") as stream:
        stream.write(f"# Sinh bởi 01_dataset/tools/speed_tracks.py apply từ {args.out.as_posix()}/track_labels.yaml\n")
        writer = csv.writer(stream)
        writer.writerow(["image_stem", "box_index", "source_class", "new_class"])
        writer.writerows(sorted(rows))
    counts = defaultdict(int)
    for *_, new in rows:
        counts[new] += 1
    print(dict(sorted(counts.items())), "->", args.csv)


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--root", type=Path, required=True, help="Nguồn YOLO (thư mục chứa data.yaml).")
    b.add_argument("--scene-merge", type=float, default=0.6)
    a = sub.add_parser("apply")
    a.add_argument("--csv", type=Path, required=True, help="File label_overrides xuất ra.")
    for p in (b, a):
        p.add_argument("--out", type=Path, required=True, help="Thư mục làm việc (tracks.csv, sheet, nhãn).")
        p.add_argument("--class-name", default="P.127")
    args = parser.parse_args()
    build(args) if args.command == "build" else apply(args)


if __name__ == "__main__":
    main()
