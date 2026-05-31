ZONE_ENTER_EVENT_TYPE = "vision.zone.entered"
ZONE_EXIT_EVENT_TYPE = "vision.zone.exited"
FEED_EVENT_TYPES = ("vision.frame.processed", ZONE_ENTER_EVENT_TYPE)

DEFAULT_QUEUE_ZONE_TYPES = frozenset({"checkout", "billing_queue", "queue", "billing"})
