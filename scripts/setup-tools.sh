#!/usr/bin/env bash
# Инструменты, дающие реальный прирост качества. Отобраны по одному критерию:
# помогают ли они получить меш, пригодный для скульптинга.
#
#   pymeshlab - ремонт и упрощение: дыры, non-manifold, вырожденные грани,
#               квадричная децимация, реконструкция Пуассона
#   rembg     - удаление фона. Качество силуэта на входе влияет на результат
#               сильнее, чем сам генератор: мусор на границе объекта
#               превращается в наросты на модели
#   xatlas    - UV-развёртка под запекание текстур
#
# Ретопология в квады НЕ ставится отдельно: QuadriFlow и Voxel Remesh уже
# встроены в Blender, ставить Instant Meshes поверх незачем.
#
#   wsl -u root -e bash -lc "tr -d '\r' < /mnt/d/Develop/photo3d/scripts/setup-tools.sh | bash"
set -euo pipefail

VENV=/opt/photo3d/venv
MODELS=/opt/photo3d/models

echo "== 1/4 системные зависимости =="
# libopengl0 критичен, хотя рендерить мы не собираемся: без него у pymeshlab
# не грузятся Qt-плагины, и молча пропадают закрытие дыр, изотропный
# ремешинг, реконструкция Пуассона и запись в PLY/STL. Пакет виден только
# по warning'ам в stderr, сам импорт при этом проходит успешно.
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  libgomp1 libglib2.0-0 libopengl0 libxkbcommon-x11-0 libdbus-1-3

echo "== 2/4 python-пакеты =="
# Экстра [cpu] обязателен: голый rembg больше не тянет onnxruntime и падает
# на первом же вызове с "No onnxruntime backend found".
# GPU-сборка потребовала бы cuDNN - несоразмерно ради 2-3 секунд на кадр
# при генерации в 60-90 секунд.
"$VENV/bin/pip" install --quiet pymeshlab "rembg[cpu]" xatlas

echo "== 3/4 веса для удаления фона =="
# Общая папка, а не ~/.u2net: скрипт идёт под root, а сервер работает
# от обычного пользователя - иначе веса скачались бы дважды.
mkdir -p "$MODELS"
export U2NET_HOME="$MODELS"
"$VENV/bin/python" - <<'PY'
import os
from rembg import new_session
print("качаю модель в", os.environ["U2NET_HOME"])
new_session("isnet-general-use")
print("готово")
PY

echo "== 4/4 проверка =="
"$VENV/bin/python" - <<'PY'
import pymeshlab, xatlas, rembg
print("pymeshlab:", pymeshlab.__version__ if hasattr(pymeshlab, "__version__") else "ok")
print("xatlas   :", "ok")
print("rembg    :", "ok")
ms = pymeshlab.MeshSet()
names = [f for f in dir(ms) if "remesh" in f or "close_holes" in f or "repair" in f]
print("фильтры ремонта:", ", ".join(sorted(names)[:12]))
PY

chmod -R a+rX /opt/photo3d
echo OK
