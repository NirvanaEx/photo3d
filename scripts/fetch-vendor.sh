#!/usr/bin/env bash
# Кладёт 3D-вьюер локально, в web/static/vendor/.
#
# Именно локально, а не ссылкой на CDN: интерфейс должен открываться,
# когда интернета нет, а сборка - не меняться под ногами при обновлении пакета.
#
#   wsl -e bash -lc "tr -d '\r' < /mnt/d/Develop/photo3d/scripts/fetch-vendor.sh | bash"
set -euo pipefail

VENDOR=/mnt/d/Develop/photo3d/web/static/vendor
mkdir -p "$VENDOR"

echo "== model-viewer =="
curl -fL --progress-bar \
  https://unpkg.com/@google/model-viewer/dist/model-viewer.min.js \
  -o "$VENDOR/model-viewer.min.js"

SIZE=$(stat -c%s "$VENDOR/model-viewer.min.js")
echo "скачано: $SIZE байт"
if [ "$SIZE" -lt 100000 ]; then
  echo "ПОДОЗРИТЕЛЬНО МАЛО - вероятно, вместо бандла прилетела заглушка или редирект"
  head -c 300 "$VENDOR/model-viewer.min.js"
  exit 1
fi
echo "OK"
