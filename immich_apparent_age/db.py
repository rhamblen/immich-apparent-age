"""SQLite store - the system of record for everything this project computes.

Schema follows docs/architecture.md. Two rules are structural rather than
conventional, because they are the integrity of the experiment:

* ``faces`` holds ground truth (``true_age``) and ``predictions`` holds model
  output. Nothing joins them except the analysis stage.
* ``predictions`` is keyed by model name *and* version, so a second model adds
  rows instead of overwriting the first.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS people (
    person_id   TEXT PRIMARY KEY,
    label       TEXT NOT NULL UNIQUE,
    birth_date  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assets (
    asset_id    TEXT PRIMARY KEY,
    asset_type  TEXT NOT NULL,
    taken_at    TEXT,
    width       INTEGER,
    height      INTEGER,
    file_name   TEXT,
    date_suspect INTEGER NOT NULL DEFAULT 0,
    seen_at     TEXT NOT NULL
);

-- One row per detected face of a configured person. Ground truth only:
-- no column here is ever derived from a model.
CREATE TABLE IF NOT EXISTS faces (
    face_id      TEXT PRIMARY KEY,
    asset_id     TEXT NOT NULL REFERENCES assets(asset_id),
    person_id    TEXT NOT NULL REFERENCES people(person_id),
    taken_at     TEXT,
    true_age     REAL,
    box_x1       INTEGER NOT NULL,
    box_y1       INTEGER NOT NULL,
    box_x2       INTEGER NOT NULL,
    box_y2       INTEGER NOT NULL,
    frame_width  INTEGER NOT NULL,
    frame_height INTEGER NOT NULL,
    source_type  TEXT,
    crop_px      INTEGER,
    blur_var     REAL,
    yaw_deg      REAL,
    passes_gate  INTEGER NOT NULL DEFAULT 0,
    gate_reason  TEXT,
    crop_path    TEXT,
    extracted_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS faces_person ON faces(person_id);
CREATE INDEX IF NOT EXISTS faces_asset ON faces(asset_id);
CREATE INDEX IF NOT EXISTS faces_gate ON faces(passes_gate);

-- Model output. Keyed by model version so a cross-check adds rows.
CREATE TABLE IF NOT EXISTS predictions (
    face_id       TEXT NOT NULL REFERENCES faces(face_id),
    model_name    TEXT NOT NULL,
    model_version TEXT NOT NULL,
    apparent_age  REAL NOT NULL,
    inferred_at   TEXT NOT NULL,
    PRIMARY KEY (face_id, model_name, model_version)
);

-- Provenance, so any figure can be traced to the code that produced it.
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    phase       TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    git_sha     TEXT,
    config_hash TEXT,
    stats       TEXT,
    notes       TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def connect(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the sidecar database."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
    elif row["version"] != SCHEMA_VERSION:
        raise RuntimeError(
            f"database at {path} is schema version {row['version']}, "
            f"this code expects {SCHEMA_VERSION}"
        )
    conn.commit()
    return conn


def upsert_people(conn: sqlite3.Connection, people: list[Any]) -> None:
    conn.executemany(
        """
        INSERT INTO people (person_id, label, birth_date) VALUES (?, ?, ?)
        ON CONFLICT(person_id) DO UPDATE SET
            label = excluded.label,
            birth_date = excluded.birth_date
        """,
        [(p.person_id, p.label, p.birth_date.isoformat()) for p in people],
    )
    conn.commit()


def upsert_asset(
    conn: sqlite3.Connection,
    asset_id: str,
    asset_type: str,
    taken_at: str | None,
    width: int | None,
    height: int | None,
    file_name: str,
    date_suspect: bool,
) -> None:
    conn.execute(
        """
        INSERT INTO assets
            (asset_id, asset_type, taken_at, width, height, file_name,
             date_suspect, seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(asset_id) DO UPDATE SET
            taken_at = excluded.taken_at,
            date_suspect = excluded.date_suspect,
            seen_at = excluded.seen_at
        """,
        (
            asset_id,
            asset_type,
            taken_at,
            width,
            height,
            file_name,
            int(date_suspect),
            _now(),
        ),
    )


def upsert_face(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    """Insert or update one face. Idempotent, keyed on face_id."""
    conn.execute(
        """
        INSERT INTO faces (
            face_id, asset_id, person_id, taken_at, true_age,
            box_x1, box_y1, box_x2, box_y2, frame_width, frame_height,
            source_type, crop_px, blur_var, yaw_deg, passes_gate, gate_reason,
            crop_path, extracted_at
        ) VALUES (
            :face_id, :asset_id, :person_id, :taken_at, :true_age,
            :box_x1, :box_y1, :box_x2, :box_y2, :frame_width, :frame_height,
            :source_type, :crop_px, :blur_var, :yaw_deg, :passes_gate,
            :gate_reason, :crop_path, :extracted_at
        )
        ON CONFLICT(face_id) DO UPDATE SET
            taken_at = excluded.taken_at,
            true_age = excluded.true_age,
            crop_px = excluded.crop_px,
            blur_var = excluded.blur_var,
            yaw_deg = excluded.yaw_deg,
            passes_gate = excluded.passes_gate,
            gate_reason = excluded.gate_reason,
            crop_path = excluded.crop_path,
            extracted_at = excluded.extracted_at
        """,
        {**row, "extracted_at": _now()},
    )


def extracted_asset_ids(conn: sqlite3.Connection, person_id: str) -> set[str]:
    """Assets already extracted for a person, so a run can resume."""
    rows = conn.execute(
        "SELECT DISTINCT asset_id FROM faces WHERE person_id = ?", (person_id,)
    ).fetchall()
    return {r["asset_id"] for r in rows}


def regate(conn: sqlite3.Connection, min_crop_px: int, min_blur_var: float) -> int:
    """Re-apply the quality gate to stored faces. No re-crawl. See ADR 0008."""
    cur = conn.execute(
        """
        UPDATE faces SET
            passes_gate = CASE
                WHEN crop_px IS NULL OR blur_var IS NULL THEN 0
                WHEN crop_px < ? THEN 0
                WHEN blur_var < ? THEN 0
                ELSE 1
            END,
            gate_reason = CASE
                WHEN crop_px IS NULL OR blur_var IS NULL THEN 'unmeasured'
                WHEN crop_px < ? THEN 'crop too small'
                WHEN blur_var < ? THEN 'too blurry'
                ELSE NULL
            END
        """,
        (min_crop_px, min_blur_var, min_crop_px, min_blur_var),
    )
    conn.commit()
    return cur.rowcount


@contextmanager
def run(
    conn: sqlite3.Connection, phase: str, notes: str | None = None
) -> Iterator[dict[str, Any]]:
    """Record a pass, with the git SHA, so results are attributable."""
    run_id = str(uuid.uuid4())
    stats: dict[str, Any] = {}
    conn.execute(
        "INSERT INTO runs (run_id, phase, started_at, git_sha, notes) VALUES (?,?,?,?,?)",
        (run_id, phase, _now(), _git_sha(), notes),
    )
    conn.commit()
    try:
        yield stats
    finally:
        conn.execute(
            "UPDATE runs SET finished_at = ?, stats = ? WHERE run_id = ?",
            (_now(), json.dumps(stats, default=str), run_id),
        )
        conn.commit()
