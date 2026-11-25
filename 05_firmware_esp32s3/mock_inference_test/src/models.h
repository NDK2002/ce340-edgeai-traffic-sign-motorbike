// Danh sách model được benchmark. Thêm model = include file .h + thêm 1 dòng vào kModels.
// File .h của Sơn ([S2]) đặt trong 04_tinyml_optimization/ (đã có trong INCLUDE_DIRS).
// Đặt tên theo <kiến trúc>_<kỹ thuật nén>_<kiểu>_<input>, ví dụ "mnv2_kd_prune_int8_96".
// Model đầu tiên (kPipelineModel trong main.cpp) được dùng cho pipeline camera và soak.
#pragma once

#include "mock_model_int8.h"

// Model thật của Sơn ([S4]): khi file 04_tinyml_optimization/traffic_sign_model_int8.h xuất hiện thì tự được
// đưa lên đầu danh sách (cả 2 firmware dùng model đầu tiên), không cần sửa code. Bản mô phỏng Wokwi
// (CE340_SIM, không có PSRAM) luôn dùng model mock.
#if __has_include("traffic_sign_model_int8.h") && !(defined(CE340_SIM) && CE340_SIM)
#include "traffic_sign_model_int8.h"
#define CE340_HAS_REAL_MODEL 1
#endif
// #include "mnv2_fp32_96.h"
// #include "mnv2_int8_96.h"
// #include "mnv2_prune_int8_96.h"

enum InputNorm {
  NORM_0_TO_1 = 0,       // YOLO / Ultralytics: x = v / 255.0f
  NORM_MINUS1_TO_1 = 1,  // MobileNetV2-SSD / Keras: x = (v / 127.5f) - 1.0f
};

struct ModelEntry {
  const char *name;
  const unsigned char *data;
  unsigned int len;
  InputNorm norm = NORM_0_TO_1;
};

// Nhánh TF (MobileNetV2-SSD / classifier Keras) chuẩn hoá ảnh về [-1, 1]. Nếu model thật là YOLO (nhánh ONNX)
// thì build với -DCE340_REAL_MODEL_NORM=NORM_0_TO_1.
#ifndef CE340_REAL_MODEL_NORM
#define CE340_REAL_MODEL_NORM NORM_MINUS1_TO_1
#endif

static const ModelEntry kModels[] = {
#ifdef CE340_HAS_REAL_MODEL
    {"traffic_sign_int8", g_traffic_sign_model_int8, g_traffic_sign_model_int8_len, CE340_REAL_MODEL_NORM},
#endif
    {"mock_int8_160", g_mock_model_int8, g_mock_model_int8_len, NORM_MINUS1_TO_1},
    // {"mnv2_fp32_96", g_mnv2_fp32_96, g_mnv2_fp32_96_len, NORM_MINUS1_TO_1},
    // {"mnv2_int8_96", g_mnv2_int8_96, g_mnv2_int8_96_len, NORM_MINUS1_TO_1},
    // {"mnv2_prune_int8_96", g_mnv2_prune_int8_96, g_mnv2_prune_int8_96_len, NORM_MINUS1_TO_1},
};
