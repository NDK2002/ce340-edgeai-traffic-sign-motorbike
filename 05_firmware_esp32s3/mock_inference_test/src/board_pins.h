// Pinout ESP32-S3-CAM N16R8 (sơ đồ camera tương thích Freenove ESP32-S3-WROOM CAM).
// Nguồn sự thật: 05_firmware_esp32s3/bom_and_hardware_specs.md — sửa ở đó trước, rồi sửa ở đây.
#pragma once

// --- Camera OV2640 ---
#define CAM_PIN_PWDN   -1
#define CAM_PIN_RESET  -1
#define CAM_PIN_XCLK   15
#define CAM_PIN_SIOD   4
#define CAM_PIN_SIOC   5
#define CAM_PIN_D7     16  // Y9
#define CAM_PIN_D6     17  // Y8
#define CAM_PIN_D5     18  // Y7
#define CAM_PIN_D4     12  // Y6
#define CAM_PIN_D3     10  // Y5
#define CAM_PIN_D2     8   // Y4
#define CAM_PIN_D1     9   // Y3
#define CAM_PIN_D0     11  // Y2
#define CAM_PIN_VSYNC  6
#define CAM_PIN_HREF   7
#define CAM_PIN_PCLK   13

// --- Ngoại vi cảnh báo ghi-đông ([H2] của Hôn dùng chung) ---
#define PIN_OLED_SDA   41
#define PIN_OLED_SCL   42
#define PIN_BUZZER     14  // buzzer passive 5V qua transistor S8050, xuất PWM (LEDC) để tạo tiếng
#define PIN_VIBRATION  1   // motor rung 3V ở tay nắm qua transistor S8050 + diode 1N4148
// OLED 1.3" dùng chip SH1106 (không phải SSD1306), địa chỉ I2C thường 0x3C
#define PIN_ALERT_LED  21
#define PIN_BUTTON     47  // tùy chọn, pull-up nội
