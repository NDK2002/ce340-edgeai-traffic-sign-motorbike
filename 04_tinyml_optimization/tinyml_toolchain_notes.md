# `[S1]` Tài liệu Kỹ thuật TinyML Toolchain & Khả năng tương thích `ESP32-S3`

**Người phụ trách:** Hoàng Cao Sơn (`25730061`)  
**Cập nhật:** `19/11/2026` *(Đã đồng bộ với commit `0dc8d64` của Phạm Thành Trung)*  
**Môi trường thực thi khuyến nghị:** **Google Colab (Linux)** để chạy `tfmot`, `onnx2tf`, `TFLiteConverter` (tránh xung đột dependency trên Windows); dùng Windows để viết code và quản lý Git.

---

## 1. Ngân sách phần cứng mục tiêu (`ESP32-S3 N16R8`)

> *Lưu ý: Dùng thông số chuẩn của module `ESP32-S3-WROOM-1 N16R8` trong khi chờ `[D1]` chốt pinout chi tiết.*

| Tài nguyên | Thông số phần cứng | Ngân sách an toàn cho TinyML | Ghi chú kỹ thuật |
| :--- | :--- | :--- | :--- |
| **Flash** | `16 MB` | Model `.tflite` (`.h`): **`< 500 KB – 1.5 MB`** | Chia sẻ với firmware, driver `OV2640`, font/icon `OLED`. |
| **Octal PSRAM** | `8 MB` *(né GPIO 33–37)* | `kTensorArenaSize`: **`1 MB – 4 MB`** | Bắt buộc bật `OPI PSRAM` khi build firmware. |
| **Internal SRAM** | `~512 KB` | Stack / DMA buffer camera | Không đủ chứa tensor arena kích thước lớn. |
| **CPU** | Xtensa LX7 Dual-Core `240 MHz` *(Vector AI)* | Mục tiêu hệ thống: **`< 150 ms`** (`>= 10–15 FPS`) | Hỗ trợ tăng tốc `ESP-NN` cho ops `int8` chuẩn. |

---

## 2. Tách 2 luồng Toolchain Nén Mô hình (Pruning + Full INT8)

Theo `requirements.txt` (phiên bản đã chốt với nhánh Training của Trung):
* `tensorflow>=2.17.0,<2.18.0`, `tf-keras>=2.17.0,<2.18.0`, `tensorflow-model-optimization>=0.7.5` (`0.8.1`)
* `numpy>=1.26.0,<2.0.0`, `onnx>=1.15.0,<1.18.0`, `protobuf>=4.25.3,<5.0.0`
* `onnx2tf>=1.20.0` *(cài trên Google Colab/Linux)*

### Luồng A — Nhánh TensorFlow / Keras (`MobileNetV2-SSD` & CNN)

```text
Keras Model (.keras / SavedModel) [TF_USE_LEGACY_KERAS=1]
  └─> tfmot.sparsity.keras.prune_low_magnitude (Fine-tuning / Mock fit)
        └─> tfmot.sparsity.keras.strip_pruning()
              └─> TFLiteConverter.from_keras_model()
                    ├─ optimizations = [Optimize.DEFAULT]
                    ├─ representative_dataset (RGB float32 scaled to [-1, 1])
                    ├─ supported_ops = [TFLITE_BUILTINS_INT8]
                    └─ inference_input/output_type = tf.int8
                          └─> model_int8.tflite -> model_int8.h (alignas(16))
```

* **Quy tắc bắt buộc từ `03_models_benchmark/mobilenetv2_ssd.py`:**
  1. Phải đặt `os.environ["TF_USE_LEGACY_KERAS"] = "1"` **trước** `import tensorflow as tf` để nạp đúng Keras 2 API tương thích `tfmot`.
  2. Dải chuẩn hóa `representative_dataset` cho `MobileNetV2-SSD` là **`RGB float32` thuộc `[-1, 1]`** (tương ứng `(img / 127.5) - 1.0`), **không** dùng `[0, 1]`.
  3. Output của `MobileNetV2-SSD` (`160x160`) là multi-output Object Detection: `class_logits (1, 3752, 13)` và `box_offsets (1, 3752, 4)`. Bước decode anchor + NMS thực hiện ngoài graph bằng C++.

