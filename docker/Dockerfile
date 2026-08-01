# Образ для TRELLIS.2 под RTX 3060.
#
# Почему Docker, а не установка в WSL: пяти расширениям нужен nvcc, то есть
# CUDA Toolkit целиком. Тащить его на хост ради этого не хочется, а рабочий
# venv с Blender и pymeshlab лучше не смешивать с torch. Runtime nvidia в
# docker на этой машине уже настроен.
#
# Отличия от официального setup.sh - каждое осознанное:
#   * conda не используется, окружение и так изолировано контейнером
#   * flash-attn ставится ГОТОВЫМ колесом; сборка из исходников на 10 ГБ ОЗУ
#     идёт часами и обычно падает по памяти
#   * gradio и tensorboard выброшены: свой веб-интерфейс уже есть, а gradio
#     тянет пол-интернета зависимостей
#   * pillow-simd выброшен: часто не собирается, выигрыш от него копеечный
#
# База ubuntu22.04 выбрана не случайно: в ней python3.10, а готовые колёса
# flash-attn собраны как раз под cp310.
FROM nvidia/cuda:12.4.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # RTX 3060 - Ampere, sm_86. Задать ОБЯЗАТЕЛЬНО: при сборке образа
    # видеокарты нет, и автоопределение архитектуры падает.
    TORCH_CUDA_ARCH_LIST=8.6 \
    # 10 ГБ ОЗУ. nvcc прожорлив, при MAX_JOBS по числу ядер сборку убивает OOM.
    MAX_JOBS=4 \
    # веса лежат снаружи, монтируются томом
    HF_HOME=/weights/hf \
    PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 python3-pip python3.10-dev \
        git build-essential cmake ninja-build \
        libgl1 libglib2.0-0 libegl1 libgles2 \
        libgl1-mesa-dev libegl1-mesa-dev libglvnd-dev \
        libjpeg-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.10 /usr/bin/python

RUN python -m pip install --upgrade pip setuptools wheel

# Версии строго как у авторов: расширения собираются против конкретного ABI
# torch, и рассогласование проявится не при сборке, а падением в рантайме.
RUN pip install torch==2.6.0 torchvision==0.21.0 \
        --index-url https://download.pytorch.org/whl/cu124

RUN pip install \
        imageio imageio-ffmpeg tqdm easydict opencv-python-headless ninja \
        trimesh transformers zstandard pandas lpips kornia timm \
        safetensors huggingface_hub hf_transfer accelerate scipy \
    && pip install git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8

# ABI не угадываем, а спрашиваем у самого torch: колёса flash-attn собраны в
# двух вариантах, и неверный даёт неразрешённые символы при импорте.
RUN set -eux; \
    ABI=$(python -c "import torch;print('TRUE' if torch._C._GLIBCXX_USE_CXX11_ABI else 'FALSE')"); \
    W="flash_attn-2.7.3+cu12torch2.6cxx11abi${ABI}-cp310-cp310-linux_x86_64.whl"; \
    echo "ABI=${ABI}, колесо ${W}"; \
    pip install "https://github.com/Dao-AILab/flash-attention/releases/download/v2.7.3/${W}"; \
    python -c "import flash_attn; print('flash-attn', flash_attn.__version__)"

# Расширения собираются из исходников - это самая долгая часть.
# --no-build-isolation обязателен: сборка импортирует уже установленный torch,
# а в изолированном окружении его нет.
RUN git clone -b v0.4.0 --depth 1 https://github.com/NVlabs/nvdiffrast.git /ext/nvdiffrast \
    && pip install /ext/nvdiffrast --no-build-isolation

RUN git clone -b renderutils --depth 1 https://github.com/JeffreyXiang/nvdiffrec.git /ext/nvdiffrec \
    && pip install /ext/nvdiffrec --no-build-isolation

RUN git clone --recursive --depth 1 https://github.com/JeffreyXiang/CuMesh.git /ext/CuMesh \
    && pip install /ext/CuMesh --no-build-isolation

RUN git clone --recursive --depth 1 https://github.com/JeffreyXiang/FlexGEMM.git /ext/FlexGEMM \
    && pip install /ext/FlexGEMM --no-build-isolation

# o-voxel лежит внутри самого репозитория TRELLIS.2, отдельного адреса нет
RUN git clone --recursive --depth 1 https://github.com/microsoft/TRELLIS.2.git /opt/trellis2 \
    && pip install /opt/trellis2/o-voxel --no-build-isolation

# Проверяем сборку сразу, а не при первом запуске: импорт расширения - это
# загрузка .so, и несовпадение ABI видно ровно здесь.
# Имена модулей скрипт берёт из метаданных пакетов, а не из списка: первая
# версия этой строки угадывала их вручную и упала на flex_gemm/flexgemm.
COPY verify_ext.py /tmp/verify_ext.py
RUN python /tmp/verify_ext.py

ENV PYTHONPATH=/opt/trellis2
WORKDIR /opt/trellis2
CMD ["python", "-c", "import trellis2; print('trellis2 готов')"]
