"""P3 - Scheduler, Channels & Simulator (hand-off): priority, channel order, frequency cap, expiry, FarmerChat flow ids."""
from .handoff import build_handoff, priority, channel_order, CapLedger, OptOutList, Admit
from .clock import SimClock, Season
from .broadcast import (
    Broadcaster, Broadcast, quality_failures, passes_quality, within_send_hours,
)
from .season import SeasonScheduler, StepResult
from .frequency import (
    FrequencyMonitor, FrequencyPeak, FrequencyScheduler, RankedHandoff,
    SeasonStageContext, ClimateContext, frequency_config, topic_of,
)
