# Yext Integration Plan (Future)

## MVP status

Yext access is **not required**. The MVP ships a `YextSource` adapter stub and a `LocationEntityComparator` interface. No credentials are requested, invented, or committed.

## Intended architecture

```
Yext facts ──┐
             ├──► LocationEntityComparator ──► gaps & recommendations
Website  ────┤
Schema   ────┘
```

Adapters implement:

```python
class SourceAdapter(Protocol):
    name: str
    def fetch_facts(self, location_id: str | None, entity: LocationEntity | None = None) -> dict:
        ...
```

Implemented today:

- `WebpageSource` — from visible extraction  
- `SchemaSource` — from JSON-LD  
- `YextSource` — stub (`enabled=False` returns `{}`; enabled raises `NotImplementedError`)

## Example future output

```
ATTRIBUTE: drive_thru
Yext: true
Visible page: not found
Schema: not found
RESULT: Known internally but not exposed publicly
RECOMMENDATION: Expose this service attribute in visible content and appropriate structured data
PRIORITY: HIGH
```

## What becomes possible with legitimate Yext access

- Compare official store of record vs public website vs schema
- Flag “known internally but not exposed” gaps at portfolio scale
- Validate hours/phone/address drift before answer engines pick a source
- Prioritize HIGH recommendations where Yext has the fact but pages do not

## Implementation notes (when credentials exist)

1. Read API key / account from environment only (`YEXT_API_KEY`, etc.)
2. Map Yext entity IDs to `LocationEntity.location_id` / URL
3. Normalize Yext fields into the same attribute keys as webpage/schema
4. Never overwrite website evidence — keep per-source values
5. Extend exports with `source_comparison.csv`
