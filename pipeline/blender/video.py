"""Склейка готовых кадров оборота в видео силами самого Blender.

Отдельного ffmpeg в системе нет (`which ffmpeg` пуст), и ставить его ради
одной склейки незачем: libavcodec собран внутрь Blender, а видеоредактор
кладёт последовательность PNG в mp4 без единой новой зависимости. Сверено с
установленным 4.5.9 LTS: контейнер MPEG4 и кодек H264 в перечислениях есть,
`sequence_editor.strips` тоже (в 4.4 коллекцию переименовали из `sequences`,
поэтому берётся та, что нашлась, - иначе скрипт умрёт на смене версии).

Кадры уже нарисованы турнтейблом, поэтому склейка стоит секунды и не трогает
ни GPU, ни сцену: полный оборот заново рендерить незачем.

    blender -b --factory-startup -noaudio -P video.py -- \
        --frames data/output/m_x/views --out data/output/m_x/spin.mp4 --fps 12
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--frames", required=True, help="папка с кадрами оборота")
    p.add_argument("--out", required=True, help="файл .mp4")
    p.add_argument("--fps", type=int, default=12)
    # Постоянный битрейт качества: PERC_LOSSLESS..LOWEST. HIGH на 512x512
    # даёт файл в пару сотен килобайт при неотличимой глазом картинке.
    p.add_argument("--crf", default="HIGH")
    return p.parse_args(argv)


def main() -> int:
    args = parse_args()
    frames = sorted(Path(args.frames).glob("*.png"))
    if not frames:
        print(f"ВИДЕО-ОШИБКА: в {args.frames} нет ни одного png")
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Размер берётся у первого кадра, а не у сцены: кадры могли рисоваться
    # с другим --res, и растянуть их до чужого разрешения значило бы мылить
    # картинку на ровном месте.
    img = bpy.data.images.load(str(frames[0]))
    w, h = img.size
    # H.264 кодирует блоками 2x2 и нечётную сторону не принимает. Модели
    # квадратные, а локации нет: коридор выходил 900x506, и однажды сторона
    # окажется нечётной. Один пиксель незаметен, отказ кодировщика - нет.
    even_w, even_h = w - w % 2, h - h % 2
    if (even_w, even_h) != (w, h):
        print(f"ВИДЕО: сторона нечётная, {w}x{h} -> {even_w}x{even_h}")

    scene = bpy.context.scene
    # Кадры уже готовые sRGB-картинки, их надо переложить в ролик как есть.
    # Штатный AgX превращает конвейер в «отрендерить заново»: он гасит
    # насыщенные цвета, и ярко-красное сердце выходило в ролике кирпичным.
    # Ровно та же причина, по которой постановочный стиль рендера переключён
    # с AgX на Standard, - только здесь потеря вдвойне бессмысленна, потому
    # что тональное отображение к этим пикселям уже применили при рендере.
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0

    r = scene.render
    r.resolution_x, r.resolution_y = even_w, even_h
    r.resolution_percentage = 100
    r.fps, r.fps_base = args.fps, 1.0
    scene.frame_start = 1
    scene.frame_end = len(frames)

    se = scene.sequence_editor_create()
    strips = getattr(se, "strips", None) or se.sequences
    strip = strips.new_image(
        name="spin", filepath=str(frames[0]), channel=1, frame_start=1,
    )
    for f in frames[1:]:
        strip.elements.append(f.name)
    strip.frame_final_duration = len(frames)

    r.image_settings.file_format = "FFMPEG"
    r.ffmpeg.format = "MPEG4"
    r.ffmpeg.codec = "H264"
    r.ffmpeg.constant_rate_factor = args.crf
    r.ffmpeg.ffmpeg_preset = "GOOD"
    r.ffmpeg.audio_codec = "NONE"
    # Ключевой кадр раз в секунду: ролик короткий, его отматывают на любой
    # ракурс, а с редкими ключевыми кадрами перемотка становится ступенчатой.
    r.ffmpeg.gopsize = max(1, args.fps)
    r.filepath = str(out)

    bpy.ops.render.render(animation=True)

    # Проверка по файлу, а не по коду возврата: правило проекта, и здесь у
    # него вторая причина. Имя выходного файла Blender оставляет как есть,
    # только если путь уже кончается расширением контейнера; иначе он
    # допишет диапазон кадров - spin0001-0024.mp4. Ловим оба случая.
    if not out.exists():
        near = sorted(
            out.parent.glob(f"{out.stem}*{out.suffix}"),
            key=lambda p: p.stat().st_mtime,
        )
        if near:
            near[-1].replace(out)

    if not out.exists() or out.stat().st_size == 0:
        print(f"ВИДЕО-ОШИБКА: {out} не появился или пуст")
        return 1

    print(f"ВИДЕО: {out} {out.stat().st_size} байт "
          f"{len(frames)} кадров {args.fps} fps {even_w}x{even_h}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
