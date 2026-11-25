# HỒ SƠ ĐỒ ÁN MÔN HỌC CE340 - TRÍ TUỆ NHÂN TẠO CHO HỆ THỐNG NHÚNG
## ĐỀ TÀI: HỆ THỐNG NHẬN DIỆN BIỂN BÁO GIAO THÔNG ĐƯỜNG BỘ VIỆT NAM CHO XE MÁY TRONG ĐIỀU KIỆN THỜI TIẾT PHỨC TẠP DỰA TRÊN EDGE AI & TINYML

---

* **Đơn vị đào tạo:** Khoa Kỹ thuật Máy tính – Trường Đại học Công nghệ Thông tin (ĐHQG-HCM)
* **Giảng viên hướng dẫn:** ThS. Phan Đình Duy (Email: `duypd@uit.edu.vn`)
* **Học kỳ:** HK1 – Năm học 2026 – 2027
* **Mục tiêu hoàn thành:** Báo cáo và nghiệm thu đồ án **Đợt 1 ở Tuần 8 (09/12/2026)**

---

### DANH SÁCH NHÓM 5 THÀNH VIÊN & PHÂN CÔNG CHUYÊN TRÁCH

| STT | Họ và Tên | MSSV | Vai Trò Chuyên Trách | Đầu Việc Chính Trong Dự Án |
| :---: | :--- | :---: | :--- | :--- |
| 1 | **Trần Hoàng Hôn** | `26410046` | **Trưởng nhóm / PM & QA** | Quản trị dự án (Agile WBS), kiểm soát chất lượng bàn giao (DoD), thiết kế kiến trúc nhúng, tối ưu hóa giao tiếp ngoại vi (OLED, Buzzer) và điều phối báo cáo |
| 2 | **Nguyễn Duy Khang** | `26410055` | **Kỹ sư Dữ liệu** | Thu thập và gán nhãn dataset biển báo Việt Nam (QCVN 41:2019); xây dựng pipeline tăng cường dữ liệu thời tiết phức tạp (mưa, mờ, che khuất) |
| 3 | **Phạm Thành Trung** | `26410141` | **Kỹ sư AI** | Huấn luyện đa mô hình học sâu (YOLOv8n, YOLOv5-tiny, MobileNetV2-SSD); đo lường và benchmark so sánh hiệu năng (`Precision`, `Recall`, `mAP@0.5`) |
| 4 | **Vũ Văn Duy** | `26410031` | **Kỹ sư Nhúng & Thực nghiệm** | Triển khai nạp mô hình nén INT8 lên phần cứng thật (ESP32-S3), thi công hộp mạch bảo vệ gắn ghi-đông xe máy và đo đạc thông số thực tế (FPS, Latency, dòng điện mA) |
| 5 | **Hoàng Cao Sơn** | `25730061` | **Kỹ sư Tối ưu hóa (TinyML)** | Thực hiện kỹ thuật cắt tỉa (Pruning) và lượng tử hóa sau huấn luyện (Post-Training Quantization INT8) trên TensorFlow Lite/ONNX |

---

### CẤU TRÚC CÁC THƯ MỤC VÀ FILE TRONG DỰ ÁN

