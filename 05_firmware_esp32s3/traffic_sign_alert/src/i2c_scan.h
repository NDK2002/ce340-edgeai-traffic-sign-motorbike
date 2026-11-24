// Quét bus I2C: liệt kê địa chỉ thiết bị trả lời (kiểm tra nhanh dây OLED khi lắp mạch [D3]).
// OLED SH1106 đúng dây sẽ hiện 0x3C (một số module là 0x3D).
// Gọi SAU khi driver I2C đã được cài (ví dụ sau SH1106Oled::init()).
#pragma once

#include <cstdio>

#include "driver/i2c.h"
#include "esp_log.h"

namespace ce340 {

// Trả về số thiết bị tìm thấy; in dòng "CSV,i2c,<port>,<địa chỉ...>".
inline int i2c_scan(i2c_port_t port) {
  int found = 0;
  std::printf("CSV,i2c,%d", static_cast<int>(port));
  for (uint8_t addr = 0x08; addr < 0x78; ++addr) {
    i2c_cmd_handle_t cmd = i2c_cmd_link_create();
    i2c_master_start(cmd);
    i2c_master_write_byte(cmd, static_cast<uint8_t>(addr << 1) | I2C_MASTER_WRITE, true);
    i2c_master_stop(cmd);
    const esp_err_t err = i2c_master_cmd_begin(port, cmd, pdMS_TO_TICKS(20));
    i2c_cmd_link_delete(cmd);
    if (err == ESP_OK) {
      std::printf(",0x%02X", addr);
      ++found;
    }
  }
  std::printf("\n");
  if (found == 0) ESP_LOGW("i2c", "Không thấy thiết bị nào trên I2C%d — kiểm tra dây SDA/SCL, VCC/GND của OLED", port);
  return found;
}

}  // namespace ce340
