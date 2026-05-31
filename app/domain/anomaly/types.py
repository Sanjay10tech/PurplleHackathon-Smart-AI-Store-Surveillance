from enum import StrEnum


class AnomalyType(StrEnum):
    QUEUE_SPIKE = "QUEUE_SPIKE"
    CONVERSION_DROP = "CONVERSION_DROP"
    DEAD_ZONE = "DEAD_ZONE"
    STALE_FEED = "STALE_FEED"


class AnomalySeverity(StrEnum):
    INFO = "INFO"
    WARN = "WARN"
    CRITICAL = "CRITICAL"
