#pragma once

#include "driver/ledc.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

namespace ce340 {

class BuzzerAlert {
 public:
  static constexpr ledc_mode_t kSpeedMode = LEDC_LOW_SPEED_MODE;
  static constexpr ledc_timer_t kTimer = LEDC_TIMER_0;
  static constexpr ledc_channel_t kChannel = LEDC_CHANNEL_0;
  static constexpr ledc_timer_bit_t kResolution = LEDC_TIMER_10_BIT; // Duty: 0..1023 (50% = 512)

  explicit BuzzerAlert(int pin = 14) : pin_(pin), muted_(false) {}

  bool init() {
    ledc_timer_config_t timer_conf = {};
    timer_conf.speed_mode = kSpeedMode;
    timer_conf.duty_resolution = kResolution;
    timer_conf.timer_num = kTimer;
    timer_conf.freq_hz = 2700; // Tần số mặc định 2.7 kHz
    timer_conf.clk_cfg = LEDC_AUTO_CLK;
    esp_err_t err = ledc_timer_config(&timer_conf);
    if (err != ESP_OK) {
      ESP_LOGE("BUZZER", "ledc_timer_config failed: %s", esp_err_to_name(err));
      return false;
    }

    ledc_channel_config_t ch_conf = {};
    ch_conf.gpio_num = pin_;
    ch_conf.speed_mode = kSpeedMode;
    ch_conf.channel = kChannel;
    ch_conf.timer_sel = kTimer;
    ch_conf.duty = 0; // Khởi đầu im lặng
    ch_conf.hpoint = 0;
    err = ledc_channel_config(&ch_conf);
    if (err != ESP_OK) {
      ESP_LOGE("BUZZER", "ledc_channel_config failed: %s", esp_err_to_name(err));
      return false;
    }

    stop();
    ESP_LOGI("BUZZER", "Khởi tạo Buzzer PWM thành công trên GPIO %d", pin_);
    return true;
  }

  void set_mute(bool mute) { muted_ = mute; }
  bool is_muted() const { return muted_; }

  void tone(uint32_t freq_hz, uint32_t duration_ms) {
    if (muted_ || freq_hz == 0) return;
    ledc_set_freq(kSpeedMode, kTimer, freq_hz);
    ledc_set_duty(kSpeedMode, kChannel, 512); // 50% duty cycle
    ledc_update_duty(kSpeedMode, kChannel);
    vTaskDelay(pdMS_TO_TICKS(duration_ms));
    stop();
  }

  void stop() {
    ledc_set_duty(kSpeedMode, kChannel, 0);
    ledc_update_duty(kSpeedMode, kChannel);
  }

  // Cảnh báo biển cấm / nguy hiểm cao (P.102, P.123, P.124, P.104, W.245):
  // 3 tiếng dồn dập (80ms bíp, 40ms nghỉ)
  void alert_high() {
    if (muted_) return;
    for (int i = 0; i < 3; ++i) {
      tone(2700, 80);
      if (i < 2) vTaskDelay(pdMS_TO_TICKS(40));
    }
  }

  // Cảnh báo hiệu lệnh, tốc độ, cảnh báo giao lộ:
  // 1 tiếng bíp ngắn dứt khoát (120ms)
  void alert_medium() {
    if (muted_) return;
    tone(2200, 120);
  }

  // Tiếng chirp chào khi khởi động
  void chirp_boot() {
    tone(2000, 50);
    vTaskDelay(pdMS_TO_TICKS(30));
    tone(2800, 70);
  }

 private:
  int pin_;
  bool muted_;
};

} // namespace ce340

