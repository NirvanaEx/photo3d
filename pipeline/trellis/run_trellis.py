"""Генерация 3D из фото. Исполняется ВНУТРИ контейнера photo3d/trellis.

    python run_trellis.py --in /work/input.png --out /work/model.glb

Скрипт монтируется в контейнер с хоста, а не копируется в образ: править его
можно без пересборки, а пересборка тут - десятки минут.

Четыре отступления от официального example.py, каждое вынужденное:

1. BiRefNet подменяется заглушкой. В конфиге он нужен (from_pretrained падает
   без ключа rembg_model), но его конструктор качает 5.4 ГБ и выполняет
   trust_remote_code=True. Вызывается он только когда у входной картинки нет
   альфа-канала - а мы всегда подаём RGBA, фон снят нашим rembg на хосте.
   Если заглушка всё-таки сработает, значит альфы не было: падаем внятно.

2. pipeline_type="512" задаётся явно. По умолчанию в конфиге стоит каскад
   1024, а его весов у нас нет и на 12 ГБ они не нужны.

3. Рендер превью выброшен. В example.py он через nvdiffrast и HDRI, а у нас
   для этого есть Blender - и лишняя нагрузка на видеопамять ни к чему.

4. Веса грузятся с диска прямо в видеопамять, минуя оперативную
   (patch_lazy_weights ниже). На машине с 10 ГБ в WSL это не оптимизация,
   а условие работоспособности: см. обоснование у самой функции.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import numpy as np  # noqa: E402
import torch  # noqa: E402
from PIL import Image  # noqa: E402


class _NoRembg:
    """Заглушка вместо BiRefNet: ничего не грузит и ничего не умеет.

    Интерфейс повторяет настоящий (to/cuda/cpu вызываются в low_vram-режиме
    безусловно), но вызов на картинке - ошибка, а не тихая работа: если сюда
    дошло, значит альфа-канала не было и фон снять нечем.
    """

    def __init__(self, *a, **kw) -> None:
        pass

    def to(self, device):  # noqa: ANN001
        return self

    def cuda(self):
        return self

    def cpu(self):
        return self

    def __call__(self, image):  # noqa: ANN001
        raise RuntimeError(
            "у входной картинки нет альфа-канала, а модель удаления фона "
            "намеренно не установлена. Фон должен сниматься на хосте (rembg) "
            "до вызова контейнера"
        )


def patch_dino_layers() -> str:
    """Починить перебор слоёв DINOv3 под нынешний transformers.

    TRELLIS.2 писался в ноябре 2025 и обходит слои как `self.model.layer`.
    В transformers 5.x они переехали внутрь энкодера: `model.model.layer`,
    и оригинальный код падает с
    `'DINOv3ViTModel' object has no attribute 'layer'`.

    Откатывать библиотеку не стали: расхождение ровно одно. Сигнатуры
    embeddings(pixel_values, bool_masked_pos) и
    layer(hidden_states, position_embeddings=...) в новой версии те же,
    проверено по inspect.signature. Поэтому подменяется только поиск списка
    слоёв, а сама логика извлечения признаков остаётся авторской.
    """
    import torch.nn.functional as F
    from trellis2.modules import image_feature_extractor as ife

    def layers_of(model):
        found = getattr(model, "layer", None)          # старый вариант
        if found is None:
            inner = getattr(model, "model", None)      # transformers >= 5
            found = getattr(inner, "layer", None) if inner is not None else None
        if found is None:
            raise RuntimeError(
                "не найден список слоёв DINOv3: ни model.layer, ни "
                "model.model.layer. Скорее всего, transformers снова "
                "переставил внутренности - смотри modeling_dinov3_vit.py"
            )
        return found

    def extract_features(self, image):  # noqa: ANN001
        model = self.model
        image = image.to(model.embeddings.patch_embeddings.weight.dtype)
        hidden = model.embeddings(image, bool_masked_pos=None)
        pos = model.rope_embeddings(image)
        for layer in layers_of(model):
            hidden = layer(hidden, position_embeddings=pos)
        return F.layer_norm(hidden, hidden.shape[-1:])

    ife.DinoV3FeatureExtractor.extract_features = extract_features
    import transformers

    return transformers.__version__


# Сколько времени и данных ушло на подачу весов в видеопамять. Копится тут,
# потому что раздача идёт из недр конвейера, а видеть её надо в отчёте: это
# теперь главная переменная часть времени генерации.
WEIGHT_IO = {"секунд": 0.0, "гигабайт": 0.0, "подач": 0}


def patch_lazy_weights() -> None:
    """Грузить веса моделей с диска СРАЗУ в видеопамять, минуя оперативную.

    Зачем. Штатный загрузчик (trellis2/models/__init__.py) делает так:

        model = Класс(**config['args'])                  # выделил 2.44 ГБ в ОЗУ
        model.load_state_dict(load_file(файл), ...)      # прочитал ещё столько же

    То есть модуль сначала создаётся со случайными весами, рядом читается файл,
    и только потом одно копируется в другое. На шести моделях это 9.22 ГБ
    постоянно занятой оперативной памяти и двойной пик на каждую модель.

    В WSL доступно 9.95 ГБ. Замер показал, что при загрузке в подкачку уходит
    3.8 ГБ, и дальше режим low_vram гоняет эти же страницы туда-сюда: перед
    каждым этапом .to('cuda'), после - .cpu(). Итог замера конца в конец:
    загрузка 317 с, «генерация» 576 с, из которых на счёт сэмплеров пришлось
    92 с (видно по их собственному прогрессу: 21 + 47 + 24). Остальные 484 с -
    это перекладывание весов через подкачку, а не вычисления.

    Как чинится. Модуль собирается на устройстве meta - там параметры не
    занимают ни байта, только форму и тип (проверено на всех шести моделях,
    сборка 2.8 с суммарно). Веса появляются ровно на время своего этапа:

        .to('cuda') -> safetensors читает файл прямо в видеопамять,
                       load_state_dict(assign=True) забирает тензоры как есть,
                       без промежуточной копии;
        .cpu()      -> параметры снова становятся пустышками на meta,
                       видеопамять освобождается.

    Оперативная память под веса не нужна вовсе, пик видеопамяти не растёт
    (там и раньше жила одна модель за раз - замеренный пик 3.85 ГБ из 12).
    Ценой становится чтение 9.22 ГБ с диска за прогон, но диск здесь быстрый:
    564 МБ/с подряд и 353 МБ/с блоками по 4 КБ, то есть секунды, а не минуты.

    Про типы. assign=True отдаёт модулю тензоры из файла как есть, а штатный
    путь копировал их в уже созданные параметры, то есть сохранял тип
    КОНСТРУКТОРА. Разница не косметическая: модель смешанной точности, часть
    слоёв живёт в fp32, и чекпойнт хранит их всё равно в bf16. Прямая отдача
    тензоров ломает счёт сразу:

        RuntimeError: mat1 and mat2 must have the same dtype,
                      got Float and BFloat16

    Поэтому перед загрузкой каждый тензор приводится к типу, который задумал
    конструктор. Взять этот тип неоткуда, кроме самой модели, - и он там есть:
    сборка на meta хранит форму и тип, не храня данных. Для подавляющего
    большинства слоёв приведение холостое (bf16 в bf16) и копии не делает.

    Про то, чего нет в чекпойнте. Не всё содержимое модели приезжает из файла,
    и таких мест два, оба вскрылись прогоном, а не чтением кода:

    - rope_phases у sparse_structure_flow_model: обычный буфер, но в чекпойнт
      он не сохранён - ровно поэтому в оригинале стоит strict=False;
    - freqs в modules/sparse/attention/rope.py: тензор лежит ПРОСТЫМ
      АТРИБУТОМ, а не через register_buffer, поэтому его нет ни в state_dict,
      ни в named_buffers. Проверка «не осталось ли чего на meta» его не
      видела, и падало это уже внутри forward, за пять кадров стека от
      причины: NotImplementedError: Cannot copy out of meta tensor.

    И то и другое считается конструктором, поэтому модель один раз собирается
    по-настоящему, из неё забирается недостающее, и она тут же выбрасывается.
    Сборка идёт без случайной инициализации весов (см. without_random_init),
    и потому стоит 1.5 с вместо 56 с. Ничего не угадывается: недостающие ключи
    сверяются с файлом, а простые тензоры ищутся обходом модулей - чекпойнт
    другой версии подхватится сам.
    """
    import contextlib
    import gc
    import json as _json

    from safetensors import safe_open
    from safetensors.torch import load_file

    from trellis2 import models as models_mod

    @contextlib.contextmanager
    def without_random_init():
        """Отключить случайную инициализацию весов на время сборки.

        Конструктор вызывается здесь только ради буферов, которых нет в
        чекпойнте; все параметры выбрасываются через строчку. Заполнять ради
        этого 1.3 млрд чисел случайными значениями - чистая трата: замер дал
        56 с на модель, причём вдобавок к самому генератору чисел платится
        ещё и за прикосновение к 2.6 ГБ памяти, которую иначе никто бы не
        тронул (torch.empty страниц не занимает, пока в них не пишут).

        Детерминированные заполнения (нулями, единицами, константой) остаются
        как есть: ими могут задаваться как раз буферы, а стоят они копейки.
        """
        import torch.nn.init as init

        names = ("uniform_", "normal_", "kaiming_uniform_", "kaiming_normal_",
                 "xavier_uniform_", "xavier_normal_", "trunc_normal_")
        saved = {n: getattr(init, n) for n in names if hasattr(init, n)}
        for n in saved:
            setattr(init, n, lambda tensor, *a, **kw: tensor)
        try:
            yield
        finally:
            for n, fn in saved.items():
                setattr(init, n, fn)

    def loose_tensors(model) -> list[tuple[str, str]]:
        """Тензоры, которые модуль держит простым атрибутом.

        Мимо register_buffer, а значит мимо state_dict, named_buffers и любого
        переноса между устройствами. Возвращает пары (путь_модуля, имя).
        """
        found: list[tuple[str, str]] = []
        for path, mod in model.named_modules():
            reserved = set(mod._parameters) | set(mod._buffers)
            for name, value in list(vars(mod).items()):
                if (isinstance(value, torch.Tensor)
                        and name not in reserved
                        and not name.startswith("_p3d")):
                    found.append((path, name))
        return found

    def release(model) -> None:
        """Отпустить веса: параметры и буферы становятся пустышками на meta."""
        for mod in model.modules():
            for name, p in list(mod._parameters.items()):
                if p is not None and p.device.type != "meta":
                    mod._parameters[name] = torch.nn.Parameter(
                        torch.empty_like(p, device="meta"),
                        requires_grad=p.requires_grad)
            for name, b in list(mod._buffers.items()):
                if b is not None and b.device.type != "meta":
                    mod._buffers[name] = torch.empty_like(b, device="meta")
        # Кэш аллокатора НЕ чистится, и это замер, а не небрежность. Сначала
        # тут стоял torch.cuda.empty_cache() - из опасения, что модели разного
        # размера (0.14, 0.88 и 2.44 ГБ) со временем раздробят свободную
        # память. Опасение оказалось дороже болезни: после сброса кэша каждый
        # из 640 тензоров модели просит у драйвера свежий кусок, а cudaMalloc
        # синхронный и медленный. Подача весов из-за этого шла 96 с на 9.13 ГБ
        # (97 МБ/с), тогда как чтение того же файла упирается в диск на
        # 457 МБ/с. От дробления же спасает не сброс кэша, а
        # PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True, он выставлен выше.

    def supply(model, device) -> None:
        """Подать веса на устройство. Читает файл прямо туда."""
        t = time.time()
        state = load_file(model._p3d_file, device=str(device))
        # Тип берётся у конструктора, а не у файла: модель смешанной точности,
        # и отдача bf16 в слой, задуманный как fp32, роняет matmul. Подробности
        # в описании функции.
        want = model._p3d_dtype
        for key, value in state.items():
            if key in want and value.dtype != want[key]:
                state[key] = value.to(want[key])
        for key, value in model._p3d_extra.items():
            state[key] = value.to(device)
        model.load_state_dict(state, strict=False, assign=True)

        # Проверять надо по факту, а не по коду возврата: load_state_dict со
        # strict=False молча оставит на meta всё, чего не нашлось в файле, и
        # упадёт это уже в forward, за пять кадров стека от причины.
        #
        # Простые атрибуты проверяются наравне с параметрами: именно на них
        # заплатка и споткнулась в первый раз, а по параметрам всё было чисто.
        left = [n for n, t_ in list(model.named_parameters())
                + list(model.named_buffers()) if t_.device.type == "meta"]
        modules = dict(model.named_modules())
        left += [f"{path}.{name} (простой атрибут)"
                 for path, name in model._p3d_loose
                 if getattr(modules[path], name).device.type == "meta"]
        if left:
            raise RuntimeError(
                f"после загрузки {model._p3d_file} на устройстве meta осталось "
                f"{len(left)} тензоров, первые: {left[:3]}. Значит, чекпойнт не "
                f"содержит этих ключей, а конструктор их не создал. Проверь, "
                f"что версия весов соответствует версии trellis2")

        WEIGHT_IO["секунд"] += time.time() - t
        WEIGHT_IO["гигабайт"] += os.path.getsize(model._p3d_file) / 2**30
        WEIGHT_IO["подач"] += 1

    def bind(model) -> None:
        """Подменить перенос между устройствами на подачу и освобождение.

        Методы вешаются на экземпляр, а не на класс: те же классы могут
        использоваться и вне этого конвейера, а объём правки должен совпадать
        с объёмом проблемы.
        """
        def to(device, *args, **kwargs):
            dev = device if isinstance(device, torch.device) else torch.device(device)
            if dev.type == "cuda":
                supply(model, dev)
            else:
                release(model)
            return model

        model.to = to
        model.cpu = lambda: (release(model), model)[1]
        model.cuda = lambda dev=None: (
            supply(model, torch.device("cuda" if dev is None else f"cuda:{dev}")),
            model)[1]

    def from_pretrained(path: str, **kwargs):
        config_file, model_file = f"{path}.json", f"{path}.safetensors"
        if not (os.path.exists(config_file) and os.path.exists(model_file)):
            raise FileNotFoundError(
                f"нет весов {model_file} или конфига {config_file}. Веса качает "
                f"scripts/fetch_weights.sh, проверь, что каталог примонтирован "
                f"в контейнер как /weights")

        with open(config_file) as f:
            config = _json.load(f)
        cls = getattr(models_mod, config["name"])

        with torch.device("meta"):
            model = cls(**config["args"], **kwargs)

        # Снимок задуманных типов, пока модель пуста. Позже взять их будет
        # неоткуда: параметры уедут в видеопамять уже приведёнными.
        dtypes = {k: v.dtype for k, v in model.state_dict().items()}

        with safe_open(model_file, framework="pt") as f:
            in_file = set(f.keys())
        need = [k for k in dtypes if k not in in_file]
        loose = loose_tensors(model)

        extra = {}
        if need or loose:
            t = time.time()
            with without_random_init():
                real = cls(**config["args"], **kwargs)
            state = real.state_dict()
            extra = {k: state[k].clone() for k in need}

            # Простые атрибуты пересаживаются сразу и остаются на процессоре:
            # они крошечные, а библиотека сама переносит их на нужное
            # устройство при первом проходе (rope.py, строка 24).
            here = dict(model.named_modules())
            there = dict(real.named_modules())
            for path, name in loose:
                setattr(here[path], name, getattr(there[path], name).clone())

            del real, state, there
            gc.collect()
            print(f"{config['name']}: вне чекпойнта {len(need)} буферов "
                  f"({', '.join(need) or 'нет'}) и {len(loose)} простых "
                  f"тензоров, добраны из конструктора за "
                  f"{time.time() - t:.1f} c", file=sys.stderr, flush=True)

        model._p3d_file = model_file
        model._p3d_extra = extra
        model._p3d_dtype = dtypes
        model._p3d_loose = loose
        bind(model)
        return model

    models_mod.from_pretrained = from_pretrained


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="src", required=True)
    p.add_argument("--out", dest="dst", required=True)
    p.add_argument("--weights", default="/weights/TRELLIS.2-4B")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--pipeline-type", dest="ptype", default="512")
    # 4096 как в примере авторов - это под 24 ГБ. Начинаем скромнее.
    p.add_argument("--texture-size", dest="texture", type=int, default=2048)
    p.add_argument("--decimation-target", dest="decimation", type=int, default=300_000)
    p.add_argument("--max-tokens", dest="max_tokens", type=int, default=49152)
    # Штатный путь загрузки - через оперативную память. Оставлен как запасной
    # выход: если правка загрузчика однажды разойдётся с новой версией
    # trellis2, сравнить с ним - дело одного флага, а не отката.
    p.add_argument("--eager-weights", dest="eager", action="store_true",
                   help="грузить веса штатным способом, через ОЗУ (медленно)")
    return p.parse_args()


def vram() -> dict[str, float]:
    if not torch.cuda.is_available():
        return {}
    free, total = torch.cuda.mem_get_info()
    return {
        "пик_выделено_ГБ": round(torch.cuda.max_memory_allocated() / 2**30, 2),
        "пик_зарезервировано_ГБ": round(torch.cuda.max_memory_reserved() / 2**30, 2),
        "свободно_ГБ": round(free / 2**30, 2),
        "всего_ГБ": round(total / 2**30, 2),
    }


def main() -> int:
    a = parse_args()
    stages: dict[str, float] = {}
    t0 = time.time()

    img = Image.open(a.src)
    if img.mode != "RGBA":
        print(json.dumps({"ошибка": f"нужен RGBA, получено {img.mode}"},
                         ensure_ascii=False))
        return 1
    alpha = np.array(img)[:, :, 3]
    if np.all(alpha == 255):
        print(json.dumps({"ошибка": "альфа-канал полностью непрозрачный, "
                                    "фон не снят"}, ensure_ascii=False))
        return 1

    # Подмена ДО from_pretrained: конструктор настоящего BiRefNet вызывается
    # прямо там (trellis2_image_to_3d.py, строка 105).
    from trellis2.pipelines import rembg as rembg_mod

    rembg_mod.BiRefNet = _NoRembg

    from trellis2.pipelines import Trellis2ImageTo3DPipeline

    tver = patch_dino_layers()
    print(f"transformers {tver}, перебор слоёв DINOv3 подправлен",
          file=sys.stderr, flush=True)

    if not a.eager:
        patch_lazy_weights()
        print("веса грузятся прямо в видеопамять, минуя ОЗУ",
              file=sys.stderr, flush=True)

    stages["импорт_с"] = round(time.time() - t0, 1)

    t = time.time()
    pipeline = Trellis2ImageTo3DPipeline.from_pretrained(a.weights)
    pipeline.cuda()   # при low_vram только запоминает устройство
    # Без --eager-weights этот этап собирает пустые модули и весов не читает:
    # они приезжают позже, каждый к своему этапу, и учтены в "веса_в_видеопамять".
    stages["загрузка_с"] = round(time.time() - t, 1)
    print(f"low_vram={pipeline.low_vram}  режим={a.ptype}", file=sys.stderr, flush=True)

    torch.cuda.reset_peak_memory_stats()
    t = time.time()
    outputs = pipeline.run(
        img,
        seed=a.seed,
        pipeline_type=a.ptype,
        max_num_tokens=a.max_tokens,
    )
    stages["генерация_с"] = round(time.time() - t, 1)
    peak_gen = vram()

    mesh = outputs[0]
    mesh.simplify(16_777_216)   # предел nvdiffrast

    t = time.time()
    import o_voxel

    glb = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices,
        faces=mesh.faces,
        attr_volume=mesh.attrs,
        coords=mesh.coords,
        attr_layout=mesh.layout,
        voxel_size=mesh.voxel_size,
        aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
        decimation_target=a.decimation,
        texture_size=a.texture,
        remesh=True,
        remesh_band=1,
        remesh_project=0,
        verbose=False,
    )
    # extension_webp=False намеренно: наш Blender-конвейер (запекание,
    # рендер) читает GLB через стандартный импортёр, а webp-текстуры он
    # понимает не во всех сборках. Размер тут вторичен.
    glb.export(a.dst, extension_webp=False)
    stages["экспорт_с"] = round(time.time() - t, 1)

    # Ключи ниже - общий договор с остальной системой: их читают _summary в
    # server/main.py и веб-интерфейс. Они те же, что отдаёт StubEngine, и
    # менять их на русские нельзя: сводка молча покажет вопросительные знаки,
    # потому что .get() на отсутствующем ключе не ошибка. Так и случилось при
    # первом прогоне через MCP.
    report = {
        "engine": "trellis2",
        "mode": a.ptype,
        "seed": a.seed,
        "vertices": int(len(glb.vertices)) if hasattr(glb, "vertices") else None,
        "faces": int(len(glb.faces)) if hasattr(glb, "faces") else None,
        "watertight": bool(getattr(glb, "is_watertight", False)),
        # дальше - подробности сверх общего договора
        "texture_size": a.texture,
        "время": stages,
        "всего_с": round(time.time() - t0, 1),
        "видеопамять": peak_gen,
        # Подача весов - теперь главная переменная часть генерации, и её видно
        # отдельно: если время поползёт, сразу ясно, диск это или счёт.
        "веса_в_видеопамять": {
            "способ": "через ОЗУ" if a.eager else "прямо с диска",
            "секунд": round(WEIGHT_IO["секунд"], 1),
            "гигабайт": round(WEIGHT_IO["гигабайт"], 2),
            "подач": WEIGHT_IO["подач"],
        },
    }
    print("TRELLIS_RESULT " + json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
