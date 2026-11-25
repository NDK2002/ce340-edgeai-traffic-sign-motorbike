// Kiểm thử bộ giải mã đầu ra model (src/model_output.h) trên máy tính, không cần bo.
// Dữ liệu đối chiếu ssd_fixture.h sinh bởi tools/make_ssd_fixture.py từ code Python của dự án.
//
// Chạy từ gốc repo (một dòng):
//   c++ -std=c++17 -O2 -I05_firmware_esp32s3/traffic_sign_alert/src 05_firmware_esp32s3/traffic_sign_alert/host_tests/test_model_output.cpp -o /tmp/test_model_output && /tmp/test_model_output

#include <chrono>
#include <cmath>
#include <cstdio>
#include <vector>

#include "../src/model_output.h"
#include "ssd_fixture.h"

using namespace ce340;

namespace {

int g_fail = 0;

void check(bool ok, const char *name, const char *detail = "") {
  std::printf("[%s] %s %s\n", ok ? "  OK  " : " FAIL ", name, detail);
  if (!ok) ++g_fail;
}

TensorView view(const void *data, ElemType t, float scale, int zp, std::initializer_list<int> dims) {
  TensorView v;
  v.data = data;
  v.type = t;
  v.scale = scale;
  v.zero_point = zp;
  for (int d : dims) v.dims[v.ndims++] = d;
  return v;
}

void test_anchor_counts() {
  bool ok = true;
  char buf[160] = "";
  for (size_t i = 0; i < sizeof(fx::kSizes) / sizeof(fx::kSizes[0]); ++i) {
    const int got = ssd_anchor_count(fx::kSizes[i]);
    if (got != fx::kCounts[i]) {
      ok = false;
      std::snprintf(buf, sizeof(buf), "(s=%d: C++ %d, Keras %d)", fx::kSizes[i], got, fx::kCounts[i]);
    }
  }
  check(ok, "số anchor khớp model Keras ở 96/128/160/192/320", buf);

  int f[kSsdLevels];
  ssd_feature_sizes(fx::kImgsz, f);
  bool shapes_ok = true;
  for (int i = 0; i < kSsdLevels; ++i) shapes_ok &= f[i] == fx::kShapes[i];
  check(shapes_ok, "kích thước 6 feature map khớp model Keras");
}

void test_anchor_values() {
  std::vector<float> a(fx::kAnchors * 4);
  ssd_build_anchors(fx::kImgsz, a.data());
  int exact = 0;
  float worst = 0;
  for (int i = 0; i < fx::kAnchors * 4; ++i) {
    exact += a[i] == fx::kAnchorsRef[i];
    worst = std::max(worst, std::fabs(a[i] - fx::kAnchorsRef[i]));
  }
  char buf[96];
  std::snprintf(buf, sizeof(buf), "(%d/%d giá trị trùng từng bit, lệch lớn nhất %.2g)", exact, fx::kAnchors * 4, worst);
  check(worst < 1e-6f, "anchor C++ = build_anchors() Python", buf);
}

void test_ssd_int8() {
  std::vector<float> anchors(fx::kAnchors * 4);
  ssd_build_anchors(fx::kImgsz, anchors.data());
  const TensorView cls = view(fx::kCls, ElemType::kInt8, fx::kClsScale, fx::kClsZp, {1, fx::kAnchors, 13});
  const TensorView box = view(fx::kBox, ElemType::kInt8, fx::kBoxScale, fx::kBoxZp, {1, fx::kAnchors, 4});

  const auto t0 = std::chrono::steady_clock::now();
  const Detection d = ssd_best(cls, box, anchors.data(), 12);
  const double us = std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - t0).count();

  char buf[160];
  std::snprintf(buf, sizeof(buf), "(C++: anchor %d lớp %d điểm %.6f | Python: anchor %d lớp %d điểm %.6f)", d.anchor,
                d.cls, d.score, fx::kBestAnchor, fx::kBestClass, fx::kBestScore);
  check(d.anchor == fx::kBestAnchor && d.cls == fx::kBestClass, "SSD INT8: đúng anchor + lớp như Python", buf);
  check(std::fabs(d.score - fx::kBestScore) < 1e-5f, "SSD INT8: điểm softmax khớp Python (sai số < 1e-5)");
  check(d.anchor == fx::kPlantedAnchor && d.cls == fx::kPlantedClass, "SSD INT8: tìm đúng biển được cài sẵn");
  float worst = 0;
  for (int i = 0; i < 4; ++i) worst = std::max(worst, std::fabs(d.box[i] - fx::kBestBox[i]));
  std::snprintf(buf, sizeof(buf), "(lệch lớn nhất %.2g; box %.3f %.3f %.3f %.3f)", worst, d.box[0], d.box[1], d.box[2],
                d.box[3]);
  check(worst < 1e-5f, "SSD INT8: khung giải mã khớp Python", buf);
  std::snprintf(buf, sizeof(buf), "(%.0f µs trên máy tính)", us);
  check(true, "SSD INT8: thời gian giải mã", buf);
}

