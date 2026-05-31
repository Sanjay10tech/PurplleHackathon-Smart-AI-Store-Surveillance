"""Shared filters for customer-facing BI metrics (defense in depth with pipeline emit rules)."""


def is_customer_metric_event(payload: dict) -> bool:
    """Return False for staff tracks and non-customer zone types."""
    if str(payload.get("class_label", "")).lower() == "staff":
        return False
    zone_type = str(payload.get("zone_type", "")).lower()
    if zone_type in ("staff_only", "ignore"):
        return False
    return True


def is_customer_session(metadata: dict | None) -> bool:
    """Return False when session metadata marks the track as staff."""
    if not metadata:
        return True
    return not bool(metadata.get("staff"))
