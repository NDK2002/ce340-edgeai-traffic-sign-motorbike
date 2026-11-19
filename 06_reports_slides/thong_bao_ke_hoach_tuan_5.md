# NỘI DUNG THÔNG BÁO KẾ HOẠCH TUẦN 5 (18/11 – 24/11/2026)
## MÔN: TRÍ TUỆ NHÂN TẠO CHO HỆ THỐNG NHÚNG (`CE340`) — NHÓM TRẦN HOÀNG HÔN

> **Người soạn:** Trần Hoàng Hôn (`26410046`) — Trưởng nhóm / PM & QA  
> **Tài liệu đính kèm:** [`Ke_Hoach_Thuc_Hien_Tuan_5.md`](../Ke_Hoach_Thuc_Hien_Tuan_5.md) | [`Bao_Cao_Tuan_4_CE340.docx`](./Bao_Cao_Tuan_4_CE340.docx)  
> **Mục tiêu:** Thông báo triển khai Tuần 5 đến 4 thành viên (Vũ Văn Duy, Nguyễn Duy Khang, Phạm Thành Trung, Hoàng Cao Sơn).

---

## 1. TIN NHẮN THÔNG BÁO CHUNG CHO TOÀN NHÓM (GỬI GROUP CHAT)

```text
📢 [CE340 - THÔNG BÁO TRIỂN KHAI KẾ HOẠCH TUẦN 5: 18/11 – 24/11/2026]

Chào cả nhóm,

Tuần 4 vừa rồi nhóm mình đã hoàn thành xuất sắc 100% mục tiêu Zero-Waiting Pipeline:
✅ Toàn bộ hạ tầng 6 phân hệ, mock training, mock TinyML INT8 và firmware benchmark đã được tích hợp sạch vào nhánh main.
✅ File Báo cáo Tuần 4 theo chuẩn mẫu Word của Giảng viên đã được tạo và lưu trữ đầy đủ.

Tuần 5 này là TUẦN BẢN LỀ CỦA ĐỒ ÁN — chúng ta chuyển dịch toàn diện từ Mock sang DỮ LIỆU THẬT & PHẦN CỨNG THẬT để kịp hoàn thiện sản phẩm nộp Báo cáo tiến độ Tuần 1 cho Thầy Phan Đình Duy vào Thứ Ba 24/11/2026.

📌 Phân công trọng tâm Tuần 5:
1. Nguyễn Duy Khang ([K1], [K2]):
   • Hoàn thiện chia tập dữ liệu thật >= 1.000 ảnh (70/20/10) theo 12 lớp QCVN 41:2019, xuất dataset_summary.md và đẩy lên Drive trước ngày 20/11.
   • Đóng gói script augment_weather.py (4 kịch bản thời tiết) & xuất 20 ảnh mẫu vào preview_samples/.
2. Phạm Thành Trung ([T3], [T4]):
   • Nhận dataset thật từ Khang, chạy train full epochs 3 baseline (YOLOv8n, YOLOv5u nano, MobileNetV2-SSD) trên GPU Colab (20/11 – 21/11).
   • Chốt mAP thật, ngưỡng threshold và export sạch ONNX + SavedModel chuyển cho Sơn (21/11).
3. Hoàng Cao Sơn ([S3], [S4]):
   • Nhận weights thật từ Trung, chạy PTQ Full INT8 với calibration dataset, bảo đảm nén >= 70% và 100% toán tử chuẩn ESP-NN (21/11 – 22/11).
   • Kiểm chứng mAP suy giảm <= 3%, xuất C-array traffic_sign_model_int8.h bàn giao cho anh Duy nạp kit (22/11).
4. Anh Vũ Văn Duy ([D3], [D4]):
   • Nhận kit ESP32-S3-CAM N16R8, cắm breadboard hoàn chỉnh (né GPIO 33-37), test camera OV2640 & OLED (18/11 – 20/11).
   • Nạp model thật từ Sơn, chạy suy luận thực tế trên bo, đo đạc FPS, Latency, SRAM/PSRAM, mA và quay video demo (22/11 – 23/11).
5. Trần Hoàng Hôn ([H4], [H5], [H6]):
   • Tích hợp module ngoại vi ghi-đông vào firmware FreeRTOS chính (18/11 – 20/11).
   • Tổ chức họp sync kỹ thuật, QA chéo số liệu và review PRs (23/11).
   • Tổng hợp số liệu và nộp Báo cáo tiến độ Tuần 1 đúng hạn trước 23h59 ngày 24/11.

Chi tiết kế hoạch từng ngày, ma trận phụ thuộc và checklist DoD đã có đầy đủ trong file: Ke_Hoach_Thuc_Hien_Tuan_5.md trên repo. Anh em vào check và bắt tay vào việc luôn nhé! Chúc nhóm tuần mới bứt phá! 💪
```

