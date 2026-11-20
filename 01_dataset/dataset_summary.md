# BÁO CÁO PHÂN BỐ DATASET 12 LỚP — CE340 ([K1])

> Sinh tự động bởi `01_dataset/remap_and_split.py`. Ảnh lưu trên Drive/Roboflow, không đưa lên GitHub.

* **Thư mục dataset:** `E:\projects\ce340-edgeai-traffic-sign-motorbike\01_dataset\processed`
* **Tỉ lệ chia (theo nhóm chống rò rỉ frame):** 70% / 20% / 10% — seed `42`
* **Tổng:** `1087` ảnh, `1339` biển, `135` nhóm

## 1. Số ảnh theo split

| Split | Ảnh | Tỉ lệ thực | Nhóm | Ảnh nền (không biển) |
| :--- | ---: | ---: | ---: | ---: |
| train | 757 | 69.6% | 102 | 89 |
| val | 216 | 19.9% | 23 | 14 |
| test | 114 | 10.5% | 10 | 5 |

## 2. Số biển báo theo lớp

`bbox_w` = trung vị bề rộng bbox / bề rộng ảnh; nhân với `imgsz` (160/320) để ước lượng số pixel của biển khi đưa vào model.

| ID | Lớp | Train | Val | Test | Tổng | bbox_w | ≈px @160 |
| ---: | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | `cam_di_nguoc_chieu` | 170 | 46 | 21 | 237 | 0.024 | 4 |
| 1 | `cam_re_trai` | 9 | 2 | 2 | 13 | 0.132 | 21 |
| 2 | `cam_re_phai` | 46 | 22 | 17 | 85 | 0.050 | 8 |
| 3 | `cam_quay_dau` | 41 | 19 | 10 | 70 | 0.087 | 14 |
| 4 | `cam_xe_mo_to` | 25 | 14 | 0 | 39 | 0.039 | 6 |
| 5 | `huong_di_thang` | 0 | 0 | 0 | 0 | 0.000 | 0 |
| 6 | `vong_xuyen` | 35 | 9 | 9 | 53 | 0.129 | 21 |
| 7 | `toc_do_40` | 52 | 15 | 7 | 74 | 0.050 | 8 |
| 8 | `toc_do_50` | 159 | 46 | 21 | 226 | 0.061 | 10 |
| 9 | `toc_do_60` | 267 | 73 | 43 | 383 | 0.057 | 9 |
| 10 | `giao_nhau_den_tin_hieu` | 18 | 0 | 0 | 18 | 0.198 | 32 |
| 11 | `di_cham` | 101 | 26 | 14 | 141 | 0.048 | 8 |

## 3. Theo nguồn dữ liệu

### `roboflow_vn`

* Ảnh đọc được: `3680` — giữ `1087` (trong đó `108` ảnh nền), trùng lặp bị loại `0`
* Gộp cảnh liền kề giống nhau (`scene_merge`): `172` lần; nhãn sửa tay (`label_overrides`): `1241` biển
* Ảnh bị loại do chứa lớp chưa tách nhãn (`exclude_if_present`): `P.127_unknown`: 132 ảnh, `P.127_mixed`: 22 ảnh
* Ánh xạ: `P.102 -> cam_di_nguoc_chieu`: 237, `P.104 -> cam_xe_mo_to`: 39, `P.123a -> cam_re_trai`: 13, `P.123b -> cam_re_phai`: 85, `P.124a -> cam_quay_dau`: 70, `P.127_40 -> toc_do_40`: 74, `P.127_50 -> toc_do_50`: 226, `P.127_60 -> toc_do_60`: 383, `P.245a -> di_cham`: 1, `R.303 -> vong_xuyen`: 53, `W.209 -> giao_nhau_den_tin_hieu`: 18, `W.245a -> di_cham`: 140
* Lớp nguồn bị bỏ (không thuộc 12 lớp): `P.130`: 701, `P.131a`: 684, `W.224`: 256, `R.302a`: 221, `W.207b`: 204, `P.127_80`: 179, `P.117`: 138, `P.106b`: 110, `W.201a`: 104, `P.103c`: 84, `P.106a`: 83, `S.509a`: 72, `R.434`: 70, `W.225`: 68, `W.207a`: 60, `W.207c`: 60, `R.407a`: 57, `W.201b`: 55, `P.103a`: 52, `W.205a`: 48, `W.205d`: 47, `R.409`: 40, `R.302b`: 31, `W.202a`: 31, `W.210`: 30, `W.202b`: 29, `W.208`: 29, `W.203b`: 23, `R.301c`: 23, `W.203c`: 22, `P.127_30`: 22, `W.233`: 21, `DP.135`: 19, `R.301d`: 18, `W.227`: 18, `R.301e`: 16, `P.107a`: 15, `P.137`: 15, `P.112`: 14, `P.115`: 13, `P.124c`: 12, `P.103b`: 11, `R.425`: 8, `W.219`: 7, `P.124b`: 7, `W.205b`: 5, `P.128`: 4, `W.221b`: 2, `P.125`: 2, `W.235`: 1

## 4. Cảnh báo

* ⚠️ Lớp 1 'cam_re_trai' chỉ có 13 biển (< 50)
* ⚠️ Lớp 4 'cam_xe_mo_to' chỉ có 39 biển (< 50)
* ⚠️ Lớp 4 'cam_xe_mo_to' không có mẫu trong split test
* ⚠️ Lớp 5 'huong_di_thang' KHÔNG có mẫu nào
* ⚠️ Lớp 10 'giao_nhau_den_tin_hieu' chỉ có 18 biển (< 50)
* ⚠️ Lớp 10 'giao_nhau_den_tin_hieu' không có mẫu trong split val
* ⚠️ Lớp 10 'giao_nhau_den_tin_hieu' không có mẫu trong split test
