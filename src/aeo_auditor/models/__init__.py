"""Pydantic models for raw pages, entities, findings, scores, and reports."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ConflictStatus(str, Enum):
    MATCH = "MATCH"
    CONFLICT = "CONFLICT"
    MISSING = "MISSING"


class Priority(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Address(BaseModel):
    street: str | None = None
    city: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country: str | None = None
    neighborhood: str | None = None

    @property
    def full(self) -> str | None:
        parts = [
            self.street,
            ", ".join(p for p in [self.city, self.region] if p) or None,
            self.postal_code,
            self.country,
        ]
        joined = " ".join(p for p in parts if p)
        return joined or None


class Geo(BaseModel):
    latitude: float | None = None
    longitude: float | None = None


class Services(BaseModel):
    drive_thru: bool | None = None
    walk_up: bool | None = None
    delivery: bool | None = None
    order_ahead: bool | None = None
    pickup: bool | None = None


class Amenities(BaseModel):
    parking: bool | None = None
    wifi: bool | None = None
    indoor_seating: bool | None = None
    outdoor_seating: bool | None = None
    wheelchair_accessible: bool | None = None


class LocalContent(BaseModel):
    description: str | None = None
    word_count: int = 0
    unique_content_score: float | None = None


class BreadcrumbItem(BaseModel):
    name: str | None = None
    url: str | None = None
    position: int | None = None


class FAQItem(BaseModel):
    question: str
    answer: str
    source: str = "visible_content"


class NearbyLocation(BaseModel):
    name: str | None = None
    url: str | None = None
    address: str | None = None


class SchemaEntity(BaseModel):
    types: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)
    valid: bool = True
    parse_error: str | None = None


class EvidenceFinding(BaseModel):
    check: str
    result: Any = None
    evidence: str | None = None
    source: str | None = None
    severity: str | None = None


class Conflict(BaseModel):
    attribute: str
    visible_value: str | None = None
    structured_value: str | None = None
    status: ConflictStatus
    evidence: str | None = None


class QuestionResult(BaseModel):
    question_id: str
    category: str
    question: str
    fact_known: bool = False
    visible_on_page: bool = False
    structured: bool = False
    explicitly_answered: bool = False
    confidence: float = 0.0
    evidence: str | None = None
    source: str | None = None

    @property
    def known(self) -> bool:
        return self.fact_known

    @property
    def exposed(self) -> bool:
        return self.visible_on_page

    @property
    def answerable(self) -> bool:
        return self.explicitly_answered


class Recommendation(BaseModel):
    priority: Priority
    title: str
    message: str
    related_checks: list[str] = Field(default_factory=list)
    evidence: str | None = None


class CategoryScore(BaseModel):
    name: str
    score: float
    max_points: float
    checks: list[EvidenceFinding] = Field(default_factory=list)


class Scorecard(BaseModel):
    total: float = 0.0
    max_total: float = 100.0
    discovery: CategoryScore
    entity_clarity: CategoryScore
    structured_data: CategoryScore
    answer_coverage: CategoryScore
    local_uniqueness: CategoryScore
    band: str = "Weak"

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "max_total": self.max_total,
            "band": self.band,
            "discovery": self.discovery.score,
            "entity_clarity": self.entity_clarity.score,
            "structured_data": self.structured_data.score,
            "answer_coverage": self.answer_coverage.score,
            "local_uniqueness": self.local_uniqueness.score,
        }


class OpenGraphData(BaseModel):
    title: str | None = None
    description: str | None = None
    url: str | None = None
    image: str | None = None
    type: str | None = None
    site_name: str | None = None


class RawPageData(BaseModel):
    url: str
    final_url: str | None = None
    status_code: int | None = None
    redirect_chain: list[str] = Field(default_factory=list)
    canonical: str | None = None
    robots_meta: str | None = None
    title: str | None = None
    meta_description: str | None = None
    h1: list[str] = Field(default_factory=list)
    headings: list[dict[str, str]] = Field(default_factory=list)
    visible_text: str = ""
    links: list[dict[str, str]] = Field(default_factory=list)
    breadcrumbs: list[BreadcrumbItem] = Field(default_factory=list)
    faqs: list[FAQItem] = Field(default_factory=list)
    json_ld_blocks: list[Any] = Field(default_factory=list)
    json_ld_raw: list[str] = Field(default_factory=list)
    json_ld_errors: list[str] = Field(default_factory=list)
    open_graph: OpenGraphData = Field(default_factory=OpenGraphData)
    html_excerpt: str | None = None
    fetched_from_cache: bool = False
    error: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)


class LocationEntity(BaseModel):
    client: str = ""
    location_id: str | None = None
    location_name: str | None = None
    url: str = ""
    canonical_url: str | None = None
    status_code: int | None = None
    indexable: bool | None = None
    in_sitemap: bool | None = None
    address: Address = Field(default_factory=Address)
    geo: Geo = Field(default_factory=Geo)
    phone: str | None = None
    hours: dict[str, Any] = Field(default_factory=dict)
    services: Services = Field(default_factory=Services)
    amenities: Amenities = Field(default_factory=Amenities)
    payment_methods: list[str] = Field(default_factory=list)
    menu_features: list[str] = Field(default_factory=list)
    breadcrumbs: list[BreadcrumbItem] = Field(default_factory=list)
    nearby_locations: list[NearbyLocation] = Field(default_factory=list)
    nearby_landmarks: list[str] = Field(default_factory=list)
    visible_faqs: list[FAQItem] = Field(default_factory=list)
    schema_entities: list[SchemaEntity] = Field(default_factory=list)
    schema_types: list[str] = Field(default_factory=list)
    visible_facts: dict[str, Any] = Field(default_factory=dict)
    structured_facts: dict[str, Any] = Field(default_factory=dict)
    answerable_questions: dict[str, QuestionResult] = Field(default_factory=dict)
    local_content: LocalContent = Field(default_factory=LocalContent)
    title: str | None = None
    meta_description: str | None = None
    findings: list[EvidenceFinding] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    scorecard: Scorecard | None = None
    strengths: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    missing_answers: list[str] = Field(default_factory=list)
    schema_opportunities: list[str] = Field(default_factory=list)


class LocationReport(BaseModel):
    entity: LocationEntity
    question_results: list[QuestionResult] = Field(default_factory=list)


class PortfolioSummary(BaseModel):
    client: str = ""
    locations_discovered: int = 0
    locations_crawled: int = 0
    average_aeo_score: float = 0.0
    category_averages: dict[str, float] = Field(default_factory=dict)
    score_distribution: dict[str, int] = Field(default_factory=dict)
    systemic_opportunities: list[str] = Field(default_factory=list)
    cross_location_stats: dict[str, Any] = Field(default_factory=dict)
    locations: list[LocationEntity] = Field(default_factory=list)
