# 03_models_benchmark — Huấn luyện đa mô hình & Benchmark

* **Phụ trách chính:** Phạm Thành Trung (`[T1]`, `[T2]`)
* **Sản phẩm Tuần 4:**
  * `train_baseline.py`: huấn luyện YOLOv8n, YOLOv5 nano hoặc MobileNetV2-SSD; cho phép chọn `--imgsz 160`, `192` hoặc `320`.
* `evaluate_benchmark.py`: đo macro Precision/Recall/F1, mAP@0.5, mAP@0.5:0.95 và confusion matrix cho checkpoint PyTorch/Keras.
  * `mobilenetv2_ssd.py`: model SSD nhiều tầng, đọc nhãn YOLO và lưu cả `.keras` lẫn TensorFlow SavedModel.
  * Checkpoint và run artifacts lớn phải lưu trên Google Drive; `.pt` và `.onnx` đã được `.gitignore` chặn.

## Trạng thái kiến trúc

`yolov8n` và `yolov5-tiny` chạy qua Ultralytics. Lựa chọn `yolov5-tiny` dùng checkpoint `yolov5nu.pt` (YOLOv5u nano), biến thể được Ultralytics duy trì; checkpoint từ repo YOLOv5 đời cũ không tương thích trực tiếp với Ultralytics hiện tại. Có thể truyền checkpoint khác bằng `--weights` nếu tương thích với phiên bản đang cài.

`mobilenetv2-ssd` dùng backbone MobileNetV2 pretrained ImageNet, các SSD head/anchor nhiều tầng và loss classification + box regression. Trọng số head detection được khởi tạo mới, vì vậy kết quả mock chỉ xác nhận code chạy; phải huấn luyện với dữ liệu thật để có model nhận diện biển báo hữu ích.

Model Keras được lưu bằng legacy Keras 2 API (`tf-keras` cùng TensorFlow `2.17.x`) để tương thích với TFMOT. Pipeline đặt `TF_USE_LEGACY_KERAS=1` trước khi nạp TensorFlow; các script tối ưu hóa khác cũng cần giữ biến môi trường này.

Benchmark dùng cùng quy ước cho cả ba model: macro P/R/F1 trên các lớp có ground truth, ngưỡng confidence tối đa macro-F1 khi chạy validation, và AP nội suy 101 điểm cho mAP. Khi so sánh ở một ngưỡng vận hành cố định, truyền cùng `--conf` cho mỗi model. Khi chạy test cuối, dùng ngưỡng đã chốt trên validation; không tự chọn threshold trên test.

## Chạy smoke-test trên mock

Chạy từ thư mục gốc repo. Bộ mock chỉ có 5 ảnh và dùng cùng split cho train/val/test; đây là smoke-test kiểm tra pipeline, không phải số liệu đánh giá mô hình.

```powershell
pip install -r requirements.txt
python 03_models_benchmark/train_baseline.py `
  --model yolov8n `
  --data 01_dataset/mock_assets/data_mock.yaml `
  --imgsz 160 --epochs 2 --batch 2 --device cpu `
  --project 03_models_benchmark/runs --name mock-yolov8n --export onnx
```

Sau khi train, dùng đường dẫn `best.pt` được in ra để benchmark:

```powershell
python 03_models_benchmark/evaluate_benchmark.py `
  --weights 03_models_benchmark/runs/mock-yolov8n/weights/best.pt `
  --data 01_dataset/mock_assets/data_mock.yaml `
  --imgsz 160 --device cpu
```

Chạy nhánh TensorFlow/Keras trên mock:

```powershell
python 03_models_benchmark/train_baseline.py `
  --model mobilenetv2-ssd `
  --data 01_dataset/mock_assets/data_mock.yaml `
  --imgsz 160 --epochs 2 --batch 2 --freeze-backbone `
  --project 03_models_benchmark/runs --name example-mobilenetv2-ssd

python 03_models_benchmark/evaluate_benchmark.py `
  --weights 03_models_benchmark/runs/example-mobilenetv2-ssd/mobilenetv2_ssd.keras `
  --data 01_dataset/mock_assets/data_mock.yaml --imgsz 160
```

Sau khi lấy ngưỡng từ validation, chạy đánh giá cuối trên test bằng ngưỡng đó:

```powershell
python 03_models_benchmark/evaluate_benchmark.py `
  --weights path/to/best.pt `
  --data 01_dataset/data.yaml --split test --conf 0.25 --imgsz 160
```

Thay `0.25` bằng ngưỡng `confidence` đã lưu trong kết quả validation của đúng model.

Kết quả benchmark gồm `benchmark_metrics.json`, `benchmark_summary.csv` và ảnh confusion matrix trong `03_models_benchmark/runs/`. Mock handoff đã gom ONNX, Keras/SavedModel, cấu hình train, metric và confusion matrix tại `03_models_benchmark/mock_outputs/` (bị Git ignore cùng artifacts lớn). Với dataset thật, thay `--data` bằng `01_dataset/data.yaml`, chọn GPU bằng `--device 0`, tăng epoch/batch theo bộ nhớ GPU và ghi checkpoint vào thư mục Google Drive được mount trong Colab.

## Export và handoff TinyML

`--export onnx` xuất ONNX để nhánh PyTorch của Sơn tiếp tục xử lý. Model MobileNetV2-SSD được lưu thành `.keras` và SavedModel để Sơn dùng cho nhánh TensorFlow/`tfmot`. `--export saved_model` của YOLO chỉ là artifact chuyển định dạng từ model PyTorch.

API train, validation và export dựa trên [tài liệu Python của Ultralytics](https://docs.ultralytics.com/usage/python/) và [tài liệu YOLOv5 của Ultralytics](https://docs.ultralytics.com/models/yolov5/).

