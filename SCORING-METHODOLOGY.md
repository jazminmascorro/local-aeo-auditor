# Scoring Methodology

## Important disclaimer

The **AEO Readiness Score** (0–100) is a **proprietary diagnostic framework** created for this tool.

It is **not**:

- a Google ranking factor or official metric
- an OpenAI, ChatGPT, Gemini, or Bing score
- a Yext score
- an industry-standard or accredited SEO/AEO benchmark

Treat scores as relative diagnostics for completeness, clarity, consistency, and machine accessibility of location information.

## Category weights (default)

Configured in [`config/scoring.yaml`](config/scoring.yaml):

| Category | Points | Focus |
|----------|--------|-------|
| Discovery | 20 | HTTP 200, indexability, canonical, sitemap inclusion, robots |
| Entity Clarity | 20 | Name, address, phone, geo, ID, breadcrumbs, nearby links |
| Structured Data | 20 | Valid JSON-LD, business type, address/phone/geo/hours, URL alignment |
| Answer Coverage | 20 | Share of relevant ontology questions that are explicitly answerable |
| Local Uniqueness | 20 | Location-specific copy, amenities/services, FAQs, low boilerplate |

## Answer coverage math

```
answerable / relevant_questions × 20
```

Example: 17 / 25 = 68% → 13.6 points.

## Bands

| Range | Label |
|-------|-------|
| 90–100 | Excellent |
| 80–89 | Strong |
| 70–79 | Good |
| 60–69 | Needs improvement |
| &lt;60 | Weak |

## Evidence rule

Checks that pass store evidence snippets (visible text, schema fields, HTTP metadata). Failed/unknown checks keep `result` false/null without inventing attributes.
