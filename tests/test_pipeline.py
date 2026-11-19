"""Offline tests for the Phase 1 pipeline - no Immich required.

Covers the parts that are easy to get silently wrong: box scaling between
renditions, the quality gate, config validation, and the database round-trip
including re-gating.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

import numpy as np
from PIL import Image

from immich_apparent_age import config as cfg
from immich_apparent_age import db, quality
from immich_apparent_age.immich import Face


def _noisy_image(w: int, h: int, seed: int = 0) -> Image.Image:
    """High-frequency noise, so Laplacian variance is comfortably above zero."""
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 256, (h, w, 3), dtype=np.uint8), "RGB")


def _structured_image(w: int, h: int, cycles: int = 4) -> Image.Image:
    """A band-limited pattern that survives rescaling.

    Per-pixel noise cannot be used to test size normalisation: its detail sits
    above the Nyquist limit of any downsample, so a resize destroys it whatever
    the normalisation does. Real photographs are band-limited, and so is this.
    """
    xs = np.linspace(0, cycles * 2 * np.pi, w)
    ys = np.linspace(0, cycles * 2 * np.pi, h)
    field = np.sin(xs)[None, :] + np.cos(ys)[:, None]
    arr = ((field - field.min()) / (field.max() - field.min()) * 255).astype(np.uint8)
    return Image.fromarray(np.dstack([arr] * 3), "RGB")


class TestBoxScaling(unittest.TestCase):
    def test_identity_when_frames_match(self):
        box = quality.scale_box((10, 20, 50, 80), frame=(100, 200), actual=(100, 200))
        self.assertEqual(box, (10.0, 20.0, 50.0, 80.0))

    def test_scales_up_to_a_larger_rendition(self):
        # Boxes computed on a 500-wide preview, applied to a 1000-wide fullsize.
        x1, y1, x2, y2 = quality.scale_box(
            (50, 100, 150, 200), frame=(500, 1000), actual=(1000, 2000)
        )
        self.assertEqual((x1, y1, x2, y2), (100.0, 200.0, 300.0, 400.0))

    def test_rejects_degenerate_frame(self):
        with self.assertRaises(ValueError):
            quality.scale_box((0, 0, 1, 1), frame=(0, 0), actual=(10, 10))


class TestCropAndGate(unittest.TestCase):
    def test_margin_adds_context_and_clamps_at_edges(self):
        img = _noisy_image(400, 400)
        # Face flush against the top-left corner: margin must clamp, not pad.
        result = quality.crop_face(
            img, (0, 0, 100, 100), (400, 400), margin=0.25, min_crop_px=50
        )
        self.assertEqual(result.image.size, (125, 125))
        self.assertTrue(result.passes_gate)

        # Face in the middle gets margin on all four sides.
        centred = quality.crop_face(
            img, (100, 100, 200, 200), (400, 400), margin=0.25, min_crop_px=50
        )
        self.assertEqual(centred.image.size, (150, 150))

    def test_gate_measures_the_face_not_the_padded_crop(self):
        img = _noisy_image(400, 400)
        # An 80px face padded to 120px must still fail a 112px threshold.
        result = quality.crop_face(
            img, (100, 100, 180, 180), (400, 400), margin=0.25, min_crop_px=112
        )
        self.assertEqual(result.crop_px, 80)
        self.assertFalse(result.passes_gate)
        self.assertEqual(result.gate_reason, "crop too small")

    def test_blur_gate_rejects_flat_crops(self):
        flat = Image.new("RGB", (400, 400), (128, 128, 128))
        result = quality.crop_face(
            flat, (0, 0, 200, 200), (400, 400), min_crop_px=112, min_blur_var=60.0
        )
        self.assertEqual(result.gate_reason, "too blurry")
        self.assertFalse(result.passes_gate)

    def test_blur_measure_is_size_normalised(self):
        """A big crop and a small crop of the same content should score alike.

        Without normalisation, Laplacian variance rises with resolution and the
        threshold would simply select large photographs rather than sharp ones.
        """
        big = _structured_image(448, 448)
        small = big.resize((112, 112), Image.Resampling.LANCZOS)
        big_score = quality.measure_blur(big)
        small_score = quality.measure_blur(small)
        self.assertGreater(small_score, 0.0)
        self.assertLess(abs(small_score - big_score), small_score * 0.25)

    def test_raw_variance_would_have_been_size_dependent(self):
        """Shows what the normalisation is protecting against.

        The same content at 4x the resolution has a markedly different raw
        Laplacian variance, which is why the measurement normalises first.
        """
        big = _structured_image(448, 448)
        small = big.resize((112, 112), Image.Resampling.LANCZOS)
        raw_big = quality._laplacian_var(np.asarray(big.convert("L"), dtype=np.float64))
        raw_small = quality._laplacian_var(
            np.asarray(small.convert("L"), dtype=np.float64)
        )
        self.assertGreater(raw_small, raw_big * 2)

    def test_degenerate_box_is_reported_not_raised(self):
        img = _noisy_image(100, 100)
        result = quality.crop_face(img, (50, 50, 50, 50), (100, 100))
        self.assertFalse(result.passes_gate)
        self.assertEqual(result.gate_reason, "degenerate box")


class TestFaceParsing(unittest.TestCase):
    def test_from_api_reads_the_documented_field_names(self):
        face = Face.from_api(
            {
                "id": "face-1",
                "boundingBoxX1": 10,
                "boundingBoxY1": 20,
                "boundingBoxX2": 110,
                "boundingBoxY2": 140,
                "imageWidth": 1000,
                "imageHeight": 2000,
                "sourceType": "machine-learning",
                "person": {"id": "person-1", "name": "x"},
            }
        )
        self.assertEqual(face.face_id, "face-1")
        self.assertEqual(face.person_id, "person-1")
        self.assertEqual((face.width, face.height), (100, 120))

    def test_unassigned_face_has_no_person(self):
        face = Face.from_api(
            {
                "id": "f",
                "boundingBoxX1": 0,
                "boundingBoxY1": 0,
                "boundingBoxX2": 1,
                "boundingBoxY2": 1,
                "imageWidth": 10,
                "imageHeight": 10,
                "person": None,
            }
        )
        self.assertIsNone(face.person_id)


class TestConfig(unittest.TestCase):
    def _write(self, text: str) -> Path:
        tmp = Path(tempfile.mkdtemp()) / "config.yaml"
        tmp.write_text(text, encoding="utf-8")
        return tmp

    def test_rejects_duplicate_labels(self):
        path = self._write(
            """
