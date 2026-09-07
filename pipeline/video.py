"""Ролик оборота из уже нарисованных кадров.

Турнтейбл кладёт в views/ полный оборот (24 кадра), и вращение по ним живёт
в веб-интерфейсе. Наружу - в переписку, в задачу, в чужой мессенджер - папку
с png не отдашь, а mp4 отдаётся и играется везде. Отсюда этот шаг: он ничего
не рендерит заново, а только склеивает готовое, поэтому стоит секунды против
сорока пяти за оборот.

Склейкой занят Blender (см. blender/video.py) - у него ffmpeg внутри, и
новых зависимостей затея не требует вовсе.

    python -m pipeline.video            # последняя модель
    python -m pipeline.video m_b3eb8f --fps 24
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from server import config
from server.errors import BlenderFailed, PipelineError

SCRIPT = config.BLENDER_SCRIPTS / "video.py"

# Плавность ролика упирается не в fps, а в число кадров: их 24 на оборот, и
# больше взять неоткуда, пока оборот не перерисован гуще. 12 fps - середина:
# при 6 видно отдельные кадры, при 24 оборот мелькает за секунду и
# рассмотреть модель не успеваешь.
DEFAULT_FPS = 12


def make_spin_video(
    frames_dir: Path,
    out_mp4: Path,
    fps: int = DEFAULT_FPS,
) -> tuple[Path, int, float]:
    """Склеивает кадры из frames_dir в out_mp4.

    Возвращает (файл, сколько кадров, длительность в секундах).
    """
    frames = sorted(Path(frames_dir).glob("*.png"))
    if not frames:
        raise PipelineError(
            stage="video",
            reason=f"в {frames_dir} нет кадров оборота",
            hint=("сначала нарисуй оборот - render_model(model_id, spin=True) "
                  "или render_turntable(); склеивать пока нечего"),
        )
    if not config.BLENDER.exists():
        raise BlenderFailed(
            f"Blender не найден по пути {config.BLENDER}", log_tail="",
        )

    out_mp4 = Path(out_mp4)
    if out_mp4.exists():
        out_mp4.unlink()

    cmd = [
        str(config.BLENDER), "-b", "--factory-startup", "-noaudio",
        "-P", str(SCRIPT), "--",
        "--frames", str(frames_dir),
        "--out", str(out_mp4),
        "--fps", str(fps),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=config.RENDER_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        raise BlenderFailed(
            f"склейка ролика не уложилась в {config.RENDER_TIMEOUT_SEC} с",
            log_tail="",
        ) from None

    log = (proc.stdout or "") + (proc.stderr or "")

    # Файл, а не код возврата: Blender завершается успехом и не записав видео.
    if not out_mp4.exists() or out_mp4.stat().st_size == 0:
        raise BlenderFailed(
            f"видео {out_mp4.name} не записалось", log_tail=log[-2000:],
        )

    return out_mp4, len(frames), len(frames) / fps


def main() -> int:
    import argparse

    from server.store import ModelStore

    p = argparse.ArgumentParser(description="ролик оборота из готовых кадров")
    p.add_argument("model_id", nargs="?", default="last")
    p.add_argument("--fps", type=int, default=DEFAULT_FPS)
    p.add_argument("--out", default="", help="по умолчанию spin.mp4 в папке модели")
    args = p.parse_args()

    store = ModelStore()
    try:
        model_id = store.resolve(args.model_id)
        model_dir = store.dir(model_id)
        out = Path(args.out) if args.out else model_dir / "spin.mp4"
        video, n, seconds = make_spin_video(model_dir / "views", out, args.fps)
    except PipelineError as e:
        # Печатаем сообщение, а не трейсбек: в нём этап, причина и следующее
        # действие, а стек вызовов тут ничего не добавляет.
        print(e)
        return 1

    size_kb = video.stat().st_size / 1024
    print(f"{model_id}: {video}")
    print(f"{n} кадров, {args.fps} fps, оборот за {seconds:.1f} с, {size_kb:.0f} КБ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
