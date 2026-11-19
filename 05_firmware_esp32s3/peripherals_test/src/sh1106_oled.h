#pragma once

#include <cstring>
#include "driver/i2c.h"
#include "esp_log.h"
#include "font5x7.h"

namespace ce340 {

class SH1106Oled {
 public:
  static constexpr uint8_t kI2CAddr = 0x3C;
  static constexpr int kWidth = 128;
  static constexpr int kHeight = 64;
  static constexpr int kPages = 8;
  static constexpr uint8_t kColOffset = 2; // SH1106 có 132 cột, panel 128x64 thường căn giữa ở offset 2

  SH1106Oled(i2c_port_t port = I2C_NUM_0, int sda = 41, int scl = 42)
      : port_(port), sda_(sda), scl_(scl) {
    std::memset(buffer_, 0, sizeof(buffer_));
  }

  bool init() {
    i2c_config_t conf = {};
    conf.mode = I2C_MODE_MASTER;
    conf.sda_io_num = sda_;
    conf.sda_pullup_en = GPIO_PULLUP_ENABLE;
    conf.scl_io_num = scl_;
    conf.scl_pullup_en = GPIO_PULLUP_ENABLE;
    conf.master.clk_speed = 400000;

    esp_err_t err = i2c_param_config(port_, &conf);
    if (err != ESP_OK) {
      ESP_LOGE("OLED", "i2c_param_config failed: %s", esp_err_to_name(err));
      return false;
    }
    err = i2c_driver_install(port_, conf.mode, 0, 0, 0);
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
      ESP_LOGE("OLED", "i2c_driver_install failed: %s", esp_err_to_name(err));
      return false;
    }

    // Lệnh khởi tạo chuẩn cho SH1106 1.3" 128x64
    static const uint8_t init_cmds[] = {
        0xAE,       // Display OFF
        0x02, 0x10, // Set lower/upper column
        0x40,       // Start line 0
        0xB0,       // Set page 0
        0x81, 0xCF, // Set Contrast (0xCF sáng rõ ngoài trời)
        0xA1,       // Set Segment Re-map (đảo trái-phải để đúng chiều)
        0xA6,       // Normal display (không đảo màu)
        0xA8, 0x3F, // Multiplex ratio (1/64)
        0xAD, 0x8B, // DC-DC control: bật bơm áp nội bộ (8B = ON)
        0x33,       // Set pump voltage 9V
        0xC8,       // Set COM Output Scan Direction (đảo trên-dưới)
        0xD3, 0x00, // Display offset = 0
        0xD5, 0x80, // Set display clock divide ratio/oscillator freq
        0xD9, 0x1F, // Dis-charge / Pre-charge Period
        0xDA, 0x12, // Common pads hardware config
        0xDB, 0x40, // VCOM deselect level
        0xAF        // Display ON
    };

    for (size_t i = 0; i < sizeof(init_cmds); ++i) {
      if (!write_cmd(init_cmds[i])) {
        ESP_LOGE("OLED", "Gửi lệnh khởi tạo 0x%02X thất bại", init_cmds[i]);
        return false;
      }
    }

    clear();
    update();
    ESP_LOGI("OLED", "Khởi tạo SH1106 thành công (SDA=%d, SCL=%d)", sda_, scl_);
    return true;
  }

  void clear() {
    std::memset(buffer_, 0, sizeof(buffer_));
  }

  void fill(uint8_t pattern = 0xFF) {
    std::memset(buffer_, pattern, sizeof(buffer_));
  }

  void set_pixel(int x, int y, bool color = true) {
    if (x < 0 || x >= kWidth || y < 0 || y >= kHeight) return;
    int page = y / 8;
    int bit = y % 8;
    int idx = page * kWidth + x;
    if (color) {
      buffer_[idx] |= (1 << bit);
    } else {
      buffer_[idx] &= ~(1 << bit);
    }
  }

