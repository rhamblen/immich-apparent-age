"""Cropping and crop-quality measurement.

Quality is *measured and stored*, never used to discard a face at extraction
time - see ADR 0008. Thresholds are guesses until there is data to tune them
against, and re-gating must not mean re-crawling a six-figure library.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import numpy as np
from PIL import Image, ImageOps

# Sharpness is measured on a crop normalised to this size. Laplacian variance
# scales with resolution, so measuring raw crops would simply rank big crops as
# sharp and make the threshold meaningless across a mixed library.
_BLUR_REFERENCE_PX = 112


@dataclass(frozen=True)
class CropResult:
    image: Image.Image
    crop_px: int
    blur_var: float
    passes_gate: bool
    gate_reason: str | None


def load_image(data: bytes) -> Image.Image:
    """Decode bytes, honouring EXIF orientation.

    Immich's face boxes are computed on the rendition it generated, which is
    already upright, so the transpose matters only for odd inputs - but a
    sideways crop silently wrecks an age estimate, so it is always applied.
    """
    img = Image.open(BytesIO(data))
    img = ImageOps.exif_transpose(img)
    return img.convert("RGB")


def scale_box(
    box: tuple[int, int, int, int],
    frame: tuple[int, int],
    actual: tuple[int, int],
) -> tuple[float, float, float, float]:
    """Map a bounding box from its reference frame onto the fetched image.

    Immich reports each face with the imageWidth/imageHeight of the rendition
    the box was computed against. That frame will not match the image actually
    downloaded unless the same rendition was requested, so scale rather than
    assume. See ADR 0004.
    """
    fw, fh = frame
    aw, ah = actual
    if fw <= 0 or fh <= 0:
        raise ValueError(f"face reports a degenerate frame: {frame}")
    sx, sy = aw / fw, ah / fh
    x1, y1, x2, y2 = box
    return x1 * sx, y1 * sy, x2 * sx, y2 * sy


def _laplacian_var(gray: np.ndarray) -> float:
    """Variance of the 4-neighbour Laplacian - the standard sharpness proxy."""
    if gray.shape[0] < 3 or gray.shape[1] < 3:
        return 0.0
    lap = (
        gray[:-2, 1:-1]
        + gray[2:, 1:-1]
        + gray[1:-1, :-2]
        + gray[1:-1, 2:]
        - 4.0 * gray[1:-1, 1:-1]
    )
    return float(lap.var())


def measure_blur(crop: Image.Image) -> float:
    """Sharpness of a crop, normalised for size so the threshold transfers."""
    shorter = min(crop.size)
    if shorter <= 0:
        return 0.0
    scale = _BLUR_REFERENCE_PX / shorter
    if scale < 1.0:
        target = (max(1, round(crop.width * scale)), max(1, round(crop.height * scale)))
        crop = crop.resize(target, Image.Resampling.LANCZOS)
    gray = np.asarray(crop.convert("L"), dtype=np.float64)
    return _laplacian_var(gray)


def crop_face(
    image: Image.Image,
    box: tuple[int, int, int, int],
    frame: tuple[int, int],
    margin: float = 0.25,
    min_crop_px: int = 112,
    min_blur_var: float = 60.0,
) -> CropResult:
    """Crop a face with context, and measure it.

    `margin` expands the box as a fraction of its size on each side: age models
    are trained on faces with some surrounding context, and a tight box costs
    accuracy. The crop is clamped to the image, so a face at the edge gets less
    context rather than a black border.
    """
    x1, y1, x2, y2 = scale_box(box, frame, image.size)
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0:
        return CropResult(
            image=Image.new("RGB", (1, 1)),
            crop_px=0,
            blur_var=0.0,
            passes_gate=False,
            gate_reason="degenerate box",
        )

    dx, dy = w * margin, h * margin
    left = max(0, int(round(x1 - dx)))
    top = max(0, int(round(y1 - dy)))
    right = min(image.width, int(round(x2 + dx)))
    bottom = min(image.height, int(round(y2 + dy)))

    crop = image.crop((left, top, right, bottom))

    # The gate measures the *face*, not the padded crop: a tiny face in a large
    # padded box is still a tiny face.
    crop_px = int(round(min(w, h)))
    blur_var = measure_blur(crop)

    reason: str | None = None
    if crop_px < min_crop_px:
        reason = "crop too small"
    elif blur_var < min_blur_var:
        reason = "too blurry"

    return CropResult(
        image=crop,
        crop_px=crop_px,
        blur_var=blur_var,
        passes_gate=reason is None,
        gate_reason=reason,
    )
