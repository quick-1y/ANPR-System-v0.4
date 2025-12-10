"""Валидация и постобработка номерных знаков."""

from pathlib import Path

from .postprocessor import PlatePostProcessor, PlateValidator

__all__ = ["PlatePostProcessor", "PlateValidator", "validation_config_dir"]


def validation_config_dir() -> Path:
    """Возвращает путь до каталога с YAML-конфигурациями стран."""

    return Path(__file__).resolve().parent / "configs"
