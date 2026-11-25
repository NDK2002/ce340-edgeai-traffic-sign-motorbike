// Nhận diện loại camera thật trên bo và chỉnh cho đúng chiều ảnh.
// Dùng chung cho mock_inference_test và traffic_sign_alert (gọi ngay sau esp_camera_init).
//
// Lý do: shop có thể giao bo kèm OV2640, OV3660 hoặc OV5640. Thư viện esp32-camera tự nhận
// cả 3 loại, nhưng OV3660 mặc định cho ảnh lộn ngược → vùng ROI "góc trên-phải" sẽ cắt nhầm
// sang góc dưới. Chỉnh theo ví dụ CameraWebServer chính thức của Espressif.
#pragma once

#include <cstdio>

#include "esp_camera.h"
#include "esp_log.h"

namespace ce340 {

// In tên cảm biến, chỉnh chiều ảnh; trả về PID (0 nếu không đọc được).
inline int tune_camera_sensor() {
  sensor_t *s = esp_camera_sensor_get();
  if (!s) {
    ESP_LOGE("camera", "Không đọc được thông tin cảm biến");
    return 0;
  }
  const camera_sensor_info_t *info = esp_camera_sensor_get_info(&s->id);
  const char *name = info ? info->name : "?";
  ESP_LOGI("camera", "Cảm biến: %s (PID 0x%04x)", name, s->id.PID);
  std::printf("CSV,sensor,%s,0x%04x\n", name, s->id.PID);

  if (s->id.PID == OV3660_PID) {
    s->set_vflip(s, 1);        // OV3660 mặc định lộn ngược
    s->set_brightness(s, 1);   // hơi tối hơn OV2640 → tăng nhẹ
    s->set_saturation(s, -2);  // màu hơi gắt → giảm nhẹ
  }
  // Nếu ảnh thật vẫn bị ngược trái/phải: thêm s->set_hmirror(s, 1) cho đúng loại cảm biến đó.
  return s->id.PID;
}

}  // namespace ce340
