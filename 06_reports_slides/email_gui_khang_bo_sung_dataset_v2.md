# THÔNG BÁO EMAIL: PHỐI HỢP BỔ SUNG DATASET V2 (LỚP 5 R.301a & CÁC LỚP HIẾM)

* **Người gửi:** Trần Hoàng Hôn (`26410046` - Trưởng nhóm / QA)
* **Người nhận:** Nguyễn Duy Khang (`26410055` - Kỹ sư Dữ liệu / `ndk1200@gmail.com` / `@NDK2002`)
* **Thời gian lập:** 20/11/2026
* **Trạng thái liên quan:** Đã merge PR #5 (`feat/k1-k2-dataset-augmentation`) chốt **Dataset v1**.

---

### Tiêu đề email:
`[CE340 - Đồ án Nhúng] Phối hợp bổ sung Dataset v2 (Bổ sung Lớp 5 & các lớp hiếm)`

### Nội dung email:

Chào Khang,

Bản **Dataset v1** trong PR #5 của em làm rất tốt và anh đã merge vào `main` để chốt mốc dữ liệu cho nhóm. 

Hiện tại, các bạn khác trong nhóm (**Trung** train Colab, **Sơn** làm TinyML, **Duy** và **Hôn** làm Firmware) **vẫn sử dụng bình thường bản Dataset v1 này** (`ce340_dataset_v1.zip`), tiến độ chung của nhóm hoàn toàn không bị ảnh hưởng hay phải chờ đợi.

Để chuẩn bị cho bản **Dataset v2** hoàn thiện hơn, anh nhờ Khang thong thả tìm kiếm và bổ sung thêm dữ liệu theo **Hướng 1 (tìm thêm các project công khai)**:

#### 1. Mục tiêu bổ sung:
* **Lớp 5 (`huong_di_thang` - R.301a):** Hiện đang có 0 mẫu (ưu tiên cao nhất).
* **Bổ sung thêm mẫu cho các lớp hiếm:**
  * Lớp 1 (`cam_re_trai` - P.123a): Hiện có 13 biển.
  * Lớp 4 (`cam_xe_mo_to` - P.104): Hiện có 39 biển (tập test đang trống).
  * Lớp 10 (`giao_nhau_den_tin_hieu` - W.209): Hiện có 18 biển (tập val/test đang trống).

#### 2. Nguồn đề xuất tìm kiếm:
* Dạo trên **Roboflow Universe** với các từ khóa: `"vietnam traffic sign"`, `"vietnamese traffic sign detection"`, `"bien bao giao thong"`. Các project của sinh viên/cộng đồng thường gán sẵn nhãn theo chuẩn YOLO.
* Hoặc bộ dữ liệu *Zalo AI Challenge 2020* (mục `zalo2020` em đã tạo khung sẵn trong `sources.yaml`).

#### 3. Cách thực hiện:
* Khang mở một branch mới (ví dụ: `feat/k1-dataset-v2`).
* Khi tìm được tập dữ liệu ưng ý, em chỉ cần khai báo thêm nguồn vào `01_dataset/sources.yaml`, chạy lại `remap_and_split.py` để sinh ra file nén `ce340_dataset_v2.zip` đưa lên Drive.

Phần này Khang cứ từ từ tìm và lọc kỹ, không bị áp lực thời gian nhé!

Thân ái,  
**Trần Hoàng Hôn**  
*PM Đồ án CE340 — Hệ thống cảnh báo biển báo giao thông trên xe máy*