---

## 2. TIN NHẮN RIÊNG TỪNG THÀNH VIÊN

### 2.1. Gửi anh Vũ Văn Duy (`[D3]`, `[D4]`) — Xưng "em - anh"
```text
Anh Duy ơi, em đã rà soát lại bản BOM phần cứng tại 05_firmware_esp32s3/bom_and_hardware_specs.md và tinh gọn lại 4 điểm sau để anh đặt hàng nhé:

1. Đầu việc [D3] (18/11 – 20/11):
   - Bo mạch: Chốt mua 1 bo ESP32-S3-CAM N16R8 kèm camera OV2640 góc thường ~66° (không lấy lens góc rộng 120° để tránh méo ảnh AI).
   - Breadboard & Nguồn: Đổi sang Breadboard 830 lỗ (loại dài) để cắm vừa bo mạch; thêm 1 tụ hóa 220uF–470uF 16V cắm 5V–GND để chống sụt áp khi chụp ảnh.
   - Phụ kiện xe: Hộp nhựa và giá kẹp xe để dành sang Tuần 7 mua sau; thẻ nhớ microSD tận dụng thẻ cũ hoặc ghi thẳng vào Flash 16MB (LittleFS).
   - Khi nhận hàng, nhờ anh cắm hoàn chỉnh mạch trên breadboard 830 lỗ theo đúng sơ đồ an toàn né dải GPIO 33–37 như anh đã vẽ, nạp code test camera OV2640 và quét I2C màn hình OLED SH1106. Nhờ anh chụp giúp em 2-3 tấm ảnh chụp mạch thực tế để em đưa vào báo cáo tiến độ nộp Thầy.
2. Đầu việc [D4] (22/11 – 23/11):
   - Khi Sơn xuất xong file C-array mô hình thật (traffic_sign_model_int8.h) và em tích hợp xong khung FreeRTOS, nhờ anh nạp lên kit thật để chạy suy luận thực tế.
   - Đo đạc giúp em các thông số thực: FPS, Latency từng chặng (chụp -> tiền xử lý -> suy luận -> hiển thị), RAM/PSRAM chiếm dụng và dòng tiêu thụ (mA).
   - Nhờ anh quay 1 đoạn clip ngắn khoảng 1-2 phút quay cảnh mạch nhận diện biển báo trên bàn test để làm minh chứng nộp báo cáo.

👉 Tổng kinh phí rút xuống chỉ còn khoảng ~380k – 450k (mỗi bạn ~80k–90k). Nhờ anh Duy đặt hàng theo danh mục này nhé ạ!
```

---

