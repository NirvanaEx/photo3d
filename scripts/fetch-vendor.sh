#!/usr/bin/env bash
# Кладёт 3D-вьюер локально, в web/static/vendor/.
#
# Именно локально, а не ссылкой на CDN: интерфейс должен открываться,
# когда интернета нет, а сборка - не меняться под ногами при обновлении пакета.
#
#   wsl -e bash -lc "tr -d '\r' < /mnt/d/Develop/photo3d/scripts/fetch-vendor.sh | bash"
#
# Аргументом можно взять только одну часть: model-viewer | three.
# Это не украшение: model-viewer тянется по latest, и лишний его перезалив
# посреди работы меняет рабочий бандл под ногами - то самое, от чего
# вендоринг и защищает. Обновлять надо намеренно и по одному.
set -euo pipefail

WHAT=${1:-all}
VENDOR=/mnt/d/Develop/photo3d/web/static/vendor
mkdir -p "$VENDOR"

if [ "$WHAT" = all ] || [ "$WHAT" = model-viewer ]; then
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
fi

# ---------------------------------------------------------------- three.js
#
# Версия ПРИБИТА, а не latest: аддоны из examples/jsm живут в одном репозитории
# с ядром и совместимости между версиями им никто не обещает. Обновление -
# осознанный шаг с проверкой, а не то, что случается само при следующем запуске.
#
# Раскладка каталогов повторяет репозиторий (build/ и examples/jsm/ -> addons/),
# потому что аддоны импортируют друг друга ОТНОСИТЕЛЬНЫМИ путями:
# GLTFLoader тянет ../utils/BufferGeometryUtils.js, Octree - ../math/Capsule.js.
# Сложить всё в одну папку нельзя, эти импорты сломаются.
#
# Список ровно такой, потому что он замкнут: больше ничего эти файлы не тянут.
# RGBELoader брать не нужно - в 0.185 это обёртка над HDRLoader, которая при
# вызове печатает предупреждение об устаревании.
if [ "$WHAT" = all ] || [ "$WHAT" = three ]; then
THREE_VER=0.185.1
THREE_DIR="$VENDOR/three"

echo "== three.js $THREE_VER =="
mkdir -p "$THREE_DIR/addons/controls" "$THREE_DIR/addons/loaders" \
         "$THREE_DIR/addons/math" "$THREE_DIR/addons/utils"

fetch_three() {   # $1 - путь в пакете, $2 - куда положить, $3 - минимальный размер
  curl -fL --progress-bar "https://unpkg.com/three@$THREE_VER/$1" -o "$2"
  local size
  size=$(stat -c%s "$2")
  if [ "$size" -lt "$3" ]; then
    echo "ПОДОЗРИТЕЛЬНО МАЛО ($size байт): $1"
    head -c 300 "$2"
    exit 1
  fi
  printf '  %-46s %8s байт\n' "$(basename "$1")" "$size"
}

# Ядро отдельным файлом — не прихоть списка: минифицированная сборка three
# разложена на два файла, и three.module.min.js первой же строкой импортирует
# ./three.core.min.js рядом с собой. Без него 404 обрывает весь граф модулей,
# и молча — на странице просто нет window.walk.
fetch_three build/three.core.min.js                      "$THREE_DIR/three.core.min.js"                   300000
fetch_three build/three.module.min.js                    "$THREE_DIR/three.module.min.js"                  30000
fetch_three examples/jsm/controls/PointerLockControls.js "$THREE_DIR/addons/controls/PointerLockControls.js" 3000
fetch_three examples/jsm/loaders/GLTFLoader.js           "$THREE_DIR/addons/loaders/GLTFLoader.js"          80000
fetch_three examples/jsm/loaders/HDRLoader.js            "$THREE_DIR/addons/loaders/HDRLoader.js"            8000
fetch_three examples/jsm/math/Octree.js                  "$THREE_DIR/addons/math/Octree.js"                 10000
fetch_three examples/jsm/math/Capsule.js                 "$THREE_DIR/addons/math/Capsule.js"                 2000
fetch_three examples/jsm/utils/BufferGeometryUtils.js    "$THREE_DIR/addons/utils/BufferGeometryUtils.js"   25000
fetch_three examples/jsm/utils/SkeletonUtils.js          "$THREE_DIR/addons/utils/SkeletonUtils.js"          8000
echo "OK"
fi
