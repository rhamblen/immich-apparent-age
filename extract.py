#!/usr/bin/env python3
"""Phase 1 - extract faces and ground truth from Immich into the sidecar DB.

For every configured person, this walks the assets they appear in, pulls the
face bounding boxes, computes their exact age at the moment of the photograph
from their birth date, crops the face, measures crop quality, and writes one
row per face.

No model runs here, and nothing a model could see is produced. Phase 2 reads
the crops back out.

Usage:
    python extract.py --probe                 # check assumptions against the server
    python extract.py --discover-people       # list people with a birth date set
    python extract.py                         # extract everyone in config.yaml
    python extract.py --person person_a       # just one, by config label
    python extract.py --limit 50 --dry-run    # sample without writing
    python extract.py --regate                # re-apply quality thresholds, no crawl
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

from immich_apparent_age import config as cfg
from immich_apparent_age import db, quality
from immich_apparent_age.immich import Client, ImmichError

log = logging.getLogger("extract")

# A face implying an age outside this range means the asset date is wrong, not
# that someone is 150. Flagged rather than dropped: a wrong date is more
# dangerous than a missing one, so it must be visible. See inventory gotcha 4.
_PLAUSIBLE_AGE = (-0.5, 120.0)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def cmd_discover_people(client: Client, configured: set[str]) -> int:
    """List people with a birth date set, as config.yaml stanzas.

    Names are printed to the terminal but deliberately not written anywhere:
    config.yaml is gitignored, and the repo is public.
    """
    with_dates: list[tuple[str, str, str]] = []
    total = 0
    for person in client.iter_people():
        total += 1
        if person.birth_date and person.name:
            with_dates.append((person.person_id, person.name, person.birth_date))

    with_dates.sort(key=lambda p: p[2])
    print(f"\n{len(with_dates)} of {total} people have a birth date set.\n")
    if not with_dates:
        print("Set birth dates in Immich (person page -> ... -> Set date of birth);")
        print("without one, a person cannot contribute a residual.")
        return 1

    print("Paste the stanzas you want into config.yaml, editing the labels")
    print("(labels appear in reports; keep real names out of them):\n")
    print("people:")
    for person_id, name, birth_date in with_dates:
        marker = "  # already configured" if person_id in configured else ""
        print(f"  - person_id: {person_id}{marker}")
        print(f"    label: {_suggest_label(name)}")
        print(f"    birth_date: {birth_date}")
    print()

    missing = total - len(with_dates)
    if missing:
        print(
            f"{missing} people have no birth date. Filling those in is the "
            f"cheapest way to enlarge the sample - see docs/project-plan.md."
        )
    return 0


def _suggest_label(name: str) -> str:
    """A report-safe label suggestion. The user is expected to change it."""
    slug = "".join(c if c.isalnum() else "_" for c in name.strip().lower())
    return slug.strip("_") or "person"


def cmd_probe(client: Client, person_id: str) -> int:
    """Check the live server against the client's assumptions."""
    print("\nProbing Immich...\n")
    findings = client.probe(person_id)
    width = max(len(k) for k in findings)
    for key, value in findings.items():
        print(f"  {key.ljust(width)}  {value}")
    print()

    ok = True
    if findings.get("faces_returned") == 0:
        print("PROBLEM: /api/faces?id=<assetId> returned nothing for an asset that")
        print("should contain a face. The spec describes that parameter as a face id,")
        print("so this server may want a different call. Nothing can be extracted")
        print("until this is resolved.")
        ok = False
    if findings.get("box_within_frame") is False:
        print("PROBLEM: the bounding box falls outside the frame it reports.")
        ok = False
    if findings.get("preview_matches_face_frame") is False:
        print("NOTE: the preview rendition is not the frame the boxes were computed")
        print("on. That is handled by scaling, but worth knowing.")
    if findings.get("matches_requested_person") is False:
        print("NOTE: no face on the sampled asset carried the requested person id.")
        print("Faces are matched by person id, so check this before a full run.")
    print("Probe looks good.\n" if ok else "Probe found problems.\n")
    return 0 if ok else 2


