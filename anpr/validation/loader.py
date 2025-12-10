"""Загрузка конфигураций стран из YAML."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Sequence

import yaml

from .base import CountryConfig, PlateFormat


def _parse_corrections(raw: Iterable[dict] | None) -> List[tuple[str, str]]:
    pairs: List[tuple[str, str]] = []
    for item in raw or []:
        src = str(item.get("from", ""))
        dst = str(item.get("to", ""))
        if src and dst:
            pairs.append((src, dst))
    return pairs


def _parse_formats(raw: Iterable[dict] | None) -> List[PlateFormat]:
    formats: List[PlateFormat] = []
    for item in raw or []:
        name = str(item.get("name", "")) or "unknown"
        regex = str(item.get("regex", ""))
        description = str(item.get("description", ""))
        if regex:
            formats.append(PlateFormat(name=name, pattern=regex, description=description))
    return formats


def load_country_configs(config_dir: Path, allowed_countries: Sequence[str] | None = None) -> List[CountryConfig]:
    """Читает YAML-конфигурации и готовит CountryConfig."""

    configs: List[CountryConfig] = []
    allow = {c.upper() for c in allowed_countries} if allowed_countries else None

    for path in sorted(config_dir.glob("*.yaml")):
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}

        code = str(data.get("code", "")).upper()
        if allow and code and code not in allow:
            continue

        min_length = data.get("min_length")
        max_length = data.get("max_length")

        cfg = CountryConfig(
            name=data.get("name", ""),
            code=code,
            priority=int(data.get("priority", 10)),
            license_plate_formats=_parse_formats(data.get("license_plate_formats", [])),
            valid_letters=str(data.get("valid_characters", {}).get("letters", "")),
            valid_digits=str(data.get("valid_characters", {}).get("digits", "")),
            stop_words=[str(w).upper() for w in data.get("stop_words", [])],
            corrections_common=_parse_corrections(data.get("corrections", {}).get("common_mistakes")),
            corrections_latin_to_cyrillic=_parse_corrections(
                data.get("corrections", {}).get("latin_to_cyrillic")
            ),
            corrections_cyrillic_to_latin=_parse_corrections(
                data.get("corrections", {}).get("cyrillic_to_latin")
            ),
            min_length=int(min_length) if min_length is not None else None,
            max_length=int(max_length) if max_length is not None else None,
            uses_cyrillic=bool(data.get("uses_cyrillic", True)),
            allow_sequences=bool(data.get("allow_sequences", False)),
        )
        configs.append(cfg)

    return sorted(configs, key=lambda c: c.priority)
