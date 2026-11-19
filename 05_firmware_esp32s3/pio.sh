#!/usr/bin/env bash
# Build/nạp firmware khi repo nằm ở đường dẫn có dấu cách (ESP-IDF không chấp nhận).
#
# Cách hoạt động: chép code firmware + model sang thư mục "gương" không dấu
# ($HOME/ce340-build), rồi chạy PlatformIO ở đó. Code vẫn sửa & commit trong repo gốc;
# thư mục gương chỉ để build, có thể xoá bất cứ lúc nào.
#
# Dùng (chạy từ thư mục gốc repo):
#   ./05_firmware_esp32s3/pio.sh                          # build mock_inference_test
#   ./05_firmware_esp32s3/pio.sh mock_inference_test run -t upload   # nạp vào bo
#   ./05_firmware_esp32s3/pio.sh mock_inference_test device monitor  # xem log
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT="${1:-mock_inference_test}"
[ $# -gt 0 ] && shift
[ $# -eq 0 ] && set -- run

MIRROR="${CE340_BUILD_DIR:-$HOME/ce340-build}"
PIO="${PIO:-$(command -v pio || echo "$HOME/.platformio-venv/bin/pio")}"
SRC="$REPO/05_firmware_esp32s3/$PROJECT"

[ -d "$SRC" ] || { echo "Không thấy project: $SRC" >&2; exit 1; }
case "$MIRROR" in *" "*) echo "CE340_BUILD_DIR không được có dấu cách: $MIRROR" >&2; exit 1;; esac

mkdir -p "$MIRROR/01_dataset" "$MIRROR/04_tinyml_optimization" "$MIRROR/05_firmware_esp32s3"

# Model mock và model thật (chỉ file .h/.tflite) — giữ đúng cấu trúc thư mục để đường dẫn tương đối không đổi
rsync -a --delete "$REPO/01_dataset/mock_assets" "$MIRROR/01_dataset/"
rsync -a --delete --include '*/' --include '*.h' --include '*.tflite' --exclude '*' \
  "$REPO/04_tinyml_optimization/" "$MIRROR/04_tinyml_optimization/"

# Code firmware. Không đụng tới cache build (.pio, managed_components, sdkconfig.<env>) ở gương
rsync -a --delete \
  --exclude .pio --exclude managed_components \
  --include sdkconfig.defaults --exclude 'sdkconfig.*' \
  "$SRC" "$MIRROR/05_firmware_esp32s3/"

echo ">> Build tại: $MIRROR/05_firmware_esp32s3/$PROJECT"
cd "$MIRROR/05_firmware_esp32s3/$PROJECT"
"$PIO" "$@"

# Đưa file khoá phiên bản thư viện về repo để commit (cả nhóm build ra giống nhau)
if [ -f dependencies.lock ] && ! cmp -s dependencies.lock "$SRC/dependencies.lock"; then
  cp dependencies.lock "$SRC/dependencies.lock"
  echo ">> Đã cập nhật $PROJECT/dependencies.lock trong repo — nhớ commit file này"
fi
