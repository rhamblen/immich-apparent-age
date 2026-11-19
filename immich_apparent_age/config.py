"""Configuration loading and validation.

config.yaml is gitignored and holds the only identifying data in the project:
the Immich host, the API key, and the person -> birth date mapping. See
docs/decisions/0007 and config.example.yaml.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(Exception):
    """Raised when config.yaml is missing, malformed, or incomplete."""


def _expand_env(value: object) -> object:
    """Replace ${VAR} with the environment value, recursively through the tree.

    A missing variable is an error rather than an empty string: silently
    authenticating with "" produces a confusing 401 much later.
    """
    if isinstance(value, str):

        def _sub(match: re.Match[str]) -> str:
            name = match.group(1)
            try:
                return os.environ[name]
            except KeyError:
                raise ConfigError(
                    f"config.yaml refers to ${{{name}}} but that environment "
                    f"variable is not set"
                ) from None

        return _ENV_PATTERN.sub(_sub, value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


@dataclass(frozen=True)
class Person:
    """A person whose chronological age is known exactly."""

    person_id: str
    label: str
    birth_date: date

    def age_at(self, when: date) -> float:
        """Age in years at `when`, as a float. Ground truth; never estimated."""
        return (when - self.birth_date).days / 365.2425


@dataclass(frozen=True)
class ImmichConfig:
    base_url: str
    api_key: str
    image_source: str = "preview"
    request_timeout_s: float = 30.0
    max_concurrency: int = 4

    def __post_init__(self) -> None:
        valid = {"preview", "fullsize", "original"}
        if self.image_source not in valid:
            raise ConfigError(
                f"immich.image_source must be one of {sorted(valid)}, "
                f"got {self.image_source!r}"
            )


@dataclass(frozen=True)
class QualityConfig:
    min_crop_px: int = 112
    min_laplacian_var: float = 60.0
    max_yaw_deg: float = 30.0
    exclude_videos: bool = True
    # Context around the face. Age models expect some margin, not a tight crop.
    crop_margin: float = 0.25


@dataclass(frozen=True)
class OutputConfig:
    database: Path = Path("out/apparent-age.db")
    crop_dir: Path = Path("crops")
    report_dir: Path = Path("reports")


@dataclass(frozen=True)
class Config:
    immich: ImmichConfig
    people: list[Person]
    quality: QualityConfig = field(default_factory=QualityConfig)
    output: OutputConfig = field(default_factory=OutputConfig)

    def person(self, person_id: str) -> Person | None:
        return next((p for p in self.people if p.person_id == person_id), None)


def _parse_date(value: object, where: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise ConfigError(f"{where}: expected a YYYY-MM-DD date, got {value!r}")


def load(path: str | Path = "config.yaml") -> Config:
    """Load and validate config.yaml."""
    path = Path(path)
    if not path.exists():
        raise ConfigError(
            f"{path} not found. Copy config.example.yaml to {path} and fill it "
            f"in - it is gitignored, and holds the host, API key and birth dates."
        )

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = _expand_env(raw)
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level")

    immich_raw = raw.get("immich") or {}
    for required in ("base_url", "api_key"):
        if not immich_raw.get(required):
            raise ConfigError(f"{path}: immich.{required} is required")

    immich = ImmichConfig(
        base_url=str(immich_raw["base_url"]).rstrip("/"),
        api_key=str(immich_raw["api_key"]),
        image_source=str(immich_raw.get("image_source", "preview")),
        request_timeout_s=float(immich_raw.get("request_timeout_s", 30.0)),
        max_concurrency=int(immich_raw.get("max_concurrency", 4)),
    )

    people: list[Person] = []
    seen_ids: set[str] = set()
    seen_labels: set[str] = set()
    for i, entry in enumerate(raw.get("people") or []):
        where = f"{path}: people[{i}]"
        if not isinstance(entry, dict):
            raise ConfigError(f"{where}: expected a mapping")
        for required in ("person_id", "label", "birth_date"):
            if required not in entry:
                raise ConfigError(f"{where}: {required} is required")
        person = Person(
            person_id=str(entry["person_id"]),
            label=str(entry["label"]),
            birth_date=_parse_date(entry["birth_date"], f"{where}.birth_date"),
        )
        if person.person_id in seen_ids:
            raise ConfigError(f"{where}: duplicate person_id {person.person_id}")
        if person.label in seen_labels:
            raise ConfigError(
                f"{where}: duplicate label {person.label!r} - labels appear in "
                f"reports and must be unique"
            )
        if person.birth_date > date.today():
            raise ConfigError(f"{where}: birth_date is in the future")
        seen_ids.add(person.person_id)
        seen_labels.add(person.label)
        people.append(person)

    if not people:
        raise ConfigError(
            f"{path}: no people configured. Only people with a known birth date "
            f"can yield a residual - run `python extract.py --discover-people` "
            f"to list candidates from Immich."
        )

    q_raw = raw.get("quality") or {}
    quality = QualityConfig(
        min_crop_px=int(q_raw.get("min_crop_px", 112)),
        min_laplacian_var=float(q_raw.get("min_laplacian_var", 60.0)),
        max_yaw_deg=float(q_raw.get("max_yaw_deg", 30.0)),
        exclude_videos=bool(q_raw.get("exclude_videos", True)),
        crop_margin=float(q_raw.get("crop_margin", 0.25)),
    )

    o_raw = raw.get("output") or {}
    output = OutputConfig(
        database=Path(o_raw.get("database", "out/apparent-age.db")),
        crop_dir=Path(o_raw.get("crop_dir", "crops")),
        report_dir=Path(o_raw.get("report_dir", "reports")),
    )

    return Config(immich=immich, people=people, quality=quality, output=output)
