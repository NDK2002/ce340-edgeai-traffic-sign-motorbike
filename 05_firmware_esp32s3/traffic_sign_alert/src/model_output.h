// Giải mã đầu ra model trên chip. C++ thuần, không phụ thuộc ESP-IDF / TFLite Micro → kiểm thử được
// trên máy tính (host_tests/test_model_output.cpp).
//
// Hai loại model được nhận tự động theo shape đầu ra (detect_layout):
//   - Classifier (đề xuất P1): 1 đầu ra [1, N], N = 12 lớp, hoặc 13 nếu thêm lớp "không phải biển".
//   - MobileNetV2-SSD (03_models_benchmark/mobilenetv2_ssd.py): 2 đầu ra [1, A, 13] logits lớp và
//     [1, A, 4] offset khung. Lớp cuối (12) là nền. Anchor sinh y hệt build_anchors() trong Python.
// Thứ tự 2 đầu ra SSD đổi giữa các lần export, nên nhận theo chiều cuối (13 hay 4), không theo thứ tự.
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace ce340 {

enum class ElemType : uint8_t { kInt8, kUInt8, kFloat32 };

struct TensorView {
  const void *data = nullptr;
  ElemType type = ElemType::kFloat32;
  float scale = 0.0f;
  int zero_point = 0;
  int dims[4] = {0, 0, 0, 0};
  int ndims = 0;

  int last_dim() const { return ndims > 0 ? dims[ndims - 1] : 0; }
  int count() const {
    int n = 1;
    for (int i = 0; i < ndims; ++i) n *= dims[i];
    return n;
  }
  // Giá trị nguyên lượng tử hoá (chỉ dùng với int8 / uint8).
  int q(int i) const {
    return type == ElemType::kInt8 ? static_cast<const int8_t *>(data)[i] : static_cast<const uint8_t *>(data)[i];
  }
  // Giá trị thực đã giải lượng tử hoá.
  float at(int i) const {
    if (type == ElemType::kFloat32) return static_cast<const float *>(data)[i];
    return (q(i) - zero_point) * scale;
  }
};

// box: x1, y1, x2, y2 chuẩn hoá 0..1 trên ảnh đưa vào model (vùng ROI nếu có cắt). anchor = -1 với classifier.
struct Detection {
  int cls = -1;
  float score = 0.0f;
  int anchor = -1;
  float box[4] = {0, 0, 0, 0};
};

// ---------------- Classifier ----------------

// Lớp có điểm cao nhất. Nếu đầu ra đã là xác suất thì giữ nguyên, nếu là logits thì tự tính softmax.
inline Detection classify(const TensorView &out) {
  Detection d;
  const int n = std::min(out.count(), 64);
  if (n <= 0) return d;
  float v[64];
  float sum = 0, mn = 0, mx = 0;
  for (int i = 0; i < n; ++i) {
    v[i] = out.at(i);
    sum += v[i];
    mn = i == 0 ? v[i] : std::min(mn, v[i]);
    mx = i == 0 ? v[i] : std::max(mx, v[i]);
  }
  const bool is_prob = mn >= -0.01f && mx <= 1.01f && sum > 0.9f && sum < 1.1f;
  if (!is_prob) {
    float total = 0;
    for (int i = 0; i < n; ++i) total += (v[i] = std::exp(v[i] - mx));
    for (int i = 0; i < n; ++i) v[i] /= total;
  }
  d.cls = static_cast<int>(std::max_element(v, v + n) - v);
  d.score = v[d.cls];
  return d;
}

// ---------------- MobileNetV2-SSD ----------------

constexpr int kSsdLevels = 6;
constexpr int kSsdAnchorsPerCell = 4;
constexpr float kSsdCenterVariance = 0.1f;
constexpr float kSsdSizeVariance = 0.2f;

// Cạnh 6 feature map theo cạnh ảnh vào s: s/8, s/8, s/16, rồi chia đôi (làm tròn lên) 3 lần.
// Đã đối chiếu với model Keras thật: s = 96/128/160/192/320 → 1352/2388/3752/5380/14936 anchor.
inline void ssd_feature_sizes(int s, int out[kSsdLevels]) {
  out[0] = (s + 7) / 8;
  out[1] = out[0];
  out[2] = (s + 15) / 16;
  for (int i = 3; i < kSsdLevels; ++i) out[i] = (out[i - 1] + 1) / 2;
}

inline int ssd_anchor_count(int s) {
  int f[kSsdLevels];
  ssd_feature_sizes(s, f);
  int n = 0;
  for (int i = 0; i < kSsdLevels; ++i) n += f[i] * f[i] * kSsdAnchorsPerCell;
  return n;
}

// Ghi anchor (cx, cy, w, h) vào out[ssd_anchor_count(s) * 4]. Tính bằng double rồi ép float như
// build_anchors() (numpy linspace float32 → toán Python double → mảng float32) để ra đúng từng bit.
inline void ssd_build_anchors(int s, float *out) {
  int f[kSsdLevels];
  ssd_feature_sizes(s, f);
  const double start = 0.08, stop = 0.90;
  const double step = (stop - start) / kSsdLevels;
  float scales[kSsdLevels + 1];
  for (int i = 0; i <= kSsdLevels; ++i) scales[i] = static_cast<float>(i == kSsdLevels ? stop : i * step + start);
  const double r2 = std::sqrt(2.0);
  int k = 0;
  for (int level = 0; level < kSsdLevels; ++level) {
    const double sc = scales[level];
    const double extra = std::sqrt(sc * static_cast<double>(scales[level + 1]));
    const double sizes[kSsdAnchorsPerCell][2] = {{sc, sc}, {extra, extra}, {sc * r2, sc / r2}, {sc / r2, sc * r2}};
    const int n = f[level];
    for (int row = 0; row < n; ++row) {
      for (int col = 0; col < n; ++col) {
        const double cx = (col + 0.5) / n;
        const double cy = (row + 0.5) / n;
        for (const auto &wh : sizes) {
          out[k++] = static_cast<float>(cx);
          out[k++] = static_cast<float>(cy);
          out[k++] = static_cast<float>(wh[0]);
          out[k++] = static_cast<float>(wh[1]);
        }
      }
    }
  }
}

// Giải mã offset của 1 anchor thành khung x1, y1, x2, y2 (giống _decode_predictions trong Python).
inline void ssd_decode_box(const TensorView &box, const float *anchors, int a, float out[4]) {
  const float *p = anchors + a * 4;
  const int b = a * 4;
  const float cx = box.at(b + 0) * p[2] * kSsdCenterVariance + p[0];
  const float cy = box.at(b + 1) * p[3] * kSsdCenterVariance + p[1];
  const float w = std::exp(std::clamp(box.at(b + 2) * kSsdSizeVariance, -10.0f, 10.0f)) * p[2];
  const float h = std::exp(std::clamp(box.at(b + 3) * kSsdSizeVariance, -10.0f, 10.0f)) * p[3];
  out[0] = std::clamp(cx - w / 2, 0.0f, 1.0f);
  out[1] = std::clamp(cy - h / 2, 0.0f, 1.0f);
  out[2] = std::clamp(cx + w / 2, 0.0f, 1.0f);
  out[3] = std::clamp(cy + h / 2, 0.0f, 1.0f);
}

// Phát hiện có điểm cao nhất trong num_classes lớp biển (bỏ lớp nền ở cuối).
// Logits int8/uint8 dùng chung 1 scale nên exp(l_i − l_max) chỉ phụ thuộc hiệu q_i − q_max ∈ [−255, 0]:
// tra bảng 256 giá trị thay cho expf, kết quả như tính trực tiếp.
inline Detection ssd_best(const TensorView &cls, const TensorView &box, const float *anchors, int num_classes) {
  Detection best;
  const int A = cls.dims[1];
  const int C = cls.last_dim();
  if (C < num_classes + 1 || C > 64) return best;
  const bool quant = cls.type != ElemType::kFloat32;
  float lut[256];
  if (quant) {
    for (int d = 0; d < 256; ++d) lut[d] = std::exp(-d * cls.scale);
  }
  float e[64];
  for (int a = 0; a < A; ++a) {
    const int base = a * C;
    float denom = 0;
    if (quant) {
      int qmax = cls.q(base);
      for (int c = 1; c < C; ++c) qmax = std::max(qmax, cls.q(base + c));
      for (int c = 0; c < C; ++c) denom += (e[c] = lut[qmax - cls.q(base + c)]);
    } else {
      float vmax = cls.at(base);
      for (int c = 1; c < C; ++c) vmax = std::max(vmax, cls.at(base + c));
      for (int c = 0; c < C; ++c) denom += (e[c] = std::exp(cls.at(base + c) - vmax));
    }
    for (int c = 0; c < num_classes; ++c) {
      const float p = e[c] / denom;
      if (p > best.score) {
        best.score = p;
        best.cls = c;
        best.anchor = a;
      }
    }
  }
  if (best.anchor >= 0) ssd_decode_box(box, anchors, best.anchor, best.box);
  return best;
}

// ---------------- Nhận dạng loại model ----------------

enum class OutputKind : uint8_t { kUnknown, kClassifier, kSsd };

struct OutputLayout {
  OutputKind kind = OutputKind::kUnknown;
  int cls_index = -1;  // chỉ số đầu ra chứa điểm lớp
  int box_index = -1;  // chỉ số đầu ra chứa offset khung (SSD)
  int anchors = 0;
  const char *error = nullptr;
};

inline const char *kind_name(OutputKind k) {
  switch (k) {
    case OutputKind::kClassifier: return "classifier";
    case OutputKind::kSsd: return "ssd";
    default: return "unknown";
  }
}

// outs: các đầu ra của model. in_h, in_w: kích thước ảnh vào. num_classes: số lớp biển (12).
inline OutputLayout detect_layout(const TensorView *outs, int n, int in_h, int in_w, int num_classes) {
  OutputLayout L;
  if (n == 1) {
    const int N = outs[0].count();
    if (outs[0].last_dim() == N && (N == num_classes || N == num_classes + 1)) {
      L.kind = OutputKind::kClassifier;
      L.cls_index = 0;
      return L;
    }
    L.error = "1 đầu ra nhưng không phải [1, 12] hoặc [1, 13]";
    return L;
  }
  if (n == 2) {
    for (int i = 0; i < 2; ++i) {
      if (outs[i].ndims == 3 && outs[i].last_dim() == num_classes + 1) L.cls_index = i;
      if (outs[i].ndims == 3 && outs[i].last_dim() == 4) L.box_index = i;
    }
    if (L.cls_index < 0 || L.box_index < 0 || L.cls_index == L.box_index) {
      L.error = "2 đầu ra nhưng không phải cặp SSD [1, A, 13] + [1, A, 4]";
      return L;
    }
    const int A = outs[L.cls_index].dims[1];
    if (A == 1 || outs[L.box_index].dims[1] == 1) {
      L.error = "đầu ra SSD có shape [1, 1, x]: model export với batch động, cần export lại với batch = 1";
      return L;
    }
    if (A != outs[L.box_index].dims[1]) {
      L.error = "2 đầu ra SSD có số anchor khác nhau";
      return L;
    }
    if (in_h != in_w || A != ssd_anchor_count(in_h)) {
      L.error = "số anchor không khớp MobileNetV2-SSD với ảnh vào vuông (anchor phải theo build_anchors)";
      return L;
    }
    L.kind = OutputKind::kSsd;
    L.anchors = A;
    return L;
  }
  L.error = "số đầu ra không hỗ trợ (cần 1 cho classifier hoặc 2 cho SSD)";
  return L;
}

}  // namespace ce340
