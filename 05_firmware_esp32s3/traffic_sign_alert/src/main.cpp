// Firmware cảnh báo biển báo — CE340 Edge AI Traffic Sign (ESP32-S3-CAM N16R8)
//
// Đây là chương trình demo thật (khác mock_inference_test chỉ để đo):
//   camera → cắt vùng ROI góc trên-phải → model (classifier hoặc MobileNetV2-SSD, tự nhận) → quy tắc chống báo nhầm → OLED + LED + buzzer
//
// Chia 2 task để cảnh báo không làm chậm nhận diện:
//   - inference_task (core 1): chụp, kiểm tra camera bị che, tiền xử lý, Invoke, quyết định có báo không.
//   - alert_task     (core 0): vẽ OLED, nháy LED, kêu buzzer, đọc nút tắt tiếng.
//
// Log Serial (lọc bằng grep '^CSV,'):
//   CSV,status,...   mỗi giây: FPS, lớp đoán, điểm, độ sáng/độ nét ảnh, trạng thái camera
//   CSV,alert,...    mỗi lần cảnh báo → dùng để đếm báo đúng / báo nhầm khi phát lại video demo
//   CSV,blocked,...  khi camera bị che / hết bị che

#include <algorithm>
#include <cinttypes>
#include <cmath>
#include <cstdio>
#include <cstring>

#include "esp_camera.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/schema/schema_generated.h"

#include "board_pins.h"     // mock_inference_test/src
#include "models.h"         // mock_inference_test/src
#include "buzzer_alert.h"   // peripherals_test/src (Hôn)
#include "led_alert.h"      // peripherals_test/src (Hôn)
#include "sh1106_oled.h"    // peripherals_test/src (Hôn)
#include "sign_icons.h"     // peripherals_test/src (Hôn): kSigns[12] + icon 32x32
#include "camera_sensor.h"  // mock_inference_test/src
#include "alert_policy.h"
#include "frame_quality.h"
#include "model_output.h"
#include "i2c_scan.h"
#include "sim_scenario.h"

// CE340_SIM=1 (env "wokwi" trong platformio.ini): không dùng camera, thay bằng ảnh giả + kịch bản
// trong sim_scenario.h. Mọi phần còn lại (model, chống báo nhầm, OLED/LED/buzzer) chạy như thật.
#ifndef CE340_SIM
#define CE340_SIM 0
#endif

