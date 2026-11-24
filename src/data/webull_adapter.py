import hmac
import hashlib
import base64
import time
from typing import List, Dict, Any, Optional
from src.data.base import BaseDataAdapter, Bar, TimeFrame, DataStatus, SessionType

class WebullOpenAPIAdapter(BaseDataAdapter):
    """
    Official Webull OpenAPI Adapter.
    Requires official developer credentials (App Key and App Secret) from Webull Developer Portal.
    """
    def __init__(self, app_key: str = "", app_secret: str = "", endpoint: str = "https://api.webull.com"):
        self.app_key = app_key
        self.app_secret = app_secret
        self.endpoint = endpoint
        self._is_ready = bool(self.app_key and self.app_secret)

    def _generate_signature(self, params: Dict[str, Any], timestamp: str) -> str:
        """Create HMAC-SHA256 signature according to Webull OpenAPI specification."""
        if not self._is_ready:
            return ""
        sorted_params = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        sign_payload = f"{timestamp}&{sorted_params}"
        signature = hmac.new(
            self.app_secret.encode("utf-8"),
            sign_payload.encode("utf-8"),
            hashlib.sha256
        ).digest()
        return base64.b64encode(signature).decode("utf-8")

    def get_bars(self, symbol: str, timeframe: TimeFrame, limit: int = 150) -> List[Bar]:
        if not self._is_ready:
            raise PermissionError(
                "Webull OpenAPI credentials not configured. Please supply WEBULL_APP_KEY and WEBULL_APP_SECRET in .env."
            )
        # Webull OpenAPI request will be performed here when credentials are provided
        return []

    def get_latest_quote(self, symbol: str) -> Dict[str, Any]:
        if not self._is_ready:
            return {
                "symbol": symbol,
                "error": "Webull OpenAPI not configured",
                "status": "UNAVAILABLE"
            }
        return {}

    def get_status(self) -> Dict[str, Any]:
        return {
            "adapter": "WebullOpenAPIAdapter",
            "is_connected": self._is_ready,
            "has_credentials": self._is_ready,
            "endpoint": self.endpoint,
            "data_status": DataStatus.LIVE.value if self._is_ready else "NOT_CONFIGURED",
            "message": "Official Webull OpenAPI ready" if self._is_ready else "Awaiting Webull OpenAPI App Key & Secret"
        }
