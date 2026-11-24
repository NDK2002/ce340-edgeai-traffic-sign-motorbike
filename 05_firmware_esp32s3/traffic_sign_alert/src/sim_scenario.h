// Kịch bản mô phỏng: chạy firmware cảnh báo khi CHƯA có camera (Wokwi hoặc trên máy tính).
// Code thuần C++, không phụ thuộc ESP-IDF → dùng chung cho firmware (env "wokwi") và host_tests/sim_run.cpp.
//
// Thay cho camera, mỗi bước kịch bản quy định:
//   - ảnh giả: bình thường (có hoa văn) hoặc tối đen (giả lập lấy tay che camera)
//   - kết quả "model nhìn thấy": lớp biển + điểm tin cậy
// Phần còn lại (đo độ sáng/độ nét, phát hiện camera bị che, quy tắc chống báo nhầm, OLED/LED/buzzer)
// chạy đúng code thật. Mục đích: xem hệ thống phản ứng đúng với từng tình huống trước khi có bo.
#pragma once

#include <cstddef>
#include <cstdint>

namespace ce340 {

enum class SimFrame : uint8_t { kNormal, kDark };

struct SimStep {
  uint32_t duration_ms;
  SimFrame frame;
  int cls;        // -1 = không có biển
  float score;    // điểm tin cậy model trả về
  const char *what;    // tình huống
  const char *expect;  // hệ thống phải làm gì
};

// Lớp theo 01_dataset/classes.yaml: 0 cấm ngược chiều, 7/8 tốc độ 40/50, 11 đi chậm.
inline constexpr SimStep kSimScenario[] = {
    {3000, SimFrame::kNormal, -1, 0.0f, "Duong trong", "OLED: DANG QUAN SAT"},
    {200, SimFrame::kNormal, 0, 0.90f, "Bien cam thoang qua 2 khung", "KHONG bao (chua du 3 khung)"},
    {1000, SimFrame::kNormal, -1, 0.0f, "Duong trong", "-"},
    {400, SimFrame::kNormal, 0, 0.45f, "Bien cam nhung model khong chac (0.45)", "KHONG bao (diem < 0.6)"},
    {1000, SimFrame::kNormal, -1, 0.0f, "Duong trong", "-"},
    {2000, SimFrame::kNormal, 0, 0.85f, "Bien cam di nguoc chieu trong 2 giay", "BAO 1 lan: icon P.102, LED chop 3, coi 3 bip"},
    {1000, SimFrame::kNormal, -1, 0.0f, "Duong trong", "-"},
    {1500, SimFrame::kNormal, 0, 0.85f, "Gap lai bien do sau 1 giay", "KHONG bao lai (chua qua 10 giay)"},
    {2000, SimFrame::kNormal, -1, 0.0f, "Duong trong", "-"},
    {1500, SimFrame::kNormal, 8, 0.80f, "Bien toc do 50", "BAO: P.127 50, 1 bip; man hinh cho nho toc do 50"},
    {3000, SimFrame::kNormal, -1, 0.0f, "Duong trong", "OLED cho hien GIOI HAN 50"},
    {1500, SimFrame::kNormal, 11, 0.75f, "Bien di cham", "BAO muc cao: W.245, 3 bip"},
    {2000, SimFrame::kNormal, -1, 0.0f, "Duong trong", "-"},
    {3500, SimFrame::kDark, -1, 0.0f, "Lay tay che camera 3.5 giay", "Sau 2 giay: CAMERA BI CHE, LED sang lien tuc"},
    {2000, SimFrame::kNormal, -1, 0.0f, "Bo tay ra", "Sau 1 giay: tro lai DANG QUAN SAT"},
    {1500, SimFrame::kNormal, 7, 0.90f, "Bien toc do 40", "BAO: P.127 40; man hinh cho doi sang 40"},
    {3000, SimFrame::kNormal, -1, 0.0f, "Duong trong", "OLED cho hien GIOI HAN 40"},
};
inline constexpr size_t kSimSteps = sizeof(kSimScenario) / sizeof(kSimScenario[0]);

inline uint32_t sim_cycle_ms() {
  uint32_t total = 0;
  for (const SimStep &s : kSimScenario) total += s.duration_ms;
  return total;
}

// Bước kịch bản tại thời điểm t (tính từ lúc bắt đầu mô phỏng); kịch bản lặp lại vô hạn.
inline size_t sim_step_index(uint32_t t_ms) {
  uint32_t t = t_ms % sim_cycle_ms();
  for (size_t i = 0; i < kSimSteps; ++i) {
    if (t < kSimScenario[i].duration_ms) return i;
    t -= kSimScenario[i].duration_ms;
  }
  return kSimSteps - 1;
}

// Vẽ ảnh giả RGB565 (byte cao trước, giống esp32-camera).
//   kNormal: ô cờ xám 8×8 px → đủ sáng, đủ nét (không bị coi là camera bị che)
//   kDark:   gần đen, phẳng   → giống lấy tay che ống kính
inline void sim_fill_frame(uint8_t *buf, int w, int h, SimFrame kind, uint32_t frame_no) {
  for (int y = 0; y < h; ++y) {
    for (int x = 0; x < w; ++x) {
      uint8_t g;
      if (kind == SimFrame::kDark) {
        g = 6;
      } else {
        const bool light = (((x + static_cast<int>(frame_no)) / 8) + (y / 8)) % 2 == 0;
        g = light ? 180 : 70;
      }
      const uint16_t v = static_cast<uint16_t>(((g >> 3) << 11) | ((g >> 2) << 5) | (g >> 3));
      uint8_t *px = buf + (static_cast<size_t>(y) * w + x) * 2;
      px[0] = static_cast<uint8_t>(v >> 8);
      px[1] = static_cast<uint8_t>(v & 0xFF);
    }
  }
}

}  // namespace ce340
