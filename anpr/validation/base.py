"""Базовые модели данных для валидации номерных знаков."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class PlateFormat:
    """Регулярное выражение и описание формата номера."""

    name: str
    pattern: str
    description: str = ""


@dataclass
class ValidationResult:
    """Результат проверки номера."""

    plate: str
    accepted: bool
    country_code: Optional[str] = None
    country_name: Optional[str] = None
    format_name: Optional[str] = None
    reason: Optional[str] = None
    raw_plate: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "plate": self.plate,
            "country": self.country_code,
            "country_name": self.country_name,
            "format": self.format_name,
            "validation_reason": self.reason,
            "raw_plate": self.raw_plate,
            "accepted": self.accepted,
        }


@dataclass
class CountryConfig:
    """Конфигурация страны, загружаемая из YAML."""

    name: str
    code: str
    priority: int
    license_plate_formats: List[PlateFormat]
    valid_letters: str
    valid_digits: str
    stop_words: List[str]
    corrections_common: List[tuple[str, str]]
    corrections_latin_to_cyrillic: List[tuple[str, str]]
    corrections_cyrillic_to_latin: List[tuple[str, str]]
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    uses_cyrillic: bool = True
    allow_sequences: bool = False
