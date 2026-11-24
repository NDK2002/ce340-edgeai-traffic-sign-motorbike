# traffic_sign_alert — Firmware cảnh báo biển báo (bản demo)

Chương trình chạy thật trên bo **ESP32-S3-CAM N16R8**: nhìn biển báo → báo cho người lái. Khác với `mock_inference_test/` (chỉ để đo số liệu), đây là firmware dùng khi demo.

```
Camera (VGA) → kiểm tra camera bị che → cắt ô 160×160 góc trên-phải → model phân loại
            → quy tắc chống báo nhầm → OLED + LED + buzzer
```

| Thành phần | Lấy từ đâu |
|---|---|
| Bảng chân, danh sách model | `mock_inference_test/src/board_pins.h`, `models.h` (dùng chung, không copy) |
| Driver OLED SH1106, buzzer, LED, nút, icon 12 biển | `peripherals_test/src/` của Hôn (`[H2]`) |
| Quy tắc chống báo nhầm | `src/alert_policy.h` |
| Phát hiện camera bị che / quá tối / quá mờ | `src/frame_quality.h` |

## Hoạt động thế nào

- **Hai việc chạy song song trên 2 nhân CPU:** nhân 1 lo nhận diện, nhân 0 lo OLED/LED/buzzer — tiếng bíp không làm chậm nhận diện.
- **Chống báo nhầm** (T9 trong [file tình huống](../../06_reports_slides/tinh_huong_thuc_te_va_tieu_chi_danh_gia.md)):
  - Cùng một biển phải xuất hiện **3 khung liên tiếp** với điểm ≥ 0,6 mới báo.
  - Biển còn trong khung hình thì **không báo lại**; cùng biển đó không báo lại trong **10 giây**.
  - Lớp có số thứ tự ≥ 12 (ví dụ lớp "không phải biển" nếu nhóm thêm sau) → bỏ qua.
- **Cảnh báo:** biển cấm / đi chậm → LED nháy 3 lần + 3 tiếng bíp dồn dập; biển khác → 1 nhịp. OLED hiện icon + tên biển trong 3 giây.
- **Biển tốc độ** (40/50/60) được nhớ và hiện cố định trên màn hình chờ đến khi gặp biển tốc độ mới.
- **Camera bị che** (T8): ảnh quá tối hoặc quá phẳng liên tục 2 giây → OLED hiện "CAMERA BI CHE", LED sáng liên tục, tạm ngừng nhận diện; ảnh tốt lại 1 giây thì tự trở lại.
- **Nút GPIO47:** bấm để tắt/bật tiếng buzzer.

Các con số trên (3 khung, 0,6, 10 giây, ngưỡng tối/mờ) nằm ở đầu `src/alert_policy.h` và `src/frame_quality.h`. **Chưa hiệu chỉnh trên bo thật** — xem mục "Khi có bo" bên dưới.

## Build / nạp / xem log

```bash
./05_firmware_esp32s3/pio.sh traffic_sign_alert
```

```bash
./05_firmware_esp32s3/pio.sh traffic_sign_alert run -t upload
```

```bash
./05_firmware_esp32s3/pio.sh traffic_sign_alert device monitor | tee alert_log.txt
```

Build đã kiểm chứng: **SUCCESS**, RAM 8,9%, Flash ~577 KB / 6 MB. **Chưa chạy trên bo thật.**

## Log để đánh giá demo

| Dòng | Khi nào | Cột |
|---|---|---|
| `CSV,sensor,...` | lúc khởi động | tên cảm biến camera thật (`OV2640` / `OV3660` / `OV5640`), mã PID |
| `CSV,i2c,...` | lúc khởi động | cổng I2C và các địa chỉ trả lời — OLED đúng dây sẽ có `0x3C` |
| `CSV,status,...` | mỗi giây | `t_ms, fps, top, score, brightness, sharpness, blocked, speed_class` |
| `CSV,alert,...` | mỗi lần cảnh báo | `t_ms, class, qcvn, score` |
| `CSV,blocked,...` | khi camera bị che / hết che | `t_ms, state` |

Khi phát lại video đường phố trước camera (Mục 7.1 file tình huống), đối chiếu thời điểm các dòng `CSV,alert` với các biển có trong video để đếm **báo đúng / bỏ sót / báo nhầm**.

## Mô phỏng khi chưa có bo

Camera không mô phỏng được, nên thay bằng **kịch bản** trong [`src/sim_scenario.h`](src/sim_scenario.h): mỗi bước quy định ảnh giả (bình thường / tối đen như bị che) và "model nhìn thấy biển gì, điểm bao nhiêu". Phần còn lại — đo độ sáng/độ nét, phát hiện camera bị che, quy tắc chống báo nhầm, OLED/LED/buzzer — là **code thật**. Kịch bản ~30 giây gồm: biển thoáng qua 2 khung, điểm thấp, biển cấm thật, gặp lại trong 10 giây, biển tốc độ 50, đi chậm, lấy tay che camera, biển tốc độ 40.