### Luồng B — Nhánh PyTorch (`YOLOv8n` / `YOLOv5u nano`)

```text
PyTorch (.pt)
  └─> torch.nn.utils.prune (hoặc Structured Channel Pruning) + prune.remove()
        └─> torch.onnx.export (opset=12/13, simplify=True) -> best.onnx
              └─> onnx2tf -i best.onnx -oiqt -cind ... (trên Google Colab Linux)
                    └─> model_int8.tflite -> model_int8.h
```

* **Cảnh báo kỹ thuật quan trọng về Pruning trên PyTorch:**
  * `torch.nn.utils.prune` mặc định chỉ thực hiện **Unstructured Pruning** (đưa trọng số về `0` nhưng giữ nguyên shape tensor).
  * `tflite-micro` trên `ESP32-S3` **không có nhân tăng tốc ma trận thưa (sparse kernel)**, do đó Unstructured Pruning **không tự làm nhỏ kích thước file `.tflite` và không giảm thời gian suy luận** — mức giảm dung lượng ~4x chủ yếu đến từ **Quantization FP32 $\rightarrow$ INT8**.
  * Để Pruning giảm kích thước/FLOPs thật trên MCU, cần dùng **Structured Channel Pruning** (cắt hẳn channel/filter) hoặc đánh giá riêng tỷ lệ sparsity trên nhánh PyTorch trong báo cáo trade-off.
* **Dải chuẩn hóa `representative_dataset` cho YOLO:** `RGB float32` thuộc `[0, 1]` (`img / 255.0`), khớp với pipeline `Ultralytics`. Output hiện tại của Trung ở `160x160` là `(1, 16, 525)`.

---

## 3. Bảng kiểm Toán tử (`tflite-micro` / `ESP-NN` trên `ESP32-S3`)

| Nhóm toán tử | Ops chuẩn `tflite-micro` (Hỗ trợ tốt `INT8`) | Rủi ro khi chuyển đổi từ `MobileNetV2-SSD` / `YOLOv8n` | Hướng xử lý |
| :--- | :--- | :--- | :--- |
| **Conv & Pool** | `CONV_2D`, `DEPTHWISE_CONV_2D`, `AVERAGE_POOL_2D`, `MAX_POOL_2D` | An toàn trên cả SSD và YOLO | Đăng ký qua `MicroMutableOpResolver` |
| **Activation** | `RELU`, `RELU6`, `LOGISTIC` (Sigmoid) | `YOLOv8n` dùng `SiLU` (`MUL` + `LOGISTIC`) chạy chậm hơn `ReLU6` | Ưu tiên `MobileNetV2` (`ReLU6`) cho MCU |
| **Tensor & Shape** | `RESHAPE`, `CONCATENATION`, `ADD`, `MUL`, `PAD`, `STRIDED_SLICE` | `YOLOv8n` có thể sinh `TRANSPOSE` 5D hoặc `SPLIT_V` từ head `DFL` | Dùng `onnx2tf` tối ưu layout; kiểm tra op list bằng `Interpreter` |
| **Upsample / Resize** | `RESIZE_NEAREST_NEIGHBOR`, `RESIZE_BILINEAR` | `Resize` với scale động dễ gây lỗi `tflite-micro` | Export ONNX với static shape (`imgsz=160`) |
| **Quantize / Head** | `QUANTIZE`, `DEQUANTIZE`, `SOFTMAX`, `FULLY_CONNECTED` | **Không nhúng `NonMaxSuppression` (NMS) vào graph TFLite** | Viết decode box + NMS bằng C++ trên ESP32-S3 |

> **Phương án dự phòng (`ESP-DL`):** Nếu ở Tuần 6 nhánh `YOLOv8n` phát sinh op không được `tflite-micro` hỗ trợ hoặc độ trễ vượt quá `150 ms` ở `160x160`, nhóm sẽ ưu tiên **MobileNetV2-SSD** (hoặc chuyển sang thư viện **`ESP-DL`** của Espressif / **Raspberry Pi** làm đối chứng).
