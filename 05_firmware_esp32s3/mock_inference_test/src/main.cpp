// [D2] Mock firmware — CE340 Edge AI Traffic Sign (ESP32-S3-CAM N16R8)
//
// Mục đích (chưa phải firmware sản phẩm):
//   1. Xác nhận phần cứng: Flash 16 MB, PSRAM 8 MB, camera OV2640.
//   2. Nạp model INT8 (mock) vào tflite-micro, đo Tensor Arena đã dùng.
//   3. Đo thời gian Invoke() khi arena nằm ở PSRAM vs SRAM trong.
//   4. Đo thời gian chụp 1 frame camera.
// Toàn bộ số liệu in ra Serial — copy log gửi Sơn & Hôn trước buổi sync.

#include <cinttypes>
#include <cstdio>
#include <cstring>

#include "esp_camera.h"
#include "esp_chip_info.h"
#include "esp_flash.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_psram.h"
#include "esp_timer.h"

#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/schema/schema_generated.h"  // esp-tflite-micro >= 1.4

#include "board_pins.h"
#include "mock_model_int8.h"  // g_mock_model_int8, g_mock_model_int8_len (01_dataset/mock_assets)

static const char *TAG = "ce340";

namespace {

constexpr size_t kProbeArenaSize = 2 * 1024 * 1024;  // dư dả trong PSRAM để đo arena thật cần bao nhiêu
constexpr int kWarmupRuns = 3;
constexpr int kTimedRuns = 20;

void report_hardware() {
  esp_chip_info_t chip;
  esp_chip_info(&chip);
  uint32_t flash_size = 0;
  esp_flash_get_size(nullptr, &flash_size);

  ESP_LOGI(TAG, "Chip: ESP32-S3 rev %d, %d core(s)", chip.revision, chip.cores);
  ESP_LOGI(TAG, "Flash: %" PRIu32 " MB", flash_size / (1024 * 1024));
  ESP_LOGI(TAG, "PSRAM: %u MB (initialized=%d)",
           (unsigned)(esp_psram_get_size() / (1024 * 1024)), esp_psram_is_initialized());
  ESP_LOGI(TAG, "Free SRAM trong: %u KB | Free PSRAM: %u KB",
           (unsigned)(heap_caps_get_free_size(MALLOC_CAP_INTERNAL) / 1024),
           (unsigned)(heap_caps_get_free_size(MALLOC_CAP_SPIRAM) / 1024));
}

// Op của model mock (Conv/DepthwiseConv/MaxPool/Mean/FullyConnected). Model thật của Sơn
// có thể cần thêm op — AllocateTensors() sẽ báo lỗi tên op còn thiếu.
using OpResolver = tflite::MicroMutableOpResolver<12>;

void register_ops(OpResolver &resolver) {
  resolver.AddConv2D();
  resolver.AddDepthwiseConv2D();
  resolver.AddMaxPool2D();
  resolver.AddAveragePool2D();
  resolver.AddMean();
  resolver.AddFullyConnected();
  resolver.AddReshape();
  resolver.AddSoftmax();
  resolver.AddQuantize();
  resolver.AddDequantize();
  resolver.AddAdd();
  resolver.AddLogistic();
}

// Chạy model với arena cho trước; trả về số byte arena đã dùng (0 nếu lỗi).
size_t run_benchmark(const tflite::Model *model, OpResolver &resolver, uint8_t *arena,
                     size_t arena_size, const char *label) {
  tflite::MicroInterpreter interpreter(model, resolver, arena, arena_size);
  if (interpreter.AllocateTensors() != kTfLiteOk) {
    ESP_LOGE(TAG, "[%s] AllocateTensors() thất bại (arena %u B)", label, (unsigned)arena_size);
    return 0;
  }

  TfLiteTensor *input = interpreter.input(0);
  TfLiteTensor *output = interpreter.output(0);
  memset(input->data.int8, 0, input->bytes);  // ảnh đen giả lập

  for (int i = 0; i < kWarmupRuns; ++i) interpreter.Invoke();

  int64_t total_us = 0, worst_us = 0;
  for (int i = 0; i < kTimedRuns; ++i) {
    int64_t t0 = esp_timer_get_time();
    if (interpreter.Invoke() != kTfLiteOk) {
      ESP_LOGE(TAG, "[%s] Invoke() lỗi", label);
      return 0;
    }
    int64_t dt = esp_timer_get_time() - t0;
    total_us += dt;
    if (dt > worst_us) worst_us = dt;
  }

  const size_t used = interpreter.arena_used_bytes();
  ESP_LOGI(TAG, "[%s] input bytes=%u, output bytes=%u, arena dùng=%u B (%.1f KB)", label,
           (unsigned)input->bytes, (unsigned)output->bytes, (unsigned)used, used / 1024.0f);
  ESP_LOGI(TAG, "[%s] Invoke: TB %.2f ms | max %.2f ms (%d lần)", label,
           total_us / 1000.0f / kTimedRuns, worst_us / 1000.0f, kTimedRuns);
  return used;
}

void benchmark_model() {
  const tflite::Model *model = tflite::GetModel(g_mock_model_int8);
  if (model->version() != TFLITE_SCHEMA_VERSION) {
    ESP_LOGE(TAG, "Schema model %" PRIu32 " khác TFLM %d", model->version(), TFLITE_SCHEMA_VERSION);
    return;
  }
  ESP_LOGI(TAG, "Model mock: %u B (%.1f KB)", g_mock_model_int8_len, g_mock_model_int8_len / 1024.0f);

  static OpResolver resolver;
  register_ops(resolver);

  // Lần 1: arena lớn trong PSRAM để biết model cần bao nhiêu.
  auto *psram_arena = static_cast<uint8_t *>(
      heap_caps_aligned_alloc(16, kProbeArenaSize, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (!psram_arena) {
    ESP_LOGE(TAG, "Không cấp phát được arena PSRAM — kiểm tra CONFIG_SPIRAM_MODE_OCT");
    return;
  }
  const size_t needed = run_benchmark(model, resolver, psram_arena, kProbeArenaSize, "PSRAM");
  heap_caps_free(psram_arena);
  if (needed == 0) return;

  // Lần 2: arena vừa đủ (+10%) trong SRAM trong, nếu còn chỗ — so sánh tốc độ.
  const size_t sram_size = needed + needed / 10 + 1024;
  auto *sram_arena = static_cast<uint8_t *>(
      heap_caps_aligned_alloc(16, sram_size, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
  if (sram_arena) {
    run_benchmark(model, resolver, sram_arena, sram_size, "SRAM");
    heap_caps_free(sram_arena);
  } else {
    ESP_LOGW(TAG, "SRAM trong không đủ %u B cho arena — model thật sẽ phải chạy trên PSRAM",
             (unsigned)sram_size);
  }
  ESP_LOGI(TAG, ">>> Gợi ý kTensorArenaSize = %u B (arena dùng + 10%%)", (unsigned)sram_size);
}

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
  config.frame_size = FRAMESIZE_QVGA;      // 320x240 — OV2640 không có chế độ 320x320
  config.jpeg_quality = 12;
  config.fb_count = 2;
  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.grab_mode = CAMERA_GRAB_LATEST;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    ESP_LOGE(TAG, "Camera init lỗi 0x%x — kiểm tra cáp camera hoặc sai pinout (board_pins.h)", err);
    return false;
  }
  ESP_LOGI(TAG, "Camera init OK (QVGA RGB565)");
  return true;
}

void benchmark_camera() {
  if (!init_camera()) return;

  for (int i = 0; i < 3; ++i) {  // bỏ vài frame đầu khi cảm biến tự cân bằng sáng
    camera_fb_t *fb = esp_camera_fb_get();
    if (fb) esp_camera_fb_return(fb);
  }

  int64_t total_us = 0;
  int ok = 0;
  for (int i = 0; i < 20; ++i) {
    int64_t t0 = esp_timer_get_time();
    camera_fb_t *fb = esp_camera_fb_get();
    int64_t dt = esp_timer_get_time() - t0;
    if (!fb) continue;
    if (ok == 0) ESP_LOGI(TAG, "Frame: %ux%u, %u B", fb->width, fb->height, (unsigned)fb->len);
    esp_camera_fb_return(fb);
    total_us += dt;
    ++ok;
  }
  if (ok > 0) {
    ESP_LOGI(TAG, "Camera capture: TB %.2f ms/frame (%d/20 frame OK)", total_us / 1000.0f / ok, ok);
  } else {
    ESP_LOGE(TAG, "Không lấy được frame nào");
  }
}

}  // namespace

extern "C" void app_main(void) {
  ESP_LOGI(TAG, "===== CE340 [D2] mock_inference_test =====");
  report_hardware();
  benchmark_model();
  benchmark_camera();
  report_hardware();  // so sánh bộ nhớ còn lại sau khi camera đã cấp phát frame buffer
  ESP_LOGI(TAG, "===== Xong. Copy toàn bộ log này vào báo cáo D2 =====");
}
