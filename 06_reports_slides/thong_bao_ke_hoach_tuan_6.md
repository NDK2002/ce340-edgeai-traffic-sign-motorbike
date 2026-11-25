# NỘI DUNG THÔNG BÁO KẾ HOẠCH TUẦN 6 (25/11 – 01/12/2026)
## MÔN: TRÍ TUỆ NHÂN TẠO CHO HỆ THỐNG NHÚNG (`CE340`) — NHÓM TRẦN HOÀNG HÔN

> **Người soạn:** Trần Hoàng Hôn (`26410046`) — Trưởng nhóm / PM & QA  
> **Tài liệu đính kèm:** [`Ke_Hoach_Thuc_Hien_Tuan_6.md`](../Ke_Hoach_Thuc_Hien_Tuan_6.md) | [`bom_and_hardware_specs.md`](../05_firmware_esp32s3/bom_and_hardware_specs.md) | [`giai_thich_phan_viec_duy.md`](../05_firmware_esp32s3/giai_thich_phan_viec_duy.md)  
> **Mục tiêu:** Thông báo triển khai Tuần 6 đến 4 thành viên (Vũ Văn Duy, Nguyễn Duy Khang, Phạm Thành Trung, Hoàng Cao Sơn).

---

## 1. TIN NHẮN THÔNG BÁO CHUNG CHO TOÀN NHÓM (GỬI GROUP CHAT)

```text
📢 [CE340 - THÔNG BÁO TRIỂN KHAI KẾ HOẠCH TUẦN 6: 25/11 – 01/12/2026]

Chào cả nhóm,

Tuần 5 vừa qua nhóm mình đã hoàn thành trọn vẹn 3 Pull Request lớn (#5, #7, #8) trên GitHub:
✅ Bộ dataset thật 12 lớp QCVN 41:2019 và pipeline augment thời tiết (Khang [K1][K2]).
✅ Script lượng tử hóa chính thức PTQ Full INT8 hỗ trợ cả TensorFlow và ONNX (Sơn [S3]).
✅ Toàn bộ firmware demo traffic_sign_alert, mô phỏng Wokwi, giải mã SSD trên chip và tool xuất báo cáo benchmark (Anh Duy [D1][D2]).

Tuần 6 này là TUẦN ĐO ĐẠC THỰC NGHIỆM & TỐI ƯU HÓA CHUYÊN SÂU. Chúng ta sẽ đưa mô hình thật lên phần cứng thật để lấy số liệu thực nghiệm chuẩn xác cho Báo cáo tiến độ Tuần 2 nộp Thầy Phan Đình Duy vào Thứ Ba 01/12/2026.

📌 Phân công trọng tâm Tuần 6:
1. Anh Vũ Văn Duy ([D5], [D6]):
   • Lắp mạch breadboard 830 lỗ, smoke test bo ESP32-S3-CAM thật, kiểm tra camera OV2640/OV3660 và quét I2C OLED 0x3C (25/11 – 26/11).
   • Nhận model thật traffic_sign_model_int8.h từ Sơn, chạy soak test 30 phút, đo dòng điện mA trên USB tester và quay video clip demo 1–2 phút (27/11 – 30/11).
2. Hoàng Cao Sơn ([S5], [S6]):
   • Nhận checkpoint mô hình thật từ Trung, chạy quantize_real_model.py xuất header C-array traffic_sign_model_int8.h bàn giao cho anh Duy (26/11 – 27/11).
   • Khảo sát Structured Pruning (20-40%), đánh giá mAP loss <= 3% và lập báo cáo Pareto Trade-off: Accuracy vs Model Size vs Latency (28/11 – 29/11).
3. Phạm Thành Trung ([T5], [T6]):
   • Chốt checkpoint baseline tốt nhất, xuất sạch SavedModel/ONNX với batch = 1 cho Sơn (25/11 – 26/11).
   • Thực hiện benchmark đối chứng toàn diện giữa FP32 vs INT8 trên tập test sạch và tập test thời tiết phức tạp; xuất ma trận nhầm lẫn đối chứng (27/11 – 29/11).
4. Nguyễn Duy Khang ([K3]):
   • Đóng gói tập kiểm thử thời tiết phức tạp độc lập test_weather/ từ split test chuẩn để Trung chạy benchmark đối chứng (25/11 – 27/11).
   • Phân tích các trường hợp biển báo bị che khuất hoặc thiếu sáng có nguy cơ nhận diện sai cao nhất.
5. Trần Hoàng Hôn ([H7], [H8]):
   • Điều phối testbench phần cứng, đối soát chéo số liệu giữa AI và Nhúng, review PRs (25/11 – 30/11).
   • Hoàn thiện và nộp Báo cáo tiến độ Tuần 2 (Word/PDF) cho Giảng viên hướng dẫn trước 23h59 ngày 01/12/2026.

Chi tiết kế hoạch từng ngày, ma trận phụ thuộc và checklist DoD đã có đầy đủ trong file: Ke_Hoach_Thuc_Hien_Tuan_6.md trên repo. Anh em cùng bám sát deadline để hoàn thành xuất sắc tuần này nhé! 💪
```