namespace {

const char *TAG = "alert";

// ---------------- Cấu hình ----------------
constexpr size_t kAppModel = 0;               // chỉ số trong kModels (models.h)
constexpr framesize_t kFrame = FRAMESIZE_VGA; // phương án C: cắt ROI từ VGA
constexpr int kRoiSide = 160;                 // 0 = dùng cả khung hình rồi thu nhỏ (phương án A)
constexpr uint32_t kAlertShowMs = 3000;       // giữ màn hình cảnh báo bao lâu
constexpr int64_t kStatusPeriodUs = 1000000;  // in CSV,status và cập nhật FPS mỗi giây
constexpr size_t kProbeArenaSize = 2 * 1024 * 1024;
constexpr int kNumSignClasses = 12;            // 12 lớp trong classes.yaml (lớp nền / "không phải biển" nằm sau)

// ---------------- Thông điệp giữa 2 task ----------------
enum class MsgKind : uint8_t { kSign, kBlocked, kUnblocked };
struct AlertMsg {
  MsgKind kind;
  int cls;
  float score;
};
struct StatusMsg {
  float fps = 0;
  int speed_cls = -1;
};

QueueHandle_t g_alert_q = nullptr;
QueueHandle_t g_status_q = nullptr;  // hộp thư 1 phần tử, ghi đè (xQueueOverwrite)

// ---------------- Ngoại vi (driver của Hôn) ----------------
ce340::SH1106Oled g_oled(I2C_NUM_0, PIN_OLED_SDA, PIN_OLED_SCL);
ce340::BuzzerAlert g_buzzer(PIN_BUZZER);  // dùng LEDC_TIMER_0 / CHANNEL_0
ce340::LedAlert g_led(static_cast<gpio_num_t>(PIN_ALERT_LED));
ce340::MuteButton g_btn(static_cast<gpio_num_t>(PIN_BUTTON));
bool g_oled_ok = false;

int64_t now_us() { return esp_timer_get_time(); }
uint32_t now_ms() { return static_cast<uint32_t>(esp_timer_get_time() / 1000); }

bool is_high(int cls) { return std::strcmp(kSigns[cls].alert_level, "high") == 0; }

// ---------------- Màn hình OLED ----------------

void draw_status_bar(const StatusMsg &st) {
  char line[32];
  std::snprintf(line, sizeof(line), "FPS %.1f | COI %s", st.fps, g_buzzer.is_muted() ? "TAT" : "BAT");
  g_oled.draw_line_h(0, 52, 128);
  g_oled.draw_string(2, 54, line);
}

void render_idle(const StatusMsg &st) {
  g_oled.clear();
  g_oled.draw_string(2, 2, "CE340 - DANG QUAN SAT");
  g_oled.draw_line_h(0, 12, 128);
  if (st.speed_cls >= 0) {
    const SignInfo &s = kSigns[st.speed_cls];
    g_oled.draw_bitmap_32x32(4, 16, s.bitmap);
    g_oled.draw_rect(2, 14, 36, 36, false);
    g_oled.draw_string(42, 18, "GIOI HAN");
    g_oled.draw_string(42, 30, "TOC DO HIEN TAI");
  } else {
    g_oled.draw_string(4, 24, "Chua gap bien toc do");
  }
  draw_status_bar(st);
  g_oled.update();
}

void render_sign(int cls, const StatusMsg &st) {
  const SignInfo &s = kSigns[cls];
  g_oled.clear();
  char header[24];
  std::snprintf(header, sizeof(header), "!! %s", s.qcvn);
  g_oled.draw_string(2, 2, header);
  g_oled.draw_line_h(0, 12, 128);
  g_oled.draw_bitmap_32x32(4, 16, s.bitmap);
  g_oled.draw_rect(2, 14, 36, 36, false);
  g_oled.draw_string(42, 18, s.name_vi);
  g_oled.draw_string(42, 34, is_high(cls) ? "NGUY HIEM!" : "CHU Y");
  draw_status_bar(st);
  g_oled.update();
}

void render_blocked(const StatusMsg &st) {
  g_oled.clear();
  g_oled.draw_rect(0, 0, 128, 50, false);
  g_oled.draw_string(16, 10, "CAMERA BI CHE");
  g_oled.draw_string(22, 24, "HOAC QUA TOI");
  g_oled.draw_string(10, 38, "KHONG NHAN DIEN");
  draw_status_bar(st);
  g_oled.update();
}

void render_message(const char *l1, const char *l2) {
  if (!g_oled_ok) return;
  g_oled.clear();
  g_oled.draw_rect(0, 0, 128, 64, false);
  g_oled.draw_string(8, 18, l1);
  g_oled.draw_string(8, 34, l2);
  g_oled.update();
}

// ---------------- Task cảnh báo (core 0) ----------------

void alert_task(void *) {
  StatusMsg st;
  bool blocked = false;
  int showing = -1;
  int64_t show_until = 0, next_redraw = 0, btn_lock_until = 0;
  bool btn_prev = false;

  for (;;) {
    AlertMsg m;
    if (xQueueReceive(g_alert_q, &m, pdMS_TO_TICKS(50)) == pdTRUE) {
      xQueuePeek(g_status_q, &st, 0);
      if (m.kind == MsgKind::kSign) {
        showing = m.cls;
        show_until = now_us() + kAlertShowMs * 1000LL;
        if (g_oled_ok) render_sign(m.cls, st);
        if (is_high(m.cls)) {
          g_led.alert_high();
          g_buzzer.alert_high();
        } else {
          g_led.alert_medium();
          g_buzzer.alert_medium();
        }
      } else if (m.kind == MsgKind::kBlocked) {
        blocked = true;
        showing = -1;
        g_led.on();  // LED sáng liên tục khi camera bị che
        if (g_oled_ok) render_blocked(st);
        g_buzzer.alert_medium();
      } else {
        blocked = false;
        g_led.off();
      }
      next_redraw = 0;
    }

    xQueuePeek(g_status_q, &st, 0);

    const bool pressed = g_btn.is_pressed();
    if (pressed && !btn_prev && now_us() >= btn_lock_until) {
      g_buzzer.set_mute(!g_buzzer.is_muted());
      ESP_LOGW(TAG, "Nút: %s buzzer", g_buzzer.is_muted() ? "TẮT" : "BẬT");
      btn_lock_until = now_us() + 300000;  // chống dội phím
      next_redraw = 0;
    }
    btn_prev = pressed;

    const int64_t t = now_us();
    if (showing >= 0 && t >= show_until) {
      showing = -1;
      next_redraw = 0;
    }
    if (g_oled_ok && t >= next_redraw) {
      if (blocked) {
        render_blocked(st);
      } else if (showing >= 0) {
        render_sign(showing, st);
      } else {
        render_idle(st);
      }
      next_redraw = t + 500000;
    }
  }
}

// ---------------- Camera ----------------

bool init_camera() {
#if CE340_SIM
  ESP_LOGW(TAG, "CHẾ ĐỘ MÔ PHỎNG: không dùng camera, chạy kịch bản %u bước (%.1f giây/vòng)",
           (unsigned)ce340::kSimSteps, ce340::sim_cycle_ms() / 1000.0);
  return true;
#endif
  camera_config_t c = {};
  c.pin_pwdn = CAM_PIN_PWDN;
  c.pin_reset = CAM_PIN_RESET;
  c.pin_xclk = CAM_PIN_XCLK;
  c.pin_sccb_sda = CAM_PIN_SIOD;
  c.pin_sccb_scl = CAM_PIN_SIOC;
  c.pin_d7 = CAM_PIN_D7;
  c.pin_d6 = CAM_PIN_D6;
  c.pin_d5 = CAM_PIN_D5;
  c.pin_d4 = CAM_PIN_D4;
  c.pin_d3 = CAM_PIN_D3;
  c.pin_d2 = CAM_PIN_D2;
  c.pin_d1 = CAM_PIN_D1;
  c.pin_d0 = CAM_PIN_D0;
  c.pin_vsync = CAM_PIN_VSYNC;
  c.pin_href = CAM_PIN_HREF;
  c.pin_pclk = CAM_PIN_PCLK;
  c.xclk_freq_hz = 20000000;
  // Buzzer (driver của Hôn) đã chiếm LEDC_TIMER_0 / CHANNEL_0 → camera dùng timer/kênh 1,
  // nếu trùng thì xung clock của camera bị buzzer ghi đè và camera mất ảnh.
  c.ledc_timer = LEDC_TIMER_1;
  c.ledc_channel = LEDC_CHANNEL_1;
  c.pixel_format = PIXFORMAT_RGB565;
  c.frame_size = kFrame;
  c.jpeg_quality = 12;
  c.fb_count = 2;
  c.fb_location = CAMERA_FB_IN_PSRAM;
  c.grab_mode = CAMERA_GRAB_LATEST;
  const esp_err_t err = esp_camera_init(&c);
  if (err != ESP_OK) {
    ESP_LOGE(TAG, "Camera init lỗi 0x%x — kiểm tra cáp camera / board_pins.h", err);
    return false;
  }
  ce340::tune_camera_sensor();  // OV2640 / OV3660 / OV5640: in tên + chỉnh chiều ảnh
  return true;
}

// ---------------- Tiền xử lý (cùng cách với mock_inference_test) ----------------

struct InputSpec {
  int w = 0, h = 0, c = 0;
  TfLiteType type = kTfLiteNoType;
};

bool input_spec(const TfLiteTensor *t, InputSpec &s) {
  if (!t || t->dims->size != 4) return false;
  s.h = t->dims->data[1];
  s.w = t->dims->data[2];
  s.c = t->dims->data[3];
  s.type = t->type;
  const bool ok = s.type == kTfLiteInt8 || s.type == kTfLiteUInt8 || s.type == kTfLiteFloat32;
  return ok && (s.c == 1 || s.c == 3);
}

struct PixelLut {
  int8_t i8[256];
  uint8_t u8[256];
  float f32[256];
};

void build_lut(const TfLiteTensor *t, InputNorm norm, PixelLut &lut) {
  const float scale = t->params.scale;
  const int zp = t->params.zero_point;
  for (int v = 0; v < 256; ++v) {
    const float x = (norm == NORM_MINUS1_TO_1) ? (v / 127.5f - 1.0f) : (v / 255.0f);
    lut.f32[v] = x;
    if (scale > 0.0f) {
      const long q = lroundf(x / scale) + zp;
      lut.i8[v] = static_cast<int8_t>(std::clamp(q, -128L, 127L));
      lut.u8[v] = static_cast<uint8_t>(std::clamp(q, 0L, 255L));
    } else {
      lut.i8[v] = static_cast<int8_t>(v - 128);
      lut.u8[v] = static_cast<uint8_t>(v);
    }
  }
}

struct Rect {
  int x, y, w, h;
};

Rect roi_rect(int fw, int fh, int side) {
  if (side <= 0) return {0, 0, fw, fh};
  const int s = std::min(side, std::min(fw, fh));
  return {fw - s, 0, s, s};  // góc trên-phải: biển báo ở lề phải, phía trên
}

template <typename T>
void crop_resize(const uint8_t *src, int src_w, const Rect &r, const InputSpec &s, const T *lut, T *dst) {
  for (int dy = 0; dy < s.h; ++dy) {
    const uint8_t *row = src + static_cast<size_t>(r.y + dy * r.h / s.h) * src_w * 2;
    for (int dx = 0; dx < s.w; ++dx) {
      const int sx = r.x + dx * r.w / s.w;
      const uint8_t hi = row[sx * 2], lo = row[sx * 2 + 1];
      const uint8_t rr = hi & 0xF8;
      const uint8_t gg = static_cast<uint8_t>(((hi & 0x07) << 5) | ((lo & 0xE0) >> 3));
      const uint8_t bb = static_cast<uint8_t>((lo & 0x1F) << 3);
      if (s.c == 3) {
        *dst++ = lut[rr];
        *dst++ = lut[gg];
        *dst++ = lut[bb];
      } else {
        *dst++ = lut[(rr * 77 + gg * 150 + bb * 29) >> 8];
      }
    }
  }
}

bool preprocess(const camera_fb_t *fb, const InputSpec &s, const PixelLut &lut, TfLiteTensor *in) {
  if (fb->format != PIXFORMAT_RGB565) return false;
  const Rect r = roi_rect(fb->width, fb->height, kRoiSide);
  switch (s.type) {
    case kTfLiteInt8: crop_resize(fb->buf, fb->width, r, s, lut.i8, in->data.int8); return true;
    case kTfLiteUInt8: crop_resize(fb->buf, fb->width, r, s, lut.u8, in->data.uint8); return true;
    case kTfLiteFloat32: crop_resize(fb->buf, fb->width, r, s, lut.f32, in->data.f); return true;
    default: return false;
  }
}

// ---------------- Giải mã đầu ra (model_output.h) ----------------

ce340::TensorView view_of(const TfLiteTensor *t) {
  ce340::TensorView v;
  v.data = t->data.raw;
  v.type = t->type == kTfLiteInt8    ? ce340::ElemType::kInt8
           : t->type == kTfLiteUInt8 ? ce340::ElemType::kUInt8
                                     : ce340::ElemType::kFloat32;
  v.scale = t->params.scale;
  v.zero_point = t->params.zero_point;
  v.ndims = std::min(t->dims->size, 4);
  for (int i = 0; i < v.ndims; ++i) v.dims[i] = t->dims->data[i];
  return v;
}

ce340::OutputLayout g_layout;
float *g_anchors = nullptr;  // chỉ dùng với SSD: số anchor × 4 float (cx, cy, w, h)

// Nhận dạng model là classifier hay MobileNetV2-SSD theo shape đầu ra. Với SSD sinh sẵn bảng anchor.
bool setup_decoder(tflite::MicroInterpreter *interp, const ModelEntry &m) {
  const size_t n_out = interp->outputs_size();
  ce340::TensorView outs[2];
  for (size_t i = 0; i < std::min<size_t>(n_out, 2); ++i) outs[i] = view_of(interp->output(i));
  const TfLiteTensor *in = interp->input(0);
  const int in_h = in->dims->size == 4 ? in->dims->data[1] : 0;
  const int in_w = in->dims->size == 4 ? in->dims->data[2] : 0;
  g_layout = ce340::detect_layout(outs, static_cast<int>(n_out), in_h, in_w, kNumSignClasses);
  if (g_layout.kind == ce340::OutputKind::kUnknown) {
    ESP_LOGE(TAG, "[%s] đầu ra không hỗ trợ: %s", m.name, g_layout.error);
    return false;
  }
  if (g_layout.kind == ce340::OutputKind::kSsd) {
    const size_t bytes = static_cast<size_t>(g_layout.anchors) * 4 * sizeof(float);
    g_anchors = static_cast<float *>(heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM));
    if (!g_anchors) g_anchors = static_cast<float *>(heap_caps_malloc(bytes, MALLOC_CAP_8BIT));
    if (!g_anchors) {
      ESP_LOGE(TAG, "[%s] không đủ RAM cho %d anchor", m.name, g_layout.anchors);
      return false;
    }
    ce340::ssd_build_anchors(in_h, g_anchors);
  }
  std::printf("CSV,model,%s,%s,%dx%d,%d,%u\n", m.name, ce340::kind_name(g_layout.kind), in_w, in_h, g_layout.anchors,
              m.len);
  return true;
}

