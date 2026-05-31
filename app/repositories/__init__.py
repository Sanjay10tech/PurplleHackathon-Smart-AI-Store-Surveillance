"""Persistence layer — repositories and CRUD adapters."""

from app.repositories.anomaly_repository import AnomalyRepository
from app.repositories.crud.base import CRUDRepository
from app.repositories.event_repository import EventRepository
from app.repositories.funnel_repository import FunnelRepository
from app.repositories.health_repository import HealthRepository
from app.repositories.heatmap_repository import HeatmapRepository
from app.repositories.interfaces import (
    AnomalyRepositoryProtocol,
    EventRepositoryProtocol,
    FunnelRepositoryProtocol,
    HealthRepositoryProtocol,
    HeatmapRepositoryProtocol,
    StoreMetricRepositoryProtocol,
    StoreRepositoryProtocol,
    TransactionRepositoryProtocol,
    VisitSessionRepositoryProtocol,
)
from app.repositories.store_metric_repository import StoreMetricRepository
from app.repositories.store_repository import StoreRepository
from app.repositories.transaction_repository import TransactionRepository
from app.repositories.visit_session_repository import VisitSessionRepository

__all__ = [
    "AnomalyRepository",
    "AnomalyRepositoryProtocol",
    "CRUDRepository",
    "EventRepository",
    "EventRepositoryProtocol",
    "FunnelRepository",
    "FunnelRepositoryProtocol",
    "HealthRepository",
    "HealthRepositoryProtocol",
    "HeatmapRepository",
    "HeatmapRepositoryProtocol",
    "StoreMetricRepository",
    "StoreMetricRepositoryProtocol",
    "StoreRepository",
    "StoreRepositoryProtocol",
    "TransactionRepository",
    "TransactionRepositoryProtocol",
    "VisitSessionRepository",
    "VisitSessionRepositoryProtocol",
]
