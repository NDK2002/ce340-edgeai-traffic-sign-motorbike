# 04_tinyml_optimization — Tối ưu hóa TinyML (Pruning & Quantization INT8)

* **Phụ trách chính:** Hoàng Cao Sơn (`[S1]`–`[S4]`)
* **Môi trường thực thi khuyến nghị:** **Google Colab (Linux)** để chạy `tfmot`, `onnx2tf`, `TFLiteConverter` (tránh xung đột dependency trên Windows).

## Sản phẩm bàn giao

| File | Vai trò | Trạng thái |
|---|---|---|
| `tinyml_toolchain_notes.md` | Tài liệu kỹ thuật: tách 2 luồng toolchain (TF/Keras và PyTorch/ONNX), bảng kiểm tra toán tử tương thích ESP-NN / TFLM trên ESP32-S3 | Hoàn thành |
| `quantize_int8_mock.py` | Script PTQ Full INT8 mô phỏng trên model mock, tạo file `.h` ban đầu cho firmware nhúng | Hoàn thành Tuần 4 |
| `mock_model_int8.h` | Mảng C-array model mock (`alignas(16)`) phục vụ kiểm thử pipeline | Hoàn thành Tuần 4 |
| `quantize_real_model.py` | Script lượng tử hóa chính thức (Full INT8) cho mô hình thật: hỗ trợ 2 nhánh TF và ONNX, xuất `.tflite`, C-array `.h` và metadata `.json` | Hoàn thành Tuần 5 (PR #7) |

---

## Hướng dẫn lượng tử hóa mô hình thật (`quantize_real_model.py`)

Script hỗ trợ cả 2 nhánh mô hình học sâu của dự án:
1. **Nhánh TensorFlow / Keras (`--branch tf`):** Dành cho MobileNetV2-SSD (`.keras` hoặc SavedModel). Chuẩn hóa ảnh calibration về dải `[-1, 1]`.
2. **Nhánh PyTorch / ONNX (`--branch onnx`):** Dành cho YOLOv8n / YOLOv5u (`.onnx`). Sử dụng `onnx2tf` (-oiqt) với chuẩn hóa `[0, 1]` (format NCHW).

### 1. Cài đặt môi trường (trên Google Colab)

```bash
pip install -r requirements.txt
pip install onnx2tf
```

### 2. Chạy lượng tử hóa

#### Nhánh MobileNetV2-SSD (TensorFlow/Keras):
```bash
python 04_tinyml_optimization/quantize_real_model.py \
  --branch tf \
  --model path/to/mobilenetv2_ssd.keras \
  --calib-dir 01_dataset/processed/images/train \
  --imgsz 160 \
  --max-calib 150 \
  --output-tflite 04_tinyml_optimization/traffic_sign_model_int8.tflite \
  --output-header 04_tinyml_optimization/traffic_sign_model_int8.h
```

#### Nhánh YOLOv8n / YOLOv5u (ONNX):
```bash
python 04_tinyml_optimization/quantize_real_model.py \
  --branch onnx \
  --model path/to/yolov8n.onnx \
  --calib-dir 01_dataset/processed/images/train \
  --imgsz 160 \
  --max-calib 150 \
  --input-name images \
  --output-tflite 04_tinyml_optimization/traffic_sign_model_int8.tflite \
  --output-header 04_tinyml_optimization/traffic_sign_model_int8.h
```

### 3. Tiêu chí chất lượng & Đầu ra
* **Tỷ lệ nén dung lượng:** Đạt $\ge 70\%$ so với bản gốc FP32.
* **Toán tử TFLM / ESP-NN:** 100% toán tử phải nằm trong danh mục hỗ trợ của `tflite-micro` trên ESP32-S3.
* **File C-array đầu ra:** Được căn chỉnh 16 bytes (`alignas(16)`), chứa hằng số độ dài `traffic_sign_model_int8_len`.
* **Metadata JSON:** File `traffic_sign_model_int8.json` đi kèm lưu trữ scale và zero-point để đối chiếu.
* **Tích hợp tự động:** Khi file `04_tinyml_optimization/traffic_sign_model_int8.h` xuất hiện, firmware `05_firmware_esp32s3/` sẽ tự động ưu tiên nạp mô hình thật lên đầu danh sách chạy suy luận.