immich: {base_url: "http://h", api_key: k}
people:
  - {person_id: a, label: same, birth_date: 1990-01-01}
  - {person_id: b, label: same, birth_date: 1991-01-01}
"""
        )
        with self.assertRaisesRegex(cfg.ConfigError, "duplicate label"):
            cfg.load(path)

    def test_rejects_future_birth_date(self):
        path = self._write(
            """
immich: {base_url: "http://h", api_key: k}
people:
  - {person_id: a, label: x, birth_date: 2999-01-01}
"""
        )
        with self.assertRaisesRegex(cfg.ConfigError, "future"):
            cfg.load(path)

    def test_missing_env_var_is_an_error_not_an_empty_key(self):
        path = self._write(
            """
immich: {base_url: "http://h", api_key: "${DEFINITELY_NOT_SET_12345}"}
people:
  - {person_id: a, label: x, birth_date: 1990-01-01}
"""
        )
        with self.assertRaisesRegex(cfg.ConfigError, "DEFINITELY_NOT_SET_12345"):
            cfg.load(path)

    def test_age_at_is_exact_ground_truth(self):
        person = cfg.Person("id", "label", date(1965, 4, 12))
        self.assertAlmostEqual(person.age_at(date(2025, 4, 12)), 60.0, places=1)
        self.assertAlmostEqual(person.age_at(date(1995, 10, 12)), 30.5, places=1)


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.conn = db.connect(self.dir / "t.db")
        db.upsert_people(self.conn, [cfg.Person("p1", "person_a", date(1990, 1, 1))])
        db.upsert_asset(
            self.conn, "a1", "IMAGE", "2020-01-01T00:00:00", 100, 100, "f.jpg", False
        )

    def _face(self, face_id: str, crop_px: int, blur: float) -> None:
        db.upsert_face(
            self.conn,
            {
                "face_id": face_id,
                "asset_id": "a1",
                "person_id": "p1",
                "taken_at": "2020-01-01T00:00:00",
                "true_age": 30.0,
                "box_x1": 0,
                "box_y1": 0,
                "box_x2": crop_px,
                "box_y2": crop_px,
                "frame_width": 1000,
                "frame_height": 1000,
                "source_type": "machine-learning",
                "crop_px": crop_px,
                "blur_var": blur,
                "yaw_deg": None,
                "passes_gate": 1,
                "gate_reason": None,
                "crop_path": None,
            },
        )
        self.conn.commit()

    def test_upsert_is_idempotent(self):
        self._face("f1", 200, 500.0)
        self._face("f1", 200, 500.0)
        n = self.conn.execute("SELECT COUNT(*) c FROM faces").fetchone()["c"]
        self.assertEqual(n, 1)

    def test_regate_changes_verdicts_without_recrawling(self):
        self._face("f1", 200, 500.0)  # good
        self._face("f2", 60, 500.0)  # too small
        self._face("f3", 200, 5.0)  # too blurry

        db.regate(self.conn, min_crop_px=112, min_blur_var=60.0)
        passed = {
            r["face_id"]
            for r in self.conn.execute("SELECT face_id FROM faces WHERE passes_gate=1")
        }
        self.assertEqual(passed, {"f1"})

        # Loosen the thresholds: f2 and f3 come back, no extraction needed.
        db.regate(self.conn, min_crop_px=50, min_blur_var=1.0)
        passed = {
            r["face_id"]
            for r in self.conn.execute("SELECT face_id FROM faces WHERE passes_gate=1")
        }
        self.assertEqual(passed, {"f1", "f2", "f3"})

    def test_resume_reports_extracted_assets(self):
        self._face("f1", 200, 500.0)
        self.assertEqual(db.extracted_asset_ids(self.conn, "p1"), {"a1"})
        self.assertEqual(db.extracted_asset_ids(self.conn, "nobody"), set())

    def test_run_records_provenance(self):
        with db.run(self.conn, phase="1-extract") as stats:
            stats["faces"] = 7
        row = self.conn.execute("SELECT * FROM runs").fetchone()
        self.assertEqual(row["phase"], "1-extract")
        self.assertIsNotNone(row["finished_at"])
        self.assertIn("7", row["stats"])


if __name__ == "__main__":
    unittest.main()
