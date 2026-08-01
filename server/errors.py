"""Ошибки, пригодные для чтения агентом.

Обычный traceback заставляет Claude гадать, что делать дальше. Здесь каждая
ошибка несёт три вещи: на каком шаге упало, почему, и что конкретно можно
предпринять. Последнее - самое ценное: оно превращает сбой в следующее действие
вместо тупика.
"""
from __future__ import annotations


class PipelineError(Exception):
    def __init__(self, stage: str, reason: str, hint: str = "") -> None:
        self.stage = stage
        self.reason = reason
        self.hint = hint
        super().__init__(reason)

    def __str__(self) -> str:
        out = f"[{self.stage}] {self.reason}"
        if self.hint:
            out += f"\nЧто делать: {self.hint}"
        return out


class ModelNotFound(PipelineError):
    def __init__(self, model_id: str, known: list[str]) -> None:
        known_str = ", ".join(known[:8]) if known else "ни одной модели пока нет"
        super().__init__(
            stage="lookup",
            reason=f"модель {model_id!r} не найдена",
            hint=f"вызови list_models(). Доступны: {known_str}",
        )


class InputNotFound(PipelineError):
    def __init__(self, path: str, searched: list[str]) -> None:
        super().__init__(
            stage="input",
            reason=f"файл {path!r} не найден",
            hint=(
                "положи фото в data/input/ и передай только имя файла, "
                f"либо укажи абсолютный путь. Искал в: {', '.join(searched)}"
            ),
        )


class BlenderFailed(PipelineError):
    def __init__(self, reason: str, log_tail: str = "") -> None:
        hint = "загляни в log.txt в папке модели - там полный вывод Blender"
        if "cannot open shared object" in log_tail or "libGL" in log_tail:
            hint = (
                "не хватает системных библиотек Blender. Прогони "
                "scripts/setup-host.sh из-под root - он доставит libgl1 и libx*"
            )
        super().__init__(stage="render", reason=reason, hint=hint)
