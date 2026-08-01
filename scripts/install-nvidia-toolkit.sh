#!/usr/bin/env bash
# Ставит nvidia-container-toolkit в WSL2 Ubuntu и прописывает nvidia-рантайм в Docker.
# Без него `docker run --gpus all` не отдаёт видеокарту в контейнер.
#
# Запускать из-под root. С Windows-стороны:
#   wsl -u root -e bash -lc "tr -d '\r' < /mnt/d/Develop/photo3d/scripts/install-nvidia-toolkit.sh | bash"
#
# Пароль пользователя Ubuntu не требуется: WSL даёт root по флагу -u,
# граница доверия здесь - учётка Windows.
set -euo pipefail

KEYRING=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
LIST=/etc/apt/sources.list.d/nvidia-container-toolkit.list

echo "== 1/5 ключ репозитория NVIDIA =="
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | gpg --dearmor --yes -o "$KEYRING"

echo "== 2/5 apt-репозиторий =="
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed "s#deb https://#deb [signed-by=$KEYRING] https://#g" > "$LIST"

echo "== 3/5 apt-get update =="
apt-get update -qq

echo "== 4/5 установка пакета =="
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nvidia-container-toolkit

echo "== 5/5 регистрация рантайма в Docker =="
nvidia-ctk runtime configure --runtime=docker
service docker restart

echo
echo "== проверка =="
docker info 2>/dev/null | grep -i -E 'runtimes|nvidia' || echo "рантайм в docker info не виден"
