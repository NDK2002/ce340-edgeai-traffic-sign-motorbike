# Tình huống thực tế & Tiêu chí đánh giá — Thiết bị nhận diện biển báo cho xe máy

* **Người soạn:** Vũ Văn Duy (`26410031`) — Kỹ sư Nhúng & Thực nghiệm
* **Trạng thái:** 🟡 Đề xuất — **cần cả nhóm thống nhất ở buổi sync** (các quyết định ở [Mục 8](#8-quyết-định-cần-chốt-ở-buổi-sync))
* **Liên quan:** [Đề cương](../De_Cuong_Chi_Tiet_Do_An_CE340.md) · [BOM & phần cứng](../05_firmware_esp32s3/bom_and_hardware_specs.md) · [`classes.yaml`](../01_dataset/classes.yaml)

---

## 1. Vì sao cần tài liệu này

Nhận diện biển báo là đề tài phổ biến. Phần lớn các nhóm dừng ở "ảnh tĩnh → mAP cao". Điểm khác biệt của nhóm mình là **thiết bị chạy thật trên xe máy ở Việt Nam**, nên cần chứng minh nó dùng được trong các tình huống thật, bằng **số đo cụ thể** chứ không chỉ mAP.

Tài liệu này liệt kê: phạm vi đề tài (làm gì / không làm gì), 9 tình huống khó, cách xử lý, chỉ số đo và ai phụ trách.

---

## 2. Phạm vi đề tài

| Điều kiện | Trong phạm vi | Ngoài phạm vi (ghi rõ trong báo cáo) |
|---|---|---|
| **Mưa** | Mưa phùn, đường ướt sau mưa, kính camera đọng vài giọt nước | Mưa lớn: người lái thường trùm áo mưa che luôn thiết bị, hoặc chuyển sang đi ô tô / Grab — thiết bị chỉ cần **tự báo "camera bị che"** |
| **Ánh sáng** | Ban ngày, ngược sáng sáng sớm / chiều tối, ban đêm đường có đèn | Đêm đường không đèn |
| **Tốc độ** | 30–50 km/h (nội đô) | > 60 km/h |
| **Biển báo** | 12 lớp trong `classes.yaml`, biển tròn/tam giác cỡ chuẩn | Biển phụ có chữ (giờ áp dụng, "trừ xe ..."), biển điện tử |
| **Vị trí** | Biển ở lề phải, phía trên làn đường | Biển treo giữa đường trên giá long môn |

---

## 3. Chín tình huống khó

| # | Tình huống | Vì sao khó | Cách xử lý | Chỉ số đo | Phụ trách |
|---|---|---|---|---|---|
| **T1** | **Biển ở xa → quá nhỏ** | Thu nhỏ cả khung hình về 160×160 thì biển ở 15 m chỉ còn ~6 pixel (xem [Mục 4](#4-phân-tích-cự-ly-và-kích-thước-biển)) | Cắt vùng góc trên bên phải từ ảnh độ phân giải cao (ROI) thay vì thu nhỏ cả khung | Cự ly nhận diện được xa nhất (m) | Duy (firmware ROI), Trung (input size) |
| **T2** | **Thời gian phản ứng** | 40 km/h ≈ 11 m/giây: chậm 1 giây là đi qua biển | Đo toàn bộ vòng camera → AI → rung | Thời gian báo trước khi tới biển (giây) | Duy |
| **T3** | **Biển không áp dụng cho xe máy** | "Cấm ô tô", biển có biển phụ "trừ xe máy" → báo là sai | Lớp "biển không liên quan" để **không** báo (cần chốt, [Mục 8](#8-quyết-định-cần-chốt-ở-buổi-sync)) | Số lần báo nhầm do biển không liên quan | Khang, Trung |
| **T4** | **Ngược sáng** | Biển thành mảng tối, mất màu đỏ | Thêm ảnh ngược sáng vào dữ liệu; thử bật/tắt cân bằng sáng tự động của camera | Recall khi ngược sáng vs bình thường | Khang, Duy |
| **T5** | **Ban đêm** | Biển phản quang sáng lên dưới đèn xe nhưng nền nhiễu, dễ nhòe | Tập kiểm thử riêng ban đêm | Recall ban đêm | Khang, Trung |
| **T6** | **Bị che khuất** | Cây, xe tải, xe buýt, bảng quảng cáo | Đã có trong tăng cường dữ liệu; đo lại trên đường | Recall khi che < 40% | Khang |
| **T7** | **Nhòe do rung** | Ổ gà, đường xấu, giá đỡ rung | Giá đỡ kẹp nhôm chống rung; giảm thời gian phơi sáng camera | Recall đường đẹp vs đường xấu | Duy |
| **T8** | **Camera bị che / mờ** | Áo mưa, giọt nước, bụi | Phần mềm đo độ nét + độ sáng ảnh; mờ/tối liên tục vài giây → báo "Camera bị che" lên OLED | Thời gian phát hiện camera bị che (giây) | Duy, Hôn |
| **T9** | **Báo nhầm gây phiền** | Thấy biển của làn khác, biển dán trên xe buýt/xe tải, vật tròn đỏ giống biển | Chỉ báo khi thấy biển ở nhiều khung hình liên tiếp; mỗi biển báo 1 lần | **Số lần báo nhầm / km** | Trung, Duy |

**Ưu tiên:** T1, T8, T9 — ảnh hưởng trực tiếp đến việc thiết bị có dùng được hay không, và ít nhóm làm.

---

## 4. Phân tích cự ly và kích thước biển

Biển tròn cỡ chuẩn đường đô thị đường kính khoảng **70 cm**. Camera OV2640 ống kính thường, góc nhìn khoảng **66°** (số liệu ước tính, cần đo lại trên bo thật). Kích thước biển trong ảnh đưa vào model (160×160):

| Cự ly tới biển | Góc biển chiếm | **A.** Thu nhỏ cả khung QVGA 320→160 | **B.** Cắt 160×160 từ QVGA (không thu nhỏ) | **C.** Cắt 160×160 từ VGA 640×480 |
|---:|---:|---:|---:|---:|
| 5 m | 8,0° | 19 px | 39 px | 78 px |
| 10 m | 4,0° | 10 px | 19 px | 39 px |
| 15 m | 2,7° | **6 px** | 13 px | **26 px** |
| 20 m | 2,0° | 5 px | 10 px | 19 px |
| 30 m | 1,3° | 3 px | 6 px | 13 px |

*Model phát hiện vật thể nhỏ thường cần biển cỡ ≥ 15–20 px mới đọc được chữ số 40/50/60.*

**Hệ quả:**
- Phương án **A** (đang dùng mặc định) chỉ nhận được biển trong khoảng **≤ 5–7 m** → ở 40 km/h người lái còn chưa tới 1 giây.
- Phương án **C** nhận được biển từ khoảng **20 m** → còn khoảng 1,5 giây. Đổi lại: vùng cắt hẹp (~16° ngang) nên phải đặt đúng góc trên bên phải; khi xe tới gần, biển trượt ra khỏi vùng cắt → **cửa sổ nhận diện khoảng 8–25 m**. Ảnh VGA tốn thêm RAM (PSRAM) và thời gian chụp — Duy đo bằng `mock_inference_test`.

**Ngân sách thời gian (ở 40 km/h ≈ 11 m/s):** nếu chạy ~5 khung hình/giây và cần 3 khung liên tiếp để xác nhận (T9) thì mất ~0,6 giây ≈ 7 m đường. Muốn báo trước biển ≥ 1 giây → phải **bắt đầu thấy biển từ ~20 m**. Đây là lý do T1 quyết định cả FPS lẫn cách chọn input.

---

## 5. Chính sách cảnh báo

| Kênh | Vai trò | Kiểu báo |
|---|---|---|
| **Motor rung ở tay nắm** | Chính — chỉ người lái cảm nhận, không làm ồn người xung quanh, vẫn dùng được khi gió to / đeo găng / trùm áo mưa | Biển cấm: 3 nhịp dồn dập · Tốc độ, hiệu lệnh, cảnh báo: 1 nhịp dài |
| **Buzzer passive** (âm lượng vừa) | Phụ — có nút tắt | Cùng nhịp với rung |
| **OLED 1.3" + LED** | Liếc để xác nhận | Icon biển + chữ ngắn; biển tốc độ hiện cố định đến khi gặp biển tốc độ mới |

**Quy tắc chống phiền (T9):**
1. Chỉ báo khi cùng một biển xuất hiện ở **≥ 3 khung hình liên tiếp** với độ tin cậy ≥ ngưỡng (ngưỡng chốt sau khi chạy thử).
2. Mỗi biển chỉ báo **1 lần**; không báo lại cùng lớp trong ~10 giây.
3. Biển không áp dụng cho xe máy (T3) → **không báo**.
4. Camera bị che (T8) → hiện "Camera bị che" trên OLED + 1 nhịp rung dài, **không** im lặng như thể không có biển.

---

## 6. Bộ chỉ số đánh giá thực tế (ngoài mAP)

| Chỉ số | Cách đo | Mục tiêu đề xuất |
|---|---|---|
| mAP@0.5, Precision, Recall (trên tập kiểm thử) | Như đề cương | ≥ 85% (thường), ≥ 75% (khó) |
| **Recall theo từng điều kiện** | Tách tập kiểm thử: ngày / ngược sáng / đêm / sau mưa / bị che | Báo cáo từng nhóm, không gộp |
| **Cự ly nhận diện xa nhất** | Chạy thử, ghi khoảng cách lúc thiết bị báo (đánh dấu mốc trên đường) | ≥ 15 m |
| **Thời gian báo trước biển** | Cự ly ÷ vận tốc | ≥ 1 giây ở 40 km/h |
| **Độ trễ toàn hệ thống** | Từ lúc chụp ảnh tới lúc motor rung (log thời gian từng khâu) | < 150 ms (đề cương) |
| **Số lần báo nhầm / km** | Đếm trên cung đường thử | Càng thấp càng tốt — ghi số thật |
| **Tỉ lệ bỏ sót biển** | Biển có trên đường nhưng không báo / tổng số biển | Ghi số thật |
| Dòng tiêu thụ (mA), nhiệt độ chip | USB tester, log nhiệt độ | Chạy 30 phút liên tục không reset |

---

## 7. Quy trình chạy thử ngoài đường

1. **Chọn 1 cung đường cố định** (2–5 km) có sẵn nhiều biển thuộc 12 lớp; lập danh sách biển và vị trí trước.
2. **Ma trận điều kiện** — chạy cùng cung đường ở: ban ngày · sáng sớm/chiều (ngược sáng) · tối · sau mưa.
3. **Hai người:** người lái chỉ tập trung lái; người ngồi sau ghi chép và quay video. Thử ở bãi trống trước khi ra đường.
4. Thẻ microSD lưu ảnh camera → gửi Khang bổ sung dữ liệu thật.
5. Ghi kết quả vào bảng:

| Lần chạy | Ngày | Điều kiện | Tốc độ TB | Số biển trên đường | Báo đúng | Bỏ sót | Báo nhầm | Cự ly báo TB (m) | Ghi chú |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| | | | | | | | | | |

---

## 8. Quyết định cần chốt ở buổi sync

| # | Câu hỏi | Ảnh hưởng tới | Đề xuất |
|---|---|---|---|
| Q1 | Dùng ROI (cắt vùng góc trên phải) hay thu nhỏ cả khung? Cắt từ QVGA hay VGA? | Trung (train đúng kiểu ảnh), Sơn (input size), Duy (firmware) | Thử **phương án C** (cắt từ VGA), đo thời gian chụp; nếu chậm quá thì lùi về B |
| Q2 | Có thêm lớp thứ 13 "biển không áp dụng cho xe máy" không? | Khang (dữ liệu), Trung, `classes.yaml` (đổi contract `nc: 12 → 13`) | Có, nếu Khang thu đủ ảnh "Cấm ô tô" và các biển tương tự; nếu không thì ghi là giới hạn |
| Q3 | Mục tiêu FPS và số khung xác nhận | Trung, Sơn, Duy | ~5 FPS, xác nhận 3 khung |
| Q4 | Ngưỡng "camera bị che" | Duy, Hôn | Chốt sau khi có ảnh thật từ bo |
| Q5 | Tập kiểm thử tách theo điều kiện (ngày/ngược sáng/đêm/sau mưa/che khuất) | Khang, Trung | Có — để báo cáo Recall theo từng điều kiện |
