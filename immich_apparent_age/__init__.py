"""immich-apparent-age - measure apparent age against chronological age.

Phase 1 (extract) lives in :mod:`immich_apparent_age.immich`,
:mod:`immich_apparent_age.db` and :mod:`immich_apparent_age.quality`, driven by
the top-level ``extract.py`` and ``verify.py`` scripts.

Nothing in this package may read ``true_age``-derived values into anything that
is handed to a model. See docs/decisions/0007.
"""

__version__ = "0.1.0"
