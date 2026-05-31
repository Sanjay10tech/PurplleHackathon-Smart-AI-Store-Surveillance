# PROMPT:
# Test business story labels exported in funnel meta helpers.
#
# CHANGES MADE:
# - stage_business_label and business_story_meta coverage.

from app.domain.funnel.stages import (
    FunnelStageName,
    business_story_meta,
    stage_business_label,
)


def test_stage_business_labels() -> None:
    assert stage_business_label(FunnelStageName.ENTRY) == "Visitor"
    assert stage_business_label("ZONE_VISIT") == "Zone Visit"
    assert stage_business_label("BILLING_QUEUE") == "Billing Queue"
    assert stage_business_label("PURCHASE") == "Purchase"


def test_business_story_meta_structure() -> None:
    meta = business_story_meta()
    assert meta["stage_order"] == ["ENTRY", "ZONE_VISIT", "BILLING_QUEUE", "PURCHASE"]
    assert meta["stage_labels"]["ENTRY"] == "Visitor"
    assert len(meta["business_story"]) == 4
    assert "conversion_formula" in meta
    assert "end_to_end_conversion_formula" in meta
