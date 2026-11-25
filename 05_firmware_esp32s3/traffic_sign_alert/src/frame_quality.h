// Phát hiện camera bị che / quá tối / quá mờ (T8 trong file tình huống thực tế).
// Code thuần C++, không phụ thuộc ESP-IDF → kiểm thử được trên máy tính (host_tests/).
//
// Mỗi khung: lấy mẫu thưa ảnh RGB565 → độ sáng trung bình (0..255) và độ nét (trung bình |gradient|).
// Che bằng tay / áo mưa → ảnh tối hoặc phẳng (gradient gần 0). Kính đọng nước → mờ (gradient thấp).
// Phải xấu LIÊN TỤC bad_hold_ms mới báo, và tốt liên tục good_hold_ms mới gỡ báo, để không nhấp nháy.
//
// Ngưỡng là giá trị khởi đầu, CHƯA hiệu chỉnh: khi có bo, xem cột brightness/sharpness trong
// dòng "CSV,status" lúc camera bình thường và lúc lấy tay che để chọn ngưỡng.
#pragma once

#include <cstdint>
#include <cstdlib>

namespace ce340 {

struct FrameStats {
  float brightness = 0;  // 0..255
  float sharpness = 0;   // trung bình |dx| + |dy| giữa các điểm lấy mẫu
};

// Byte RGB565 của esp32-camera: RRRRRGGG GGGBBBBB (byte cao trước).
inline uint8_t rgb565_gray(const uint8_t *px) {
  const int r = px[0] & 0xF8;
  const int g = ((px[0] & 0x07) << 5) | ((px[1] & 0xE0) >> 3);
  const int b = (px[1] & 0x1F) << 3;
  return static_cast<uint8_t>((r * 77 + g * 150 + b * 29) >> 8);
}

// Lấy mẫu mỗi `step` pixel theo cả 2 chiều (step = 8 trên VGA ≈ 4.800 điểm, rất nhanh).
inline FrameStats measure_frame(const uint8_t *rgb565, int width, int height, int step = 8) {
  FrameStats s;
  if (!rgb565 || width < 2 * step || height < 2 * step) return s;
  uint64_t sum = 0, grad = 0;
  uint32_t n = 0, ng = 0;
  for (int y = 0; y + step < height; y += step) {
    const uint8_t *row = rgb565 + static_cast<size_t>(y) * width * 2;
    const uint8_t *next = rgb565 + static_cast<size_t>(y + step) * width * 2;
    for (int x = 0; x + step < width; x += step) {
      const int g = rgb565_gray(row + x * 2);
      sum += g;
      ++n;
      grad += std::abs(g - rgb565_gray(row + (x + step) * 2)) + std::abs(g - rgb565_gray(next + x * 2));
      ++ng;
    }
  }
  s.brightness = n ? static_cast<float>(sum) / n : 0;
  s.sharpness = ng ? static_cast<float>(grad) / ng : 0;
  return s;
}

struct BlockedConfig {
  float dark_below = 25.0f;     // độ sáng TB thấp hơn → coi là bị che / quá tối
  float flat_below = 4.0f;      // độ nét thấp hơn → coi là bị che / quá mờ
  uint32_t bad_hold_ms = 2000;  // xấu liên tục bao lâu thì báo
  uint32_t good_hold_ms = 1000; // tốt liên tục bao lâu thì gỡ báo
};

class BlockedDetector {
 public:
  explicit BlockedDetector(const BlockedConfig &cfg = BlockedConfig()) : cfg_(cfg) {}

  // Trả về trạng thái sau khi cập nhật: true = đang báo "camera bị che".
  bool update(const FrameStats &s, uint32_t now_ms) {
    const bool bad = s.brightness < cfg_.dark_below || s.sharpness < cfg_.flat_below;
    if (bad) {
      good_since_ = kNone;
      if (bad_since_ == kNone) bad_since_ = now_ms;
      if (!blocked_ && now_ms - bad_since_ >= cfg_.bad_hold_ms) blocked_ = true;
    } else {
      bad_since_ = kNone;
      if (good_since_ == kNone) good_since_ = now_ms;
      if (blocked_ && now_ms - good_since_ >= cfg_.good_hold_ms) blocked_ = false;
    }
    return blocked_;
  }

  bool blocked() const { return blocked_; }

 private:
  static constexpr uint32_t kNone = 0xFFFFFFFFu;
  BlockedConfig cfg_;
  bool blocked_ = false;
  uint32_t bad_since_ = kNone;
  uint32_t good_since_ = kNone;
};

}  // namespace ce340
