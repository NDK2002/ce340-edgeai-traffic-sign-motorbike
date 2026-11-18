// [D2] Firmware benchmark — CE340 Edge AI Traffic Sign (ESP32-S3-CAM N16R8)
//
// Chạy một lượt rồi in số liệu cho Chương 4 của báo cáo:
//   1. Phần cứng: Flash, PSRAM, RAM trống, nhiệt độ chip, tốc độ ghi thẻ microSD.
//   2. Mọi model trong models.h: kích thước, Tensor Arena, thời gian Invoke() khi arena ở PSRAM và SRAM.
//   3. Camera: thời gian lấy 1 frame QVGA / VGA (RGB565).
//   4. Pipeline đầu-cuối theo phương án A/B/C: chụp → crop ROI góc trên-phải + resize → Invoke → argmax.
//   5. Soak: chạy pipeline liên tục để đọc dòng (mA) trên USB tester và theo dõi nhiệt độ, FPS.
//
// Dòng bắt đầu bằng "CSV," là số liệu (dòng "CSV,#..." là tiêu đề cột). Nếu có thẻ microSD,
// toàn bộ các dòng này được ghi thêm vào /sdcard/bench.csv.
// Lọc từ log Serial:  grep '^CSV,' log.txt > bench.csv

#include <algorithm>
#include <cinttypes>
#include <cmath>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <unistd.h>

#include "driver/sdmmc_host.h"
#include "driver/temperature_sensor.h"
#include "esp_camera.h"
#include "esp_chip_info.h"
#include "esp_flash.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_psram.h"
#include "esp_timer.h"
#include "esp_vfs_fat.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdmmc_cmd.h"

#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/schema/schema_generated.h"  // esp-tflite-micro >= 1.4

#include "board_pins.h"
#include "models.h"

