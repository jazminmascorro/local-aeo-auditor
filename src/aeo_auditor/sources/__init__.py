"""Source adapters: webpage, schema, and future Yext."""

from __future__ import annotations

from typing import Any, Protocol

from aeo_auditor.models import LocationEntity


class SourceAdapter(Protocol):
    name: str

    def fetch_facts(self, location_id: str | None, entity: LocationEntity | None = None) -> dict[str, Any]:
        """Return attribute → value map for a location. Unknown keys omitted; never invent."""
        ...


class WebpageSource:
    name = "webpage"

    def fetch_facts(self, location_id: str | None, entity: LocationEntity | None = None) -> dict[str, Any]:
        if entity is None:
            return {}
        return dict(entity.visible_facts)


class SchemaSource:
    name = "schema"

    def fetch_facts(self, location_id: str | None, entity: LocationEntity | None = None) -> dict[str, Any]:
        if entity is None:
            return {}
        return dict(entity.structured_facts)


class YextSource:
    """Stub for future Yext Knowledge Graph integration. No credentials used."""

    name = "yext"

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    def fetch_facts(self, location_id: str | None, entity: LocationEntity | None = None) -> dict[str, Any]:
        if not self.enabled:
            return {}
        raise NotImplementedError(
            "Yext adapter is not implemented in the MVP. "
            "See YEXT-INTEGRATION-PLAN.md for the intended comparator flow."
        )


class LocationEntityComparator:
    """Compare facts across sources (webpage, schema, future Yext)."""

    def __init__(self, sources: list[SourceAdapter] | None = None) -> None:
        self.sources = sources or [WebpageSource(), SchemaSource(), YextSource(enabled=False)]

    def compare_attribute(self, attribute: str, entity: LocationEntity) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for source in self.sources:
            try:
                facts = source.fetch_facts(entity.location_id, entity)
            except NotImplementedError:
                values[source.name] = None
                continue
            values[source.name] = facts.get(attribute)
        return {
            "attribute": attribute,
            "values": values,
        }
