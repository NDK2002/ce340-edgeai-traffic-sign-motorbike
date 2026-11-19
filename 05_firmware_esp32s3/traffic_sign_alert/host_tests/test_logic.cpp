// Kiểm thử trên máy tính cho alert_policy.h và frame_quality.h (không cần bo ESP32).
// Chạy:  c++ -std=c++17 -I05_firmware_esp32s3/traffic_sign_alert/src \
//          05_firmware_esp32s3/traffic_sign_alert/host_tests/test_logic.cpp -o /tmp/test_logic && /tmp/test_logic
#include <cstdio>
#include <vector>

#include "alert_policy.h"
#include "frame_quality.h"

using namespace ce340;

static int g_fail = 0;
#define CHECK(cond)                                                   \
  do {                                                                \
    if (!(cond)) {                                                    \
      std::printf("  FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond);   \
      ++g_fail;                                                       \
    }                                                                 \
  } while (0)

static void test_needs_three_frames() {
  AlertPolicy p;
  CHECK(p.update(0, 0.9f, 0) == -1);
  CHECK(p.update(0, 0.9f, 200) == -1);
  CHECK(p.update(0, 0.9f, 400) == 0);  // khung thứ 3 → báo
}

static void test_fires_once_while_visible() {
  AlertPolicy p;
  int alerts = 0;
  for (uint32_t t = 0; t < 30000; t += 200) alerts += p.update(1, 0.9f, t) == 1;  // biển đứng yên 30 giây
  CHECK(alerts == 1);
}

static void test_low_score_and_gap_reset_streak() {
  AlertPolicy p;
  p.update(2, 0.9f, 0);
  p.update(2, 0.9f, 200);
  CHECK(p.update(2, 0.3f, 400) == -1);  // điểm thấp → đứt chuỗi
  CHECK(p.update(2, 0.9f, 600) == -1);
  CHECK(p.update(2, 0.9f, 800) == -1);
  CHECK(p.update(2, 0.9f, 1000) == 2);
}

static void test_flicker_between_classes_never_fires() {
  AlertPolicy p;
  int alerts = 0;
  for (int i = 0; i < 20; ++i) alerts += p.update(i % 2 ? 3 : 4, 0.9f, i * 200) >= 0;
  CHECK(alerts == 0);
}

static void test_cooldown_same_class() {
  AlertPolicy p;
  for (int i = 0; i < 3; ++i) p.update(5, 0.9f, i * 200);
  p.update(-1, 0.f, 1000);  // biển ra khỏi khung
  int again = -1;
  for (int i = 0; i < 3; ++i) again = p.update(5, 0.9f, 2000 + i * 200);
  CHECK(again == -1);  // trong 10 giây → không báo lại
  p.update(-1, 0.f, 9000);
  for (int i = 0; i < 3; ++i) again = p.update(5, 0.9f, 11000 + i * 200);
  CHECK(again == 5);  // sau 10 giây → báo lại
}

static void test_other_class_not_blocked_by_cooldown() {
  AlertPolicy p;
  for (int i = 0; i < 3; ++i) p.update(5, 0.9f, i * 200);
  int r = -1;
  for (int i = 0; i < 3; ++i) r = p.update(6, 0.9f, 1000 + i * 200);
  CHECK(r == 6);
}

static void test_not_a_sign_class_ignored() {
  AlertPolicy p;
  int r = 0;
  for (int i = 0; i < 5; ++i) r = p.update(12, 0.99f, i * 200);  // lớp thứ 13 "không phải biển"
  CHECK(r == -1);
}

static void test_speed_limit_memory() {
  AlertPolicy p;
  CHECK(p.speed_class() == -1);
  for (int i = 0; i < 3; ++i) p.update(8, 0.9f, i * 200);
  CHECK(p.speed_class() == 8);
  for (int i = 0; i < 3; ++i) p.update(0, 0.9f, 1000 + i * 200);
  CHECK(p.speed_class() == 8);  // gặp biển khác vẫn giữ giới hạn tốc độ
  for (int i = 0; i < 3; ++i) p.update(7, 0.9f, 2000 + i * 200);
  CHECK(p.speed_class() == 7);
}

// Tạo khung RGB565 xám: pattern 0 = phẳng, 1 = bàn cờ (nhiều cạnh).
static std::vector<uint8_t> make_frame(int w, int h, uint8_t level, bool checker) {
  std::vector<uint8_t> f(static_cast<size_t>(w) * h * 2);
  for (int y = 0; y < h; ++y)
    for (int x = 0; x < w; ++x) {
      uint8_t v = level;
      if (checker && ((x / 8 + y / 8) % 2)) v = static_cast<uint8_t>(255 - level);
      const uint16_t px = static_cast<uint16_t>(((v >> 3) << 11) | ((v >> 2) << 5) | (v >> 3));
      f[(static_cast<size_t>(y) * w + x) * 2] = static_cast<uint8_t>(px >> 8);
      f[(static_cast<size_t>(y) * w + x) * 2 + 1] = static_cast<uint8_t>(px & 0xFF);
    }
  return f;
}

static void test_frame_stats() {
  auto dark = make_frame(640, 480, 5, false);
  auto flat = make_frame(640, 480, 128, false);
  auto busy = make_frame(640, 480, 60, true);
  FrameStats sd = measure_frame(dark.data(), 640, 480);
  FrameStats sf = measure_frame(flat.data(), 640, 480);
  FrameStats sb = measure_frame(busy.data(), 640, 480);
  std::printf("  dark: brightness=%.1f sharpness=%.1f\n", sd.brightness, sd.sharpness);
  std::printf("  flat: brightness=%.1f sharpness=%.1f\n", sf.brightness, sf.sharpness);
  std::printf("  busy: brightness=%.1f sharpness=%.1f\n", sb.brightness, sb.sharpness);
  CHECK(sd.brightness < 25);
  CHECK(sf.sharpness < 4 && sf.brightness > 100);
  CHECK(sb.sharpness > 50);
}

static void test_blocked_hysteresis() {
  BlockedDetector d;
  FrameStats bad{10, 1}, good{120, 40};
  CHECK(!d.update(bad, 0));
  CHECK(!d.update(bad, 1500));
  CHECK(d.update(bad, 2100));    // xấu đủ 2 giây → báo
  CHECK(d.update(good, 2300));   // vừa tốt lại chưa gỡ ngay
  CHECK(d.update(bad, 2500));    // xấu lại → giữ báo
  CHECK(d.update(good, 2700));
  CHECK(!d.update(good, 3800));  // tốt đủ 1 giây → gỡ báo
  CHECK(!d.update(bad, 4000));   // 1 khung xấu lẻ không báo
}

int main() {
  struct { const char *name; void (*fn)(); } tests[] = {
      {"needs_three_frames", test_needs_three_frames},
      {"fires_once_while_visible", test_fires_once_while_visible},
      {"low_score_and_gap_reset_streak", test_low_score_and_gap_reset_streak},
      {"flicker_between_classes_never_fires", test_flicker_between_classes_never_fires},
      {"cooldown_same_class", test_cooldown_same_class},
      {"other_class_not_blocked_by_cooldown", test_other_class_not_blocked_by_cooldown},
      {"not_a_sign_class_ignored", test_not_a_sign_class_ignored},
      {"speed_limit_memory", test_speed_limit_memory},
      {"frame_stats", test_frame_stats},
      {"blocked_hysteresis", test_blocked_hysteresis},
  };
  for (auto &t : tests) {
    std::printf("[ RUN ] %s\n", t.name);
    const int before = g_fail;
    t.fn();
    std::printf("[ %s ] %s\n", g_fail == before ? " OK " : "FAIL", t.name);
  }
  std::printf("\n%s (%d lỗi)\n", g_fail ? "CÓ TEST LỖI" : "TẤT CẢ ĐẠT", g_fail);
  return g_fail ? 1 : 0;
}