```
D:\Trí tuệ nhân tạo\HK3\Trí tuệ nhân tạo cho hệ thống nhúng\Đồ án\
├── 📁 01_dataset/                                 <-- Thu thập, gán nhãn & Data Contract 12 lớp (classes.yaml)
├── 📁 02_augmentation/                            <-- Pipeline Albumentations tăng cường thời tiết phức tạp
├── 📁 03_models_benchmark/                         <-- Huấn luyện & đánh giá baseline (YOLOv8n, YOLOv5u, MobileNetV2-SSD)
├── 📁 04_tinyml_optimization/                     <-- Tối ưu hóa TinyML: Pruning & Full INT8 Quantization cho ESP32-S3
├── 📁 05_firmware_esp32s3/                        <-- BOM phần cứng, firmware demo cảnh báo (traffic_sign_alert), benchmark & driver ngoại vi
├── 📁 06_reports_slides/                          <-- Báo cáo tuần, tài liệu kịch bản thực tế xe máy & slide nghiệm thu
├── 📄 De_Cuong_Chi_Tiet_Do_An_CE340.docx           <-- [FILE CHÍNH THỨC NỘP THẦY] Đề cương chi tiết (Word)
├── 📊 Ke_Hoach_Thuc_Hien_Do_An_CE340_Nhom_Hon.xlsx   <-- [FILE CHÍNH THỨC NỘP THẦY] Bảng tiến độ 8 tuần (Excel)
├── 📝 De_Cuong_Chi_Tiet_Do_An_CE340.md             <-- Bản thảo Markdown đề cương chi tiết đầy đủ nội dung
├── 📑 Khao_Sat_De_Tai_Va_Phuong_An_Thiet_Ke_CE340.md <-- Báo cáo phân tích tính mới & so sánh gắn xe vs mũ bảo hiểm
├── 📋 Ke_Hoach_Thuc_Hien_Tuan_4.md                 <-- Kế hoạch & kết quả nghiệm thu chi tiết Tuần 4 (Hoàn thành 100%)
├── 📋 Ke_Hoach_Thuc_Hien_Tuan_5.md                 <-- Kế hoạch & tổng kết nghiệm thu Tuần 5 (Dữ liệu thật, PTQ script, Firmware demo PR #8)
├── 📋 Ke_Hoach_Thuc_Hien_Tuan_6.md                 <-- Kế hoạch thực hiện chi tiết Tuần 6 (Tối ưu hóa TinyML, thực nghiệm bo thật & Báo cáo Tuần 2)
└── 📖 README.md                                    <-- Tài liệu này
```

---

### TIẾN ĐỘ THỰC HIỆN & DEADLINE THEO TUẦN

| Tuần | Mốc thời gian | Nhiệm vụ trọng tâm | Sản phẩm nghiệm thu |
| :---: | :---: | :--- | :--- |
| **Tuần 3** | 04/11 – 10/11 | Chốt đề tài & Nộp Đề cương chi tiết + Kế hoạch tiến độ | 🟢 **100% Hoàn thành** *(Đã nộp Giảng viên)* |
| **Tuần 4** | 11/11 – 17/11 | Zero-Waiting Pipeline: Data Contract 12 lớp, mock benchmark, ngoại vi & BOM | 🟢 **100% Hoàn thành** *(Đã nghiệm thu & merge main)* |
| **Tuần 5** | 18/11 – 24/11 | Dataset thật $\ge 1.000$ ảnh; script PTQ INT8; firmware demo & mô phỏng Wokwi | 🟢 **100% Hoàn thành** *(Merged PR #5, #7, #8)* |
| **Tuần 6** | 25/11 – 01/12 | Tối ưu TinyML chuyên sâu (Pruning & INT8); nạp bo thật; **Nộp Báo cáo Tuần 2** | 🟡 **Đang thực hiện** *(25/11 – 01/12/2026)* |
| **Tuần 7** | 02/12 – 08/12 | Nạp model lên ESP32-S3; ráp hộp ghi-đông; đo FPS/độ trễ; **Nộp Báo cáo Tuần 3** | **0%** *(Dự kiến)* |
| **Tuần 8** | 09/12 – 15/12 | **BÁO CÁO VÀ BẢO VỆ NGHIỆM THU ĐỒ ÁN ĐỢT 1 TRƯỚC LỚP** | **0%** *(Dự kiến)* |
| **Tuần 9** | 16/12 – 22/12 | Hiệu chỉnh sau bảo vệ (nếu có) & Đóng gói source code GitHub | **0%** *(Dự kiến)* |
| **Tuần 10**| 23/12/2026 | Ôn tập tổng kết và thi tập trung cuối kỳ môn CE340 (90 phút) | **0%** *(Dự kiến)* |
