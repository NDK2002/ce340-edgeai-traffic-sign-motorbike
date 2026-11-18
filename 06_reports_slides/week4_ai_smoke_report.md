# Báo cáo smoke-test AI — Tuần 4

**Người phụ trách:** Phạm Thành Trung (`26410141`)
**Ngày chạy:** 18/11/2026
**Mục đích:** xác nhận các pipeline huấn luyện, benchmark và export chạy được với mock assets. Đây không phải kết quả benchmark trên dataset thật.

## Cấu hình chạy

- Python `3.11.9`, PyTorch `2.15.0+cpu`, Ultralytics `8.4.215`, TensorFlow `2.17.1`, `tf-keras` `2.17.0`, TFMOT `0.8.1`, ONNX `1.17.0`.
- Dataset `01_dataset/mock_assets/data_mock.yaml`: 5 ảnh, 6 object, cùng 5 ảnh dùng cho train/validation/test.
- Input `160x160`, 2 epochs, batch `2`, seed `42`; YOLO chạy CPU, MobileNetV2-SSD đóng băng backbone ImageNet để kiểm tra nhanh pipeline.

## Kết quả benchmark mock

Các chỉ số dưới đây được tính lại ngày `18/11/2026` bằng cùng evaluator: macro Precision/Recall/F1 tại ngưỡng confidence tối đa macro-F1 trên validation; mAP dùng nội suy 101 điểm. Confusion matrix cũng được tạo tại ngưỡng đó.

| Mô hình | Conf. | Precision | Recall | F1 | mAP@0.5 | mAP@0.5:0.95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| YOLOv8n | 0.096 | 0.7497 | 0.1667 | 0.1108 | 0.1106 | 0.0691 |
| YOLOv5u nano (`yolov5-tiny` alias) | 0.010 | 0.3161 | 0.6630 | 0.2286 | 0.3086 | 0.2681 |
| MobileNetV2-SSD | 0.600 | 0.0185 | 0.1667 | 0.0333 | 0.0185 | 0.0037 |

Loss của MobileNetV2-SSD giảm từ `30.9309` ở epoch 1 xuống `26.5947` ở epoch 2. Threshold được tối ưu trên mock validation nên không phải ngưỡng production. Bộ mock chỉ có 5 ảnh, 6 object và cùng ảnh cho train/validation/test; số liệu chỉ chứng minh evaluator chạy được, không dùng để kết luận model nào tốt hơn.

## Kiểm tra export

- YOLOv8n: ONNX `12.63 MB`; ONNX checker pass, ONNX Runtime CPU inference pass, output shape `(1, 16, 525)`.
- YOLOv5u nano: ONNX `10.62 MB`; ONNX checker pass, ONNX Runtime CPU inference pass, output shape `(1, 16, 525)`. Đây là checkpoint YOLOv5u nano dùng thay cho alias `yolov5-tiny`, không phải checkpoint YOLOv5-tiny từ một repo/architecture riêng.
- MobileNetV2-SSD: `.keras` và TensorFlow SavedModel đã tạo; cả hai load/inference pass ở input `160x160`, outputs `(1, 3752, 13)` class logits và `(1, 3752, 4)` box offsets. TFMOT `prune_low_magnitude` bọc được model sau khi nạp qua legacy Keras.

Các graph ONNX dùng các op phổ biến như `Conv`, `Add`, `Concat`, `Resize`, `MaxPool`, `Sigmoid`, `Slice`, `Reshape` và `Transpose`. Chưa xác nhận các op này với TensorFlow Lite Micro trên ESP32-S3.

## Artifacts

Run đầy đủ nằm tại `03_models_benchmark/runs/`; handoff mock gọn đã được gom trong `03_models_benchmark/mock_outputs/`. Cả hai thư mục bị `.gitignore` chặn để tránh đẩy weights lên GitHub.

- `mock_outputs/yolov8n/`: `best.onnx`, cấu hình train và confusion matrix.
- `mock_outputs/yolov5u-nano/`: `best.onnx`, cấu hình train và confusion matrix.
- `mock_outputs/mobilenetv2-ssd/`: `.keras`, SavedModel, log train và confusion matrix.
- `mock_outputs/benchmark_summary.csv`, `mock_outputs/benchmark_summary.json`.

## Trạng thái đầu việc

- **[T1] Khung train:** có CLI chung cho ba kiến trúc, cấu hình input `160/192/320`, dataset YAML, seed và metadata của run; đã chạy smoke trên CPU. Chưa xác nhận GPU/Colab.
- **[T2] Mock training/benchmark:** chạy smoke-test cả ba mô hình, sinh metric, confusion matrix và model artifacts; ONNX checker/Runtime, Keras/SavedModel inference và TFMOT wrapper đã qua kiểm tra.
- **Cần chốt tên baseline YOLOv5:** checkpoint dùng hiện tại là YOLOv5u nano (`yolov5nu.pt`) để thay alias `yolov5-tiny`; nếu rubric yêu cầu một kiến trúc/checkpoint khác thì đổi weights và chạy lại benchmark trước khi nộp.
- **Handoff TinyML:** có ONNX cho hai nhánh PyTorch và Keras/SavedModel cho nhánh TensorFlow. Bước pruning/INT8 và xác nhận op trên TFLM thuộc phần Sơn/Duy.
- **Còn bước đồng bộ bên ngoài workspace:** mock artifacts có sẵn trong `mock_outputs/` để bàn giao tại máy này; chưa tải lên Google Drive vì workspace không có Drive connector/mount. Hãy chuyển artifacts lên Drive nếu nhóm cần truy cập từ Colab/máy khác.
- **Còn cần cho Tuần 5:** thay mock bằng dataset thật, chia train/val/test độc lập theo nguồn/video, huấn luyện baseline đủ epochs, chốt threshold bằng validation rồi đánh giá test một lần.
