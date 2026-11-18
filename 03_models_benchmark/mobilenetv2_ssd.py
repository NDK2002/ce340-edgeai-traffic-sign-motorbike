"""Small TensorFlow SSD detector with a MobileNetV2 backbone.

The module keeps dataset parsing, anchor matching, training, and evaluation
local to the project so the Keras model can be passed to the TensorFlow/TFLite
optimization branch.
"""

from __future__ import annotations

import json
import math
import os
import csv
from pathlib import Path
from typing import Any
from importlib.metadata import version as package_version

# TFMOT currently integrates with Keras 2. Set this before importing TensorFlow
# so the saved `.keras` model uses the same Keras API expected by the optimizer.
os.environ.setdefault("TF_USE_LEGACY_KERAS", "1")

import numpy as np
import yaml
from PIL import Image


ANCHORS_PER_CELL = 4
CENTER_VARIANCE = 0.1
SIZE_VARIANCE = 0.2


def load_data_config(data_yaml: Path) -> tuple[dict[str, Any], Path, list[str]]:
    data_yaml = data_yaml.expanduser().resolve()
    config = yaml.safe_load(data_yaml.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or int(config.get("nc", 0)) < 1 or "names" not in config:
        raise ValueError(f"data.yaml phải khai báo nc và names hợp lệ: {data_yaml}")
    root = Path(config.get("path") or data_yaml.parent)
    if not root.is_absolute():
        root = (data_yaml.parent / root).resolve()
    names_config = config["names"]
    if isinstance(names_config, dict):
        names = [str(names_config[i]) for i in range(int(config["nc"]))]
    else:
        names = [str(name) for name in names_config]
    if len(names) != int(config["nc"]):
        raise ValueError("Số tên lớp trong data.yaml không khớp nc.")
    return config, root, names


def _split_images(split_value: Any, root: Path) -> list[Path]:
    if isinstance(split_value, list):
        entries = split_value
    else:
        entries = [split_value]
    paths: list[Path] = []
    image_suffixes = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    for entry in entries:
        path = Path(str(entry))
        if not path.is_absolute():
            path = root / path
        if path.is_dir():
            paths.extend(p for p in path.rglob("*") if p.suffix.lower() in image_suffixes)
        elif path.is_file() and path.suffix.lower() in image_suffixes:
            paths.append(path)
        elif path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                item = Path(line.strip())
                paths.append(item if item.is_absolute() else (root / item).resolve())
        else:
            raise FileNotFoundError(f"Không tìm thấy split dữ liệu: {path}")
    return sorted(set(path.resolve() for path in paths))


def _label_path(image_path: Path) -> Path:
    parts = list(image_path.parts)
    image_index = next((i for i, part in enumerate(parts) if part.lower() == "images"), None)
    if image_index is not None:
        parts[image_index] = "labels"
        return Path(*parts).with_suffix(".txt")
    return image_path.parent.parent / "labels" / f"{image_path.stem}.txt"


def read_yolo_annotation(image_path: Path, num_classes: int) -> np.ndarray:
    label_path = _label_path(image_path)
    if not label_path.exists():
        return np.zeros((0, 5), dtype=np.float32)
    rows = []
    for line_number, line in enumerate(label_path.read_text(encoding="utf-8").splitlines(), start=1):
        fields = line.split()
        if len(fields) != 5:
            raise ValueError(f"Nhãn YOLO cần đúng 5 cột tại {label_path}:{line_number}")
        values = np.asarray([float(value) for value in fields], dtype=np.float64)
        if not np.isfinite(values).all():
            raise ValueError(f"Nhãn có giá trị không hữu hạn tại {label_path}:{line_number}")
        cls, cx, cy, width, height = values
        box_inside_image = (
            cx - width / 2 >= 0
            and cy - height / 2 >= 0
            and cx + width / 2 <= 1
            and cy + height / 2 <= 1
        )
        if (
            cls != int(cls)
            or not 0 <= int(cls) < num_classes
            or width <= 0
            or height <= 0
            or not box_inside_image
        ):
            raise ValueError(f"Nhãn YOLO ngoài phạm vi tại {label_path}:{line_number}: {line}")
        rows.append((int(cls), cx, cy, width, height))
    return np.asarray(rows, dtype=np.float32).reshape((-1, 5))


def _corners(boxes: np.ndarray) -> np.ndarray:
    center = boxes[:, :2]
    half = boxes[:, 2:] / 2
    return np.concatenate((center - half, center + half), axis=1)


def _iou_matrix(boxes_a: np.ndarray, boxes_b: np.ndarray) -> np.ndarray:
    if not len(boxes_a) or not len(boxes_b):
        return np.zeros((len(boxes_a), len(boxes_b)), dtype=np.float32)
    a, b = _corners(boxes_a), _corners(boxes_b)
    top_left = np.maximum(a[:, None, :2], b[None, :, :2])
    bottom_right = np.minimum(a[:, None, 2:], b[None, :, 2:])
    extent = np.maximum(bottom_right - top_left, 0)
    intersection = extent[..., 0] * extent[..., 1]
    area_a = np.prod(np.maximum(a[:, 2:] - a[:, :2], 0), axis=1)
    area_b = np.prod(np.maximum(b[:, 2:] - b[:, :2], 0), axis=1)
    return intersection / np.maximum(area_a[:, None] + area_b[None, :] - intersection, 1e-8)


def _iou_xyxy(box: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    if not len(boxes):
        return np.zeros((0,), dtype=np.float32)
    top_left = np.maximum(box[None, :2], boxes[:, :2])
    bottom_right = np.minimum(box[None, 2:], boxes[:, 2:])
    extent = np.maximum(bottom_right - top_left, 0)
    intersection = extent[:, 0] * extent[:, 1]
    area_a = max(float(box[2] - box[0]), 0.0) * max(float(box[3] - box[1]), 0.0)
    area_b = np.maximum(boxes[:, 2] - boxes[:, 0], 0) * np.maximum(boxes[:, 3] - boxes[:, 1], 0)
    return intersection / np.maximum(area_a + area_b - intersection, 1e-8)


def build_anchors(feature_shapes: list[tuple[int, int]]) -> np.ndarray:
    scales = np.linspace(0.08, 0.90, len(feature_shapes) + 1, dtype=np.float32)
    anchors: list[tuple[float, float, float, float]] = []
    for level, (height, width) in enumerate(feature_shapes):
        scale = float(scales[level])
        next_scale = float(scales[level + 1])
        extra = math.sqrt(scale * next_scale)
        sizes = (
            (scale, scale),
            (extra, extra),
            (scale * math.sqrt(2), scale / math.sqrt(2)),
            (scale / math.sqrt(2), scale * math.sqrt(2)),
        )
        for row in range(height):
            for col in range(width):
                center_x, center_y = (col + 0.5) / width, (row + 0.5) / height
                anchors.extend((center_x, center_y, box_w, box_h) for box_w, box_h in sizes)
    return np.asarray(anchors, dtype=np.float32)


def build_model(num_classes: int, imgsz: int, backbone_weights: str | None = "imagenet"):
    import tensorflow as tf

    image = tf.keras.Input(shape=(imgsz, imgsz, 3), name="image_normalized_minus1_to_1")
    backbone = tf.keras.applications.MobileNetV2(
        input_shape=(imgsz, imgsz, 3), include_top=False, weights=backbone_weights, input_tensor=image
    )
    feature_names = ("block_4_expand_relu", "block_6_expand_relu", "block_13_expand_relu")
    features = [backbone.get_layer(name).output for name in feature_names]
    extra = features[-1]
    for i in range(3):
        extra = tf.keras.layers.Conv2D(128, 1, activation="relu", name=f"ssd_extra_{i}_reduce")(extra)
        extra = tf.keras.layers.Conv2D(
            256, 3, strides=2, padding="same", activation="relu", name=f"ssd_extra_{i}_down"
        )(extra)
        features.append(extra)

    class_outputs, box_outputs, feature_shapes = [], [], []
    for level, feature in enumerate(features):
        shape = feature.shape
        feature_shapes.append((int(shape[1]), int(shape[2])))
        classes = tf.keras.layers.Conv2D(
            ANCHORS_PER_CELL * (num_classes + 1), 3, padding="same", name=f"ssd_class_{level}"
        )(feature)
        boxes = tf.keras.layers.Conv2D(
            ANCHORS_PER_CELL * 4, 3, padding="same", name=f"ssd_box_{level}"
        )(feature)
        class_outputs.append(tf.keras.layers.Reshape((-1, num_classes + 1))(classes))
        box_outputs.append(tf.keras.layers.Reshape((-1, 4))(boxes))

    class_logits = tf.keras.layers.Concatenate(axis=1, name="class_logits")(class_outputs)
    box_offsets = tf.keras.layers.Concatenate(axis=1, name="box_offsets")(box_outputs)
    model = tf.keras.Model(image, (class_logits, box_offsets), name="mobilenetv2_ssd")
    anchors = build_anchors(feature_shapes)
    if model.output[0].shape[1] != len(anchors):
        raise RuntimeError("Số SSD anchors không khớp số đầu ra của model.")
    return model, anchors, backbone


def match_targets(annotations: np.ndarray, anchors: np.ndarray, num_classes: int) -> tuple[np.ndarray, np.ndarray]:
    target_classes = np.full((len(anchors),), num_classes, dtype=np.int32)  # last id is background
    target_offsets = np.zeros((len(anchors), 4), dtype=np.float32)
    if not len(annotations):
        return target_classes, target_offsets
    gt_classes = annotations[:, 0].astype(np.int32)
    gt_boxes = annotations[:, 1:5]
    overlaps = _iou_matrix(anchors, gt_boxes)
    matched_gt = np.argmax(overlaps, axis=1)
    positive = overlaps.max(axis=1) >= 0.5
    forced_anchors: set[int] = set()
    gt_order = np.argsort(overlaps.max(axis=0))[::-1]
    for gt_id in gt_order:
        for anchor_id in np.argsort(overlaps[:, gt_id])[::-1]:
            if int(anchor_id) not in forced_anchors:
                forced_anchors.add(int(anchor_id))
                positive[anchor_id] = True
                matched_gt[anchor_id] = gt_id
                break
    target_classes[positive] = gt_classes[matched_gt[positive]]
    matched = gt_boxes[matched_gt[positive]]
    prior = anchors[positive]
    target_offsets[positive, :2] = (matched[:, :2] - prior[:, :2]) / (prior[:, 2:] * CENTER_VARIANCE)
    target_offsets[positive, 2:] = np.log(np.maximum(matched[:, 2:] / prior[:, 2:], 1e-6)) / SIZE_VARIANCE
    return target_classes, target_offsets


def _dataset(data_yaml: Path, split: str, imgsz: int, num_classes: int, anchors: np.ndarray):
    import tensorflow as tf

    config, root, _ = load_data_config(data_yaml)
    if split not in config or not config[split]:
        raise ValueError(f"data.yaml không có split '{split}'.")
    image_paths = _split_images(config[split], root)
    if not image_paths:
        raise ValueError(f"Split '{split}' không có ảnh: {data_yaml}")

    def generate():
        for image_path in image_paths:
            with Image.open(image_path) as image:
                pixels = np.asarray(image.convert("RGB").resize((imgsz, imgsz)), dtype=np.float32)
            pixels = pixels / 127.5 - 1.0
            annotations = read_yolo_annotation(image_path, num_classes)
            classes, offsets = match_targets(annotations, anchors, num_classes)
            yield pixels, classes, offsets

    signature = (
        tf.TensorSpec((imgsz, imgsz, 3), tf.float32),
        tf.TensorSpec((len(anchors),), tf.int32),
        tf.TensorSpec((len(anchors), 4), tf.float32),
    )
    return tf.data.Dataset.from_generator(generate, output_signature=signature), image_paths


def train_model(
    data_yaml: Path,
    output_dir: Path,
    imgsz: int = 320,
    epochs: int = 100,
    batch: int = 16,
    seed: int = 42,
    learning_rate: float = 1e-4,
    backbone_weights: str | None = "imagenet",
    freeze_backbone: bool = False,
) -> Path:
    import tensorflow as tf

    tf.keras.utils.set_random_seed(seed)
    config, _, names = load_data_config(data_yaml)
    num_classes = int(config["nc"])
    model, anchors, backbone = build_model(num_classes, imgsz, backbone_weights)
    backbone.trainable = not freeze_backbone
    optimizer = tf.keras.optimizers.Adam(learning_rate=learning_rate)
    train_data, image_paths = _dataset(data_yaml, "train", imgsz, num_classes, anchors)
    train_data = train_data.shuffle(
        max(len(image_paths), 1), seed=seed, reshuffle_each_iteration=True
    ).batch(batch)

    @tf.function
    def train_step(images, target_classes, target_offsets):
        with tf.GradientTape() as tape:
            class_logits, box_offsets = model(images, training=True)
            class_loss = tf.nn.sparse_softmax_cross_entropy_with_logits(
                labels=target_classes, logits=class_logits
            )
            positive = target_classes < num_classes
            negative = tf.logical_not(positive)
            num_positive = tf.reduce_sum(tf.cast(positive, tf.int32), axis=1)
            rank = tf.argsort(tf.argsort(-class_loss, axis=1), axis=1)
            keep_negatives = tf.maximum(3 * num_positive, 32)
            selected_negative = tf.logical_and(negative, rank < keep_negatives[:, None])
            selected = tf.logical_or(positive, selected_negative)
            normalizer = tf.maximum(tf.cast(num_positive, tf.float32), 1.0)
            classification = tf.reduce_sum(tf.where(selected, class_loss, 0.0), axis=1) / normalizer

            delta = tf.abs(target_offsets - box_offsets)
            smooth_l1 = tf.where(delta < 1.0, 0.5 * tf.square(delta), delta - 0.5)
            localization = tf.reduce_sum(tf.reduce_sum(smooth_l1, axis=-1) * tf.cast(positive, tf.float32), axis=1)
            localization /= normalizer
            loss = tf.reduce_mean(classification + localization)
        gradients = tape.gradient(loss, model.trainable_variables)
        optimizer.apply_gradients((g, v) for g, v in zip(gradients, model.trainable_variables) if g is not None)
        return loss

    output_dir.mkdir(parents=True, exist_ok=True)
    epoch_losses = []
    for epoch in range(epochs):
        losses = [float(train_step(images, classes, offsets).numpy()) for images, classes, offsets in train_data]
        epoch_loss = float(np.mean(losses)) if losses else 0.0
        epoch_losses.append(epoch_loss)
        print(f"Epoch {epoch + 1}/{epochs}: loss={epoch_loss:.5f}")

    keras_path = output_dir / "mobilenetv2_ssd.keras"
    saved_model_path = output_dir / "saved_model"
    if saved_model_path.exists():
        raise FileExistsError(f"SavedModel đã tồn tại, hãy đổi --name để giữ artifact cũ: {saved_model_path}")
    model.save(keras_path)

    @tf.function(input_signature=[tf.TensorSpec((None, imgsz, imgsz, 3), tf.float32, name="image")])
    def serving(images):
        class_logits, box_offsets = model(images, training=False)
        return {"class_logits": class_logits, "box_offsets": box_offsets}

    tf.saved_model.save(model, str(saved_model_path), signatures={"serving_default": serving})
    (output_dir / "training_log.json").write_text(
        json.dumps(
            {
                "model": "MobileNetV2-SSD",
                "data_yaml": str(data_yaml.resolve()),
                "imgsz": imgsz,
                "epochs": epochs,
                "batch": batch,
                "seed": seed,
                "backbone_weights": backbone_weights,
                "freeze_backbone": freeze_backbone,
                "epoch_loss": epoch_losses,
                "tensorflow_version": package_version("tensorflow"),
                "tf_keras_version": package_version("tf-keras"),
                "input_preprocessing": "RGB float32 scaled to [-1, 1]",
                "keras_model": str(keras_path.resolve()),
                "saved_model": str(saved_model_path.resolve()),
                "class_names": names,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return keras_path


def _decode_predictions(
    class_logits,
    box_offsets,
    anchors,
    num_classes,
    threshold=0.001,
    top_k=100,
    nms_iou=0.7,
    max_det=300,
):
    import tensorflow as tf

    priors = tf.convert_to_tensor(anchors, dtype=tf.float32)
    centers = box_offsets[:, :2] * priors[:, 2:] * CENTER_VARIANCE + priors[:, :2]
    sizes = tf.exp(tf.clip_by_value(box_offsets[:, 2:] * SIZE_VARIANCE, -10.0, 10.0)) * priors[:, 2:]
    boxes = tf.concat((centers - sizes / 2, centers + sizes / 2), axis=-1)
    boxes = tf.clip_by_value(boxes, 0.0, 1.0)
    scores = tf.nn.softmax(class_logits, axis=-1)[:, :num_classes]
    detections = []
    for class_id in range(num_classes):
        class_scores = scores[:, class_id]
        candidates = tf.where(class_scores >= threshold)[:, 0]
        selected_scores = tf.gather(class_scores, candidates)
        selected_boxes = tf.gather(boxes, candidates)
        # TensorFlow NMS expects [y1, x1, y2, x2].
        yxyx = tf.gather(selected_boxes, [1, 0, 3, 2], axis=1)
        keep = tf.image.non_max_suppression(yxyx, selected_scores, top_k, iou_threshold=nms_iou)
        for index in keep.numpy().tolist():
            detections.append(
                (class_id, float(selected_scores[index].numpy()), selected_boxes[index].numpy().tolist())
            )
    return sorted(detections, key=lambda item: item[1], reverse=True)[:max_det]


def _match_class_predictions(predictions, ground_truths, class_id, iou_threshold):
    matched_by_image: dict[int, set[int]] = {}
    true_positives, false_positives = [], []
    for score, image_id, box in predictions:
        annotations = ground_truths[image_id]
        gt_ids = np.where(annotations[:, 0].astype(int) == class_id)[0]
        gt_boxes = annotations[gt_ids, 1:5]
        overlaps = _iou_xyxy(box, _corners(gt_boxes)) if len(gt_boxes) else np.zeros((0,))
        best = int(np.argmax(overlaps)) if len(overlaps) else -1
        used = matched_by_image.setdefault(image_id, set())
        is_true_positive = (
            best >= 0
            and overlaps[best] >= iou_threshold
            and int(gt_ids[best]) not in used
        )
        true_positives.append(1 if is_true_positive else 0)
        false_positives.append(0 if is_true_positive else 1)
        if is_true_positive:
            used.add(int(gt_ids[best]))
    return np.asarray(true_positives, dtype=bool), np.asarray(false_positives, dtype=bool)


def _average_precision_101(true_positives: np.ndarray, false_positives: np.ndarray, num_ground_truth: int) -> float:
    if num_ground_truth <= 0:
        return 0.0
    tp_cumulative = np.cumsum(true_positives)
    fp_cumulative = np.cumsum(false_positives)
    recall = tp_cumulative / num_ground_truth
    precision = tp_cumulative / np.maximum(tp_cumulative + fp_cumulative, 1e-8)
    points = []
    for recall_point in np.linspace(0.0, 1.0, 101):
        eligible = precision[recall >= recall_point]
        points.append(float(np.max(eligible)) if len(eligible) else 0.0)
    return float(np.mean(points))


def evaluate_model(
    model_path: Path,
    data_yaml: Path,
    output_dir: Path,
    imgsz: int = 320,
    split: str = "val",
    confidence: float | None = None,
) -> dict[str, Any]:
    import tensorflow as tf

    config, _, names = load_data_config(data_yaml)
    num_classes = int(config["nc"])
    if split not in ("val", "test"):
        raise ValueError("split phải là 'val' hoặc 'test'.")
    if split == "test" and confidence is None:
        raise ValueError("Khi đánh giá split=test, truyền --conf đã chọn trên validation để tránh tune trên test.")
    if confidence is not None and not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence phải nằm trong [0, 1].")
    loaded = tf.keras.models.load_model(model_path)
    feature_shapes = [
        (
            int(loaded.get_layer(f"ssd_class_{level}").output.shape[1]),
            int(loaded.get_layer(f"ssd_class_{level}").output.shape[2]),
        )
        for level in range(6)
    ]
    anchors = build_anchors(feature_shapes)
    if loaded.output[0].shape[1] != len(anchors):
        raise ValueError("Model anchor count không khớp với imgsz đang dùng để evaluate.")
    dataset, image_paths = _dataset(data_yaml, split, imgsz, num_classes, anchors)
    ground_truths: list[np.ndarray] = []
    predictions: list[list[tuple[int, float, list[float]]]] = []
    for index, (pixels, _, _) in enumerate(dataset):
        image_path = image_paths[index]
        annotations = read_yolo_annotation(image_path, num_classes)
        ground_truths.append(annotations)
        logits, offsets = loaded(pixels[None, ...], training=False)
        predictions.append(
            _decode_predictions(logits[0], offsets[0], anchors, num_classes, threshold=0.001)
        )

    class_ap50: list[float] = []
    class_ap50_95: list[float] = []
    class_operating_curves: list[tuple[np.ndarray, np.ndarray, np.ndarray, int]] = []
    confusion = np.zeros((num_classes + 1, num_classes + 1), dtype=np.int64)
    for class_id in range(num_classes):
        class_gt = sum(int(np.sum(annotations[:, 0].astype(int) == class_id)) for annotations in ground_truths)
        if class_gt == 0:
            continue
        predictions_for_class = []
        for image_id, detections in enumerate(predictions):
            for pred_class, score, box in detections:
                if pred_class == class_id:
                    predictions_for_class.append((score, image_id, np.asarray(box, dtype=np.float32)))
        predictions_for_class.sort(key=lambda row: row[0], reverse=True)
        tp50, fp50 = _match_class_predictions(predictions_for_class, ground_truths, class_id, 0.5)
        class_ap50.append(_average_precision_101(tp50, fp50, class_gt))
        class_operating_curves.append(
            (np.asarray([item[0] for item in predictions_for_class]), tp50, fp50, class_gt)
        )
        for iou_threshold in np.linspace(0.5, 0.95, 10):
            tp_iou, fp_iou = _match_class_predictions(
                predictions_for_class, ground_truths, class_id, float(iou_threshold)
            )
            class_ap50_95.append(_average_precision_101(tp_iou, fp_iou, class_gt))

    confidence_grid = np.linspace(0.0, 1.0, 1000)
    per_class_precision, per_class_recall, per_class_f1 = [], [], []
    for scores, true_positives, false_positives, class_gt in class_operating_curves:
        selected = scores[:, None] >= confidence_grid[None, :]
        tp = np.sum(selected & true_positives[:, None], axis=0)
        fp = np.sum(selected & false_positives[:, None], axis=0)
        class_precision = tp / np.maximum(tp + fp, 1)
        class_recall = tp / class_gt
        class_f1 = 2 * class_precision * class_recall / np.maximum(class_precision + class_recall, 1e-8)
        per_class_precision.append(class_precision)
        per_class_recall.append(class_recall)
        per_class_f1.append(class_f1)

    if per_class_f1:
        mean_f1_curve = np.mean(np.stack(per_class_f1), axis=0)
        if confidence is None:
            confidence_index = int(np.argmax(mean_f1_curve))
        else:
            confidence_index = int(np.argmin(np.abs(confidence_grid - confidence)))
        confidence = float(confidence_grid[confidence_index])
        precision = float(np.mean(np.stack(per_class_precision)[:, confidence_index]))
        recall = float(np.mean(np.stack(per_class_recall)[:, confidence_index]))
        f1 = float(mean_f1_curve[confidence_index])
    else:
        confidence = float(confidence or 0.0)
        precision = recall = f1 = 0.0

    # Detection confusion matrix, with the final row/column representing background.
    for image_id, annotations in enumerate(ground_truths):
        used_gt: set[int] = set()
        for pred_class, score, box in predictions[image_id]:
            if score < confidence:
                continue
            gt_boxes = annotations[:, 1:5]
            overlaps = _iou_xyxy(np.asarray(box, dtype=np.float32), _corners(gt_boxes)) if len(gt_boxes) else np.zeros((0,))
            best = int(np.argmax(overlaps)) if len(overlaps) else -1
            if best >= 0 and overlaps[best] >= 0.5 and best not in used_gt:
                true_class = int(annotations[best, 0])
                confusion[true_class, pred_class] += 1
                used_gt.add(best)
            else:
                confusion[num_classes, pred_class] += 1
        for gt_id, annotation in enumerate(annotations):
            if gt_id not in used_gt:
                confusion[int(annotation[0]), num_classes] += 1

    metrics = {
        "model": "MobileNetV2-SSD",
        "weights": str(model_path.resolve()),
        "data_yaml": str(data_yaml.resolve()),
        "imgsz": imgsz,
        "split": split,
        "confidence": confidence,
        "metric_averaging": "macro over classes present in split",
        "num_images": len(image_paths),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "map50": float(np.mean(class_ap50)) if class_ap50 else 0.0,
        "map50_95": float(np.mean(class_ap50_95)) if class_ap50_95 else 0.0,
        "confusion_matrix": str((output_dir / "confusion_matrix.png").resolve()),
        "results_dir": str(output_dir.resolve()),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "benchmark_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (output_dir / "confusion_matrix.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["true\\predicted", *names, "background"])
        for label, values in zip([*names, "background"], confusion):
            writer.writerow([label, *values.tolist()])
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(11, 9))
    ax.imshow(confusion, cmap="Blues")
    labels = [*names, "background"]
    color_limit = max(int(confusion.max()), 1)
    for row_index in range(len(labels)):
        for col_index in range(len(labels)):
            value = int(confusion[row_index, col_index])
            ax.text(
                col_index,
                row_index,
                str(value),
                ha="center",
                va="center",
                color="white" if value > color_limit / 2 else "black",
                fontsize=6,
            )
    ax.set_xticks(range(len(labels)), labels=labels, rotation=90, fontsize=7)
    ax.set_yticks(range(len(labels)), labels=labels, fontsize=7)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Ground truth")
    ax.set_title(f"MobileNetV2-SSD confusion matrix ({split}, conf={confidence:.3f})")
    fig.colorbar(ax.images[0], ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    fig.savefig(output_dir / "confusion_matrix.png", dpi=160)
    plt.close(fig)
    return metrics
