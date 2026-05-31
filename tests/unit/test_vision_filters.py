# PROMPT:
# BI staff filter unit tests — customer metric event exclusion rules.
#
# CHANGES MADE:
# - Validates staff class_label and staff_only zone_type are excluded from customer BI.

"""Unit tests for customer metric event filters."""

from app.domain.vision.filters import is_customer_metric_event, is_customer_session


def test_staff_class_label_excluded() -> None:
    assert is_customer_metric_event({"class_label": "staff", "zone_type": "browse"}) is False


def test_staff_only_zone_excluded() -> None:
    assert is_customer_metric_event({"zone_type": "staff_only"}) is False


def test_visitor_event_included() -> None:
    assert is_customer_metric_event({"class_label": "visitor", "zone_type": "browse"}) is True


def test_staff_session_excluded() -> None:
    assert is_customer_session({"staff": True}) is False


def test_visitor_session_included() -> None:
    assert is_customer_session({"store_entry": True}) is True
