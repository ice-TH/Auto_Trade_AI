from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any

class PlanStatus(str, Enum):
    WAITING_CONDITIONS = "WAITING_CONDITIONS"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    WAITING_USER_CONFIRM = "WAITING_USER_CONFIRM"
    ORDER_PLACED = "ORDER_PLACED"
    POSITION_OPEN = "POSITION_OPEN"
    POSITION_CLOSED = "POSITION_CLOSED"
    REJECTED_NO_TRADE = "REJECTED_NO_TRADE"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"

@dataclass
class TradingPlan:
    plan_id: str
    symbol: str
    strategy_name: str = "DAY_SUPPORT_BOUNCE_V1"
    strategy_version: str = "1.0.0"
    direction: str = "LONG" # "LONG" (Default) or "SHORT"
    status: PlanStatus = PlanStatus.WAITING_CONDITIONS
    
    # Zones & Context
    day_zone_id: Optional[str] = None
    day_zone_type: str = "SUPPORT"
    day_zone_low: float = 0.0
    day_zone_high: float = 0.0
    week_trend: str = "NEUTRAL" # BULLISH, NEUTRAL, BEARISH
    
    # Prices & R:R
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    headroom_to_resistance: float = 0.0
    risk_reward_ratio: float = 0.0
    
    # Money Management
    shares: int = 0
    lot_size: float = 0.0
    risk_thb: float = 0.0
    notional_thb: float = 0.0
    effective_leverage: float = 0.0
    
    # Journal & Non-entry reason
    rejection_reason: Optional[str] = None
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confirmed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "symbol": self.symbol,
            "strategy_name": self.strategy_name,
            "strategy_version": self.strategy_version,
            "direction": self.direction,
            "status": self.status.value,
            "day_zone_id": self.day_zone_id,
            "day_zone_type": self.day_zone_type,
            "day_zone_range": f"${self.day_zone_low:.2f} - ${self.day_zone_high:.2f}",
            "week_trend": self.week_trend,
            "entry_price": round(self.entry_price, 2),
            "stop_loss": round(self.stop_loss, 2),
            "take_profit": round(self.take_profit, 2),
            "sl_distance": round(abs(self.entry_price - self.stop_loss), 2),
            "tp_distance": round(abs(self.take_profit - self.entry_price), 2),
            "headroom_to_resistance": round(self.headroom_to_resistance, 2),
            "risk_reward_ratio": round(self.risk_reward_ratio, 2),
            "shares": self.shares,
            "lot_size": self.lot_size,
            "risk_thb": round(self.risk_thb, 2),
            "notional_thb": round(self.notional_thb, 2),
            "effective_leverage": round(self.effective_leverage, 2),
            "rejection_reason": self.rejection_reason,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
        }
