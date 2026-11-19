# [D2] mock_inference_test — Firmware benchmark trên ESP32-S3

Firmware (ESP-IDF qua PlatformIO) cho bo **ESP32-S3-CAM N16R8**. Chạy một lượt rồi in số liệu cho Chương 4 của báo cáo:

| Bước | Đo gì | Dùng cho |
|---|---|---|
| `hw` | Flash, PSRAM, RAM trống, nhiệt độ chip (lúc khởi động, sau khi nạp model, sau khi bật camera, cuối) | Xác nhận đúng bo N16R8 |
| `sd` | Tốc độ ghi thẻ microSD | Biết có kịp lưu ảnh khi chạy thử trên xe |
| `model` | Mọi model trong `src/models.h`: kích thước, Tensor Arena, `Invoke()` khi arena ở PSRAM và SRAM | Bảng so sánh FP32 / INT8 / pruned / KD — phần tối ưu của Sơn |
| `camera` | Thời gian lấy 1 frame QVGA và VGA (RGB565) | Chọn phương án input |
| `pipeline` | Chụp → crop ROI góc trên-phải + resize → `Invoke` → argmax, đo từng khâu, theo phương án A/B/C | Latency toàn hệ thống, FPS thực tế |
| `soak` | Chạy pipeline liên tục 30 phút, mỗi 10 giây in FPS, nhiệt độ, PSRAM trống, số lỗi | Đo dòng (mA) trên USB tester, độ ổn định |

Phương án A/B/C lấy từ Mục 4 của [`tinh_huong_thuc_te_va_tieu_chi_danh_gia.md`](../../06_reports_slides/tinh_huong_thuc_te_va_tieu_chi_danh_gia.md):

| Tên | Frame | Vùng đưa vào model |
|---|---|---|
| `A_qvga_full` | QVGA 320×240 | Cả khung, thu nhỏ về input model |
| `B_qvga_roi160` | QVGA 320×240 | Ô 160×160 góc trên-phải |
| `C_vga_roi160` | VGA 640×480 | Ô 160×160 góc trên-phải (dùng khi soak) |
| `C2_vga_roi320` | VGA 640×480 | Ô 320×320 góc trên-phải, thu nhỏ về input model |

Các tham số đo (số lần chạy, thời gian soak, model dùng cho pipeline, lề ROI) nằm ở đầu `src/main.cpp`, mục "Cấu hình đo".

### Lấy số liệu

Mọi dòng số liệu bắt đầu bằng `CSV,` (dòng `CSV,#...` là tiêu đề cột). Nếu có thẻ microSD, các dòng này được ghi thêm vào `/sdcard/bench.csv` (ghi nối tiếp qua mỗi lần chạy).

```bash
./05_firmware_esp32s3/pio.sh mock_inference_test device monitor | tee bench_log.txt
```

```bash
grep '^CSV,' bench_log.txt > bench.csv
```

Đổi thành bảng Markdown + biểu đồ cho báo cáo (đọc được cả `bench.csv` chép từ thẻ nhớ lẫn log Serial; biểu đồ cần `matplotlib`):

```bash
python3 05_firmware_esp32s3/tools/bench_report.py bench.csv -o bench_report.md --charts charts/
```

### Lưu ý khi đọc số liệu

- Bước `model` cho input toàn số 0: chỉ đo thời gian, không đo độ chính xác.
- Model mock là **model phân loại** 160×160×3, nên số arena/latency của nó **thấp hơn nhiều** so với model thật — chỉ để chứng minh pipeline chạy thông.
- Tiền xử lý giả định model huấn luyện với ảnh chuẩn hoá về `[0, 1]` (hàm `build_lut`). Model của Trung/Sơn dùng cách chuẩn hoá khác thì sửa ở đó.
- Thứ tự màu RGB565 theo `esp32-camera`. Khi có bo, chụp thử biển đỏ và kiểm tra kênh R có cao nhất không.
- Trong lúc soak, chip chạy liên tục: đây là lúc đọc dòng (mA) trên USB tester. Sau khi soak xong chip ở trạng thái nghỉ: đọc thêm dòng lúc nghỉ để so sánh.

## ⚠️ Repo nằm ở đường dẫn có dấu cách? Dùng `pio.sh`

