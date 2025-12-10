# /anpr/validation/plate_validator.py
"""Правила постобработки и валидации распознанных номеров."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

import yaml


@dataclass
class PlateValidationResult:
    """Результат проверки номера."""

    text: str
    is_valid: bool
    country_code: Optional[str] = None
    country_name: Optional[str] = None
    plate_format: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class _LicensePlateFormat:
    name: str
    regex: re.Pattern[str]
    description: str


@dataclass
class _CountryRules:
    name: str
    code: str
    priority: int
    license_plate_formats: List[_LicensePlateFormat]
    valid_letters: str
    valid_digits: str
    corrections_common: Dict[str, str]
    corrections_latin_to_cyr: Dict[str, str]
    use_cyrillic_normalization: bool

    def normalize(self, text: str) -> str:
        normalized = text
        for src, dst in self.corrections_common.items():
            normalized = normalized.replace(src, dst)
        if self.use_cyrillic_normalization:
            for src, dst in self.corrections_latin_to_cyr.items():
                normalized = normalized.replace(src, dst)
        return normalized

    def is_allowed_charset(self, text: str) -> bool:
        allowed = set(self.valid_letters + self.valid_digits)
        return all(ch in allowed for ch in text)

    def match_format(self, text: str) -> Optional[_LicensePlateFormat]:
        for fmt in self.license_plate_formats:
            if fmt.regex.match(text):
                return fmt
        return None


class PlateValidator:
    """Расширяемый валидатор автомобильных номеров."""

    def __init__(
        self,
        config_dir: Optional[str] = None,
        allowed_countries: Optional[Sequence[str]] = None,
        stop_words: Optional[Iterable[str]] = None,
        enable: bool = True,
    ) -> None:
        self.enable = enable
        self.allowed_countries = {c.upper() for c in allowed_countries or []}
        self.stop_words = {w.upper() for w in (stop_words or ("TEST", "SAMPLE"))}
        self.rules: List[_CountryRules] = self._load_rules(config_dir)

    def _load_rules(self, config_dir: Optional[str]) -> List[_CountryRules]:
        base_dir = config_dir or os.path.join(os.path.dirname(__file__), "configs")
        rules: List[_CountryRules] = []
        for entry in sorted(os.listdir(base_dir)):
            if not entry.endswith(".yaml"):
                continue
            full_path = os.path.join(base_dir, entry)
            with open(full_path, "r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh)
            if not raw:
                continue
            rules.append(self._parse_country(raw))
        rules.sort(key=lambda r: r.priority)
        return rules

    @staticmethod
    def _parse_country(raw: Dict) -> _CountryRules:
        formats = [
            _LicensePlateFormat(
                name=item.get("name", "unknown"),
                regex=re.compile(item.get("regex", "^$")),
                description=item.get("description", ""),
            )
            for item in raw.get("license_plate_formats", [])
        ]
        letters = raw.get("valid_characters", {}).get("letters", "")
        digits = raw.get("valid_characters", {}).get("digits", "0123456789")
        corrections = raw.get("corrections", {})
        common = {c.get("from", ""): c.get("to", "") for c in corrections.get("common_mistakes", [])}
        latin_to_cyr = {
            c.get("from", ""): c.get("to", "") for c in corrections.get("latin_to_cyrillic", [])
        }
        return _CountryRules(
            name=raw.get("name", ""),
            code=raw.get("code", ""),
            priority=int(raw.get("priority", 100)),
            license_plate_formats=formats,
            valid_letters=letters,
            valid_digits=digits,
            corrections_common=common,
            corrections_latin_to_cyr=latin_to_cyr,
            use_cyrillic_normalization=bool(raw.get("use_cyrillic_normalization", False)),
        )

    @staticmethod
    def _sanitize(text: str) -> str:
        cleaned = re.sub(r"[\s\-]+", "", text or "")
        return cleaned.upper()

    @staticmethod
    def _is_repeating_sequence(text: str, min_length: int = 4) -> bool:
        if not text:
            return False
        if len(text) >= min_length and len(set(text)) == 1:
            return True
        if text.isdigit() and len(text) >= min_length:
            return text in ("0123", "1234", "2345", "3456", "4567", "5678", "6789")
        return False

    def validate(self, text: str) -> PlateValidationResult:
        if not self.enable:
            return PlateValidationResult(text=text, is_valid=True)

        sanitized = self._sanitize(text)
        if not sanitized:
            return PlateValidationResult(text="", is_valid=False, reason="empty")

        if sanitized in self.stop_words:
            return PlateValidationResult(text=sanitized, is_valid=False, reason="stop_word")

        if self._is_repeating_sequence(sanitized):
            return PlateValidationResult(text=sanitized, is_valid=False, reason="sequence")

        for country in self.rules:
            if self.allowed_countries and country.code.upper() not in self.allowed_countries:
                continue
            normalized = country.normalize(sanitized)
            if not country.is_allowed_charset(normalized):
                continue
            matched_format = country.match_format(normalized)
            if matched_format:
                return PlateValidationResult(
                    text=normalized,
                    is_valid=True,
                    country_code=country.code,
                    country_name=country.name,
                    plate_format=matched_format.name,
                )

        return PlateValidationResult(text=sanitized, is_valid=False, reason="no_match")
