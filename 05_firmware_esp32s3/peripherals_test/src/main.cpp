// [H2] Firmware test ngoại vi cảnh báo ghi-đông — CE340
// Trần Hoàng Hôn (MSSV: 26410046) — Trưởng nhóm / Giao tiếp ngoại vi
//
// Ngoại vi kiểm thử:
//   1. Màn hình OLED 1.3" I2C SH1106 (SDA=GPIO41, SCL=GPIO42, Addr=0x3C)
//   2. Còi Buzzer passive 5V qua transistor S8050 (GPIO14, PWM LEDC)
//   3. Đèn LED đỏ siêu sáng cảnh báo (GPIO21)
//   4. Nút bấm tắt/bật tiếng cảnh báo (GPIO47, pull-up)
//
// Vòng lặp mô phỏng lần lượt 12 lớp biển báo trong `01_dataset/classes.yaml`
// với bitmap icon 32x32, âm thanh và tín hiệu LED tương ứng cấp độ cảnh báo.

#include <cstdio>
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "sh1106_oled.h"
#include "buzzer_alert.h"
#include "led_alert.h"
#include "sign_icons.h"

static const char *TAG = "H2_PERIPH";

namespace {

// Cấu hình chân (né tuyệt đối GPIO 33-37 của Octal PSRAM)
constexpr int PIN_OLED_SDA = 41;
constexpr int PIN_OLED_SCL = 42;
constexpr int PIN_BUZZER   = 14;
constexpr int PIN_LED      = 21;
constexpr int PIN_BTN      = 47;

ce340::SH1106Oled g_oled(I2C_NUM_0, PIN_OLED_SDA, PIN_OLED_SCL);
ce340::BuzzerAlert g_buzzer(PIN_BUZZER);
ce340::LedAlert g_led(static_cast<gpio_num_t>(PIN_LED));
ce340::MuteButton g_btn(static_cast<gpio_num_t>(PIN_BTN));

void render_splash() {
  g_oled.clear();
  g_oled.draw_rect(0, 0, 128, 64, false);
  g_oled.draw_rect(2, 2, 124, 60, false);
  g_oled.draw_string(14, 8,  "CE340 - EDGE AI");
  g_oled.draw_string(8,  22, "CANH BAO BIEN BAO");
  g_oled.draw_string(16, 36, "XE MAY - TINYML");
  g_oled.draw_string(10, 48, "[H2] HOANG HON QA");
  g_oled.update();

  g_buzzer.chirp_boot();
  g_led.alert_medium();
  vTaskDelay(pdMS_TO_TICKS(2000));
}

void render_sign_ui(const SignInfo &sign, bool is_muted, int index) {
  g_oled.clear();

  // 1. Thanh tiêu đề trên cùng
  char header[32];
  std::snprintf(header, sizeof(header), "[%02d/11] %s", index, sign.qcvn);
  g_oled.draw_string(2, 2, header);
  g_oled.draw_line_h(0, 12, 128);

  // 2. Icon biển báo 32x32 bên trái
  g_oled.draw_bitmap_32x32(4, 16, sign.bitmap);
  g_oled.draw_rect(2, 14, 36, 36, false); // Khung viền icon

  // 3. Tên và nhóm biển báo bên phải
  g_oled.draw_string(42, 16, sign.name_vi);

  char group_str[24];
  if (std::strcmp(sign.group, "cam") == 0) {
    std::snprintf(group_str, sizeof(group_str), "Nhom: BIEN CAM");
  } else if (std::strcmp(sign.group, "toc_do") == 0) {
    std::snprintf(group_str, sizeof(group_str), "Nhom: TOC DO");
  } else if (std::strcmp(sign.group, "hieu_lenh") == 0) {
    std::snprintf(group_str, sizeof(group_str), "Nhom: HIEU LENH");
  } else {
    std::snprintf(group_str, sizeof(group_str), "Nhom: NGUY HIEM");
  }
  g_oled.draw_string(42, 28, group_str);

  // Mức cảnh báo
  if (std::strcmp(sign.alert_level, "high") == 0) {
    g_oled.draw_string(42, 40, "MUC: NGUY HIEM!");
  } else {
    g_oled.draw_string(42, 40, "MUC: CANH BAO");
  }

  // 4. Thanh trạng thái dưới cùng
  g_oled.draw_line_h(0, 52, 128);
  char status[32];
  std::snprintf(status, sizeof(status), "COI: %s | DEMO", is_muted ? "TAT" : "BAT");
  g_oled.draw_string(2, 54, status);

  g_oled.update();
}

} // namespace

extern "C" void app_main(void) {
  ESP_LOGI(TAG, "=================================================");
  ESP_LOGI(TAG, "  CE340 [H2] TEST NGOAI VI GHI-DONG (OLED/BUZZER/LED)");
  ESP_LOGI(TAG, "  Tran Hoang Hon (MSSV: 26410046)");
  ESP_LOGI(TAG, "=================================================");

  // 1. Khởi tạo toàn bộ ngoại vi
  bool oled_ok = g_oled.init();
  bool bz_ok = g_buzzer.init();
  bool led_ok = g_led.init();
  bool btn_ok = g_btn.init();

  ESP_LOGI(TAG, "Trang thai: OLED=%s | Buzzer=%s | LED=%s | Button=%s",
           oled_ok ? "OK" : "LOI", bz_ok ? "OK" : "LOI",
           led_ok ? "OK" : "LOI", btn_ok ? "OK" : "LOI");

  if (oled_ok) {
    render_splash();
  }

  ESP_LOGI(TAG, "Bat dau vong lap kiem thu 12 bien bao giao thong...");
  int sign_idx = 0;

  while (true) {
    const SignInfo &sign = kSigns[sign_idx];
    bool is_high = (std::strcmp(sign.alert_level, "high") == 0);

    ESP_LOGI(TAG, "[Class %02d] %s - %s (Nhom: %s, Cap do: %s)",
             sign.id, sign.qcvn, sign.name_vi, sign.group, sign.alert_level);

    // Cập nhật giao diện màn hình OLED
    if (oled_ok) {
      render_sign_ui(sign, g_buzzer.is_muted(), sign_idx);
    }

    // Kích hoạt tín hiệu LED & Buzzer theo cấp độ cảnh báo
    if (is_high) {
      // Biển cấm / nguy hiểm cao: 3 nháy LED + 3 bíp dồn dập
      g_led.alert_high();
      g_buzzer.alert_high();
    } else {
      // Biển hiệu lệnh / tốc độ: 1 nhịp LED + 1 bíp ngắn
      g_led.alert_medium();
      g_buzzer.alert_medium();
    }

    // Khoảng thời gian dừng giữa 2 biển để quan sát (2.5 giây)
    // Đồng thời quét kiểm tra nút bấm tắt tiếng (Mute toggle)
    for (int t = 0; t < 25; ++t) {
      if (g_btn.is_pressed()) {
        bool new_mute = !g_buzzer.is_muted();
        g_buzzer.set_mute(new_mute);
        ESP_LOGW(TAG, "-> Nút bấm: %s coi buzzer!", new_mute ? "TAT (MUTE)" : "BAT");
        if (oled_ok) {
          render_sign_ui(sign, new_mute, sign_idx);
        }
        vTaskDelay(pdMS_TO_TICKS(300)); // Chống dội phím (debounce)
      }
      vTaskDelay(pdMS_TO_TICKS(100));
    }

    // Chuyển sang biển tiếp theo
    sign_idx = (sign_idx + 1) % 12;
  }
}
