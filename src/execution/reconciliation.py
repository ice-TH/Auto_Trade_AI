import hashlib
from typing import Set, Dict, Any, List
from datetime import datetime

class OrderReconciler:
    def __init__(self):
        # In-memory idempotency hash registry
        self._executed_order_hashes: Set[str] = set()

    def generate_order_hash(self, symbol: str, timeframe: str, bar_time: str, direction: str) -> str:
        payload = f"{symbol}_{timeframe}_{bar_time}_{direction.upper()}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def is_order_duplicate(self, symbol: str, timeframe: str, bar_time: str, direction: str) -> bool:
        order_hash = self.generate_order_hash(symbol, timeframe, bar_time, direction)
        return order_hash in self._executed_order_hashes

    def record_order_execution(self, symbol: str, timeframe: str, bar_time: str, direction: str):
        order_hash = self.generate_order_hash(symbol, timeframe, bar_time, direction)
        self._executed_order_hashes.add(order_hash)

    def reconcile_startup(self, mt5_positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Reconcile terminal state on application startup to ensure consistency.
        """
        active_tickets = [p["ticket"] for p in mt5_positions]
        return {
            "status": "RECONCILED",
            "active_mt5_tickets": active_tickets,
            "count": len(active_tickets),
            "message": f"Startup reconciliation complete. Found {len(active_tickets)} active positions in MT5."
        }

order_reconciler = OrderReconciler()