### 2.2. Gửi Nguyễn Duy Khang (`[K1]`, `[K2]`) — Xưng "anh - em"
```text
Khang ơi, anh gửi em nhiệm vụ Tuần 5 của em nhé:

Tuần này em là mắt xích mở đầu cực kỳ quan trọng để cấp dữ liệu thật cho Trung và Sơn:
1. Đầu việc [K1] (Hạn chót: 20/11):
   - Chạy script 01_dataset/remap_and_split.py trên tập dữ liệu công khai trên Drive, lọc và ánh xạ đúng 12 lớp theo classes.yaml (QCVN 41:2019).
   - Đảm bảo quy mô tập thật >= 1.000 ảnh, chia chuẩn tỷ lệ 70% Train, 20% Val, 10% Test.
   - Xuất file báo cáo phân bố nhãn 01_dataset/dataset_summary.md và thông báo cho Trung để bạn ấy kéo về train Colab nhé.
2. Đầu việc [K2] (Hạn chót: 21/11):
   - Đóng gói script 02_augmentation/augment_weather.py áp dụng 4 kịch bản thời tiết (mưa đọng, mờ rung lắc, che khuất, thiếu sáng).
   - Xuất 20 ảnh mẫu kiểm chứng vào 02_augmentation/preview_samples/ kèm file chú thích ngắn để đưa vào báo cáo tiến độ.

Cố gắng đẩy nhanh dataset trước ngày 20/11 để Trung có đủ thời gian train GPU nha em!
```

---

### 2.3. Gửi Phạm Thành Trung (`[T3]`, `[T4]`) — Xưng "anh - em"
```text
Trung ơi, anh gửi em kế hoạch huấn luyện AI Tuần 5 nhé:

Tuần này mình chạy huấn luyện chính thức trên dữ liệu thật:
1. Đầu việc [T3] (20/11 – 21/11):
   - Khi Khang bàn giao dataset thật trên Drive, em nạp lên GPU Colab và chạy train full epochs cho cả 3 baseline: YOLOv8n, YOLOv5u nano và MobileNetV2-SSD.
   - Nhớ dùng đúng cờ --imgsz 160 hoặc 192 phù hợp với chip nhúng và lưu checkpoint thường xuyên lên Drive phòng Colab ngắt kết nối nhé.
2. Đầu việc [T4] (21/11 – 22/11):
   - Chạy script evaluate_benchmark.py để đo mAP@0.5 thật trên tập test, xác định ngưỡng confidence threshold tối ưu.
   - Xuất bảng kết quả 03_models_benchmark/benchmark_real_summary.csv và ảnh ma trận nhầm lẫn confusion_matrix_real.png.
   - Export sạch 2 định dạng trung gian: ONNX (yolov8n, yolov5u) và SavedModel (MobileNetV2-SSD) rồi bàn giao ngay cho Sơn lượng tử hóa nhé.

Mục tiêu mAP@0.5 baseline thật đạt >= 75% trên tập validation nha em!
```

---

### 2.4. Gửi Hoàng Cao Sơn (`[S3]`, `[S4]`) — Xưng "anh - em"
```text
Sơn ơi, anh gửi em nhiệm vụ tối ưu hóa TinyML Tuần 5 nhé:

Tuần này mình chuyển toàn bộ toolchain sang nén mô hình thật:
1. Đầu việc [S3] (21/11 – 22/11):
   - Khi Trung bàn giao file trọng số thật và Khang cấp 100-200 ảnh calibration, em chạy script PTQ Full INT8 (quantize_real_model.py).
   - Kiểm tra kỹ 100% toán tử phải nằm trong danh mục hỗ trợ của tflite-micro và nhân ESP-NN của Espressif; đảm bảo tỷ lệ nén dung lượng >= 70% so với FP32.
2. Đầu việc [S4] (22/11 – 23/11):
   - Đánh giá độ suy giảm mAP sau khi lượng tử hóa (yêu cầu suy giảm mAP <= 3.0% so với FP32 gốc).
   - Xuất file header C-array 04_tinyml_optimization/traffic_sign_model_int8.h với định dạng căn chỉnh bộ nhớ alignas(16) và bàn giao cho anh Duy nạp lên kit ESP32-S3 nhé.

Tuần 4 em làm mảng mock rất mượt rồi, tuần này áp dụng đúng quy trình đó cho model thật là chuẩn bài nha em!
```

