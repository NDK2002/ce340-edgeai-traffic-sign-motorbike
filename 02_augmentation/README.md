# 02_augmentation — Tăng cường dữ liệu thời tiết phức tạp

* **Phụ trách chính:** Nguyễn Duy Khang (`[K2]`)
* **Sản phẩm Tuần 4:**
  * `augment_weather.py` — 4 kịch bản `Albumentations 2.x` với `BboxParams(format='yolo', label_fields=['class_labels'], min_visibility=0.4)`
  * `preview_samples/` — `20` ảnh vẽ bounding box kiểm chứng + `_grid_overview.jpg` (cột: gốc | mưa | mờ | che | đêm)
  * `tests/test_augment_weather.py`

## Kịch bản

| Kịch bản | Transform | Mô phỏng |
| :--- | :--- | :--- |
| `rain` | `RandomRain` (drizzle/heavy, vệt dài ~4% cạnh ảnh) + `Spatter(mode='rain')` | Mưa rơi + giọt nước đọng ống kính |
| `motion_blur` | `MotionBlur`, kernel 2–4.5% cạnh ngắn ảnh | Rung/mờ khi xe chạy `30–50 km/h` |
| `occlusion` | `ConstrainedCoarseDropout` — 1 mảng che màu ngẫu nhiên **bên trong mỗi bbox**, mỗi chiều 30–60% bbox | Bị che khuất `< 40%` (cành cây, xe khác, cột điện) |
| `night` | `RandomBrightnessContrast` (tối) + `RandomGamma` + `GaussNoise` | Thiếu sáng ban đêm, nhiễu cảm biến |

**Bảo đảm nhãn:** cả 4 kịch bản là biến đổi mức pixel (không dịch/xoay/crop) nên tọa độ bbox giữ nguyên. Mỗi ảnh đầu ra được tự kiểm tra: không mất nhãn, bbox không lệch quá `1.5px`, tỉ lệ che từng biển đo trên mask `< 40%`; mẫu không đạt được sinh lại (tối đa `--max-attempts`), thất bại thì ghi vào `augment_summary.json` và script trả mã lỗi `1`.

## Cách chạy (từ thư mục gốc repo)

```powershell
pip install -r requirements.txt

# Smoke-test trên 5 ảnh mock + sinh 20 ảnh preview
python 02_augmentation/augment_weather.py --preview 20

# Dataset thật: chạy SAU remap_and_split.py, riêng cho từng split để không rò rỉ giữa các split
python 02_augmentation/augment_weather.py `
  --images <dataset>/images/train --labels <dataset>/labels/train `
  --out <dataset_aug>/train --copies 1 --preview 0

# Kiểm thử
python -m pytest 02_augmentation/tests -q
```

* Đầu ra: `<out>/images/*.jpg`, `<out>/labels/*.txt` (tên `<ảnh gốc>__<kịch bản><n>`), `<out>/augment_summary.json`.
* `02_augmentation/outputs/` đã bị `.gitignore` chặn — lưu ảnh tăng cường trên Drive.
* Tập thử thách thời tiết cho benchmark: chạy script trên split `test` ra thư mục riêng, **không** trộn vào train.