**Cách 1 — chạy ngay trên máy tính (không cần cài gì thêm):**

```bash
c++ -std=c++17 -I05_firmware_esp32s3/traffic_sign_alert/src -I05_firmware_esp32s3/peripherals_test/src 05_firmware_esp32s3/traffic_sign_alert/host_tests/sim_run.cpp -o /tmp/sim_run && /tmp/sim_run
```

In ra dòng thời gian "lúc nào OLED hiện gì, LED/còi làm gì", cuối cùng tự kiểm tra: phải có đúng 4 lần cảnh báo + 1 lần báo camera bị che. Hiện **đúng như mong đợi**.

**Cách 2 — xem màn hình OLED, LED, còi chạy trên Wokwi (VS Code):**

1. Cài extension **Wokwi Simulator** trong VS Code, đăng nhập Wokwi và lấy license miễn phí theo hướng dẫn của extension.
2. Build bản mô phỏng (không dùng camera, không dùng PSRAM):
   ```bash
   ./05_firmware_esp32s3/pio.sh traffic_sign_alert run -e wokwi
   ```
3. Mở thư mục `~/ce340-build/05_firmware_esp32s3/traffic_sign_alert` trong VS Code (firmware nằm ở thư mục gương do `pio.sh` tạo), mở `diagram.json` → bấm ▶. Sơ đồ mạch giống `peripherals_test` của Hôn.
4. Log Serial có thêm dòng `CSV,sim,...` báo đang ở bước nào của kịch bản để đối chiếu với màn hình.

Build bản Wokwi đã kiểm chứng: **SUCCESS**. **Chưa chạy thử trên Wokwi** (máy chưa cài extension). `pio.sh traffic_sign_alert` / `run -t upload` mặc định vẫn chỉ build và nạp bản cho bo thật.

## Kiểm thử logic trên máy tính (không cần bo)

```bash
c++ -std=c++17 -I05_firmware_esp32s3/traffic_sign_alert/src 05_firmware_esp32s3/traffic_sign_alert/host_tests/test_logic.cpp -o /tmp/test_logic && /tmp/test_logic
```

10 bài kiểm thử cho quy tắc chống báo nhầm (cần 3 khung, chỉ báo 1 lần, khoảng chờ 10 giây, nhớ biển tốc độ…) và phát hiện camera bị che — hiện **đạt cả 10**.

## Khi có bo

1. Nạp, kiểm tra OLED hiện "DANG QUAN SAT", buzzer kêu chào lúc khởi động. Trong log tìm:
   - `CSV,i2c,0,0x3C` → OLED đúng dây (tiêu chí nghiệm thu `[D3]`). Không thấy `0x3C` → kiểm tra thứ tự chân VCC/GND/SCL/SDA in trên module.
   - `CSV,sensor,OV3660,...` (hoặc OV2640) → loại camera thật. Đưa một biển báo vào **góc trên-phải** khung hình và xem cột `top` trong `CSV,status` có đổi không; nếu ảnh vẫn ngược, chỉnh `set_vflip` / `set_hmirror` trong `mock_inference_test/src/camera_sensor.h`.
2. **Hiệu chỉnh ngưỡng camera bị che:** xem cột `brightness`, `sharpness` trong `CSV,status` lúc camera nhìn bình thường và lúc lấy tay che → sửa `dark_below`, `flat_below` trong `src/frame_quality.h`.
3. **Ngưỡng điểm `min_score`:** model mock chỉ đoán ngẫu nhiên, nên số lần báo lúc này không có ý nghĩa. Khi có model thật của Sơn, chạy video demo và chỉnh `min_score` / `confirm_frames` cho cân bằng giữa bỏ sót và báo nhầm.
4. **Đổi model:** khai báo trong `mock_inference_test/src/models.h`, sửa `kAppModel` ở đầu `src/main.cpp` nếu model không đứng đầu danh sách.

## Lưu ý kỹ thuật

- Buzzer (driver của Hôn) dùng `LEDC_TIMER_0 / CHANNEL_0`, nên camera ở đây dùng `LEDC_TIMER_1 / CHANNEL_1` — trùng nhau thì camera mất xung clock.
- Camera dùng I2C1, OLED dùng I2C0, cả hai dùng driver I2C "legacy" (đặt trong `sdkconfig.defaults`). Trộn driver I2C cũ và mới sẽ làm ESP-IDF dừng ngay khi khởi động.
