# Architecture

## Product

**Location Answerability Auditor** is a brand-agnostic pipeline:

```
Sitemap / URL list
  → Crawler (cached, rate-limited)
  → RawExtractor → RawPageData
  → Schema extractor + LocationNormalizer → LocationEntity
  → Source adapters (webpage, schema, yext stub)
  → Answerability matrix
  → Deterministic scoring
  → Recommendations + portfolio aggregation
  → Dashboard + CSV/JSON/HTML exports
```

## Package layout

```
src/aeo_auditor/
  models/            Pydantic data models
  sitemap/           Sitemap index/urlset discovery
  crawler/           httpx fetch, disk cache, resume journal
  parser/            HTML → RawPageData
  schema/            JSON-LD graph walk
  entities/          Normalization + conflict detection
  sources/           SourceAdapter protocol (webpage/schema/yext)
  answers/           Question ontology evaluation
  scoring/           Configurable 0–100 score
  recommendations/   HIGH/MEDIUM/LOW actions
  portfolio/         Cross-location rollups
  reporting/         Exporters
  llm/               Optional hooks (off by default)
  api/               FastAPI + Jinja dashboard
  cli.py             Typer CLI
  pipeline.py        Orchestration
clients/<slug>/      Per-brand configuration only
config/              Global questions, scoring, crawl
```

## Separation of concerns

| Concern | Module |
|---------|--------|
| Fetching | `crawler` |
| Parsing | `parser`, `schema` |
| Business normalization | `entities` |
| Client-specific settings | `clients/*` |
| Deterministic scoring | `scoring` + YAML |
| Generative assistance | `llm` (optional) |

Dutch Bros lives only under `clients/dutch-bros/`. Core code must not encode Dutch Bros business rules.

## Data contracts

- Unknown facts stay `null` — never inferred from images or weak implication.
- Every finding stores `evidence` + `source` when available.
- Recommendations reference related checks / question IDs.

## UI

FastAPI serves:

1. Portfolio overview (averages, distribution, systemic opportunities)
2. Sortable location table
3. Location detail (scorecard, facts, conflicts, answer matrix, recommendations)

CLI writes `output/run.json`; the UI reads the latest run.