void test_ssd_float_matches_int8() {
  std::vector<float> anchors(fx::kAnchors * 4);
  ssd_build_anchors(fx::kImgsz, anchors.data());
  std::vector<float> clsf(fx::kAnchors * 13), boxf(fx::kAnchors * 4);
  for (size_t i = 0; i < clsf.size(); ++i) clsf[i] = (fx::kCls[i] - fx::kClsZp) * fx::kClsScale;
  for (size_t i = 0; i < boxf.size(); ++i) boxf[i] = (fx::kBox[i] - fx::kBoxZp) * fx::kBoxScale;
  const TensorView cls = view(clsf.data(), ElemType::kFloat32, 0, 0, {1, fx::kAnchors, 13});
  const TensorView box = view(boxf.data(), ElemType::kFloat32, 0, 0, {1, fx::kAnchors, 4});
  const Detection d = ssd_best(cls, box, anchors.data(), 12);
  check(d.anchor == fx::kBestAnchor && d.cls == fx::kBestClass && std::fabs(d.score - fx::kBestScore) < 1e-5f,
        "SSD FP32: cùng kết quả với bản INT8 (bảng tra exp không làm sai)");
}

void test_classifier() {
  const float probs[12] = {0.01f, 0.02f, 0.03f, 0.04f, 0.05f, 0.5f, 0.05f, 0.1f, 0.05f, 0.05f, 0.05f, 0.05f};
  Detection d = classify(view(probs, ElemType::kFloat32, 0, 0, {1, 12}));
  check(d.cls == 5 && std::fabs(d.score - 0.5f) < 1e-6f, "classifier: đầu ra đã là xác suất → giữ nguyên");

  const int8_t logits[13] = {-50, -40, 20, -60, -60, -60, -60, -60, -60, -60, -60, -60, 0};
  d = classify(view(logits, ElemType::kInt8, 0.1f, -10, {1, 13}));
  const double e2 = std::exp(3.0), e12 = std::exp(1.0);
  double total = e2 + e12 + std::exp(-4.0) + std::exp(-3.0);
  for (int i = 0; i < 9; ++i) total += std::exp(-5.0);
  check(d.cls == 2 && std::fabs(d.score - e2 / total) < 1e-5, "classifier: logits INT8 → softmax đúng");
}

void test_layout() {
  int8_t dummy[4] = {};
  const TensorView c12 = view(dummy, ElemType::kInt8, 1, 0, {1, 12});
  OutputLayout L = detect_layout(&c12, 1, 96, 96, 12);
  check(L.kind == OutputKind::kClassifier, "nhận dạng: [1, 12] → classifier");

  const TensorView c13 = view(dummy, ElemType::kInt8, 1, 0, {1, 13});
  L = detect_layout(&c13, 1, 64, 64, 12);
  check(L.kind == OutputKind::kClassifier, "nhận dạng: [1, 13] (có lớp không-phải-biển) → classifier");

  TensorView ssd_box_first[2] = {view(dummy, ElemType::kInt8, 1, 0, {1, 3752, 4}),
                                 view(dummy, ElemType::kInt8, 1, 0, {1, 3752, 13})};
  L = detect_layout(ssd_box_first, 2, 160, 160, 12);
  check(L.kind == OutputKind::kSsd && L.cls_index == 1 && L.box_index == 0 && L.anchors == 3752,
        "nhận dạng: SSD 160 với đầu ra box đứng trước");

  TensorView dynamic[2] = {view(dummy, ElemType::kInt8, 1, 0, {1, 1, 4}), view(dummy, ElemType::kInt8, 1, 0, {1, 1, 13})};
  L = detect_layout(dynamic, 2, 96, 96, 12);
  check(L.kind == OutputKind::kUnknown && L.error != nullptr, "nhận dạng: SSD batch động [1,1,x] → báo lỗi rõ ràng",
        L.error ? L.error : "");

  TensorView wrong_size[2] = {view(dummy, ElemType::kInt8, 1, 0, {1, 3752, 13}),
                              view(dummy, ElemType::kInt8, 1, 0, {1, 3752, 4})};
  L = detect_layout(wrong_size, 2, 96, 96, 12);
  check(L.kind == OutputKind::kUnknown, "nhận dạng: số anchor không khớp cỡ ảnh → báo lỗi");
}

}  // namespace

int main() {
  test_anchor_counts();
  test_anchor_values();
  test_ssd_int8();
  test_ssd_float_matches_int8();
  test_classifier();
  test_layout();
  std::printf("\n%s (%d lỗi)\n", g_fail == 0 ? "TẤT CẢ ĐẠT" : "CÓ LỖI", g_fail);
  return g_fail == 0 ? 0 : 1;
}
