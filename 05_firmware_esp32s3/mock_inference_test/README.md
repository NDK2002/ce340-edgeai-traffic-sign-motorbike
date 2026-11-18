# [D2] mock_inference_test — Kiểm tra phần cứng & tflite-micro

Firmware thử (ESP-IDF qua PlatformIO) cho bo **ESP32-S3-CAM N16R8**. Nó in ra Serial:

| Số liệu | Dùng cho ai |
|---|---|
| Flash / PSRAM thực tế, RAM còn trống | Xác nhận đúng bo N16R8 |
| Tensor Arena model đã dùng + gợi ý `kTensorArenaSize` | Sơn (`[S2]`) — ngân sách model |
| Thời gian `Invoke()` khi arena ở PSRAM vs SRAM trong | Báo cáo Latency |
| Camera init OK + thời gian chụp 1 frame QVGA | Xác nhận pinout cho Hôn (`[H2]`), ngân sách 150 ms |

Model đang dùng là **mock phân loại** (`01_dataset/mock_assets/mock_model_int8.h`, input 160×160×3, output 12 lớp). Số arena/latency này **thấp hơn nhiều** so với model phát hiện thật — chỉ để chứng minh pipeline chạy thông.

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
RAM:   [=         ]   8.0% (used 26064 bytes from 327680 bytes)
Flash: [=         ]   7.9% (used 495544 bytes from 6291456 bytes)
```

Firmware chiếm ~484 KB trên phân vùng app 6 MB → còn ~5.5 MB cho model thật. Các `warning: ... shadows a parameter` trong log đến từ thư viện tflite-micro, không ảnh hưởng.

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
| `Didn't find op for builtin opcode` | Model cần op chưa đăng ký → thêm vào `register_ops()` |

## Khi có model thật từ Sơn

Đổi `#include "mock_model_int8.h"` và đường dẫn `INCLUDE_DIRS` trong `src/CMakeLists.txt` sang file `.h` mới, rồi build lại. Không cần sửa logic đo.
