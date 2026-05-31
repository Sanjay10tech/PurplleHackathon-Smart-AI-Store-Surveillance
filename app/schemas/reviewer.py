from typing import Any

from pydantic import BaseModel, Field


class ReviewerCheckItem(BaseModel):
    label: str
    passed: bool
    evidence: str


class ReviewerSnapshotResponse(BaseModel):
    generated_at: str
    demo_store_id: str
    api_key_hint: str
    reviewer_mode: bool = True
    period_start: str
    period_end: str
    dashboard_url: str
    docs_url: str
    api_guide_url: str = "/reviewer/api"
    checks_passed: int
    checks_total: int
    ready_for_review: bool
    checks: list[ReviewerCheckItem]
    summary: dict[str, Any]
    endpoints: dict[str, str]
    api_base_url: str = "http://localhost:8000"
    reviewer_proof: dict[str, Any]


class ReviewerApiRoute(BaseModel):
    name: str
    method: str
    path: str
    auth_required: bool
    description: str
    curl: str


class ReviewerApiGuideResponse(BaseModel):
    reviewer_mode: bool
    api_base_url: str
    demo_store_id: str
    api_key: str
    auth_header: str = "X-API-Key"
    auth_example: dict[str, str]
    quick_start: list[str]
    routes: list[ReviewerApiRoute]
    notes: list[str]
