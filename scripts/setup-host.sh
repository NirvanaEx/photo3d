#!/usr/bin/env bash
# Готовит хост WSL под MCP-сервер photo3d: Python-venv и портативный Blender.
# Тяжёлые модели сюда НЕ ставятся - они поедут в GPU-контейнер отдельно.
#
# Запускать из-под root. С Windows-стороны:
#   wsl -u root -e bash -lc "tr -d '\r' < /mnt/d/Develop/photo3d/scripts/setup-host.sh | bash"
#
# Идемпотентен: повторный запуск ничего не ломает.
set -euo pipefail

BLENDER_VER=4.5.9
BLENDER_DIR=/opt/blender
VENV=/opt/photo3d/venv

echo "== 1/4 системные пакеты =="
# python3-venv - для venv и pip
# libx*/libgl1 - Blender линкуется с ними даже в headless-режиме (-b)
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  python3-venv python3-dev \
  libx11-6 libxi6 libxxf86vm1 libxfixes3 libxrender1 libxkbcommon0 \
  libgl1 libsm6 libegl1 xz-utils

echo "== 2/4 venv в $VENV =="
if [ ! -x "$VENV/bin/python" ]; then
  mkdir -p /opt/photo3d
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
# mcp - SDK для MCP-сервера, остальное - работа с картинками и мешами.
# scipy обязателен: без него у trimesh отваливаются графовые операции
# (fix_normals, split, body_count) - падает на ModuleNotFoundError.
"$VENV/bin/pip" install --quiet mcp pillow numpy trimesh scipy

echo "== 3/4 Blender $BLENDER_VER =="
if [ ! -x "$BLENDER_DIR/blender" ]; then
  TMP=$(mktemp -d)
  curl -fL --progress-bar \
    "https://download.blender.org/release/Blender${BLENDER_VER%.*}/blender-${BLENDER_VER}-linux-x64.tar.xz" \
    -o "$TMP/blender.tar.xz"
  mkdir -p "$BLENDER_DIR"
  tar -xJf "$TMP/blender.tar.xz" -C "$BLENDER_DIR" --strip-components=1
  rm -rf "$TMP"
fi

echo "== 4/4 проверка =="
echo -n "python: "; "$VENV/bin/python" --version
echo -n "mcp:    "; "$VENV/bin/python" -c "import mcp; print(mcp.__version__ if hasattr(mcp,'__version__') else 'ok')"
echo -n "trimesh:"; "$VENV/bin/python" -c "import trimesh; print(trimesh.__version__)"
echo -n "blender:"; "$BLENDER_DIR/blender" --version 2>/dev/null | head -1
# venv и blender остаются root-owned и читаемыми всем - серверу запись в них не нужна
chmod -R a+rX /opt/photo3d "$BLENDER_DIR"
echo "OK"
