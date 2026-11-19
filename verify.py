#!/usr/bin/env python3
"""Phase 1 verification - contact sheets and a coverage report.

Two things have to be true before any model is allowed near this data, and
neither can be checked by a machine:

1. **The crops contain the right person, the right way up.** Immich's identity
   clustering is good but not perfect, and a mis-assigned face produces a
   confidently wrong residual, because the true age will be the wrong person's.
   The contact sheet exists to be looked at.
2. **There is enough data per person to support a conclusion.** The coverage
   report says how much, and where it sits in the age range.

Usage:
    python verify.py                    # contact sheets + coverage report
    python verify.py --coverage-only
    python verify.py --sheet-size 48
"""

from __future__ import annotations

import argparse
import logging
import random
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw

from immich_apparent_age import config as cfg
from immich_apparent_age import db

log = logging.getLogger("verify")

_TILE = 160
_COLS = 8
_LABEL_H = 18


def contact_sheet(
    conn: sqlite3.Connection,
    label: str,
    out_path: Path,
    sample: int,
    seed: int,
    gated: bool,
) -> int:
    """Build one contact sheet, sampled across the whole age range.

    Sampling is stratified by integer age so the sheet shows the span of a
    person's life rather than whichever years they were photographed most.
    """
    rows = conn.execute(
        """
        SELECT f.crop_path, f.true_age, f.crop_px, f.blur_var, a.taken_at
        FROM faces f JOIN people p ON p.person_id = f.person_id
        JOIN assets a ON a.asset_id = f.asset_id
        WHERE p.label = ? AND f.passes_gate = ? AND f.crop_path IS NOT NULL
        """,
        (label, 1 if gated else 0),
    ).fetchall()

    usable = [r for r in rows if r["crop_path"] and Path(r["crop_path"]).exists()]
    if not usable:
        return 0

    by_age: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for row in usable:
        by_age[int(row["true_age"] or 0)].append(row)

    rng = random.Random(seed)
    picked: list[sqlite3.Row] = []
    ages = sorted(by_age)
    while len(picked) < sample and any(by_age[a] for a in ages):
        for age in ages:
            if not by_age[age]:
                continue
            picked.append(by_age[age].pop(rng.randrange(len(by_age[age]))))
            if len(picked) >= sample:
                break
    picked.sort(key=lambda r: r["true_age"] or 0)

    cols = min(_COLS, len(picked))
    rows_n = (len(picked) + cols - 1) // cols
    sheet = Image.new(
        "RGB", (cols * _TILE, rows_n * (_TILE + _LABEL_H)), (24, 24, 27)
    )
    draw = ImageDraw.Draw(sheet)

    for i, row in enumerate(picked):
        x = (i % cols) * _TILE
        y = (i // cols) * (_TILE + _LABEL_H)
        try:
            with Image.open(row["crop_path"]) as crop:
                crop = crop.convert("RGB")
                crop.thumbnail((_TILE, _TILE), Image.Resampling.LANCZOS)
                sheet.paste(
                    crop,
                    (x + (_TILE - crop.width) // 2, y + (_TILE - crop.height) // 2),
                )
        except OSError:
            draw.rectangle([x, y, x + _TILE, y + _TILE], fill=(60, 20, 20))

        taken = (row["taken_at"] or "")[:4]
        draw.text(
            (x + 4, y + _TILE + 3),
            f"{row['true_age']:.0f}y  {taken}  {row['crop_px']}px",
            fill=(200, 200, 205),
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, "JPEG", quality=88)
    return len(picked)


def coverage(conn: sqlite3.Connection, out_path: Path) -> str:
    """Faces per person per decade of life, plus the gate's effect."""
    rows = conn.execute(
        """
        SELECT p.label,
               CAST(f.true_age / 10 AS INTEGER) * 10 AS decade,
               SUM(f.passes_gate)        AS passed,
               COUNT(*)                  AS total
        FROM faces f JOIN people p ON p.person_id = f.person_id
        WHERE f.true_age IS NOT NULL
        GROUP BY p.label, decade
        ORDER BY p.label, decade
        """
    ).fetchall()

    if not rows:
        return "No faces extracted yet.\n"

    decades = sorted({r["decade"] for r in rows})
    labels = sorted({r["label"] for r in rows})
    grid: dict[tuple[str, int], tuple[int, int]] = {
        (r["label"], r["decade"]): (r["passed"], r["total"]) for r in rows
    }

    lines = ["# Phase 1 coverage", ""]
    lines.append("Faces passing the quality gate, out of all faces extracted.")
    lines.append("")
    header = "| person | " + " | ".join(f"{d}s" for d in decades) + " | total |"
    lines.append(header)
    lines.append("|" + "---|" * (len(decades) + 2))

    for label in labels:
        cells = []
        tp = tt = 0
        for d in decades:
            passed, total = grid.get((label, d), (0, 0))
            tp += passed
            tt += total
            cells.append(f"{passed}/{total}" if total else "-")
        lines.append(f"| {label} | " + " | ".join(cells) + f" | **{tp}/{tt}** |")

    # Matched pairs: the comparisons that survive scrutiny. See ADR 0006.
    pairs = conn.execute(
        """
        SELECT pa.label AS a, pb.label AS b, COUNT(DISTINCT fa.asset_id) AS n
        FROM faces fa
        JOIN faces fb ON fb.asset_id = fa.asset_id AND fb.person_id < fa.person_id
        JOIN people pa ON pa.person_id = fa.person_id
        JOIN people pb ON pb.person_id = fb.person_id
        WHERE fa.passes_gate = 1 AND fb.passes_gate = 1
        GROUP BY pa.label, pb.label
        HAVING n > 0
        ORDER BY n DESC
        """
    ).fetchall()

    lines += ["", "## Same-photo pairs", ""]
    if pairs:
        lines.append("Assets where both people have a gated face - the matched-pair")
        lines.append("sample that ADR 0006 treats as the headline result.")
        lines.append("")
        lines.append("| pair | shared photos |")
        lines.append("|---|---|")
        for p in pairs:
            lines.append(f"| {p['a']} + {p['b']} | {p['n']} |")
    else:
        lines.append("None yet. Without these, only the weaker cross-photo")
        lines.append("comparisons are available.")

    gate = conn.execute(
        """
        SELECT gate_reason, COUNT(*) n FROM faces
        WHERE passes_gate = 0 GROUP BY gate_reason ORDER BY n DESC
        """
    ).fetchall()
    if gate:
        lines += ["", "## Why faces were gated out", "", "| reason | faces |", "|---|---|"]
        for g in gate:
            lines.append(f"| {g['gate_reason'] or 'unknown'} | {g['n']} |")

    text = "\n".join(lines) + "\n"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--sheet-size", type=int, default=32)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--coverage-only", action="store_true")
    parser.add_argument(
        "--gated",
        action="store_true",
        help="sheet the REJECTED faces instead, to sanity-check the thresholds",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        conf = cfg.load(args.config)
    except cfg.ConfigError as exc:
        log.error("%s", exc)
        return 1

    if not Path(conf.output.database).exists():
        log.error("no database at %s - run extract.py first", conf.output.database)
        return 1

    conn = db.connect(conf.output.database)
    report_dir = Path(conf.output.report_dir)

    text = coverage(conn, report_dir / "phase1-coverage.md")
    print()
    print(text)
    log.info("coverage report: %s", report_dir / "phase1-coverage.md")

    if args.coverage_only:
        return 0

    suffix = "-gated" if args.gated else ""
    for person in conf.people:
        out = report_dir / "contact-sheets" / f"{person.label}{suffix}.jpg"
        n = contact_sheet(
            conn, person.label, out, args.sheet_size, args.seed, args.gated
        )
        if n:
            log.info("contact sheet: %s (%d crops)", out, n)
        else:
            log.warning("%s: no crops available for a sheet", person.label)

    log.info(
        "\nLook at the sheets before going further. Every face should be the "
        "right person, upright, and roughly the age printed under it."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
