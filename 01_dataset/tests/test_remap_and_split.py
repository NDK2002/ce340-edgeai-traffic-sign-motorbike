"""Kiểm thử remap_and_split.py — chạy: python -m pytest 01_dataset/tests -q"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml

MODULE_PATH = Path(__file__).resolve().parents[1] / "remap_and_split.py"
CLASSES = Path(__file__).resolve().parents[1] / "classes.yaml"
spec = importlib.util.spec_from_file_location("remap_and_split", MODULE_PATH)
rs = importlib.util.module_from_spec(spec)
sys.modules["remap_and_split"] = rs
spec.loader.exec_module(rs)

SOURCE_NAMES = ["P.102", "P.123a", "P.103a", "P.127_50", "W.245"]
YOLO_MAP = {"P.102": "cam_di_nguoc_chieu", "P.123a": "cam_re_trai", "P.103a": "drop",
            "P.127_50": "toc_do_50", "W.245": 11}


def write_png(path: Path, seed: int, size: tuple[int, int] = (64, 48)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = np.random.default_rng(seed).integers(0, 255, size=(size[1], size[0], 3), dtype=np.uint8)
    cv2.imwrite(str(path), image)


def make_yolo_source(root: Path, clips: int = 30, frames: int = 4) -> None:
    """Giả lập export Roboflow: frame video '<clip>_mp4-<n>_jpg.rf.<hash>' rải ở cả train/valid."""
    (root).mkdir(parents=True, exist_ok=True)
    (root / "data.yaml").write_text(yaml.safe_dump({"names": SOURCE_NAMES}), encoding="utf-8")
    seed = 0
    for clip in range(clips):
        for frame in range(frames):
            split = "train" if frame % 2 == 0 else "valid"
            stem = f"clip{clip:02d}_mp4-{frame:04d}_jpg.rf.{seed:08x}"
            write_png(root / split / "images" / f"{stem}.jpg", seed)
            cls = clip % len(SOURCE_NAMES)
            lines = [f"{cls} 0.5 0.5 0.2 0.3", "2 0.2 0.2 0.1 0.1"]  # luôn kèm 1 biển P.103a bị bỏ
            if clip == 0 and frame == 0:
                lines.append("1 0.1 0.1 0.3 0.1 0.3 0.3 0.1 0.3")  # nhãn polygon
            label = root / split / "labels" / f"{stem}.txt"
            label.parent.mkdir(parents=True, exist_ok=True)
            label.write_text("\n".join(lines) + "\n", encoding="utf-8")
            seed += 1
    # Ảnh trùng byte: cùng nội dung với ảnh seed 0 nhưng nằm ở split test
    dup = root / "test" / "images" / "copy_of_first.jpg"
    write_png(dup, 0)


def make_coco_source(root: Path, n: int = 12) -> None:
    images, annotations = [], []
    for i in range(n):
        name = f"{i}.png"
        write_png(root / "images" / name, 10_000 + i, size=(100, 50))
        images.append({"id": i, "file_name": name, "width": 100, "height": 50})
        annotations.append({"id": i, "image_id": i, "category_id": 1 if i % 2 == 0 else 4,
                            "bbox": [10, 5, 20, 20]})
    data = {"images": images, "annotations": annotations,
            "categories": [{"id": 1, "name": "No entry"}, {"id": 4, "name": "Max Speed"}]}
    (root / "ann.json").write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    make_yolo_source(tmp_path / "raw" / "rf")
    make_coco_source(tmp_path / "raw" / "zalo")
    sources = {"sources": [
        {"name": "rf", "format": "yolo", "root": "raw/rf", "group": "auto", "map": YOLO_MAP},
        {"name": "zalo", "format": "coco", "images": "raw/zalo/images", "annotations": "raw/zalo/ann.json",
         "group": "stem", "map": {"No entry": "cam_di_nguoc_chieu", "Max Speed": "drop"}},
        {"name": "off", "enabled": False, "format": "yolo", "root": "missing", "map": {}},
    ]}
    (tmp_path / "sources.yaml").write_text(yaml.safe_dump(sources, allow_unicode=True), encoding="utf-8")
    return tmp_path


def run_main(ws: Path, *extra: str) -> int:
    return rs.main([
        "--sources", str(ws / "sources.yaml"), "--classes", str(CLASSES), "--out", str(ws / "out"),
        "--data-yaml", str(ws / "data.yaml"), "--summary", str(ws / "summary.md"), "--min-instances", "1", *extra,
    ])


def read_split(out: Path) -> dict[str, dict[str, list[int]]]:
    result = {}
    for sp in rs.SPLITS:
        result[sp] = {}
        for label in (out / "labels" / sp).glob("*.txt"):
            result[sp][label.stem] = [int(l.split()[0]) for l in label.read_text().splitlines() if l]
            assert any((out / "images" / sp).glob(f"{label.stem}.*")), label
    return result


@pytest.mark.parametrize("stem,rule,expected", [
    ("clip03_mp4-0012_jpg.rf.abc123", "auto", "clip03"),
    ("photo_jpg.rf.0f9e", "auto", "photo"),
    ("IMG_4004-MOV_out0001_png.rf.491614737b2efd25", "auto", "IMG_4004"),  # Roboflow VN v6
    ("IMG_4004-MOV_out0137_png.rf.e105acc15f0593", "auto", "IMG_4004"),
    ("image_12_jpg.rf.abc", "auto", "image_12"),
    ("q1_frame_000123", "auto", "q1"),
    ("IMG_1234", "auto", "IMG_1234"),  # không tự gộp ảnh điện thoại thành 1 nhóm
    ("17", "auto", "17"),
    ("q1_2026-11-20_000123", r"regex:^(.+)_\d+$", "q1_2026-11-20"),
    ("anything", "stem", "anything"),
])
def test_group_key(stem: str, rule: str, expected: str) -> None:
    assert rs.group_key(stem, rule) == expected


def test_resolve_target_accepts_name_id_drop_and_rejects_unknown() -> None:
    names = rs.load_class_names(CLASSES)
    assert rs.resolve_target("cam_re_trai", names) == 1
    assert rs.resolve_target(11, names) == 11
    assert rs.resolve_target("drop", names) is None
    assert rs.resolve_target(None, names) is None
    with pytest.raises(ValueError):
        rs.resolve_target("cam_o_to", names)
    with pytest.raises(ValueError):
        rs.resolve_target(12, names)


def test_end_to_end_mapping_split_and_reports(workspace: Path) -> None:
    assert run_main(workspace) == 0
    splits = read_split(workspace / "out")

    # 1) Không rò rỉ: mỗi clip chỉ nằm trong đúng 1 split
    clip_split: dict[str, set[str]] = {}
    for sp, files in splits.items():
        for stem in files:
            if stem.startswith("rf__"):
                clip_split.setdefault(stem.split("_mp4")[0], set()).add(sp)
    assert len(clip_split) == 30 and all(len(v) == 1 for v in clip_split.values())

    # 2) Ánh xạ đúng & P.103a / Max Speed bị bỏ
    all_ids = Counter(c for files in splits.values() for ids in files.values() for c in ids)
    assert set(all_ids) <= {0, 1, 8, 11}
    rf_ids = [ids for files in splits.values() for stem, ids in files.items() if stem.startswith("rf__clip03_")]
    assert all(ids == [8] for ids in rf_ids)  # clip03 -> P.127_50 -> toc_do_50

    # 3) Ảnh trùng bị loại; ảnh Zalo 'Max Speed' thành ảnh nền và bị giới hạn theo --background-ratio
    names = {stem for files in splits.values() for stem in files}
    assert "rf__copy_of_first" not in names
    total = sum(len(f) for f in splits.values())
    background = sum(1 for files in splits.values() for ids in files.values() if not ids)
    assert background <= 0.1 * total + 1

    # 4) Tỉ lệ chia gần 70/20/10
    shares = {sp: len(splits[sp]) / total for sp in rs.SPLITS}
    assert shares["train"] == pytest.approx(0.7, abs=0.1)
    assert shares["val"] == pytest.approx(0.2, abs=0.1)
    assert shares["test"] == pytest.approx(0.1, abs=0.08)

    # 5) data.yaml & báo cáo
    portable = yaml.safe_load((workspace / "out" / "data.yaml").read_text(encoding="utf-8"))
    assert "path" not in portable and portable["nc"] == 12 and portable["train"] == "images/train"
    shared = yaml.safe_load((workspace / "data.yaml").read_text(encoding="utf-8"))
    assert shared["path"] == "/content/ce340_v1"  # mặc định: nơi giải nén trên Colab
    summary = (workspace / "summary.md").read_text(encoding="utf-8")
    assert "`P.103a`" in summary and "P.123a -> cam_re_trai" in summary


def test_split_balances_rare_classes_without_leaking_groups() -> None:
    import random
    rng = random.Random(7)
    weights = [30, 6, 6, 4, 3, 20, 5, 15, 15, 10, 8, 3]  # lớp 4 & 11 rất hiếm
    samples = []
    for g in range(300):
        cls = rng.choices(range(12), weights)[0]
        for f in range(rng.randint(1, 25)):  # mỗi clip 1–25 frame
            s = rs.Sample("src", Path(f"c{g}_{f}.jpg"), f"src/c{g}")
            s.boxes = [rs.Box(cls, 0.5, 0.5, 0.1, 0.1)]
            samples.append(s)
    assignment = rs.split_groups(samples, (0.7, 0.2, 0.1), seed=42)
    groups = {sp: {s.group for s in assignment[sp]} for sp in rs.SPLITS}
    assert not (groups["train"] & groups["val"] or groups["train"] & groups["test"] or groups["val"] & groups["test"])
    total = Counter(s.boxes[0].class_id for s in samples)
    clips = Counter(s.boxes[0].class_id for s in {s.group: s for s in samples}.values())
    checked = 0
    for c in range(12):
        if clips[c] < 5:  # quá ít clip thì không thể chia 3 split mà không tách frame cùng clip
            continue
        checked += 1
        test_share = sum(1 for s in assignment["test"] if s.boxes[0].class_id == c) / total[c]
        assert 0.03 <= test_share <= 0.25, (c, clips[c], test_share)
    assert checked >= 10


def test_rerun_is_deterministic_and_clears_stale_files(workspace: Path) -> None:
    run_main(workspace)
    first = read_split(workspace / "out")
    stale = workspace / "out" / "labels" / "train" / "stale.txt"
    stale.write_text("0 0.5 0.5 0.1 0.1\n")
    run_main(workspace)
    assert read_split(workspace / "out") == first
    assert not stale.exists()


def test_inspect_lists_source_classes(workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_main(workspace, "--inspect") == 0
    output = capsys.readouterr().out
    assert '"P.103a": drop' in output and '"Max Speed": drop' in output
    assert "- name: off" not in output  # nguồn enabled: false bị bỏ qua


def test_exclude_if_present_drops_whole_images(workspace: Path) -> None:
    config = yaml.safe_load((workspace / "sources.yaml").read_text(encoding="utf-8"))
    rf = config["sources"][0]
    rf["map"] = {**YOLO_MAP, "P.127_50": "drop"}
    rf["exclude_if_present"] = ["P.127_50"]
    (workspace / "sources.yaml").write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    assert run_main(workspace, "--only", "rf") == 0
    stems = {stem for files in read_split(workspace / "out").values() for stem in files}
    assert stems and not any(s.startswith(("rf__clip03_", "rf__clip08_")) for s in stems)  # clip % 5 == 3
    assert "`P.127_50`: 24 ảnh" in (workspace / "summary.md").read_text(encoding="utf-8")

    rf["map"]["P.127_50"] = "toc_do_50"
    (workspace / "sources.yaml").write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="exclude_if_present"):
        run_main(workspace, "--only", "rf")


def test_scene_merge_joins_adjacent_similar_images(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    scene_a = rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)
    scene_b = rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)
    paths = []
    for i, base in enumerate([scene_a, scene_a, scene_a, scene_b, scene_b]):
        noisy = np.clip(base.astype(int) + rng.integers(-8, 8, base.shape), 0, 255).astype(np.uint8)
        path = tmp_path / f"image_{i + 1}.png"
        cv2.imwrite(str(path), noisy)
        paths.append(path)
    groups = {p: f"src/{p.stem}" for p in paths}  # ban đầu mỗi ảnh 1 nhóm
    merged, merges = rs.merge_scenes(paths, groups, threshold=0.6)
    assert merges == 3
    assert len({merged[p] for p in paths[:3]}) == 1 and len({merged[p] for p in paths[3:]}) == 1
    assert merged[paths[0]] != merged[paths[3]]


def test_label_overrides_rename_boxes_and_detect_mismatch(workspace: Path) -> None:
    config = yaml.safe_load((workspace / "sources.yaml").read_text(encoding="utf-8"))
    rf = config["sources"][0]
    # clip00 frame 2 (frame 0 bị loại vì trùng byte với copy_of_first): box 0 là P.102 -> đổi thành W.245
    stem = "clip00_mp4-0002_jpg.rf.00000002"
    (workspace / "ov.csv").write_text(
        "# ghi chú\nimage_stem,box_index,source_class,new_class\n" f"{stem},0,P.102,W.245\n", encoding="utf-8")
    rf["label_overrides"] = "ov.csv"
    (workspace / "sources.yaml").write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    assert run_main(workspace, "--only", "rf") == 0
    labels = {stem: ids for files in read_split(workspace / "out").values() for stem, ids in files.items()}
    assert labels[f"rf__{stem}"][0] == 11

    (workspace / "ov.csv").write_text(f"image_stem,box_index,source_class,new_class\n{stem},0,P.127,X\n",
                                      encoding="utf-8")
    with pytest.raises(ValueError, match="lệch dataset"):
        run_main(workspace, "--only", "rf")


def test_source_without_mapping_fails_loudly(workspace: Path) -> None:
    with pytest.raises(ValueError, match="chưa ánh xạ"):
        run_main(workspace, "--only", "off")


def test_dataset_path_local_writes_absolute_out(workspace):
    assert run_main(workspace, "--dataset-path", "local") == 0
    config = yaml.safe_load((workspace / "data.yaml").read_text(encoding="utf-8"))
    assert Path(config["path"]) == (workspace / "out").resolve()