ESP-IDF từ chối build nếu đường dẫn có dấu cách (`Error: Detected a whitespace character in project paths`). Có 2 cách:

1. **Giữ repo ở chỗ cũ (khuyên dùng nếu thư mục môn học có dấu cách):** chạy script [`../pio.sh`](../pio.sh) từ thư mục gốc repo. Script chép code sang `~/ce340-build/` (không dấu) rồi build ở đó. Sửa code, commit, push vẫn làm trong repo gốc như bình thường.
   ```bash
   ./05_firmware_esp32s3/pio.sh
   ```
   ```bash
   ./05_firmware_esp32s3/pio.sh mock_inference_test run -t upload
   ```
   ```bash
   ./05_firmware_esp32s3/pio.sh mock_inference_test device monitor
   ```
2. **Hoặc** clone repo vào đường dẫn không dấu (`~/projects/ce340/`, `D:\projects\ce340\`) và dùng thẳng các lệnh `pio` ở mục dưới.

`~/ce340-build/` chỉ là chỗ build tạm: **không sửa code ở đó** (lần chạy sau sẽ bị ghi đè), xoá đi lúc nào cũng được.

## Kết quả build đã kiểm chứng (18/11/2026)

`pio run` → **SUCCESS** trên macOS Apple Silicon, ESP-IDF 5.3.1, `esp-tflite-micro` 1.4.3, `esp32-camera` 2.1.9:

```
RAM:   [=         ]   8.7% (used 28448 bytes from 327680 bytes)
Flash: [=         ]  10.3% (used 650496 bytes from 6291456 bytes)
```

Firmware chiếm ~635 KB trên phân vùng app 6 MB → còn ~5.3 MB cho các model. Các `warning: ... shadows a parameter` trong log đến từ thư viện tflite-micro, không ảnh hưởng.

## Cài đặt (một lần)

1. Cài **VS Code** → tab Extensions → cài **PlatformIO IDE**.
2. Mở thư mục `05_firmware_esp32s3/mock_inference_test/` trong VS Code (mở đúng thư mục này, không mở cả repo).
3. Lần build đầu PlatformIO tự tải toolchain ESP-IDF (~1 GB) và các component `esp-tflite-micro`, `esp32-camera` — mất 10–20 phút.

Hoặc dùng dòng lệnh:

```bash
pip install -U platformio
```

## Build / nạp / xem log

```bash
pio run
```

```bash
pio run -t upload
```

```bash
pio device monitor
```

**Mục tiêu bắt buộc của Tuần 4 khi chưa có bo:** chỉ cần `pio run` báo `SUCCESS` (compile pass), rồi ghi lại kích thước Flash/RAM ở cuối log build.

## Xử lý lỗi thường gặp

| Hiện tượng | Nguyên nhân hay gặp |
|---|---|
| `Bad CPU type in executable: .../tool-cmake/bin/cmake` | Mac M1/M2/M3 — đã xử lý bằng `platform_packages = platformio/tool-cmake@~3.30.2` trong `platformio.ini` |
| Máy không nhận cổng COM | Cáp Type-C chỉ sạc, không có dây dữ liệu → đổi cáp; thử cổng Type-C còn lại |
| Không nạp được | Giữ nút **BOOT**, nhấn **RST**, thả BOOT rồi nạp lại |
| Bo reset liên tục, log báo lỗi PSRAM | Bo không phải N16R8 hoặc sai mode PSRAM (`CONFIG_SPIRAM_MODE_OCT`) |
| `Camera init lỗi 0x105` / `0x20004` | Cáp camera cắm lỏng/ngược, hoặc pinout bo khác Freenove → sửa `src/board_pins.h` |
| `Didn't find op for builtin opcode` | Model cần op chưa đăng ký → thêm vào hàm `resolver()` trong `main.cpp` |

## Thêm model để benchmark

1. Đặt file `.h` (mảng C của `.tflite`) vào `04_tinyml_optimization/`.
2. Trong `src/models.h`: thêm 1 dòng `#include` và 1 dòng trong `kModels`.
3. Build và nạp lại. Model nào thiếu op thì log báo lỗi `AllocateTensors()` kèm tên op → thêm vào hàm `resolver()` trong `main.cpp`.

Model đứng đầu `kModels` (`kPipelineModel = 0`) được dùng cho bước `pipeline` và `soak`.
