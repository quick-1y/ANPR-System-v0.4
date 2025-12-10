"""Постобработка распознанных номеров и выбор страны."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

from .base import ValidationResult
from .country_validator import CountryValidator
from .loader import load_country_configs


class PlateValidator:
    """Агрегирует валидаторы стран и применяет общие правила."""

    def __init__(
        self,
        validators: Sequence[CountryValidator],
        stop_words: Iterable[str] | None = None,
    ) -> None:
        self.validators = sorted(validators, key=lambda v: v.priority)
        self.stop_words = {w.upper() for w in (stop_words or [])}
        self.generic_map = self._build_generic_translation()

    def _build_generic_translation(self) -> dict[int, str]:
        mapping: dict[int, str] = {}
        for validator in self.validators:
            mapping.update(validator.translation_map)
        return mapping

    def normalize_for_vote(self, plate: str) -> str:
        cleaned = plate.strip().upper().replace(" ", "").replace("-", "").replace(".", "")
        return cleaned.translate(self.generic_map)

    def validate(self, plate: str) -> ValidationResult:
        if not self.validators:
            return ValidationResult(plate=plate, raw_plate=plate, accepted=True)

        if plate.upper() in self.stop_words:
            return ValidationResult(
                plate=plate,
                raw_plate=plate,
                accepted=False,
                reason="Служебное значение",
            )

        for validator in self.validators:
            result = validator.validate(plate)
            if result.accepted:
                return result

        return ValidationResult(
            plate=plate,
            raw_plate=plate,
            accepted=False,
            reason="Не прошёл валидацию ни в одной стране",
        )

    @classmethod
    def from_config_dir(
        cls,
        config_dir: Path,
        countries: Sequence[str] | None = None,
        stop_words: Iterable[str] | None = None,
    ) -> "PlateValidator":
        configs = load_country_configs(config_dir, allowed_countries=countries)
        validators = [CountryValidator(cfg) for cfg in configs]
        return cls(validators, stop_words=stop_words)


class PlatePostProcessor:
    """Оборачивает PlateValidator и умеет отключаться по конфигурации."""

    def __init__(
        self,
        enabled: bool,
        config_dir: Path,
        countries: Sequence[str] | None = None,
        stop_words: Iterable[str] | None = None,
    ) -> None:
        self.enabled = enabled
        self.validator = PlateValidator.from_config_dir(config_dir, countries, stop_words)

    def normalize_for_vote(self, plate: str) -> str:
        if not self.enabled:
            return plate.strip().upper()
        return self.validator.normalize_for_vote(plate)

    def validate(self, plate: str) -> ValidationResult:
        if not self.enabled:
            return ValidationResult(plate=plate, raw_plate=plate, accepted=bool(plate))
        return self.validator.validate(plate)
