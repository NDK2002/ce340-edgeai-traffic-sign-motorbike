# 05_firmware_esp32s3 — Phần cứng, Ngoại vi & Firmware TFLite Micro

* **Phụ trách chính:** Vũ Văn Duy (`[D1]`, `[D2]`), Trần Hoàng Hôn (`[H2]` ngoại vi `OLED`, `Buzzer`, `LED`)
* **Hướng phần cứng đã chốt:** bản tối giản trên breadboard, cảnh báo bằng OLED + LED + buzzer passive. Không làm hộp chống nước, không motor rung. Demo chính là phát lại video đường phố trước camera đặt trên bàn; chỉ gắn tạm lên xe để quay clip khi trời khô.

## Sản phẩm

| File / thư mục | Nội dung | Trạng thái |
|---|---|---|
| [`bom_and_hardware_specs.md`](./bom_and_hardware_specs.md) | `[D1]` Chọn bo `ESP32-S3-CAM N16R8`, BOM tối giản, bảng chân (né `GPIO 33–37` PSRAM), ngân sách bộ nhớ, cách lắp tạm và demo | Đề xuất, chờ đặt hàng |
| [`images/`](./images/) | Sơ đồ đấu dây, hướng dẫn chọn bo/camera, hình minh hoạ linh kiện nhóm B/C | Xong |
| [`mock_inference_test/`](./mock_inference_test/README.md) | `[D2]` Firmware benchmark: Flash/PSRAM, Tensor Arena và `Invoke()` của mọi model trong `models.h` (PSRAM vs SRAM), thời gian chụp QVGA/VGA, pipeline đầu-cuối theo phương án A/B/C/C2, soak 30 phút (mA, nhiệt độ, FPS), ghi số liệu ra `/sdcard/bench.csv` | Build thành công, **chưa chạy trên bo thật** |
| [`pio.sh`](./pio.sh) | Build/nạp firmware khi repo nằm ở đường dẫn có dấu cách | Xong |
| [`peripherals_test/`](./peripherals_test/README.md) | `[H2]` Driver test OLED SH1106 / buzzer PWM / LED đỏ / nút mute (Hôn) | Hoàn thành |
