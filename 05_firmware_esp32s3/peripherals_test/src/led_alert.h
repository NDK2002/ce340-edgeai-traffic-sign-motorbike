#pragma once

#include "driver/gpio.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

namespace ce340 {

class LedAlert {
 public:
  explicit LedAlert(gpio_num_t pin = GPIO_NUM_21) : pin_(pin) {}

  bool init() {
    gpio_config_t io_conf = {};
    io_conf.intr_type = GPIO_INTR_DISABLE;
    io_conf.mode = GPIO_MODE_OUTPUT;
    io_conf.pin_bit_mask = (1ULL << pin_);
    io_conf.pull_down_en = GPIO_PULLDOWN_DISABLE;
    io_conf.pull_up_en = GPIO_PULLUP_DISABLE;
    esp_err_t err = gpio_config(&io_conf);
    if (err != ESP_OK) {
      ESP_LOGE("LED", "gpio_config failed: %s", esp_err_to_name(err));
      return false;
    }
    off();
    ESP_LOGI("LED", "Khởi tạo LED cảnh báo trên GPIO %d", pin_);
    return true;
  }

  void on() { gpio_set_level(pin_, 1); }
  void off() { gpio_set_level(pin_, 0); }

  void alert_high() {
    for (int i = 0; i < 3; ++i) {
      on();
      vTaskDelay(pdMS_TO_TICKS(80));
      off();
      if (i < 2) vTaskDelay(pdMS_TO_TICKS(50));
    }
  }

  void alert_medium() {
    on();
    vTaskDelay(pdMS_TO_TICKS(180));
    off();
  }

 private:
  gpio_num_t pin_;
};

class MuteButton {
 public:
  explicit MuteButton(gpio_num_t pin = GPIO_NUM_47) : pin_(pin) {}

  bool init() {
    gpio_config_t io_conf = {};
    io_conf.intr_type = GPIO_INTR_DISABLE;
    io_conf.mode = GPIO_MODE_INPUT;
    io_conf.pin_bit_mask = (1ULL << pin_);
    io_conf.pull_down_en = GPIO_PULLDOWN_DISABLE;
    io_conf.pull_up_en = GPIO_PULLUP_ENABLE; // Pull-up nội, nhấn nút nối xuống GND
    esp_err_t err = gpio_config(&io_conf);
    if (err != ESP_OK) {
      ESP_LOGE("BUTTON", "gpio_config failed: %s", esp_err_to_name(err));
      return false;
    }
    ESP_LOGI("BUTTON", "Khởi tạo Nút nhấn trên GPIO %d (Pull-up)", pin_);
    return true;
  }

  bool is_pressed() const {
    return (gpio_get_level(pin_) == 0); // Active LOW
  }

 private:
  gpio_num_t pin_;
};

} // namespace ce340
