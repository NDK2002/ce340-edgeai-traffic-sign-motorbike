"""Kiểm thử augment_weather.py — chạy: python -m pytest 02_augmentation/tests -q"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "augment_weather.py"
spec = importlib.util.spec_from_file_location("augment_weather", MODULE_PATH)
aw = importlib.util.module_from_spec(spec)
sys.modules["augment_weather"] = aw
spec.loader.exec_module(aw)

NUM_CLASSES = 12
BBOXES = [[0.3, 0.3, 0.2, 0.2], [0.7, 0.6, 0.15, 0.25]]
LABELS = [1, 7]


def synthetic_image(h: int = 320, w: int = 320) -> np.ndarray:
    rng = np.random.default_rng(0)
    return rng.integers(60, 200, size=(h, w, 3), dtype=np.uint8)


def test_yolo_label_roundtrip_and_clipping(tmp_path: Path) -> None:
    src = tmp_path / "a.txt"
    src.write_text("1 0.5 0.5 0.2 0.2\n\n7 0.95 0.5 0.2 0.2\n", encoding="utf-8")
    bboxes, labels, warnings = aw.read_yolo_labels(src, NUM_CLASSES)
    assert labels == [1, 7]
    assert bboxes[1] == pytest.approx([0.925, 0.5, 0.15, 0.2])  # bbox vượt biên phải được cắt
    assert len(warnings) == 1

    out = tmp_path / "b.txt"
    aw.write_yolo_labels(out, bboxes, labels)
    again, again_labels, _ = aw.read_yolo_labels(out, NUM_CLASSES)
    assert again_labels == labels
    assert np.allclose(again, bboxes, atol=1e-6)


def test_missing_label_file_means_background(tmp_path: Path) -> None:
    assert aw.read_yolo_labels(tmp_path / "none.txt", NUM_CLASSES) == ([], [], [])


def test_rejects_class_outside_contract(tmp_path: Path) -> None:
    src = tmp_path / "a.txt"
    src.write_text("12 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ngoài khoảng"):
        aw.read_yolo_labels(src, NUM_CLASSES)


@pytest.mark.parametrize("scenario", aw.SCENARIOS)
def test_scenarios_keep_every_bbox_and_change_pixels(scenario: str) -> None:
    image = synthetic_image()
    augmenter = aw.WeatherAugmenter(NUM_CLASSES, seed=1)
    for _ in range(15):
        result, attempts, worst, error = augmenter.augment(image, BBOXES, LABELS, scenario)
        assert error is None and result is not None
        assert result.shape == image.shape and result.dtype == np.uint8
        assert not np.array_equal(result, image)
        assert worst < aw.MAX_OCCLUSION


def test_occlusion_hits_every_sign_below_limit() -> None:
    image = synthetic_image()
    augmenter = aw.WeatherAugmenter(NUM_CLASSES, seed=3)
    transform = augmenter._transform("occlusion", image.shape)
    for _ in range(50):
        out = transform(image=image, mask=np.zeros(image.shape[:2], np.uint8), bboxes=BBOXES, class_labels=LABELS)
        fractions = aw.occlusion_fractions(out["mask"], BBOXES)
        assert all(0.0 < f < aw.MAX_OCCLUSION for f in fractions), fractions


def test_validate_output_detects_failures() -> None:
    mask = np.zeros((100, 100), np.uint8)
    assert aw.validate_output(BBOXES, LABELS, BBOXES, LABELS, mask) is None
    assert "mất nhãn" in aw.validate_output(BBOXES, LABELS, BBOXES[:1], LABELS[:1], mask)
    one_px = [[b[0] + 0.01, *b[1:]] for b in BBOXES]  # 1px trên ảnh 100px: làm tròn, chấp nhận
    assert aw.validate_output(BBOXES, LABELS, one_px, LABELS, mask) is None
    shifted = [[b[0] + 0.03, *b[1:]] for b in BBOXES]  # 3px: lệch thật
    assert "lệch" in aw.validate_output(BBOXES, LABELS, shifted, LABELS, mask)
    mask[20:40, 20:40] = 255  # che toàn bộ bbox đầu tiên
    assert "che" in aw.validate_output(BBOXES, LABELS, BBOXES, LABELS, mask)


def test_cli_end_to_end_on_mock(tmp_path: Path) -> None:
    out, preview = tmp_path / "out", tmp_path / "preview"
    code = aw.main(["--out", str(out), "--preview-dir", str(preview), "--preview", "8"])
    assert code == 0
    images = sorted((out / "images").glob("*.jpg"))
    labels = sorted((out / "labels").glob("*.txt"))
    assert len(images) == len(labels) == 5 * len(aw.SCENARIOS)
    assert len(list(preview.glob("mock_*.jpg"))) == 8
    assert (preview / "_grid_overview.jpg").is_file()
    assert (out / "augment_summary.json").is_file()