// Kết quả 1 khung: lớp có điểm cao nhất (classifier) hoặc phát hiện tốt nhất (SSD).
ce340::Detection decode(tflite::MicroInterpreter *interp) {
  if (g_layout.kind == ce340::OutputKind::kSsd) {
    return ce340::ssd_best(view_of(interp->output(g_layout.cls_index)), view_of(interp->output(g_layout.box_index)),
                           g_anchors, kNumSignClasses);
  }
  return ce340::classify(view_of(interp->output(0)));
}

// ---------------- Model ----------------

using OpResolver = tflite::MicroMutableOpResolver<24>;

OpResolver &resolver() {
  static OpResolver r;
  static bool ready = false;
  if (!ready) {
    r.AddConv2D();
    r.AddDepthwiseConv2D();
    r.AddMaxPool2D();
    r.AddAveragePool2D();
    r.AddMean();
    r.AddFullyConnected();
    r.AddReshape();
    r.AddSoftmax();
    r.AddQuantize();
    r.AddDequantize();
    r.AddAdd();
    r.AddMul();
    r.AddSub();
    r.AddPad();
    r.AddRelu();
    r.AddRelu6();
    r.AddHardSwish();
    r.AddLogistic();
    r.AddConcatenation();
    ready = true;
  }
  return r;
}

