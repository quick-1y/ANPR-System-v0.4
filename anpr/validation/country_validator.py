"""Валидатор конкретной страны."""

from __future__ import annotations

import re
from typing import Iterable, List

from .base import CountryConfig, ValidationResult


class CountryValidator:
    """Применяет правила одной страны: нормализация и проверка форматов."""

    def __init__(self, config: CountryConfig) -> None:
        self.config = config
        self.patterns: List[tuple[str, re.Pattern[str]]] = [
            (fmt.name, re.compile(fmt.pattern)) for fmt in self.config.license_plate_formats
        ]
        self.allowed_chars = set(self.config.valid_letters + self.config.valid_digits)
        self._generic_map = self._build_translation_map(
            self.config.corrections_common
            + self.config.corrections_latin_to_cyrillic
            + self.config.corrections_cyrillic_to_latin
        )

    @staticmethod
    def _build_translation_map(pairs: Iterable[tuple[str, str]]) -> dict[int, str]:
        mapping: dict[int, str] = {}
        for src, dst in pairs:
            if not src:
                continue
            mapping[ord(src.upper())] = dst.upper()
            mapping[ord(src.lower())] = dst.upper()
        return mapping

    def normalize(self, plate: str, aggressive: bool = True) -> str:
        text = plate.strip().upper()
        text = re.sub(r"[\s\-\.]+", "", text)
        text = text.translate(self._generic_map)
        if aggressive:
            filtered = [ch for ch in text if ch in self.allowed_chars]
            text = "".join(filtered)
        return text

    def _has_forbidden_chars(self, plate: str) -> bool:
        return any(ch not in self.allowed_chars for ch in plate)

    def _is_stop_word(self, plate: str) -> bool:
        normalized = plate.upper()
        return any(normalized == word.upper() for word in self.config.stop_words)

    @staticmethod
    def _is_uniform_sequence(text: str) -> bool:
        return len(text) >= 3 and len(set(text)) == 1

    @staticmethod
    def _is_simple_counter(text: str) -> bool:
        if len(text) < 3 or not text.isdigit():
            return False
        deltas = {int(b) - int(a) for a, b in zip(text, text[1:])}
        return len(deltas) == 1 and abs(next(iter(deltas))) == 1

    def validate(self, plate: str) -> ValidationResult:
        normalized = self.normalize(plate)

        if not normalized:
            return ValidationResult(plate=plate, raw_plate=plate, accepted=False, reason="Пустое значение")

        if self._has_forbidden_chars(normalized):
            return ValidationResult(
                plate=normalized,
                raw_plate=plate,
                accepted=False,
                reason="Недопустимые символы",
            )

        if self.config.min_length and len(normalized) < self.config.min_length:
            return ValidationResult(
                plate=normalized,
                raw_plate=plate,
                accepted=False,
                reason="Слишком короткий номер",
            )

        if self.config.max_length and len(normalized) > self.config.max_length:
            return ValidationResult(
                plate=normalized,
                raw_plate=plate,
                accepted=False,
                reason="Слишком длинный номер",
            )

        if self._is_stop_word(normalized):
            return ValidationResult(
                plate=normalized,
                raw_plate=plate,
                accepted=False,
                reason="Служебное значение",
            )

        if self._is_uniform_sequence(normalized):
            return ValidationResult(
                plate=normalized,
                raw_plate=plate,
                accepted=False,
                reason="Повторяющиеся символы",
            )

        if not self.config.allow_sequences and self._is_simple_counter(normalized):
            return ValidationResult(
                plate=normalized,
                raw_plate=plate,
                accepted=False,
                reason="Последовательность цифр",
            )

        for name, pattern in self.patterns:
            if pattern.match(normalized):
                return ValidationResult(
                    plate=normalized,
                    raw_plate=plate,
                    accepted=True,
                    country_code=self.config.code,
                    country_name=self.config.name,
                    format_name=name,
                )

        return ValidationResult(
            plate=normalized,
            raw_plate=plate,
            accepted=False,
            reason="Не совпало ни с одним форматом",
        )

    @property
    def priority(self) -> int:
        return self.config.priority

    @property
    def translation_map(self) -> dict[int, str]:
        return self._generic_map