  void draw_line_h(int x, int y, int w, bool color = true) {
    for (int i = 0; i < w; ++i) set_pixel(x + i, y, color);
  }

  void draw_line_v(int x, int y, int h, bool color = true) {
    for (int i = 0; i < h; ++i) set_pixel(x, y + i, color);
  }

  void draw_rect(int x, int y, int w, int h, bool fill = false, bool color = true) {
    if (fill) {
      for (int dy = 0; dy < h; ++dy) draw_line_h(x, y + dy, w, color);
    } else {
      draw_line_h(x, y, w, color);
      draw_line_h(x, y + h - 1, w, color);
      draw_line_v(x, y, h, color);
      draw_line_v(x + w - 1, y, h, color);
    }
  }

  void draw_char(int x, int y, char c, bool color = true) {
    if (c < 0x20 || c > 0x7E) c = '?';
    const uint8_t *glyph = FONT5x7[c - 0x20];
    for (int col = 0; col < 5; ++col) {
      uint8_t line = glyph[col];
      for (int row = 0; row < 7; ++row) {
        if (line & (1 << row)) {
          set_pixel(x + col, y + row, color);
        }
      }
    }
  }

  void draw_string(int x, int y, const char *str, bool color = true) {
    int cur_x = x;
    while (*str) {
      if (*str == '\n') {
        cur_x = x;
        y += 9;
      } else {
        draw_char(cur_x, y, *str, color);
        cur_x += 6;
      }
      ++str;
    }
  }

  // Vẽ bitmap 32x32 (32 dòng, mỗi dòng 4 byte, MSB là bit ngoài cùng bên trái)
  void draw_bitmap_32x32(int x, int y, const uint8_t *bitmap, bool color = true) {
    for (int row = 0; row < 32; ++row) {
      for (int byte_idx = 0; byte_idx < 4; ++byte_idx) {
        uint8_t b = bitmap[row * 4 + byte_idx];
        for (int bit = 0; bit < 8; ++bit) {
          if (b & (0x80 >> bit)) {
            set_pixel(x + byte_idx * 8 + bit, y + row, color);
          }
        }
      }
    }
  }

  // Đẩy toàn bộ buffer ra màn hình SH1106 (8 trang)
  void update() {
    for (uint8_t page = 0; page < kPages; ++page) {
      write_cmd(0xB0 + page);                      // Chọn Page 0..7
      write_cmd(0x00 + (kColOffset & 0x0F));        // Lower column
      write_cmd(0x10 + ((kColOffset >> 4) & 0x0F)); // Higher column

      i2c_cmd_handle_t cmd = i2c_cmd_link_create();
      i2c_master_start(cmd);
      i2c_master_write_byte(cmd, (kI2CAddr << 1) | I2C_MASTER_WRITE, true);
      i2c_master_write_byte(cmd, 0x40, true); // Control byte 0x40 = Dữ liệu VRAM
      i2c_master_write(cmd, &buffer_[page * kWidth], kWidth, true);
      i2c_master_stop(cmd);
      i2c_master_cmd_begin(port_, cmd, pdMS_TO_TICKS(100));
      i2c_cmd_link_delete(cmd);
    }
  }

 private:
  bool write_cmd(uint8_t cmd) {
    i2c_cmd_handle_t link = i2c_cmd_link_create();
    i2c_master_start(link);
    i2c_master_write_byte(link, (kI2CAddr << 1) | I2C_MASTER_WRITE, true);
    i2c_master_write_byte(link, 0x00, true); // Control byte 0x00 = Lệnh (Command)
    i2c_master_write_byte(link, cmd, true);
    i2c_master_stop(link);
    esp_err_t ret = i2c_master_cmd_begin(port_, link, pdMS_TO_TICKS(50));
    i2c_cmd_link_delete(link);
    return (ret == ESP_OK);
  }

  i2c_port_t port_;
  int sda_;
  int scl_;
  uint8_t buffer_[kWidth * kPages];
};

} // namespace ce340