// Dò arena cần dùng bằng PSRAM, rồi chuyển sang SRAM trong (nhanh hơn) nếu vừa.
tflite::MicroInterpreter *load_model(const ModelEntry &m) {
  const tflite::Model *model = tflite::GetModel(m.data);
  if (model->version() != TFLITE_SCHEMA_VERSION) {
    ESP_LOGE(TAG, "[%s] schema model khác TFLM", m.name);
    return nullptr;
  }
  size_t used = 0;
  {
    size_t probe_size = kProbeArenaSize;
    auto *probe = static_cast<uint8_t *>(heap_caps_aligned_alloc(16, probe_size, MALLOC_CAP_SPIRAM));
    if (!probe) {  // không có PSRAM (bản mô phỏng Wokwi) → dò trong SRAM, đủ cho model nhỏ
      probe_size = heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT) * 3 / 4;
      probe = static_cast<uint8_t *>(heap_caps_aligned_alloc(16, probe_size, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
    }
    if (!probe) return nullptr;
    tflite::MicroInterpreter tmp(model, resolver(), probe, probe_size);
    if (tmp.AllocateTensors() == kTfLiteOk) used = tmp.arena_used_bytes();
    heap_caps_free(probe);
  }
  if (used == 0) {
    ESP_LOGE(TAG, "[%s] AllocateTensors() lỗi — thiếu op? xem resolver()", m.name);
    return nullptr;
  }
  const size_t size = used + used / 10 + 1024;
  uint8_t *arena = static_cast<uint8_t *>(heap_caps_aligned_alloc(16, size, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
  const char *where = "SRAM";
  if (!arena) {
    arena = static_cast<uint8_t *>(heap_caps_aligned_alloc(16, size, MALLOC_CAP_SPIRAM));
    where = "PSRAM";
  }
  if (!arena) return nullptr;
  auto *interp = new tflite::MicroInterpreter(model, resolver(), arena, size);
  if (interp->AllocateTensors() != kTfLiteOk) return nullptr;
  ESP_LOGI(TAG, "Model %s: arena %u KB ở %s", m.name, (unsigned)(size / 1024), where);
  return interp;
}

// ---------------- Task nhận diện (core 1) ----------------

void inference_task(void *arg) {
  auto *interp = static_cast<tflite::MicroInterpreter *>(arg);
  const ModelEntry &m = kModels[kAppModel];
  InputSpec spec;
  if (!input_spec(interp->input(0), spec)) {
    ESP_LOGE(TAG, "[%s] input phải là NHWC 1/3 kênh, int8/uint8/float32", m.name);
    render_message("LOI MODEL", "Xem log Serial");
    vTaskDelete(nullptr);
  }
  static PixelLut lut;
  build_lut(interp->input(0), m.norm, lut);

  ce340::AlertPolicy policy;
  ce340::BlockedDetector detector;
  int frames = 0, last_top = -1;
  float last_score = 0;
  ce340::FrameStats last_stats;
  int64_t window_start = now_us();

#if CE340_SIM
  constexpr int kSimW = 160, kSimH = 160;  // ảnh giả nhỏ, vừa SRAM (bản mô phỏng không có PSRAM)
  auto *sim_buf = static_cast<uint8_t *>(heap_caps_malloc(kSimW * kSimH * 2, MALLOC_CAP_8BIT));
  if (!sim_buf) {
    ESP_LOGE(TAG, "Không đủ RAM cho ảnh mô phỏng");
    vTaskDelete(nullptr);
  }
  const uint32_t sim_t0 = now_ms();
  uint32_t sim_frame_no = 0;
  size_t sim_last = ce340::kSimSteps;
  std::printf("CSV,#sim,t_ms,step,situation,expect\n");
#endif

  for (;;) {
#if CE340_SIM
    const uint32_t t_ms = now_ms();
    const size_t si = ce340::sim_step_index(t_ms - sim_t0);
    const ce340::SimStep &step = ce340::kSimScenario[si];
    if (si != sim_last) {
      std::printf("CSV,sim,%" PRIu32 ",%u,%s,%s\n", t_ms, (unsigned)si, step.what, step.expect);
      sim_last = si;
    }
    ce340::sim_fill_frame(sim_buf, kSimW, kSimH, step.frame, sim_frame_no++);
    camera_fb_t sim_fb = {};
    sim_fb.buf = sim_buf;
    sim_fb.len = kSimW * kSimH * 2;
    sim_fb.width = kSimW;
    sim_fb.height = kSimH;
    sim_fb.format = PIXFORMAT_RGB565;
    camera_fb_t *fb = &sim_fb;
#else
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
      vTaskDelay(pdMS_TO_TICKS(10));
      continue;
    }
    const uint32_t t_ms = now_ms();
#endif
    last_stats = ce340::measure_frame(fb->buf, fb->width, fb->height);
    const bool was_blocked = detector.blocked();
    const bool blocked = detector.update(last_stats, t_ms);

    bool ok = false;
    if (!blocked) ok = preprocess(fb, spec, lut, interp->input(0));
#if !CE340_SIM
    esp_camera_fb_return(fb);  // trả frame sớm để camera chụp tiếp trong lúc Invoke
#endif

    if (blocked != was_blocked) {
      policy.reset();
      AlertMsg msg{blocked ? MsgKind::kBlocked : MsgKind::kUnblocked, -1, 0};
      xQueueSend(g_alert_q, &msg, 0);
      std::printf("CSV,blocked,%" PRIu32 ",%d\n", t_ms, blocked ? 1 : 0);
    }

    last_top = -1;
    last_score = 0;
    if (ok && interp->Invoke() == kTfLiteOk) {
      const ce340::Detection det = decode(interp);
      last_top = det.cls;
      last_score = det.score;
#if CE340_SIM
      // Model mock chỉ đoán ngẫu nhiên → dùng "kết quả model" do kịch bản quy định
      // (Invoke vẫn chạy thật để đo tốc độ).
      last_top = step.cls;
      last_score = step.score;
#endif
      const int cls = policy.update(last_top, last_score, t_ms);
      if (cls >= 0) {
        AlertMsg msg{MsgKind::kSign, cls, last_score};
        xQueueSend(g_alert_q, &msg, 0);
        std::printf("CSV,alert,%" PRIu32 ",%d,%s,%.2f\n", t_ms, cls, kSigns[cls].qcvn, last_score);
      }
    }
    ++frames;

    const int64_t t = now_us();
    if (t - window_start >= kStatusPeriodUs) {
      StatusMsg st;
      st.fps = frames * 1e6f / (t - window_start);
      st.speed_cls = policy.speed_class();
      xQueueOverwrite(g_status_q, &st);
      std::printf("CSV,status,%" PRIu32 ",%.1f,%d,%.2f,%.1f,%.1f,%d,%d\n", t_ms, st.fps, last_top, last_score,
                  last_stats.brightness, last_stats.sharpness, blocked ? 1 : 0, st.speed_cls);
      frames = 0;
      window_start = t;
    }
#if CE340_SIM
    vTaskDelay(pdMS_TO_TICKS(100));  // ~10 khung/giây như camera thật
#else
    vTaskDelay(1);  // nhường CPU cho task IDLE (watchdog)
#endif
  }
}

}  // namespace

extern "C" void app_main(void) {
  ESP_LOGI(TAG, "===== CE340 traffic_sign_alert =====");

  g_oled_ok = g_oled.init();
  const bool bz_ok = g_buzzer.init();
  const bool led_ok = g_led.init();
  g_btn.init();
  ESP_LOGI(TAG, "OLED=%s Buzzer=%s LED=%s", g_oled_ok ? "OK" : "LOI", bz_ok ? "OK" : "LOI", led_ok ? "OK" : "LOI");
  if (g_oled_ok) ce340::i2c_scan(I2C_NUM_0);  // OLED đúng dây → thấy 0x3C
  render_message("CE340 EDGE AI", "Dang khoi dong...");
  g_buzzer.chirp_boot();

  if (!init_camera()) {
    render_message("LOI CAMERA", "Kiem tra cap camera");
    return;
  }
  if (kAppModel >= sizeof(kModels) / sizeof(kModels[0])) {
    ESP_LOGE(TAG, "kAppModel vượt quá số model trong models.h");
    return;
  }
  std::printf("CSV,#model,name,kind,input,anchors,size_bytes\n");
  tflite::MicroInterpreter *interp = load_model(kModels[kAppModel]);
  if (!interp || !setup_decoder(interp, kModels[kAppModel])) {
    render_message("LOI MODEL", "Xem log Serial");
    return;
  }

  g_alert_q = xQueueCreate(4, sizeof(AlertMsg));
  g_status_q = xQueueCreate(1, sizeof(StatusMsg));
  StatusMsg st0;
  xQueueOverwrite(g_status_q, &st0);

  std::printf("CSV,#status,t_ms,fps,top,score,brightness,sharpness,blocked,speed_class\n");
  std::printf("CSV,#alert,t_ms,class,qcvn,score\n");
  std::printf("CSV,#blocked,t_ms,state\n");

  xTaskCreatePinnedToCore(alert_task, "alert", 6144, nullptr, 5, nullptr, 0);
  xTaskCreatePinnedToCore(inference_task, "infer", 16384, interp, 4, nullptr, 1);
}
