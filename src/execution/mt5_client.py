import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False

from config.settings import settings

logger = logging.getLogger("mt5_client")

class MT5Client:
    def __init__(self):
        self.is_connected: bool = False
        self.account_info: Dict[str, Any] = {}
        self.simulated_positions: List[Dict[str, Any]] = []
        self._sim_ticket_counter = 100000

    def connect(self) -> Dict[str, Any]:
        """
        Connect to the active MetaTrader 5 terminal on localhost.
        Adheres to user agreement: connects to already logged-in Exness Demo profile.
        """
        if not MT5_AVAILABLE:
            return {
                "connected": False,
                "error": "MetaTrader5 Python driver not available."
            }

        # Attempt to initialize with active terminal
        init_ok = mt5.initialize()
        if not init_ok and settings.mt5_path:
            init_ok = mt5.initialize(path=settings.mt5_path)

        if not init_ok:
            last_err = mt5.last_error()
            self.is_connected = False
            return {
                "connected": False,
                "error": f"MT5 terminal initialization failed: {last_err}. Please ensure MT5 Exness is open and logged into your Demo account.",
                "status": "DISCONNECTED"
            }

        # Retrieve account details
        acc = mt5.account_info()
        if acc is None:
            last_err = mt5.last_error()
            self.is_connected = False
            return {
                "connected": False,
                "error": f"Authorization required: {last_err}. Please log in to your Exness Demo account in MT5.",
                "status": "UNAUTHORIZED"
            }

        self.is_connected = True
        self.account_info = {
            "login": acc.login,
            "server": acc.server,
            "currency": acc.currency,
            "balance": acc.balance,
            "equity": acc.equity,
            "margin": acc.margin,
            "free_margin": acc.margin_free,
            "leverage": acc.leverage,
            "company": acc.company,
            "trade_allowed": acc.trade_allowed,
            "is_demo": "demo" in acc.server.lower() or "trial" in acc.server.lower(),
        }
        return {
            "connected": True,
            "status": "CONNECTED (Demo)" if self.account_info["is_demo"] else "CONNECTED",
            "account": self.account_info
        }

    def get_symbol_quote(self, symbol: str) -> Dict[str, Any]:
        """Fetch live bid, ask, and spread for a CFD symbol from MT5."""
        if not self.is_connected:
            return {"error": "MT5 not connected", "symbol": symbol}

        # Select symbol in Market Watch if not visible
        if not mt5.symbol_select(symbol, True):
            return {"error": f"Symbol {symbol} not found in MT5", "symbol": symbol}

        info = mt5.symbol_info(symbol)
        if info is None:
            return {"error": f"Failed to get info for {symbol}", "symbol": symbol}

        tick = mt5.symbol_info_tick(symbol)
        bid = tick.bid if tick else info.bid
        ask = tick.ask if tick else info.ask
        spread = round(ask - bid, 4)
        last_price = tick.last if (tick and tick.last > 0) else round((bid + ask) / 2.0, 2)

        return {
            "symbol": symbol,
            "bid": bid,
            "ask": ask,
            "last": last_price,
            "spread": spread,
            "contract_size": info.trade_contract_size,
            "min_volume": info.volume_min,
            "volume_step": info.volume_step,
            "max_volume": info.volume_max,
            "point": info.point,
            "currency": info.currency_base,
            "trade_allowed": info.trade_mode == mt5.SYMBOL_TRADE_MODE_FULL
        }

    def send_order(
        self,
        symbol: str,
        direction: str,  # "BUY" or "SELL"
        volume: float,
        sl_price: float,
        tp_price: float,
        comment: str = "AutoTrade Plan"
    ) -> Dict[str, Any]:
        """
        Send a market order with mandatory broker-side Hard Stop Loss and Take Profit.
        """
        if sl_price <= 0:
            return {
                "success": False,
                "error": "Hard Stop Loss is mandatory. Order rejected by safety guard."
            }

        # Safety Guard: Account Whitelist & Symbol Restrictions
        upper_sym = symbol.upper()
        current_login = self.account_info.get("login")
        
        # Cent Account Specific Rule: Account #160219615 is strictly restricted ONLY to XAUUSDc
        if current_login == 160219615:
            if upper_sym not in ["XAUUSDC", "XAUUSD"]:
                logger.error(f"Execution rejected for {symbol}: Cent Account #160219615 is strictly restricted ONLY to XAUUSDc.")
                return {
                    "success": False,
                    "error": f"Safety Guard: Account #{current_login} is strictly locked to trade ONLY XAUUSDc (Attempted: {symbol})."
                }
            # Normalize symbol to XAUUSDc for this account
            symbol = "XAUUSDc"
        else:
            # For other accounts, enforce Demo check for BTC / Gold / High Risk
            if any(keyword in upper_sym for keyword in ["BTC", "XAU", "GOLD"]):
                if self.is_connected and not self.account_info.get("is_demo", False):
                    logger.error(f"Execution rejected for {symbol}: Connected account is NOT a Demo account.")
                    return {
                        "success": False,
                        "error": "Safety Guard: Real money execution prohibited. Connected MT5 account must be Demo/Trial or Whitelisted Cent."
                    }

                if settings.mt5_login:
                    if current_login and current_login != settings.mt5_login:
                        logger.error(f"Execution rejected for {symbol}: login #{current_login} != allowed #{settings.mt5_login}")
                        return {
                            "success": False,
                            "error": f"Safety Guard: {symbol} trading is strictly permitted only on configured account #{settings.mt5_login} (current: #{current_login})."
                        }

        # If real MT5 is connected, execute real Demo trade
        if self.is_connected:
            mt5.symbol_select(symbol, True)
            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                return {"success": False, "error": f"Cannot get tick price for {symbol}"}

            order_type = mt5.ORDER_TYPE_BUY if direction.upper() == "BUY" else mt5.ORDER_TYPE_SELL
            price = tick.ask if direction.upper() == "BUY" else tick.bid

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": order_type,
                "price": price,
                "sl": sl_price,
                "tp": tp_price,
                "deviation": 20,
                "magic": 202611,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                return {
                    "success": False,
                    "retcode": result.retcode,
                    "error": f"MT5 order rejected: {result.comment} (code {result.retcode})"
                }

            # Fail-Safe Verification: Verify that the broker accepted Hard SL
            pos_info = mt5.positions_get(ticket=result.order)
            if pos_info and len(pos_info) > 0:
                pos = pos_info[0]
                if pos.sl <= 0:
                    # Emergency Fail-Safe: SL missing! Close immediately!
                    self.close_position(result.order)
                    return {
                        "success": False,
                        "error": "CRITICAL FAIL-SAFE: Hard SL was not confirmed by broker. Order was immediately closed."
                    }

            return {
                "success": True,
                "ticket": result.order,
                "symbol": symbol,
                "direction": direction,
                "volume": volume,
                "price": result.price,
                "sl": sl_price,
                "tp": tp_price,
                "comment": comment,
                "message": f"Order #{result.order} filled successfully with verified Hard SL."
            }

        # Safe Simulated Demo execution (When MT5 terminal is not open)
        self._sim_ticket_counter += 1
        ticket = self._sim_ticket_counter
        sim_pos = {
            "ticket": ticket,
            "symbol": symbol,
            "direction": direction.upper(),
            "volume": volume,
            "open_price": sl_price + 2.5 if direction == "BUY" else sl_price - 2.5,
            "current_price": sl_price + 2.8 if direction == "BUY" else sl_price - 2.8,
            "sl": sl_price,
            "tp": tp_price,
            "profit_usd": 0.30,
            "profit_thb": 10.50,
            "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "comment": f"{comment} [SIM_DEMO]"
        }
        self.simulated_positions.append(sim_pos)
        return {
            "success": True,
            "ticket": ticket,
            "symbol": symbol,
            "direction": direction,
            "volume": volume,
            "price": sim_pos["open_price"],
            "sl": sl_price,
            "tp": tp_price,
            "comment": sim_pos["comment"],
            "message": f"Demo Order #{ticket} recorded with Hard SL at ${sl_price:.2f}."
        }

    def get_open_positions(self) -> List[Dict[str, Any]]:
        """Retrieve live open positions from MT5 (or simulated demo positions)."""
        if self.is_connected:
            positions = mt5.positions_get()
            if positions is None:
                return []
            is_cent = self.account_info.get("currency") == "USC"
            res = []
            for p in positions:
                profit_raw = p.profit
                # If account is USC, profit is in USC. Convert to real USD (profit_raw / 100) and THB
                profit_usd = round(profit_raw / 100.0, 2) if is_cent else profit_raw
                profit_thb = round((profit_raw / 100.0) * 35.0, 2) if is_cent else round(profit_raw * 35.0, 2)
                res.append({
                    "ticket": p.ticket,
                    "symbol": p.symbol,
                    "direction": "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL",
                    "volume": p.volume,
                    "open_price": p.price_open,
                    "current_price": p.price_current,
                    "sl": p.sl,
                    "tp": p.tp,
                    "profit_native": profit_raw,
                    "currency": "USC" if is_cent else "USD",
                    "profit_usd": profit_usd,
                    "profit_thb": profit_thb,
                    "time": datetime.fromtimestamp(p.time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "comment": p.comment
                })
            return res
        return list(self.simulated_positions)

    def modify_position_sltp(self, ticket: int, sl: float, tp: float) -> Dict[str, Any]:
        """Modify SL and TP of an open position in MT5."""
        if not self.is_connected:
            # Simulated position modification
            for pos in self.simulated_positions:
                if pos["ticket"] == ticket:
                    pos["sl"] = sl
                    pos["tp"] = tp
                    return {"success": True, "ticket": ticket, "sl": sl, "tp": tp, "simulated": True}
            return {"success": False, "error": f"Simulated position #{ticket} not found"}

        pos_list = mt5.positions_get(ticket=ticket)
        if not pos_list:
            return {"success": False, "error": f"Position #{ticket} not found in MT5."}

        pos = pos_list[0]
        req = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": pos.symbol,
            "sl": float(sl),
            "tp": float(tp),
        }
        res = mt5.order_send(req)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            comment = res.comment if res else "Unknown MT5 error"
            return {"success": False, "error": f"Failed to modify SL/TP for position #{ticket}: {comment}"}

        return {"success": True, "ticket": ticket, "sl": sl, "tp": tp, "comment": res.comment}

    def check_and_apply_breakeven_locks(self, min_r_multiple: float = 1.0) -> List[Dict[str, Any]]:
        """
        Scans all open positions and locks Stop Loss to Breakeven (+ spread buffer)
        for any trade where floating profit reaches or exceeds `min_r_multiple * initial_risk`.
        Guarantees capital preservation and prevents winning trades from reversing into full losses.
        """
        results = []
        positions = self.get_open_positions()
        if not positions:
            return results

        for p in positions:
            ticket = p["ticket"]
            symbol = p["symbol"]
            pos_type = str(p.get("direction", "BUY")).upper()
            open_price = float(p.get("open_price") or 0.0)
            current_price = float(p.get("current_price") or 0.0)
            sl = float(p.get("sl") or 0.0)
            tp = float(p.get("tp") or 0.0)

            # Skip if no SL was set or invalid prices
            if sl <= 0 or open_price <= 0 or current_price <= 0:
                continue

            # Calculate initial risk R
            if pos_type == "BUY":
                initial_risk = open_price - sl
                current_gain = current_price - open_price
            else: # SELL
                initial_risk = sl - open_price
                current_gain = open_price - current_price

            # Only evaluate valid positive initial risk (at least $0.10)
            if initial_risk <= 0.10:
                continue

            r_multiple_achieved = current_gain / initial_risk

            # Check if profit reaches or exceeds the threshold (e.g. 1.0x R)
            if r_multiple_achieved >= min_r_multiple:
                # Determine broker spread
                spread = 0.25
                if self.is_connected and MT5_AVAILABLE and mt5 is not None:
                    tick = mt5.symbol_info_tick(symbol)
                    if tick:
                        spread = max(round(tick.ask - tick.bid, 2), 0.20)

                # Buffer to cover live spread + small slippage cushion ($0.10)
                buffer = round(spread + 0.10, 2)
                new_sl = round(open_price + buffer, 2) if pos_type == "BUY" else round(open_price - buffer, 2)

                # Check if SL is already at or better than Breakeven
                already_secured = (sl >= new_sl) if pos_type == "BUY" else (sl <= new_sl)
                if already_secured:
                    continue

                # Apply modification
                mod_res = self.modify_position_sltp(ticket=ticket, sl=new_sl, tp=tp)
                if mod_res.get("success"):
                    logger.info(
                        f"🛡️ Breakeven Locked for #{ticket} ({symbol} {pos_type}): "
                        f"SL moved from {sl} to {new_sl} (Gain: +{current_gain:.2f} USD, R: {r_multiple_achieved:.2f}x R)"
                    )
                    results.append({
                        "ticket": ticket,
                        "symbol": symbol,
                        "direction": pos_type,
                        "open_price": open_price,
                        "previous_sl": sl,
                        "new_sl": new_sl,
                        "r_multiple": round(r_multiple_achieved, 2),
                        "status": "LOCKED"
                    })
                else:
                    logger.warning(f"Failed to lock Breakeven for #{ticket}: {mod_res.get('error')}")

        return results

    def close_position(self, ticket: int) -> Dict[str, Any]:
        """Close an active position by ticket."""
        if self.is_connected:
            pos_list = mt5.positions_get(ticket=ticket)
            if not pos_list:
                return {"success": False, "error": f"Position #{ticket} not found in MT5."}
            pos = pos_list[0]
            close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
            tick = mt5.symbol_info_tick(pos.symbol)
            close_price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask

            req = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": ticket,
                "symbol": pos.symbol,
                "volume": pos.volume,
                "type": close_type,
                "price": close_price,
                "deviation": 20,
                "magic": 202611,
                "comment": "AutoTrade Close",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            res = mt5.order_send(req)
            if res.retcode != mt5.TRADE_RETCODE_DONE:
                return {"success": False, "error": f"Failed to close position: {res.comment}"}
            return {"success": True, "ticket": ticket, "message": f"Position #{ticket} closed at ${close_price:.2f}."}

        # Simulated close
        existing = next((p for p in self.simulated_positions if p["ticket"] == ticket), None)
        if existing:
            self.simulated_positions.remove(existing)
            return {"success": True, "ticket": ticket, "message": f"Position #{ticket} closed successfully."}
        return {"success": False, "error": f"Position #{ticket} not found."}

    def send_limit_order(
        self,
        symbol: str,
        direction: str,  # "BUY" or "SELL"
        volume: float,
        price: float,
        sl_price: float,
        tp_price: float,
        expiry_minutes: int = 10,
        comment: str = "SmartLimit [TTL:10m]"
    ) -> Dict[str, Any]:
        """
        Send a pending limit order (BUY_LIMIT or SELL_LIMIT) with broker-side Dead Man's Switch (Expiry)
        and mandatory Hard Stop Loss.
        """
        if sl_price <= 0:
            return {
                "success": False,
                "error": "Hard Stop Loss is mandatory. Limit order rejected by safety guard."
            }

        # Safety Guard: Account Whitelist & Symbol Restrictions
        upper_sym = symbol.upper()
        current_login = self.account_info.get("login")
        
        # Cent Account Specific Rule: Account #160219615 is strictly restricted ONLY to XAUUSDc
        if current_login == 160219615:
            if upper_sym not in ["XAUUSDC", "XAUUSD"]:
                logger.error(f"Execution rejected for limit {symbol}: Cent Account #160219615 is strictly restricted ONLY to XAUUSDc.")
                return {
                    "success": False,
                    "error": f"Safety Guard: Account #{current_login} is strictly locked to trade ONLY XAUUSDc (Attempted: {symbol})."
                }
            symbol = "XAUUSDc"
        else:
            if any(keyword in upper_sym for keyword in ["BTC", "XAU", "GOLD"]):
                if self.is_connected and not self.account_info.get("is_demo", False):
                    return {
                        "success": False,
                        "error": "Safety Guard: Real money execution prohibited. Connected MT5 account must be Demo/Trial or Whitelisted Cent."
                    }
                if settings.mt5_login:
                    if current_login and current_login != settings.mt5_login:
                        return {
                            "success": False,
                            "error": f"Safety Guard: {symbol} trading is strictly permitted only on configured account #{settings.mt5_login}."
                        }

        now_utc = datetime.now(timezone.utc)
        expiry_dt = now_utc + timedelta(minutes=expiry_minutes)

        if self.is_connected:
            mt5.symbol_select(symbol, True)
            order_type = mt5.ORDER_TYPE_BUY_LIMIT if direction.upper() == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT
            
            # Broker expiry timestamp (POSIX timestamp in integer)
            expiry_timestamp = int(expiry_dt.timestamp())

            request = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": symbol,
                "volume": volume,
                "type": order_type,
                "price": price,
                "sl": sl_price,
                "tp": tp_price,
                "deviation": 20,
                "magic": 202611,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_SPECIFIED,
                "expiration": expiry_timestamp,
                "type_filling": mt5.ORDER_FILLING_RETURN,
            }

            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                return {
                    "success": False,
                    "retcode": result.retcode,
                    "error": f"MT5 pending order rejected: {result.comment} (code {result.retcode})"
                }

            return {
                "success": True,
                "ticket": result.order,
                "symbol": symbol,
                "direction": direction,
                "volume": volume,
                "price": price,
                "sl": sl_price,
                "tp": tp_price,
                "expiry_time": expiry_dt.isoformat(),
                "comment": comment,
                "message": f"Pending {direction}_LIMIT #{result.order} set at ${price:.2f} with {expiry_minutes}m Dead Man's Switch."
            }

        # Simulated Demo Pending Order
        self._sim_ticket_counter += 1
        ticket = self._sim_ticket_counter
        sim_order = {
            "ticket": ticket,
            "symbol": symbol,
            "direction": direction.upper(),
            "volume": volume,
            "price": price,
            "sl": sl_price,
            "tp": tp_price,
            "expiry_time": expiry_dt.isoformat(),
            "created_time": now_utc.isoformat(),
            "renewal_count": 0,
            "comment": f"{comment} [SIM_DEMO]"
        }
        if not hasattr(self, "simulated_orders"):
            self.simulated_orders = []
        self.simulated_orders.append(sim_order)
        return {
            "success": True,
            "ticket": ticket,
            "symbol": symbol,
            "direction": direction,
            "volume": volume,
            "price": price,
            "sl": sl_price,
            "tp": tp_price,
            "expiry_time": expiry_dt.isoformat(),
            "comment": sim_order["comment"],
            "message": f"Simulated Pending {direction}_LIMIT #{ticket} placed at ${price:.2f} (Expiry: {expiry_minutes}m)."
        }

    def get_pending_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve live pending orders from MT5 or simulated memory."""
        if self.is_connected:
            orders = mt5.orders_get(symbol=symbol) if symbol else mt5.orders_get()
            if orders is None:
                return []
            res = []
            for o in orders:
                direction = "BUY" if o.type == mt5.ORDER_TYPE_BUY_LIMIT else ("SELL" if o.type == mt5.ORDER_TYPE_SELL_LIMIT else "OTHER")
                res.append({
                    "ticket": o.ticket,
                    "symbol": o.symbol,
                    "direction": direction,
                    "type": o.type,
                    "volume": o.volume_current,
                    "price": o.price_open,
                    "sl": o.sl,
                    "tp": o.tp,
                    "expiration": o.time_expiration,
                    "comment": o.comment
                })
            return res

        sim_orders = getattr(self, "simulated_orders", [])
        if symbol:
            return [o for o in sim_orders if o["symbol"].upper() == symbol.upper()]
        return list(sim_orders)

    def renew_pending_order_expiry(self, ticket: int, additional_minutes: int = 10) -> Dict[str, Any]:
        """
        Lease Renewal: Extend the expiration time of an existing pending order in MT5.
        """
        new_expiry_dt = datetime.now(timezone.utc) + timedelta(minutes=additional_minutes)
        new_timestamp = int(new_expiry_dt.timestamp())

        if self.is_connected:
            orders = mt5.orders_get(ticket=ticket)
            if not orders:
                return {"success": False, "error": f"Pending order #{ticket} not found"}
            order = orders[0]

            request = {
                "action": mt5.TRADE_ACTION_MODIFY,
                "order": ticket,
                "price": order.price_open,
                "sl": order.sl,
                "tp": order.tp,
                "type_time": mt5.ORDER_TIME_SPECIFIED,
                "expiration": new_timestamp,
            }
            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                return {"success": False, "error": f"Failed to renew expiry for #{ticket}: {result.comment}"}
            return {
                "success": True,
                "ticket": ticket,
                "new_expiry": new_expiry_dt.isoformat(),
                "message": f"Lease Renewal: Order #{ticket} expiry extended by {additional_minutes}m."
            }

        # Simulated renewal
        sim_orders = getattr(self, "simulated_orders", [])
        existing = next((o for o in sim_orders if o["ticket"] == ticket), None)
        if existing:
            existing["renewal_count"] = existing.get("renewal_count", 0) + 1
            existing["expiry_time"] = new_expiry_dt.isoformat()
            return {
                "success": True,
                "ticket": ticket,
                "renewal_count": existing["renewal_count"],
                "new_expiry": new_expiry_dt.isoformat(),
                "message": f"Simulated Lease Renewal: #{ticket} renewed (count: {existing['renewal_count']})."
            }
        return {"success": False, "error": f"Order #{ticket} not found."}

    def cancel_pending_order(self, ticket: int) -> Dict[str, Any]:
        """Cancel/delete an existing pending limit order."""
        if self.is_connected:
            request = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": ticket
            }
            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                return {"success": False, "error": f"Failed to cancel order #{ticket}: {result.comment}"}
            return {"success": True, "ticket": ticket, "message": f"Pending order #{ticket} successfully cancelled."}

        # Simulated cancel
        sim_orders = getattr(self, "simulated_orders", [])
        existing = next((o for o in sim_orders if o["ticket"] == ticket), None)
        if existing:
            sim_orders.remove(existing)
            return {"success": True, "ticket": ticket, "message": f"Simulated order #{ticket} cancelled."}
        return {"success": False, "error": f"Order #{ticket} not found."}

    def emergency_close_all(self) -> Dict[str, Any]:
        """Emergency Kill Switch: Close all open positions immediately."""
        closed = []
        errors = []
        positions = list(self.get_open_positions())
        for p in positions:
            res = self.close_position(p["ticket"])
            if res.get("success"):
                closed.append(p["ticket"])
            else:
                errors.append(f"Ticket #{p['ticket']}: {res.get('error')}")

        return {
            "status": "EMERGENCY_CLOSE_COMPLETED",
            "closed_count": len(closed),
            "closed_tickets": closed,
            "errors": errors
        }

mt5_client = MT5Client()
