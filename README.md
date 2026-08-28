# Location Answerability Auditor

Measure how clearly search engines and AI systems can understand and answer questions about every business location.

This tool evaluates multi-location business pages for technical discoverability, local entity clarity, structured data quality, answer-engine readiness, and location uniqueness. It produces deterministic AEO readiness scores, evidence-backed recommendations, portfolio dashboards, and CSV/JSON exports.

**Positioning:** Improves the completeness, clarity, consistency, and machine accessibility of location information. It does **not** guarantee AI citations.

Dutch Bros is included as a **demonstration client configuration** only. The core engine is brand-agnostic.

## Why AEO matters for multi-location brands

Answer engines and traditional search systems need explicit, consistent, machine-readable facts per location (hours, address, services, amenities, FAQs). Template pages that bury or omit those facts create portfolio-wide answer gaps. This auditor surfaces page-level and systemic opportunities.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Optional environment variables: see [`.env.example`](.env.example). LLM assistance is optional and disabled by default.

## Development commands

```bash
# Unit tests (fixtures only — no live crawl required)
pytest

# List client configs
python -m aeo_auditor.cli clients

# Single-location mode
python -m aeo_auditor.cli analyze --url "https://www.dutchbros.com/locations/az/phoenix/2961-e.-bell-rd." --client dutch-bros -o output

# Demo batch (3–5 Dutch Bros pages from clients/dutch-bros/demo_urls.txt)
python -m aeo_auditor.cli analyze --client dutch-bros --demo --limit 5 -o output

# Sitemap mode (uses client sitemap; falls back to demo URLs if empty)
python -m aeo_auditor.cli analyze --client dutch-bros --sitemap "https://www.dutchbros.com/locations/sitemap.xml" --limit 5 -o output

# Dashboard
python -m aeo_auditor.cli serve --host 0.0.0.0 --port 8000
```

## Output structure

Writes under `output/`:

| File | Contents |
|------|----------|
| `locations.csv` | Core location fields |
| `location_scores.csv` | Category scores |
| `answer_coverage.csv` | Question matrix |
| `schema_findings.csv` | Schema inventory |
| `issues.csv` | Conflicts / opportunities |
| `recommendations.csv` | Prioritized actions |
| `summary.json` | Portfolio rollup |
| `run.json` | Full run payload for the UI |
| `aeo-report.html` | Human-readable report |

Fetched HTML is cached under `.cache/pages/` to avoid hammering production sites.

## Configuration

- [`config/questions.yaml`](config/questions.yaml) — question ontology
- [`config/scoring.yaml`](config/scoring.yaml) — scoring weights
- [`config/crawl.yaml`](config/crawl.yaml) — crawl safety defaults
- [`clients/dutch-bros/`](clients/dutch-bros/) — demo client config + demo URLs

The app runs without a client config; client config improves filtering and expected schema types.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md), [SCORING-METHODOLOGY.md](SCORING-METHODOLOGY.md), [QUESTION-ONTOLOGY.md](QUESTION-ONTOLOGY.md), and [YEXT-INTEGRATION-PLAN.md](YEXT-INTEGRATION-PLAN.md).

## Limitations

- Deterministic extractors may miss facts only present in images, maps widgets, or heavy client-side rendering.
- Empty or blocked sitemaps require `--url`, `--urls-file`, or client `demo_urls.txt`.
- Yext comparison is stubbed for MVP (no credentials).
- LLM helpers are optional; default path never invents attributes.
- Full-network crawls should use conservative `--limit`, delay, and concurrency settings.

## License

Proprietary diagnostic prototype — scoring methodology is not an industry standard metric.