def extract_person(
    client: Client,
    conn,
    person: cfg.Person,
    conf: cfg.Config,
    limit: int | None,
    dry_run: bool,
    resume: bool,
    stats: dict,
) -> None:
    """Extract every usable face of one person."""
    already = db.extracted_asset_ids(conn, person.person_id) if resume else set()
    if already:
        log.info("%s: %d assets already extracted, skipping those", person.label, len(already))

    seen = faces_written = skipped_type = skipped_date = no_face = 0

    for asset in client.iter_person_assets(person.person_id):
        if limit is not None and seen >= limit:
            break
        seen += 1

        if asset.asset_id in already:
            continue
        if conf.quality.exclude_videos and asset.asset_type != "IMAGE":
            skipped_type += 1
            continue
        if asset.local_date_time is None:
            skipped_date += 1
            log.debug("%s: asset %s has no date, skipped", person.label, asset.asset_id)
            continue

        taken_on = asset.local_date_time.date()
        true_age = person.age_at(taken_on)
        date_suspect = not (_PLAUSIBLE_AGE[0] <= true_age <= _PLAUSIBLE_AGE[1])
        if date_suspect:
            log.warning(
                "%s: asset %s implies age %.1f - asset date is probably an import "
                "artefact; recorded but gated out",
                person.label,
                asset.asset_id,
                true_age,
            )

        try:
            faces = client.get_faces(asset.asset_id)
        except ImmichError as exc:
            log.warning("faces lookup failed for %s: %s", asset.asset_id, exc)
            continue

        mine = [f for f in faces if f.person_id == person.person_id]
        if not mine:
            no_face += 1
            log.debug(
                "%s: asset %s matched the person search but has no face for them",
                person.label,
                asset.asset_id,
            )
            continue

        image = None
        for face in mine:
            if image is None:
                try:
                    raw = client.get_image(asset.asset_id, conf.immich.image_source)
                    image = quality.load_image(raw)
                except (ImmichError, OSError) as exc:
                    log.warning("image fetch failed for %s: %s", asset.asset_id, exc)
                    break

            try:
                result = quality.crop_face(
                    image,
                    (face.x1, face.y1, face.x2, face.y2),
                    (face.image_width, face.image_height),
                    margin=conf.quality.crop_margin,
                    min_crop_px=conf.quality.min_crop_px,
                    min_blur_var=conf.quality.min_laplacian_var,
                )
            except ValueError as exc:
                log.warning("crop failed for face %s: %s", face.face_id, exc)
                continue

            passes = result.passes_gate and not date_suspect
            reason = result.gate_reason or ("suspect asset date" if date_suspect else None)

            crop_path = None
            if not dry_run and passes:
                crop_path = _write_crop(conf, person, face.face_id, result.image)

            if dry_run:
                log.info(
                    "%s  %s  age %5.1f  crop %4dpx  blur %7.1f  %s",
                    person.label,
                    taken_on.isoformat(),
                    true_age,
                    result.crop_px,
                    result.blur_var,
                    "pass" if passes else f"gated: {reason}",
                )
                faces_written += 1
                continue

            db.upsert_asset(
                conn,
                asset_id=asset.asset_id,
                asset_type=asset.asset_type,
                taken_at=asset.local_date_time.isoformat(),
                width=asset.width,
                height=asset.height,
                file_name=asset.original_file_name,
                date_suspect=date_suspect,
            )
            db.upsert_face(
                conn,
                {
                    "face_id": face.face_id,
                    "asset_id": asset.asset_id,
                    "person_id": person.person_id,
                    "taken_at": asset.local_date_time.isoformat(),
                    "true_age": true_age,
                    "box_x1": face.x1,
                    "box_y1": face.y1,
                    "box_x2": face.x2,
                    "box_y2": face.y2,
                    "frame_width": face.image_width,
                    "frame_height": face.image_height,
                    "source_type": face.source_type,
                    "crop_px": result.crop_px,
                    "blur_var": result.blur_var,
                    "yaw_deg": None,
                    "passes_gate": int(passes),
                    "gate_reason": reason,
                    "crop_path": crop_path,
                },
            )
            faces_written += 1

        if not dry_run and faces_written and faces_written % 100 == 0:
            conn.commit()
            log.info("%s: %d faces so far (%d assets seen)", person.label, faces_written, seen)

    if not dry_run:
        conn.commit()

    log.info(
        "%s: %d assets seen, %d faces written, %d non-image, %d undated, "
        "%d with no matching face",
        person.label,
        seen,
        faces_written,
        skipped_type,
        skipped_date,
        no_face,
    )
    stats[person.label] = {
        "assets_seen": seen,
        "faces_written": faces_written,
        "skipped_non_image": skipped_type,
        "skipped_undated": skipped_date,
        "no_matching_face": no_face,
    }


