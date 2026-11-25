// Quy tắc chống báo nhầm (T9 trong 06_reports_slides/tinh_huong_thuc_te_va_tieu_chi_danh_gia.md, Mục 5).
// Code thuần C++, không phụ thuộc ESP-IDF → kiểm thử được trên máy tính (host_tests/).
//
//   1. Chỉ báo khi CÙNG một lớp xuất hiện ở >= confirm_frames khung liên tiếp với điểm >= min_score.
//   2. Mỗi lần biển xuất hiện chỉ báo 1 lần (biển còn trong khung hình thì không báo lại).
//   3. Cùng một lớp không báo lại trong cooldown_ms kể từ lần báo trước.
//   4. Lớp >= num_classes (ví dụ lớp "không phải biển" nếu nhóm thêm sau) → coi như không có biển.
//   5. Biển tốc độ (40/50/60) được nhớ để OLED hiện cố định đến khi gặp biển tốc độ mới.
#pragma once

#include <cstdint>

namespace ce340 {

struct AlertPolicyConfig {
  int num_classes = 12;
  int confirm_frames = 3;
  float min_score = 0.6f;
  uint32_t cooldown_ms = 10000;
  int speed_class_first = 7;  // toc_do_40
  int speed_class_last = 9;   // toc_do_60
};

class AlertPolicy {
 public:
  explicit AlertPolicy(const AlertPolicyConfig &cfg = AlertPolicyConfig()) : cfg_(cfg) { reset(); }

  void reset() {
    candidate_ = -1;
    streak_ = 0;
    fired_for_streak_ = false;
  }

  // Gọi mỗi khung hình. Trả về lớp cần cảnh báo, hoặc -1 nếu không báo gì.
  int update(int top_class, float score, uint32_t now_ms) {
    const bool valid = top_class >= 0 && top_class < cfg_.num_classes && score >= cfg_.min_score;
    if (!valid) {
      reset();
      return -1;
    }
    if (top_class == candidate_) {
      ++streak_;
    } else {
      candidate_ = top_class;
      streak_ = 1;
      fired_for_streak_ = false;
    }
    if (fired_for_streak_ || streak_ < cfg_.confirm_frames) return -1;

    fired_for_streak_ = true;  // biển còn trong khung hình thì không báo lại
    const bool in_cooldown = last_alert_class_ == top_class && (now_ms - last_alert_ms_) < cfg_.cooldown_ms;
    if (in_cooldown) return -1;

    last_alert_class_ = top_class;
    last_alert_ms_ = now_ms;
    if (top_class >= cfg_.speed_class_first && top_class <= cfg_.speed_class_last) speed_class_ = top_class;
    return top_class;
  }

  // Lớp biển tốc độ đang áp dụng (7/8/9), -1 nếu chưa gặp.
  int speed_class() const { return speed_class_; }

 private:
  AlertPolicyConfig cfg_;
  int candidate_ = -1;
  int streak_ = 0;
  bool fired_for_streak_ = false;
  int last_alert_class_ = -1;
  uint32_t last_alert_ms_ = 0;
  int speed_class_ = -1;
};

}  // namespace ce340
