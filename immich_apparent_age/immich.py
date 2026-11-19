"""Immich REST client - read-only.

Field shapes verified against the Immich OpenAPI spec (info.version
3.4.0-rc.0) on 2026-11-19. Two things differ from the obvious guess, and both
are load-bearing:

* **Face bounding boxes do not live on the asset.** ``GET /api/assets/{id}``
  returns ``people[]`` (PersonResponseDto) with no nested ``faces``. Boxes come
  from ``GET /api/faces?id=...`` returning ``AssetFaceResponseDto[]``, each
  carrying ``boundingBoxX1/X2/Y1/Y2``, ``imageWidth``/``imageHeight`` and the
  owning ``person``.
* **The documented paging and person filter are deprecated.** On
  ``POST /api/search/metadata``, top-level ``personIds`` is deprecated since
  v3.2.0 in favour of ``filter.personIds`` (an IdsFilter with
  ``all``/``any``/``none``), and ``page`` is deprecated in favour of
  ``cursor``/``nextCursor``. Both legacy forms still work, so this client
  prefers the modern shape and falls back automatically.

The ``id`` query parameter of ``GET /api/faces`` is described in the spec as a
"Face ID" while the endpoint summary says it retrieves the faces of an *asset*.
The spec cannot settle it, so :meth:`Client.probe` checks against the live
server and ``get_faces`` reports clearly if it comes back empty.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterator

import httpx

log = logging.getLogger(__name__)

_RETRY_STATUS = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 4


class ImmichError(Exception):
    """A request to Immich failed in a way that is not worth retrying."""


@dataclass(frozen=True)
class Face:
    """One detected face, with its bounding box and reference frame."""

    face_id: str
    person_id: str | None
    x1: int
    y1: int
    x2: int
    y2: int
    image_width: int
    image_height: int
    source_type: str | None

    @property
    def width(self) -> int:
        return max(0, self.x2 - self.x1)

    @property
    def height(self) -> int:
        return max(0, self.y2 - self.y1)

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "Face":
        person = raw.get("person") or {}
        return cls(
            face_id=raw["id"],
            person_id=person.get("id"),
            x1=int(raw["boundingBoxX1"]),
            y1=int(raw["boundingBoxY1"]),
            x2=int(raw["boundingBoxX2"]),
            y2=int(raw["boundingBoxY2"]),
            image_width=int(raw["imageWidth"]),
            image_height=int(raw["imageHeight"]),
            source_type=raw.get("sourceType"),
        )


@dataclass(frozen=True)
class Asset:
    asset_id: str
    asset_type: str
    original_file_name: str
    local_date_time: datetime | None
    width: int | None
    height: int | None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "Asset":
        return cls(
            asset_id=raw["id"],
            asset_type=raw.get("type", "IMAGE"),
            original_file_name=raw.get("originalFileName", ""),
            local_date_time=_parse_dt(raw.get("localDateTime")),
            width=raw.get("width"),
            height=raw.get("height"),
        )


@dataclass(frozen=True)
class PersonSummary:
    person_id: str
    name: str
    birth_date: str | None
    is_hidden: bool


def _parse_dt(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        log.warning("unparseable datetime from Immich: %r", value)
        return None


class Client:
    """Read-only Immich client. Phases 1-4 issue no writes."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_s: float = 30.0,
        session: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = session or httpx.Client(
            base_url=self.base_url,
            headers={"x-api-key": api_key, "Accept": "application/json"},
            timeout=timeout_s,
            follow_redirects=True,
        )
        # Set on first successful search; avoids re-probing per person.
        self._use_modern_filter: bool | None = None

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # ---------------------------------------------------------------- requests

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Issue a request, retrying transient failures with backoff."""
        last: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = self._client.request(method, path, **kwargs)
            except httpx.TransportError as exc:
                last = exc
                if attempt == _MAX_ATTEMPTS:
                    break
                time.sleep(2 ** (attempt - 1))
                continue

            if response.status_code in _RETRY_STATUS and attempt < _MAX_ATTEMPTS:
                wait = float(response.headers.get("Retry-After") or 2 ** (attempt - 1))
                log.warning(
                    "%s %s returned %s, retrying in %.0fs (attempt %d/%d)",
                    method,
                    path,
                    response.status_code,
                    wait,
                    attempt,
                    _MAX_ATTEMPTS,
                )
                time.sleep(wait)
                continue

            if response.status_code == 401:
                raise ImmichError(
                    "401 from Immich - the API key is missing, wrong, or revoked. "
                    "Check immich.api_key in config.yaml (or $IMMICH_API_KEY)."
                )
            if response.status_code >= 400:
                raise ImmichError(
                    f"{method} {path} failed: {response.status_code} "
                    f"{response.text[:300]}"
                )
            return response

        raise ImmichError(f"{method} {path} failed after {_MAX_ATTEMPTS} attempts: {last}")

    def _get_json(self, path: str, **params: Any) -> Any:
        clean = {k: v for k, v in params.items() if v is not None}
        return self._request("GET", path, params=clean).json()

    # ------------------------------------------------------------------ people

    def iter_people(self, with_hidden: bool = False, size: int = 500) -> Iterator[PersonSummary]:
        """Yield every person. Envelope is {people, total, hidden, hasNextPage?}."""
        page = 1
        seen = 0
        while True:
            payload = self._get_json(
                "/api/people", page=page, size=size, withHidden=with_hidden
            )
            batch = payload.get("people") or []
            if not batch:
                return
            for raw in batch:
                seen += 1
                yield PersonSummary(
                    person_id=raw["id"],
                    name=raw.get("name") or "",
                    birth_date=raw.get("birthDate"),
                    is_hidden=bool(raw.get("isHidden")),
                )
            # hasNextPage is optional in the spec, so fall back to counting.
            if "hasNextPage" in payload:
                if not payload["hasNextPage"]:
                    return
            elif seen >= int(payload.get("total") or 0):
                return
            page += 1

    # ------------------------------------------------------------------ assets

    def iter_person_assets(
        self, person_id: str, size: int = 250
    ) -> Iterator[Asset]:
        """Yield every asset containing `person_id`, newest first.

        Prefers filter.personIds + cursor paging; falls back to the deprecated
        top-level personIds + page if the server rejects the modern shape.
        """
        if self._use_modern_filter is None:
            self._use_modern_filter = self._supports_modern_filter(person_id)

        if self._use_modern_filter:
            yield from self._iter_assets_cursor(person_id, size)
        else:
            yield from self._iter_assets_paged(person_id, size)

    def _supports_modern_filter(self, person_id: str) -> bool:
        body = {
            "filter": {"personIds": {"any": [person_id]}},
            "size": 1,
            "withExif": True,
        }
        try:
            self._request("POST", "/api/search/metadata", json=body)
        except ImmichError as exc:
            log.warning(
                "server rejected filter.personIds (%s) - falling back to the "
                "deprecated top-level personIds",
                exc,
            )
            return False
        return True

    def _search(self, body: dict[str, Any]) -> dict[str, Any]:
        payload = self._request("POST", "/api/search/metadata", json=body).json()
        # Root carries both "albums" and "assets"; only assets matter here.
        return payload.get("assets") or {}

    def _iter_assets_cursor(self, person_id: str, size: int) -> Iterator[Asset]:
        cursor: str | None = None
        while True:
            body: dict[str, Any] = {
                "filter": {"personIds": {"any": [person_id]}},
                "size": size,
                "withExif": True,
            }
            if cursor:
                body["cursor"] = cursor
            assets = self._search(body)
            items = assets.get("items") or []
            for raw in items:
                yield Asset.from_api(raw)
            cursor = assets.get("nextCursor")
            if not cursor or not items:
                return

    def _iter_assets_paged(self, person_id: str, size: int) -> Iterator[Asset]:
        page = 1
        while True:
            assets = self._search(
                {
                    "personIds": [person_id],
                    "page": page,
                    "size": size,
                    "withExif": True,
                }
            )
            items = assets.get("items") or []
            for raw in items:
                yield Asset.from_api(raw)
            if not assets.get("nextPage") or not items:
                return
            page += 1

    # ------------------------------------------------------------------- faces

    def get_faces(self, asset_id: str) -> list[Face]:
        """Faces detected on one asset, with bounding boxes.

        GET /api/faces?id=<assetId>. The spec labels the parameter a "Face ID"
        while describing the endpoint as returning an asset's faces; in practice
        it takes the asset id. An empty list for an asset Immich shows people on
        means that assumption is wrong on this server - see probe().
        """
        payload = self._get_json("/api/faces", id=asset_id)
        if not isinstance(payload, list):
            raise ImmichError(
                f"GET /api/faces?id={asset_id} returned {type(payload).__name__}, "
                f"expected a list of AssetFaceResponseDto"
            )
        return [Face.from_api(raw) for raw in payload]

    # -------------------------------------------------------------------- bytes

    def get_image(self, asset_id: str, size: str = "preview") -> bytes:
        """Raw image bytes for an asset rendition.

        size is an AssetMediaSize: thumbnail | preview | fullsize | original.
        "original" on this endpoint is deprecated, so route it to /original.
        """
        if size == "original":
            return self._request("GET", f"/api/assets/{asset_id}/original").content
        return self._request(
            "GET", f"/api/assets/{asset_id}/thumbnail", params={"size": size}
        ).content

    def get_asset(self, asset_id: str) -> dict[str, Any]:
        """Full asset detail. Only needed for spot checks; search returns enough."""
        return self._get_json(f"/api/assets/{asset_id}")

    # -------------------------------------------------------------------- probe

    def probe(self, person_id: str) -> dict[str, Any]:
        """Verify the live server against this client's assumptions.

        Returns a dict of findings rather than raising, so a single run reports
        everything that is wrong instead of only the first thing.
        """
        findings: dict[str, Any] = {}

        try:
            payload = self._get_json("/api/server/about")
            findings["server_version"] = payload.get("version", "unknown")
        except ImmichError as exc:
            findings["server_version"] = f"unavailable ({exc})"

        findings["modern_filter_accepted"] = self._supports_modern_filter(person_id)

        try:
            assets = list(self._iter_person_assets_limited(person_id, limit=3))
            findings["person_assets_sampled"] = len(assets)
            findings["paging_mode"] = (
                "cursor" if self._use_modern_filter else "page (deprecated)"
            )
        except ImmichError as exc:
            findings["person_assets_sampled"] = f"failed ({exc})"
            return findings

        if not assets:
            findings["faces_endpoint"] = "no assets to test against"
            return findings

        asset = assets[0]
        try:
            faces = self.get_faces(asset.asset_id)
        except ImmichError as exc:
            findings["faces_endpoint"] = f"failed ({exc})"
            return findings

        findings["faces_returned"] = len(faces)
        findings["faces_id_param_is_asset_id"] = len(faces) > 0
        if faces:
            face = faces[0]
            findings["face_frame"] = f"{face.image_width}x{face.image_height}"
            findings["face_box"] = f"({face.x1},{face.y1})-({face.x2},{face.y2})"
            findings["box_within_frame"] = (
                0 <= face.x1 < face.x2 <= face.image_width
                and 0 <= face.y1 < face.y2 <= face.image_height
            )
            findings["box_looks_like_pixels_not_normalised"] = (
                face.x2 > 1 or face.y2 > 1
            )
            findings["face_has_person_id"] = face.person_id is not None
            findings["matches_requested_person"] = any(
                f.person_id == person_id for f in faces
            )

        try:
            data = self.get_image(asset.asset_id, "preview")
            findings["preview_bytes"] = len(data)
            if faces:
                from io import BytesIO

                from PIL import Image

                with Image.open(BytesIO(data)) as img:
                    findings["preview_size"] = f"{img.width}x{img.height}"
                    findings["preview_matches_face_frame"] = (
                        img.width == faces[0].image_width
                        and img.height == faces[0].image_height
                    )
        except Exception as exc:  # noqa: BLE001 - probe reports, never raises
            findings["preview_bytes"] = f"failed ({exc})"

        return findings

    def _iter_person_assets_limited(
        self, person_id: str, limit: int
    ) -> Iterator[Asset]:
        for i, asset in enumerate(self.iter_person_assets(person_id)):
            if i >= limit:
                return
            yield asset
