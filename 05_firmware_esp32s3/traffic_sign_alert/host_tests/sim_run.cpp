// Mô phỏng firmware cảnh báo ngay trên máy tính (không cần bo, không cần Wokwi).
//
// Chạy 1 vòng kịch bản src/sim_scenario.h ở 10 khung/giây qua ĐÚNG code thật của firmware:
//   measure_frame + BlockedDetector (frame_quality.h) và AlertPolicy (alert_policy.h),
// theo cùng thứ tự như inference_task trong src/main.cpp. In ra dòng thời gian
// "màn hình OLED / LED / còi sẽ làm gì", rồi kiểm tra kết quả có đúng như mong đợi không.
//
// Build & chạy (từ thư mục gốc repo):
//   c++ -std=c++17 -I05_firmware_esp32s3/traffic_sign_alert/src -I05_firmware_esp32s3/peripherals_test/src \
//       05_firmware_esp32s3/traffic_sign_alert/host_tests/sim_run.cpp -o sim_run && ./sim_run
#include <cstdio>
#include <cstring>
#include <vector>

#include "alert_policy.h"
#include "frame_quality.h"
#include "sim_scenario.h"
#include "sign_icons.h"

int main() {
  constexpr int kW = 160, kH = 160;
  constexpr uint32_t kFrameMs = 100;  // 10 FPS
  std::vector<uint8_t> frame(kW * kH * 2);

  ce340::AlertPolicy policy;
  ce340::BlockedDetector detector;
  std::vector<int> alerts;
  int blocked_events = 0, unblocked_events = 0;
  size_t last_step = static_cast<size_t>(-1);
  const uint32_t cycle = ce340::sim_cycle_ms();

  std::printf("Mô phỏng 1 vòng kịch bản: %.1f giây, %u ms/khung\n\n", cycle / 1000.0, kFrameMs);
  for (uint32_t t = 0, n = 0; t < cycle; t += kFrameMs, ++n) {
    const size_t i = ce340::sim_step_index(t);
    const ce340::SimStep &step = ce340::kSimScenario[i];
    if (i != last_step) {
      std::printf("%6.1fs  ── %s\n          (mong đợi: %s)\n", t / 1000.0, step.what, step.expect);
      last_step = i;
    }

    ce340::sim_fill_frame(frame.data(), kW, kH, step.frame, n);
    const ce340::FrameStats st = ce340::measure_frame(frame.data(), kW, kH);
    const bool was_blocked = detector.blocked();
    const bool blocked = detector.update(st, t);
    if (blocked != was_blocked) {
      policy.reset();
      if (blocked) {
        ++blocked_events;
        std::printf("%6.1fs  ⚠ OLED: CAMERA BI CHE | LED sáng liên tục | còi 1 bíp (sáng %.0f, nét %.1f)\n",
                    t / 1000.0, st.brightness, st.sharpness);
      } else {
        ++unblocked_events;
        std::printf("%6.1fs  ✓ Camera nhìn rõ lại → OLED: DANG QUAN SAT\n", t / 1000.0);
      }
    }
    if (blocked) continue;  // đang bị che → không nhận diện, giống firmware

    const int cls = policy.update(step.cls, step.score, t);
    if (cls >= 0) {
      alerts.push_back(cls);
      const SignInfo &s = kSigns[cls];
      const bool high = std::strcmp(s.alert_level, "high") == 0;
      std::printf("%6.1fs  🔔 CẢNH BÁO %s %s (điểm %.2f) | LED %s | còi %s\n", t / 1000.0, s.qcvn, s.name_vi,
                  step.score, high ? "chớp 3 lần" : "sáng 1 nhịp", high ? "3 bíp dồn dập" : "1 bíp");
      if (policy.speed_class() == cls) std::printf("          → màn hình chờ nhớ: GIOI HAN %s\n", s.name_vi);
    }
  }

  // Kiểm tra: đúng 4 lần báo (cấm ngược chiều, tốc độ 50, đi chậm, tốc độ 40), 1 lần che camera.
  const std::vector<int> expected = {0, 8, 11, 7};
  const bool ok = alerts == expected && blocked_events == 1 && unblocked_events == 1 && policy.speed_class() == 7;
  std::printf("\nTổng kết: %zu lần cảnh báo, %d lần báo camera bị che, tốc độ đang nhớ: lớp %d\n", alerts.size(),
              blocked_events, policy.speed_class());
  std::printf("%s\n", ok ? "KẾT QUẢ ĐÚNG như kịch bản mong đợi" : "SAI so với mong đợi — xem dòng thời gian ở trên");
  return ok ? 0 : 1;
}
