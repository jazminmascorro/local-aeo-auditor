# Question Ontology

Questions live in configuration, not application hard-coding:

- Global: [`config/questions.yaml`](config/questions.yaml)
- Optional per-client overrides / subset via `question_sets` in client `config.yaml`

## Categories

1. **Hours** — open/close, open now, Sunday, holiday hours  
2. **Location** — where, address, neighborhood, landmarks, closest store  
3. **Services** — drive-thru, walk-up, order ahead, pickup, delivery  
4. **Amenities** — indoor/outdoor seating, parking, Wi-Fi, accessibility  
5. **Payments** — cash, cards, Apple Pay, methods list  
6. **Menu** — products, dietary options, cold brew, customization  
7. **Ordering** — online, app, schedule, pickup  

## Answerability states

For each question the auditor records:

| Field | Meaning |
|-------|---------|
| `fact_known` | A factual value can be extracted (KNOWN) |
| `visible_on_page` | Present in visible crawlable content (EXPOSED) |
| `structured` | Present in machine-readable schema (STRUCTURED) |
| `explicitly_answered` | Enough explicit evidence for a direct answer (ANSWERABLE) |

Implied-only signals (e.g., a photo of a drive-thru without text) leave the attribute `null` / unanswered.

## Extending

Add questions to YAML with `id`, `question`, optional `fact_keys`, and `keywords`. Clients select categories with `question_sets` without changing core code.
