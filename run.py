"""
AutoTrade - US Equities Analysis & MT5 CFD Trading System (Local Web Dashboard)
Entry point to run the application server.
"""
import uvicorn
from config.settings import settings

if __name__ == "__main__":
    import socket
    port = settings.app_port
    # Test if port is available; if busy due to lingering socket, fallback to 8001
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex((settings.app_host, port)) == 0:
            port = 8001

    print("=" * 60)
    print("  AUTOTRADE SYSTEM - US EQUITIES ANALYSIS & MT5 CFD DASHBOARD")
    print("  Theme:          Modern Fintech Light (Dime Style)")
    print("=" * 60)
    print(f"  Mode:           {settings.trading_mode} (Execution: {settings.execution_enabled})")
    print(f"  Data Source:    {settings.data_source}")
    print(f"  Capital:        {settings.base_capital_thb:.2f} THB")
    print(f"  Max Leverage:   1:{settings.max_leverage}")
    print(f"  Local URL:      http://{settings.app_host}:{port}")
    print("=" * 60)
    print("Starting server... Press Ctrl+C to stop.")
    uvicorn.run(
        "src.web.app:app",
        host=settings.app_host,
        port=port,
        reload=True
    )