namespace {

const char *TAG = "ce340";

// ---------------- Cấu hình đo ----------------
constexpr size_t kProbeArenaSize = 4 * 1024 * 1024;  // arena dò trong PSRAM để biết model cần bao nhiêu
constexpr int kWarmupRuns = 3;
constexpr int kTimedRuns = 20;
constexpr int kCameraRuns = 20;
constexpr int kPipelineRuns = 30;
constexpr size_t kPipelineModel = 0;   // chỉ số trong kModels dùng cho pipeline và soak
constexpr int kSoakSeconds = 30 * 60;  // 0 = bỏ qua soak
constexpr int kSoakReportSeconds = 10;
constexpr int kRoiMarginRight = 0;     // ROI bám góc trên-phải: biển báo nằm ở lề phải, phía trên
constexpr int kRoiMarginTop = 0;
constexpr const char *kSdMount = "/sdcard";

struct PipelineCfg {
  const char *name;
  framesize_t frame;
  int roi_side;  // 0 = lấy cả khung hình rồi thu nhỏ
};

// Phương án A/B/C ở Mục 4 của 06_reports_slides/tinh_huong_thuc_te_va_tieu_chi_danh_gia.md
constexpr PipelineCfg kPipelineCfgs[] = {
    {"A_qvga_full", FRAMESIZE_QVGA, 0},
    {"B_qvga_roi160", FRAMESIZE_QVGA, 160},
    {"C_vga_roi160", FRAMESIZE_VGA, 160},
    {"C2_vga_roi320", FRAMESIZE_VGA, 320},
};
constexpr size_t kSoakCfg = 2;  // phương án dùng khi soak (C_vga_roi160)

constexpr size_t kNumModels = sizeof(kModels) / sizeof(kModels[0]);

FILE *g_csv = nullptr;
temperature_sensor_handle_t g_tsens = nullptr;
size_t g_arena_needed[kNumModels] = {};

// ---------------- Tiện ích ----------------

// In số liệu ra Serial và ghi thêm vào thẻ microSD (nếu có).
void emit(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
void emit(const char *fmt, ...) {
  va_list ap;
  va_start(ap, fmt);
  vprintf(fmt, ap);
  va_end(ap);
  if (g_csv) {
    va_start(ap, fmt);
    vfprintf(g_csv, fmt, ap);
    va_end(ap);
    fflush(g_csv);
  }
}

void emit_headers() {
  emit("CSV,#hw,stage,flash_mb,psram_mb,free_sram_kb,free_psram_kb,temp_c\n");
  emit("CSV,#sd,write_kb,ms,kb_per_s\n");
  emit("CSV,#model,name,input,dtype,size_kb,mem,arena_kb,avg_ms,max_ms,runs\n");
  emit("CSV,#camera,frame,width,height,bytes,avg_ms,frames_ok\n");
  emit("CSV,#pipeline,model,cfg,frame,roi,capture_ms,preproc_ms,invoke_ms,total_ms,fps,top_class\n");
  emit("CSV,#soak,model,cfg,elapsed_s,fps,total_ms,temp_c,free_psram_kb,errors\n");
}

float ms(int64_t us) { return us / 1000.0f; }

size_t arena_with_margin(size_t used) { return used + used / 10 + 1024; }

void init_temp_sensor() {
  temperature_sensor_config_t cfg = TEMPERATURE_SENSOR_CONFIG_DEFAULT(10, 80);
  if (temperature_sensor_install(&cfg, &g_tsens) != ESP_OK || temperature_sensor_enable(g_tsens) != ESP_OK) {
    ESP_LOGW(TAG, "Không bật được cảm biến nhiệt độ chip");
    g_tsens = nullptr;
  }
}

float chip_temp_c() {
  float t = NAN;
  if (g_tsens) temperature_sensor_get_celsius(g_tsens, &t);
  return t;
}

void report_hardware(const char *stage) {
  esp_chip_info_t chip;
  esp_chip_info(&chip);
  uint32_t flash_size = 0;
  esp_flash_get_size(nullptr, &flash_size);
  ESP_LOGI(TAG, "[%s] ESP32-S3 rev %d, %d core(s), PSRAM initialized=%d", stage, chip.revision, chip.cores,
           esp_psram_is_initialized());
  emit("CSV,hw,%s,%" PRIu32 ",%u,%u,%u,%.1f\n", stage, flash_size / (1024 * 1024),
       (unsigned)(esp_psram_get_size() / (1024 * 1024)),
       (unsigned)(heap_caps_get_free_size(MALLOC_CAP_INTERNAL) / 1024),
       (unsigned)(heap_caps_get_free_size(MALLOC_CAP_SPIRAM) / 1024), chip_temp_c());
}

// ---------------- Thẻ microSD ----------------

void init_sd() {
  esp_vfs_fat_sdmmc_mount_config_t mount = {};
  mount.format_if_mount_failed = false;
  mount.max_files = 4;
  mount.allocation_unit_size = 16 * 1024;

  sdmmc_host_t host = SDMMC_HOST_DEFAULT();
  sdmmc_slot_config_t slot = SDMMC_SLOT_CONFIG_DEFAULT();
  slot.width = 1;
  slot.clk = static_cast<gpio_num_t>(PIN_SD_CLK);
  slot.cmd = static_cast<gpio_num_t>(PIN_SD_CMD);
  slot.d0 = static_cast<gpio_num_t>(PIN_SD_D0);
  slot.flags |= SDMMC_SLOT_FLAG_INTERNAL_PULLUP;

  sdmmc_card_t *card = nullptr;
  const esp_err_t err = esp_vfs_fat_sdmmc_mount(kSdMount, &host, &slot, &mount, &card);
  if (err != ESP_OK) {
    ESP_LOGW(TAG, "Không mount được microSD (0x%x) — số liệu chỉ in ra Serial", err);
    return;
  }
  sdmmc_card_print_info(stdout, card);
  g_csv = fopen("/sdcard/bench.csv", "a");
  if (!g_csv) ESP_LOGW(TAG, "Không mở được /sdcard/bench.csv");
}

// Tốc độ ghi tuần tự — dùng để biết có kịp lưu ảnh camera ra thẻ khi chạy thử trên xe hay không.
void sd_speed_test() {
  if (!g_csv) return;
  constexpr size_t kChunk = 4096;
  constexpr size_t kTotal = 512 * 1024;
  auto *buf = static_cast<uint8_t *>(heap_caps_malloc(kChunk, MALLOC_CAP_DMA));
  if (!buf) return;
  memset(buf, 0xA5, kChunk);
  FILE *f = fopen("/sdcard/speed.bin", "wb");
  if (f) {
    const int64_t t0 = esp_timer_get_time();
    for (size_t done = 0; done < kTotal; done += kChunk) fwrite(buf, 1, kChunk, f);
    fflush(f);
    fsync(fileno(f));
    fclose(f);
    const int64_t dt = esp_timer_get_time() - t0;
    unlink("/sdcard/speed.bin");
    emit("CSV,sd,%u,%.1f,%.1f\n", (unsigned)(kTotal / 1024), ms(dt), (kTotal / 1024.0f) / (dt / 1e6f));
  }
  heap_caps_free(buf);
}

// ---------------- TFLite Micro ----------------

// Op cho các model phân loại thường gặp (CNN nhỏ, MobileNetV1/V2/V3). Model thiếu op thì
// AllocateTensors() báo lỗi kèm tên op — thêm vào đây và tăng kích thước resolver nếu cần.
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

void shape_str(const TfLiteTensor *t, char *out, size_t n) {
  size_t pos = 0;
  out[0] = '\0';
  for (int i = 1; i < t->dims->size && pos < n; ++i) {
    pos += snprintf(out + pos, n - pos, i == 1 ? "%d" : "x%d", t->dims->data[i]);
  }
}

// Chạy 1 model với arena cho trước, in 1 dòng CSV. Trả về số byte arena đã dùng (0 nếu lỗi).
size_t bench_one(const ModelEntry &m, const tflite::Model *model, uint8_t *arena, size_t arena_size,
                 const char *mem) {
  tflite::MicroInterpreter interp(model, resolver(), arena, arena_size);
  if (interp.AllocateTensors() != kTfLiteOk) {
    ESP_LOGE(TAG, "[%s/%s] AllocateTensors() thất bại (arena %u B)", m.name, mem, (unsigned)arena_size);
    return 0;
  }
  TfLiteTensor *in = interp.input(0);
  memset(in->data.raw, 0, in->bytes);  // input rỗng: chỉ đo thời gian, không đo độ chính xác

  for (int i = 0; i < kWarmupRuns; ++i) {
    if (interp.Invoke() != kTfLiteOk) {
      ESP_LOGE(TAG, "[%s/%s] Invoke() lỗi", m.name, mem);
      return 0;
    }
  }
  int64_t total_us = 0, worst_us = 0;
  for (int i = 0; i < kTimedRuns; ++i) {
    const int64_t t0 = esp_timer_get_time();
    interp.Invoke();
    const int64_t dt = esp_timer_get_time() - t0;
    total_us += dt;
    worst_us = std::max(worst_us, dt);
    vTaskDelay(1);  // nhường CPU cho task IDLE, tránh cảnh báo watchdog với model chậm (ngoài vùng đo)
  }

  const size_t used = interp.arena_used_bytes();
  char shape[32];
  shape_str(in, shape, sizeof(shape));
  emit("CSV,model,%s,%s,%s,%.1f,%s,%.1f,%.2f,%.2f,%d\n", m.name, shape, TfLiteTypeGetName(in->type),
       m.len / 1024.0f, mem, used / 1024.0f, ms(total_us) / kTimedRuns, ms(worst_us), kTimedRuns);
  return used;
}

void benchmark_models() {
  auto *probe = static_cast<uint8_t *>(
      heap_caps_aligned_alloc(16, kProbeArenaSize, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (!probe) {
    ESP_LOGE(TAG, "Không cấp phát được arena PSRAM — kiểm tra CONFIG_SPIRAM_MODE_OCT");
    return;
  }
  for (size_t i = 0; i < kNumModels; ++i) {
    const ModelEntry &m = kModels[i];
    const tflite::Model *model = tflite::GetModel(m.data);
    if (model->version() != TFLITE_SCHEMA_VERSION) {
      ESP_LOGE(TAG, "[%s] schema %" PRIu32 " khác TFLM %d", m.name, model->version(), TFLITE_SCHEMA_VERSION);
      continue;
    }
    const size_t needed = bench_one(m, model, probe, kProbeArenaSize, "psram");
    g_arena_needed[i] = needed;
    if (needed == 0) continue;

    const size_t sram_size = arena_with_margin(needed);
    auto *sram = static_cast<uint8_t *>(heap_caps_aligned_alloc(16, sram_size, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
    if (sram) {
      bench_one(m, model, sram, sram_size, "sram");
      heap_caps_free(sram);
    } else {
      ESP_LOGW(TAG, "[%s] SRAM trong không đủ %u B — model này phải chạy trên PSRAM", m.name, (unsigned)sram_size);
    }
  }
  heap_caps_free(probe);
}

// ---------------- Camera ----------------

bool init_camera() {
  camera_config_t config = {};
  config.pin_pwdn = CAM_PIN_PWDN;
  config.pin_reset = CAM_PIN_RESET;
  config.pin_xclk = CAM_PIN_XCLK;
  config.pin_sccb_sda = CAM_PIN_SIOD;
  config.pin_sccb_scl = CAM_PIN_SIOC;
  config.pin_d7 = CAM_PIN_D7;
  config.pin_d6 = CAM_PIN_D6;
  config.pin_d5 = CAM_PIN_D5;
  config.pin_d4 = CAM_PIN_D4;
  config.pin_d3 = CAM_PIN_D3;
  config.pin_d2 = CAM_PIN_D2;
  config.pin_d1 = CAM_PIN_D1;
  config.pin_d0 = CAM_PIN_D0;
  config.pin_vsync = CAM_PIN_VSYNC;
  config.pin_href = CAM_PIN_HREF;
  config.pin_pclk = CAM_PIN_PCLK;
  config.xclk_freq_hz = 20000000;
  config.ledc_timer = LEDC_TIMER_0;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.pixel_format = PIXFORMAT_RGB565;  // ảnh thô, không phải giải nén JPEG trước khi suy luận
  config.frame_size = FRAMESIZE_VGA;       // frame buffer cấp theo kích thước lớn nhất sẽ dùng
  config.jpeg_quality = 12;
  config.fb_count = 2;
  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.grab_mode = CAMERA_GRAB_LATEST;

  const esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    ESP_LOGE(TAG, "Camera init lỗi 0x%x — kiểm tra cáp camera hoặc sai pinout (board_pins.h)", err);
    return false;
  }
  ESP_LOGI(TAG, "Camera init OK (RGB565)");
  return true;
}

const char *frame_name(framesize_t fs) {
  switch (fs) {
    case FRAMESIZE_QVGA: return "QVGA";
    case FRAMESIZE_VGA: return "VGA";
    default: return "?";
  }
}

// Đổi độ phân giải rồi bỏ vài frame đầu (frame cũ + cảm biến tự cân bằng sáng).
bool set_frame(framesize_t fs) {
  sensor_t *s = esp_camera_sensor_get();
  if (!s || s->set_framesize(s, fs) != 0) {
    ESP_LOGE(TAG, "Không đổi được độ phân giải sang %s", frame_name(fs));
    return false;
  }
  for (int i = 0; i < 4; ++i) {
    camera_fb_t *fb = esp_camera_fb_get();
    if (fb) esp_camera_fb_return(fb);
  }
  return true;
}

void benchmark_camera() {
  for (framesize_t fs : {FRAMESIZE_QVGA, FRAMESIZE_VGA}) {
    if (!set_frame(fs)) continue;
    int64_t total_us = 0;
    int ok = 0;
    unsigned w = 0, h = 0, len = 0;
    for (int i = 0; i < kCameraRuns; ++i) {
      const int64_t t0 = esp_timer_get_time();
      camera_fb_t *fb = esp_camera_fb_get();
      const int64_t dt = esp_timer_get_time() - t0;
      if (!fb) continue;
      w = fb->width;
      h = fb->height;
      len = fb->len;
      esp_camera_fb_return(fb);
      total_us += dt;
      ++ok;
    }
    emit("CSV,camera,%s,%u,%u,%u,%.2f,%d\n", frame_name(fs), w, h, len, ok ? ms(total_us) / ok : NAN, ok);
  }
}

// ---------------- Tiền xử lý: crop ROI + resize + lượng tử hoá ----------------

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
  const bool type_ok = s.type == kTfLiteInt8 || s.type == kTfLiteUInt8 || s.type == kTfLiteFloat32;
  return type_ok && (s.c == 1 || s.c == 3);
}

// Bảng tra pixel 0..255 → giá trị đưa vào model, tránh phép chia và float trong vòng lặp từng pixel.
// Giả định model huấn luyện với ảnh chuẩn hoá về [0, 1] (chốt trong firmware contract với Trung/Sơn).
// Nếu model dùng [-1, 1] hoặc giữ nguyên 0..255 thì chỉ cần sửa biến x bên dưới.
struct PixelLut {
  int8_t i8[256];
  uint8_t u8[256];
  float f32[256];
};

void build_lut(const TfLiteTensor *t, PixelLut &lut) {
  const float scale = t->params.scale;
  const int zp = t->params.zero_point;
  for (int v = 0; v < 256; ++v) {
    const float x = v / 255.0f;
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

// roi_side = 0: cả khung hình. Ngược lại: ô vuông roi_side × roi_side ở góc trên-phải.
Rect roi_rect(int frame_w, int frame_h, int roi_side) {
  if (roi_side <= 0) return {0, 0, frame_w, frame_h};
  const int side = std::min(roi_side, std::min(frame_w, frame_h));
  const int x = std::max(0, frame_w - side - kRoiMarginRight);
  const int y = std::min(kRoiMarginTop, frame_h - side);
  return {x, y, side, side};
}

// Crop + resize nearest-neighbor từ frame RGB565 thẳng vào input tensor.
// Byte RGB565 của esp32-camera: RRRRRGGG GGGBBBBB (cách tách giống fmt2rgb888 trong esp32-camera).
template <typename T>
void crop_resize(const uint8_t *src, int src_w, const Rect &r, const InputSpec &s, const T *lut, T *dst) {
  for (int dy = 0; dy < s.h; ++dy) {
    const int sy = r.y + dy * r.h / s.h;
    const uint8_t *row = src + static_cast<size_t>(sy) * src_w * 2;
    for (int dx = 0; dx < s.w; ++dx) {
      const int sx = r.x + dx * r.w / s.w;
      const uint8_t hi = row[sx * 2];
      const uint8_t lo = row[sx * 2 + 1];
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

bool preprocess(const camera_fb_t *fb, const Rect &r, const InputSpec &s, const PixelLut &lut, TfLiteTensor *in) {
  if (fb->format != PIXFORMAT_RGB565) return false;
  switch (s.type) {
    case kTfLiteInt8: crop_resize(fb->buf, fb->width, r, s, lut.i8, in->data.int8); return true;
    case kTfLiteUInt8: crop_resize(fb->buf, fb->width, r, s, lut.u8, in->data.uint8); return true;
    case kTfLiteFloat32: crop_resize(fb->buf, fb->width, r, s, lut.f32, in->data.f); return true;
    default: return false;
  }
}

int argmax(const TfLiteTensor *out) {
  int n = 1;
  for (int i = 0; i < out->dims->size; ++i) n *= out->dims->data[i];
  int best = 0;
  for (int i = 1; i < n; ++i) {
    bool better = false;
    switch (out->type) {
      case kTfLiteInt8: better = out->data.int8[i] > out->data.int8[best]; break;
      case kTfLiteUInt8: better = out->data.uint8[i] > out->data.uint8[best]; break;
      case kTfLiteFloat32: better = out->data.f[i] > out->data.f[best]; break;
      default: return -1;
    }
    if (better) best = i;
  }
  return best;
}

// ---------------- Pipeline đầu-cuối ----------------

struct StepTimes {
  int64_t capture_us = 0, preproc_us = 0, invoke_us = 0;
  int top = -1;
};

// Một vòng: chụp → crop/resize vào input → trả frame cho camera → Invoke → argmax.
// Trả frame trước khi Invoke để camera chụp frame kế tiếp song song với suy luận.
bool pipeline_step(tflite::MicroInterpreter &interp, const InputSpec &s, const PixelLut &lut, const PipelineCfg &cfg,
                   StepTimes &t) {
  const int64_t t0 = esp_timer_get_time();
  camera_fb_t *fb = esp_camera_fb_get();
  const int64_t t1 = esp_timer_get_time();
  if (!fb) return false;
  const bool ok = preprocess(fb, roi_rect(fb->width, fb->height, cfg.roi_side), s, lut, interp.input(0));
  esp_camera_fb_return(fb);
  const int64_t t2 = esp_timer_get_time();
  if (!ok || interp.Invoke() != kTfLiteOk) return false;
  const int64_t t3 = esp_timer_get_time();
  t.capture_us = t1 - t0;
  t.preproc_us = t2 - t1;
  t.invoke_us = t3 - t2;
  t.top = argmax(interp.output(0));
  return true;
}

void run_pipelines(tflite::MicroInterpreter &interp, const ModelEntry &m, const InputSpec &s, const PixelLut &lut) {
  for (const PipelineCfg &cfg : kPipelineCfgs) {
    if (!set_frame(cfg.frame)) continue;
    StepTimes t;
    for (int i = 0; i < kWarmupRuns; ++i) pipeline_step(interp, s, lut, cfg, t);

    int64_t cap = 0, pre = 0, inv = 0;
    int ok = 0, top = -1;
    for (int i = 0; i < kPipelineRuns; ++i) {
      if (pipeline_step(interp, s, lut, cfg, t)) {
        cap += t.capture_us;
        pre += t.preproc_us;
        inv += t.invoke_us;
        top = t.top;
        ++ok;
      }
      vTaskDelay(1);
    }
    if (ok == 0) {
      ESP_LOGE(TAG, "[%s] pipeline không chạy được vòng nào", cfg.name);
      continue;
    }
    const resolution_info_t &res = resolution[cfg.frame];
    const Rect r = roi_rect(res.width, res.height, cfg.roi_side);
    const float total = ms(cap + pre + inv) / ok;
    emit("CSV,pipeline,%s,%s,%s,%dx%d,%.2f,%.2f,%.2f,%.2f,%.1f,%d\n", m.name, cfg.name, frame_name(cfg.frame), r.w,
         r.h, ms(cap) / ok, ms(pre) / ok, ms(inv) / ok, total, 1000.0f / total, top);
  }
}

// Chạy liên tục để đo dòng tiêu thụ (đọc trên USB tester), nhiệt độ chip và độ ổn định.
void run_soak(tflite::MicroInterpreter &interp, const ModelEntry &m, const InputSpec &s, const PixelLut &lut) {
  if (kSoakSeconds <= 0) return;
  const PipelineCfg &cfg = kPipelineCfgs[kSoakCfg];
  if (!set_frame(cfg.frame)) return;
  ESP_LOGI(TAG, "Soak %d giây với %s/%s — đọc dòng mA trên USB tester trong lúc này", kSoakSeconds, m.name, cfg.name);

  const int64_t start = esp_timer_get_time();
  const int64_t end = start + static_cast<int64_t>(kSoakSeconds) * 1000000;
  int64_t next_report = start + static_cast<int64_t>(kSoakReportSeconds) * 1000000;
  int64_t window_us = 0;
  int frames = 0, errors = 0;
  StepTimes t;
  while (esp_timer_get_time() < end) {
    if (pipeline_step(interp, s, lut, cfg, t)) {
      window_us += t.capture_us + t.preproc_us + t.invoke_us;
      ++frames;
    } else {
      ++errors;
    }
    vTaskDelay(1);
    const int64_t now = esp_timer_get_time();
    if (now >= next_report) {
      const float avg = frames ? ms(window_us) / frames : NAN;
      emit("CSV,soak,%s,%s,%d,%.1f,%.2f,%.1f,%u,%d\n", m.name, cfg.name, (int)((now - start) / 1000000),
           frames ? 1000.0f / avg : 0.0f, avg, chip_temp_c(),
           (unsigned)(heap_caps_get_free_size(MALLOC_CAP_SPIRAM) / 1024), errors);
      window_us = 0;
      frames = 0;
      next_report += static_cast<int64_t>(kSoakReportSeconds) * 1000000;
    }
  }
}

void benchmark_pipeline_and_soak() {
  if (kPipelineModel >= kNumModels || g_arena_needed[kPipelineModel] == 0) {
    ESP_LOGW(TAG, "Bỏ qua pipeline: model kPipelineModel chưa chạy được ở bước benchmark");
    return;
  }
  const ModelEntry &m = kModels[kPipelineModel];
  const size_t arena_size = arena_with_margin(g_arena_needed[kPipelineModel]);
  auto *arena = static_cast<uint8_t *>(heap_caps_aligned_alloc(16, arena_size, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
  if (!arena) {
    arena = static_cast<uint8_t *>(heap_caps_aligned_alloc(16, arena_size, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  }
  if (!arena) {
    ESP_LOGE(TAG, "Không cấp phát được arena %u B cho pipeline", (unsigned)arena_size);
    return;
  }
  {
    tflite::MicroInterpreter interp(tflite::GetModel(m.data), resolver(), arena, arena_size);
    InputSpec s;
    if (interp.AllocateTensors() != kTfLiteOk || !input_spec(interp.input(0), s)) {
      ESP_LOGE(TAG, "[%s] input phải là NHWC 1 hoặc 3 kênh, kiểu int8/uint8/float32", m.name);
    } else {
      static PixelLut lut;
      build_lut(interp.input(0), lut);
      run_pipelines(interp, m, s, lut);
      run_soak(interp, m, s, lut);
    }
  }
  heap_caps_free(arena);
}

}  // namespace

extern "C" void app_main(void) {
  ESP_LOGI(TAG, "===== CE340 [D2] bench — %u model =====", (unsigned)kNumModels);
  init_temp_sensor();
  init_sd();
  emit_headers();
  sd_speed_test();
  report_hardware("boot");

  benchmark_models();
  report_hardware("after_models");

  if (init_camera()) {
    report_hardware("after_camera");
    benchmark_camera();
    benchmark_pipeline_and_soak();
  }

  report_hardware("end");
  if (g_csv) {
    fclose(g_csv);
    g_csv = nullptr;
  }
  ESP_LOGI(TAG, "===== Xong. Lọc số liệu: grep '^CSV,' =====");
}
