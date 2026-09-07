"""Фон помещения — синтезом.

    python scripts/make_sounds.py

Кладёт room_tone.wav в game/assets/audio/. Скриптом, а не файлом в
репозитории, по той же причине, что и иконка: звук здесь настраивается
числами, и «сделать гул глуше» должно быть правкой одной строки.

ШАГИ ЗДЕСЬ БОЛЬШЕ НЕ ГЕНЕРИРУЮТСЯ, и это результат проверки, а не решение
на вкус. Синтезированные шаги были признаны негодными на слух: у настоящей
записи есть призвуки, скрип подошвы и неровность, которых формулой не
получить, и никакая правка резонансов этого не заменила. Сейчас шаги — записи
в assets/audio/steps/ (лицензии в assets/audio/CREDITS.md).

Код синтеза шага оставлен ниже намеренно: он ещё пригодится для звуков, где
синтез уместен, — гудения ламп, электрического треска, ударов. Фон комнаты
как раз такой случай: ровный низкий шум записывать хлопотнее, чем построить.
"""
from __future__ import annotations

import struct
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "game" / "assets" / "audio"
SR = 44100


def write_wav(path: Path, data: np.ndarray) -> float:
    """Сохранить моно 16 бит. Возвращает длительность в секундах."""
    peak = np.max(np.abs(data)) or 1.0
    # Нормируем до -3 дБ, а не до единицы: у самого края целочисленное
    # округление даёт щелчки на пиках.
    pcm = np.int16(np.clip(data / peak * 0.7, -1, 1) * 32767)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return len(data) / SR


def resonate(noise: np.ndarray, freq: float, q: float) -> np.ndarray:
    """Полосовой резонанс. Обычный двухполюсный фильтр, посчитанный вручную.

    Через БПФ было бы короче, но резонанс должен звенеть ПОСЛЕ импульса -
    это и есть призвук материала, а маска в частотной области хвоста не даёт.
    """
    w = 2 * np.pi * freq / SR
    r = np.exp(-w / (2 * q))
    a1, a2 = -2 * r * np.cos(w), r * r
    out = np.zeros_like(noise)
    for i in range(2, len(noise)):
        out[i] = noise[i] - a1 * out[i - 1] - a2 * out[i - 2]
    return out


def footstep(seed: int, *, bright: float, decay: float,
             body: float, length: float = 0.22) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(SR * length)
    t = np.arange(n) / SR

    # Удар: шум, гаснущий за миллисекунды. Это «контакт», без него шаг звучит
    # как гудок, а не как касание.
    click = rng.normal(0, 1, n) * np.exp(-t * 380)

    # Отклик материала: два резонанса. Верхний даёт породу (дерево звонкое),
    # нижний - объём под ногой.
    ring = (resonate(click, bright, 9) * 0.9
            + resonate(click, body, 5) * 0.6)

    # Общая огибающая: атака в один миллисекунд, дальше выдержанное затухание.
    env = np.exp(-t * decay)
    env[:int(SR * 0.001)] *= np.linspace(0, 1, int(SR * 0.001))
    return (click * 0.35 + ring) * env


def room_tone(seed: int, length: float = 8.0) -> np.ndarray:
    """Фон помещения: то, что слышно, когда «тихо».

    Полной тишины в комнате не бывает, и её отсутствие мозг замечает сразу -
    сцена начинает казаться неlive, а записью. Здесь это низкий шум с очень
    медленным дыханием и еле слышным гулом ламп на 100 Гц (вторая гармоника
    сети - именно её слышно от дросселей).
    """
    rng = np.random.default_rng(seed)
    n = int(SR * length)
    t = np.arange(n) / SR

    noise = rng.normal(0, 1, n)
    # Три наложенных низких резонанса вместо честного фильтра нижних частот:
    # так у фона появляется собственный тембр помещения.
    base = (resonate(noise, 90, 1.2) * 1.0
            + resonate(noise, 210, 0.9) * 0.5
            + resonate(noise, 430, 0.7) * 0.25)
    hum = np.sin(2 * np.pi * 100 * t) * 0.012
    breath = 1 + 0.25 * np.sin(2 * np.pi * 0.07 * t)
    out = base * breath + hum

    # Стык петли: перекрёстное затухание последней секунды на первую. Без него
    # в момент повтора слышен щелчок, и весь фон разваливается.
    fade = int(SR * 1.0)
    ramp = np.linspace(0, 1, fade)
    out[:fade] = out[:fade] * ramp + out[-fade:] * (1 - ramp)
    return out[:-fade]


def main() -> None:
    dur = write_wav(OUT / "room_tone.wav", room_tone(7))
    print(f"room_tone.wav: {dur:.2f} с -> {OUT.relative_to(ROOT)}")
    print("шаги не трогаются: они записанные, лежат в "
          f"{(OUT / 'steps').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
