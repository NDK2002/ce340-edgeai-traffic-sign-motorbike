# 01_dataset — Thu thập, chuẩn hóa & Data Contract 12 lớp biển báo

* **Phụ trách chính:** Nguyễn Duy Khang (`[K1]`), Trần Hoàng Hôn (`[H1]` khởi tạo Contract & Mock Stub)
* **Tài liệu chuẩn:** [`classes.yaml`](./classes.yaml) (khóa cứng `class_id` `0..11` theo QCVN 41:2019/BGTVT)
* **Lưu ý Git:** Toàn bộ ảnh thật (`raw/`, `processed/`, `images/`, `labels/`, `train/`, `val/`, `test/`) bị chặn bởi `.gitignore` và lưu trên Google Drive / Roboflow; chỉ commit `classes.yaml`, `sources.yaml`, script `remap_and_split.py`, `data.yaml`, `dataset_summary.md` và thư mục mẫu nhỏ `mock_assets/`.

## `[K1]` Gộp nhãn & chia Train/Val/Test

| File | Vai trò |
| :--- | :--- |
| `sources.yaml` | Khai báo nguồn (YOLO/Roboflow hoặc COCO JSON như Zalo AI) + ánh xạ lớp nguồn → 12 lớp + quy tắc nhóm |
| `remap_and_split.py` | Ánh xạ nhãn, loại ảnh trùng, chia `70/20/10` theo nhóm chống rò rỉ frame, xuất YOLO |
| `tools/speed_tracks.py` | Tách lớp gộp `P.127` thành 40/50/60: ghép bbox qua các frame thành track, xuất bảng ảnh để đọc số 1 lần/track, sinh `label_overrides` |
| `overrides/` | Nhãn sửa tay có kiểm chứng: `p127/track_labels.yaml` (383 track) → `roboflow_vn_p127.csv` |
| `data.yaml` | *(sinh tự động)* cấu hình Ultralytics với `path: /content/ce340_v1` (nơi giải nén trên Colab, đổi bằng `--dataset-path`); trong zip có bản không `path` dùng được ở mọi nơi |
| `dataset_summary.md` | *(sinh tự động)* phân bố ảnh/biển theo split & lớp, kích thước bbox, lớp bị bỏ, cảnh báo |

### Quy trình

```powershell
# 1. Tải dataset về 01_dataset/raw/<tên nguồn>/ (hoặc Drive), đặt enabled: true trong sources.yaml
# 2. Xem tên lớp THẬT của nguồn + khung 'map' để điền
python 01_dataset/remap_and_split.py --inspect
# 3. Điền 'map' trong sources.yaml theo Ý NGHĨA biển (đọc kỹ ghi chú QCVN trong classes.yaml), rồi chạy
python 01_dataset/remap_and_split.py --out 01_dataset/processed
#    Trên Colab: --raw-root /content/drive/MyDrive/<raw> --out /content/drive/MyDrive/<dataset>
# 4. Kiểm thử
python -m pytest 01_dataset/tests -q
```

### Dùng dataset trên Colab

Bản đóng gói nằm ở Drive `ce340-edgeai-traffic-sign-motorbike/datasets/ce340_dataset_v<N>.zip` (tạo bằng
`python -c "import shutil; shutil.make_archive('01_dataset/ce340_dataset_v1', 'zip', '01_dataset/processed')"`,
không ghi đè bản cũ — tăng `v<N>`). Thư mục được chia sẻ nên cần **Add shortcut** vào My Drive trước.

```python
from google.colab import drive; drive.mount('/content/drive')
!unzip -q /content/drive/MyDrive/ce340-edgeai-traffic-sign-motorbike/datasets/ce340_dataset_v1.zip -d /content/ce340_v1
# train: --data /content/ce340_v1/data.yaml   (giải nén ra /content, đọc thẳng từ Drive rất chậm)
```

### Cách chia chống rò rỉ

* Ảnh cùng **nhóm** luôn vào cùng split. `group: auto` gộp các bản augment Roboflow của cùng ảnh gốc (`_jpg.rf.<hash>`) và frame video (`<clip>_mp4-0012`, `<clip>_frame_0012`); clip tự quay đặt tên khác thì dùng `group: 'regex:^(.+)_\d+$'`.
* Split của nguồn (train/valid/test của Roboflow) bị bỏ qua — mọi ảnh được gộp rồi chia lại theo nhóm.
* Gán nhóm tham lam cực tiểu sai lệch so với mục tiêu `70/20/10` cho **từng lớp** và số ảnh, nên lớp hiếm vẫn có mặt ở val/test (trừ khi lớp đó có quá ít clip — báo cáo sẽ cảnh báo).
* `scene_merge: 0.6` gộp thêm các ảnh **liền kề theo tên** có nội dung giống nhau (so phần trên ảnh, bỏ tay lái/gương) — bắt các clip liên tiếp quay cùng đoạn đường và ảnh `image_N` là frame video.
* Ảnh không còn biển nào sau ánh xạ được giữ làm mẫu nền tối đa `--background-ratio` (mặc định 10%).

### Tùy chọn nâng cao trong `sources.yaml`

* `label_overrides: <csv>` — đổi lớp nguồn của từng bbox (`image_stem,box_index,source_class,new_class`) trước khi ánh xạ; báo lỗi nếu CSV lệch phiên bản dataset.
* `exclude_if_present: [...]` — loại **cả ảnh** chứa lớp nguồn chưa gán được nhãn (giữ ảnh mà bỏ nhãn sẽ dạy model coi biển đó là nền).

### Tách biển tốc độ `P.127`

```powershell
python 01_dataset/tools/speed_tracks.py build --root 01_dataset/raw/roboflow_vn --out 01_dataset/overrides/p127
# Mở overrides/p127/sheet_*.jpg, điền overrides/p127/track_labels.yaml (40/50/60/30/80/unknown/mixed)
python 01_dataset/tools/speed_tracks.py apply --out 01_dataset/overrides/p127 --csv 01_dataset/overrides/roboflow_vn_p127.csv
```

> ⚠️ Nguồn hiện tại (Roboflow VN v6) **không có biển `R.301a` (đi thẳng)** → lớp 5 chưa có mẫu; lớp 1 (13 biển), 4 (39) và 10 (18, chỉ 1 cảnh) rất ít — cần nguồn bổ sung hoặc tự quay.
>
> ⚠️ Zalo AI 2020 chỉ có 7 lớp gộp (VD "No turning" gồm cả rẽ trái/phải/quay đầu, "Max Speed" gồm mọi tốc độ) nên chỉ ánh xạ thẳng được lớp *Cấm đi ngược chiều*. Cần nguồn chi tiết theo mã QCVN (Roboflow Universe) hoặc tách lớp thủ công cho các lớp còn lại.