---

## 2. TIN NHẮN RIÊNG TỪNG THÀNH VIÊN

### 2.1. Gửi anh Vũ Văn Duy (`[D5]`, `[D6]`) — Xưng "em - anh"
```text
Anh Duy ơi, PR #8 của anh em đã review và merge vào main rồi, chất lượng code và bộ mô phỏng Wokwi rất tuyệt vời!

Tuần 6 này khi bo mạch về, anh em mình triển khai thực nghiệm phần cứng theo các bước sau nhé:
1. Smoke test bo ([D5]): Anh cắm bo ESP32-S3-CAM lên breadboard 830 lỗ, nhớ gắn tụ 470uF chống sụt áp và né chân GPIO 33-37 của PSRAM. Nạp code kiểm tra xem log CSV,hw có báo đúng 16 MB Flash / 8 MB PSRAM và CSV,i2c có thấy OLED 0x3C không nhé.
2. Nạp model thật & Chạy soak 30 phút ([D6]): Khi Sơn bàn giao file traffic_sign_model_int8.h, firmware sẽ tự động nạp model thật lên đầu danh sách. Anh chạy mock_inference_test liên tục 30 phút, đọc dòng điện mA trên USB tester và xuất file bench.csv.
3. Chạy script bench_report.py để sinh bảng Markdown và biểu đồ cho báo cáo. Sau đó quay giúp nhóm 1 đoạn clip ngắn (~1-2 phút) quay cảnh bo mạch nhận diện biển báo thật trên bàn test nhé anh!

Có trục trặc gì về nguồn hay cáp nạp anh cứ nhắn em hỗ trợ ngay nhé!
```

---

### 2.2. Gửi Hoàng Cao Sơn (`[S5]`, `[S6]`)
```text
Sơn ơi, script quantize_real_model.py (PR #7) đã được merge vào main và cập nhật tài liệu hướng dẫn đầy đủ tại 04_tinyml_optimization/README.md rồi nhé.

Nhiệm vụ tuần 6 của Sơn:
1. Lượng tử hóa model thật ([S5]): Ngay khi Trung gửi checkpoint tốt nhất, Sơn chạy script quantize_real_model.py để xuất file C-array 04_tinyml_optimization/traffic_sign_model_int8.h (lưu ý batch = 1 và alignas(16)) kèm file metadata .json bàn giao cho anh Duy nạp chip trước ngày 27/11 nhé.
2. Khảo sát Pruning & Trade-off ([S6]): Sơn thực hiện thử nghiệm Structured Pruning (20% – 40%) trên mô hình và viết báo cáo quantization_tradeoff_report.md phân tích đồ thị Pareto: Accuracy vs Model Size vs Latency. Nhớ giải thích rõ vì sao Unstructured Pruning không tăng tốc được trên ESP32-S3 do thiếu sparse kernel để đưa vào Chương 4 báo cáo nhé!
```

---

### 2.3. Gửi Phạm Thành Trung (`[T5]`, `[T6]`)
```text
Trung ơi, tiến độ train model trên GPU Colab tuần này cần chốt sớm để Sơn và anh Duy kịp nạp chip nhé:
1. Chốt weights thật ([T5]): Trung chọn checkpoint có mAP cao nhất (mục tiêu mAP@0.5 >= 75%), xuất định dạng SavedModel (cho nhánh TF) hoặc ONNX (cho nhánh PyTorch). Cần lưu ý cố định batch size = 1 để tránh lỗi tensor động khi chuyển sang TFLite Micro, gửi cho Sơn trước ngày 26/11.
2. Benchmark đối chứng ([T6]): Trung chạy benchmark so sánh song song giữa FP32 gốc và bản INT8 của Sơn trên cả 2 tập: tập test chuẩn và tập test_weather từ Khang. Xuất bảng chỉ số mAP@0.5, mAP@0.5:0.95 và ma trận nhầm lẫn đối chứng trước ngày 29/11 để Hôn tổng hợp vào Báo cáo Tuần 2 nhé!
```

---

### 2.4. Gửi Nguyễn Duy Khang (`[K3]`)
```text
Khang ơi, bộ dataset 12 lớp và pipeline augment thời tiết tuần 5 làm rất tốt, các test kiểm thử chạy pass 100%.

Tuần 6 này Khang hỗ trợ nhóm mục kiểm thử thử thách nhé:
1. Đóng gói tập test_weather ([K3]): Khang chạy augment_weather.py trên riêng split test (tuyệt đối không trộn vào train/val) để tạo ra tập kiểm thử thời tiết phức tạp độc lập 01_dataset/processed/test_weather/ bàn giao cho Trung trước ngày 27/11.
2. Phân tích các ca khó: Khang viết ngắn file 01_dataset/weather_test_analysis.md tổng kết các trường hợp biển báo bị che khuất > 30% hoặc trời tối có nguy cơ làm model nhận diện sai để làm minh chứng đánh giá độ bền vững cho báo cáo nhé!
```