def _write_crop(conf: cfg.Config, person: cfg.Person, face_id: str, image) -> str:
    """Cache the crop. Gitignored and regenerable; keyed by face id."""
    out_dir = conf.output.crop_dir / person.label
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{face_id}.jpg"
    image.save(path, "JPEG", quality=95)
    return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    parser.add_argument("--person", action="append", help="config label; repeatable")
    parser.add_argument("--limit", type=int, help="max assets per person")
    parser.add_argument("--dry-run", action="store_true", help="measure, write nothing")
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="re-extract assets already in the database",
    )
    parser.add_argument("--discover-people", action="store_true")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument(
        "--regate",
        action="store_true",
        help="re-apply quality thresholds to stored faces without re-crawling",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    _setup_logging(args.verbose)

    try:
        conf = cfg.load(args.config)
    except cfg.ConfigError as exc:
        # --discover-people must work before config.yaml has any people in it.
        if args.discover_people and "no people configured" in str(exc):
            conf = None
        else:
            log.error("%s", exc)
            return 1

    if args.regate:
        if conf is None:
            log.error("--regate needs a valid config")
            return 1
        conn = db.connect(conf.output.database)
        n = db.regate(conn, conf.quality.min_crop_px, conf.quality.min_laplacian_var)
        log.info(
            "re-gated %d faces at min_crop_px=%d min_laplacian_var=%.1f",
            n,
            conf.quality.min_crop_px,
            conf.quality.min_laplacian_var,
        )
        return 0

    if conf is None:
        log.error("config.yaml could not be loaded")
        return 1

    with Client(
        conf.immich.base_url, conf.immich.api_key, conf.immich.request_timeout_s
    ) as client:
        if args.discover_people:
            return cmd_discover_people(client, {p.person_id for p in conf.people})

        if args.probe:
            return cmd_probe(client, conf.people[0].person_id)

        people = conf.people
        if args.person:
            wanted = set(args.person)
            people = [p for p in conf.people if p.label in wanted]
            unknown = wanted - {p.label for p in people}
            if unknown:
                log.error("no such label(s) in config: %s", ", ".join(sorted(unknown)))
                return 1

        conn = db.connect(conf.output.database)
        db.upsert_people(conn, conf.people)

        log.info(
            "extracting %d people from %s (%s rendition)%s",
            len(people),
            conf.immich.base_url,
            conf.immich.image_source,
            " [dry run]" if args.dry_run else "",
        )

        with db.run(conn, phase="1-extract") as stats:
            for person in people:
                try:
                    extract_person(
                        client,
                        conn,
                        person,
                        conf,
                        limit=args.limit,
                        dry_run=args.dry_run,
                        resume=not args.no_resume,
                        stats=stats,
                    )
                except ImmichError as exc:
                    log.error("%s: aborted - %s", person.label, exc)
                    stats[person.label] = {"error": str(exc)}
                except KeyboardInterrupt:
                    log.warning("interrupted; committing what is done")
                    conn.commit()
                    return 130

    log.info("done. next: python verify.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
