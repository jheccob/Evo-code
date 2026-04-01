import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from config import ProductionConfig
from database.database import db as runtime_db
from services.binance_user_data_stream import BinanceFuturesUserDataStream
from services.risk_management_service import RiskManagementService
from trading_bot import TradingBot

logger = logging.getLogger(__name__)


class FuturesTrading(TradingBot):
    """
    Trading bot especializado para mercado futuro em pares USDT.
    """

    def __init__(self, exchange_name: str = "binance"):
        super().__init__()
        self.exchange_name = exchange_name
        self._exchange_testnet = ProductionConfig.BINANCE_FUTURES_TESTNET
        self.database = runtime_db
        self.risk_management_service = RiskManagementService(database=self.database)
        self._runtime_state_lock = threading.RLock()
        self._user_data_stream = None
        self._last_recovery_timestamps = {}
        self._last_user_stream_event = None

        # Par padrao de futuros.
        self.symbol = "XLM/USDT"

        # Configuracoes especificas de futuros.
        self.leverage = 5
        self.position_size_pct = 0.1
        self.stop_loss_pct = ProductionConfig.DEFAULT_LIVE_STOP_LOSS_PCT / 100
        self.take_profit_pct = ProductionConfig.DEFAULT_LIVE_TAKE_PROFIT_PCT / 100
        self.max_positions = 1

    def set_testnet_mode(self, enabled: bool = True):
        """Alternar ambiente entre Binance Futures testnet e producao."""
        enabled = bool(enabled)
        if self._exchange_testnet != enabled:
            self._exchange_testnet = enabled
            self._exchange = None
        return self._exchange_testnet

    def get_exchange_environment(self) -> str:
        return "testnet" if bool(getattr(self, "_exchange_testnet", False)) else "mainnet"

    def _ensure_runtime_state_lock(self):
        lock = getattr(self, "_runtime_state_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._runtime_state_lock = lock
        return lock

    def _get_runtime_state_path(self) -> Path:
        path = Path(ProductionConfig.BINANCE_FUTURES_RUNTIME_STATE_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _runtime_state_key(self, symbol: str, timeframe: Optional[str] = None) -> str:
        resolved_symbol = symbol or self.symbol
        resolved_timeframe = timeframe or self.timeframe
        resolved_exchange = getattr(self, "exchange_name", "binance")
        return f"{resolved_exchange}:{self.get_exchange_environment()}:{resolved_symbol}:{resolved_timeframe}".lower()

    def _load_runtime_state_store(self) -> Dict[str, Dict[str, Any]]:
        lock = self._ensure_runtime_state_lock()
        with lock:
            path = self._get_runtime_state_path()
            if not path.exists():
                return {}
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                return payload if isinstance(payload, dict) else {}
            except Exception as exc:
                logger.warning("Falha ao ler snapshot runtime de futuros: %s", exc)
                return {}

    def _save_runtime_state_store(self, store: Dict[str, Dict[str, Any]]):
        lock = self._ensure_runtime_state_lock()
        with lock:
            path = self._get_runtime_state_path()
            temp_path = path.parent / f"{path.name}.tmp"
            temp_path.write_text(
                json.dumps(store, ensure_ascii=True, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            temp_path.replace(path)

    def get_runtime_snapshot(self, symbol: Optional[str] = None, timeframe: Optional[str] = None) -> Optional[Dict[str, Any]]:
        resolved_symbol = symbol or self.symbol
        key = self._runtime_state_key(resolved_symbol, timeframe=timeframe)
        return self._load_runtime_state_store().get(key)

    def _persist_runtime_snapshot(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        resolved_symbol = snapshot.get("symbol") or self.symbol
        resolved_timeframe = snapshot.get("timeframe") or self.timeframe
        key = self._runtime_state_key(resolved_symbol, timeframe=resolved_timeframe)
        store = self._load_runtime_state_store()
        merged = dict(store.get(key) or {})
        merged.update(snapshot)
        merged.update(
            {
                "exchange": getattr(self, "exchange_name", "binance"),
                "environment": self.get_exchange_environment(),
                "symbol": resolved_symbol,
                "timeframe": resolved_timeframe,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        store[key] = merged
        self._save_runtime_state_store(store)
        return merged

    def _normalize_binance_symbol(self, raw_symbol: Optional[str]) -> Optional[str]:
        if not raw_symbol:
            return None
        if "/" in str(raw_symbol):
            return str(raw_symbol).upper()

        compact = str(raw_symbol).replace(":", "").upper()
        for quote in ("USDT", "USDC", "BUSD"):
            if compact.endswith(quote) and len(compact) > len(quote):
                base = compact[: -len(quote)]
                return f"{base}/{quote}"
        return compact

    def _infer_entry_side_from_position(self, position: Optional[Dict[str, Any]]) -> str:
        side = str((position or {}).get("side") or "").lower()
        return "buy" if side in {"long", "buy"} else "sell"

    def _can_attempt_recovery(self, symbol: str) -> bool:
        timestamps = getattr(self, "_last_recovery_timestamps", None)
        if timestamps is None:
            timestamps = {}
            self._last_recovery_timestamps = timestamps

        now = datetime.now(timezone.utc).timestamp()
        last_attempt = float(timestamps.get(symbol, 0.0) or 0.0)
        if (now - last_attempt) < float(ProductionConfig.BINANCE_RUNTIME_RECOVERY_COOLDOWN_SECONDS):
            return False
        timestamps[symbol] = now
        return True

    # Configuracao

    def set_leverage(self, symbol: str, leverage: int):
        """Define alavancagem para um simbolo USDT."""
        try:
            if leverage <= 0:
                return False, "Alavancagem deve ser maior que zero"

            if not self.validate_usdt_pair(symbol):
                return False, f"Simbolo {symbol} nao e um par USDT valido para futuros"

            self.exchange.set_leverage(leverage, symbol)
            self.leverage = leverage
            return True, f"Alavancagem {leverage}x definida para {symbol} (USDT)"
        except Exception as e:
            return False, f"Erro ao definir alavancagem: {str(e)}"

    # Conta

    def get_account_balance(self):
        """Obtem saldo da conta de futuros em USDT."""
        try:
            balance = self.exchange.fetch_balance()
            usdt_balance = balance.get("USDT") or {}
            balance_info = balance.get("info") or {}

            return {
                "total_balance": usdt_balance.get("total", 0),
                "available_balance": usdt_balance.get("free", 0),
                "used_balance": usdt_balance.get("used", 0),
                "unrealized_pnl": balance_info.get("totalUnrealizedProfit", 0),
                "margin_ratio": balance_info.get("totalMaintMargin", 0),
                "currency": "USDT",
            }
        except Exception as e:
            logger.error("Erro ao obter saldo USDT: %s", e)
            return None

    def calculate_position_size(
        self,
        balance: float,
        price: float,
        signal_strength: float = 1.0,
    ):
        """
        Calcula o tamanho da posicao com base no saldo em USDT e alavancagem.
        """
        if not self.symbol.endswith("/USDT"):
            raise ValueError("Mercado futuro configurado apenas para pares USDT")

        if price <= 0:
            raise ValueError("Preco deve ser maior que zero")

        if balance <= 0:
            return 0.0

        adjusted_strength = max(0.0, min(float(signal_strength), 1.0))
        adjusted_size_pct = self.position_size_pct * adjusted_strength
        position_value = balance * adjusted_size_pct
        quantity = (position_value * self.leverage) / price
        return round(max(quantity, 0.0), 6)

    def get_live_execution_readiness(
        self,
        symbol: str = None,
        timeframe: str = None,
        strategy_version: str = None,
    ) -> Dict:
        """Consultar se o setup atual esta liberado para ordens reais."""
        return self.database.get_live_execution_readiness(
            symbol=symbol or self.symbol,
            timeframe=timeframe or self.timeframe,
            strategy_version=strategy_version,
        )

    def _get_risk_management_service(self) -> RiskManagementService:
        service = getattr(self, "risk_management_service", None)
        if service is None:
            service = RiskManagementService(database=getattr(self, "database", runtime_db))
            self.risk_management_service = service
        return service

    def _build_client_order_id(self, prefix: str, symbol: str) -> str:
        compact_symbol = "".join(ch for ch in (symbol or self.symbol or "").upper() if ch.isalnum())
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")[-12:]
        return f"evo_{prefix}_{compact_symbol[:8]}_{timestamp}"[:36]

    def _build_entry_order_params(self, client_order_id: str, order_type: str) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "newClientOrderId": client_order_id,
            "newOrderRespType": ProductionConfig.BINANCE_FUTURES_ENTRY_RESPONSE_TYPE,
        }
        if order_type == "limit":
            params["timeInForce"] = "GTC"
        return params

    def _build_exit_order_params(self, client_order_id: str, trigger_price: float) -> Dict[str, Any]:
        return {
            "stopPrice": trigger_price,
            "closePosition": True,
            "workingType": ProductionConfig.BINANCE_FUTURES_WORKING_TYPE,
            "priceProtect": bool(ProductionConfig.BINANCE_FUTURES_PRICE_PROTECT),
            "newClientOrderId": client_order_id,
        }

    def _resolve_order_fill_price(self, order: Optional[Dict], fallback: Optional[float] = None) -> Optional[float]:
        if not order:
            return fallback

        for key in ("average", "avgPrice", "price"):
            value = order.get(key)
            if value not in (None, "", 0, 0.0):
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue

        info = order.get("info") or {}
        for key in ("avgPrice", "price", "stopPrice"):
            value = info.get(key)
            if value not in (None, "", 0, 0.0):
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
        return fallback

    def _resolve_filled_quantity(self, order: Optional[Dict], fallback: float) -> float:
        if not order:
            return float(fallback or 0.0)

        for key in ("filled", "amount"):
            value = order.get(key)
            if value not in (None, "", 0, 0.0):
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue

        info = order.get("info") or {}
        for key in ("executedQty", "origQty"):
            value = info.get(key)
            if value not in (None, "", 0, 0.0):
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
        return float(fallback or 0.0)

    def _normalize_symbol_match(self, left: Optional[str], right: Optional[str]) -> bool:
        return str(left or "").replace(":", "").upper() == str(right or "").replace(":", "").upper()

    def _is_protection_order(self, order: Dict[str, Any]) -> bool:
        order_type = str(order.get("type") or order.get("orderType") or "").upper()
        info = order.get("info") or {}
        raw_type = str(info.get("origType") or info.get("type") or "").upper()
        return bool(order.get("reduceOnly") or info.get("reduceOnly") or info.get("closePosition")) or order_type in {
            "STOP_MARKET",
            "TAKE_PROFIT_MARKET",
            "TRAILING_STOP_MARKET",
        } or raw_type in {"STOP_MARKET", "TAKE_PROFIT_MARKET", "TRAILING_STOP_MARKET"}

    def _safe_fetch_open_orders(self, symbol: str) -> list[Dict[str, Any]]:
        try:
            return self.exchange.fetch_open_orders(symbol) or []
        except Exception as e:
            logger.warning("Falha ao buscar ordens abertas para %s: %s", symbol, e)
            return []

    def _safe_fetch_recent_trades(self, symbol: str) -> list[Dict[str, Any]]:
        try:
            return self.exchange.fetch_my_trades(
                symbol,
                limit=int(ProductionConfig.BINANCE_FUTURES_RECONCILIATION_FETCH_LIMIT),
            ) or []
        except Exception as e:
            logger.warning("Falha ao buscar trades recentes para %s: %s", symbol, e)
            return []

    def _get_symbol_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        for position in self.get_open_positions():
            if self._normalize_symbol_match(position.get("symbol"), symbol):
                return position
        return None

    def _create_native_exit_orders(
        self,
        symbol: str,
        entry_side: str,
        stop_loss: Optional[float],
        take_profit: Optional[float],
    ) -> tuple[list[Dict[str, Any]], list[str]]:
        exit_side = "sell" if entry_side == "buy" else "buy"
        created_orders: list[Dict[str, Any]] = []
        errors: list[str] = []

        exit_specs = (
            ("stop_loss", "STOP_MARKET", stop_loss),
            ("take_profit", "TAKE_PROFIT_MARKET", take_profit),
        )
        for label, order_type, trigger_price in exit_specs:
            if trigger_price is None:
                continue
            client_order_id = self._build_client_order_id(label, symbol)
            params = self._build_exit_order_params(client_order_id, trigger_price)
            try:
                order = self.exchange.create_order(
                    symbol=symbol,
                    type=order_type,
                    side=exit_side,
                    amount=None,
                    price=None,
                    params=params,
                )
                created_orders.append(
                    {
                        "label": label,
                        "order_id": order.get("id"),
                        "client_order_id": client_order_id,
                        "type": order_type,
                        "trigger_price": trigger_price,
                    }
                )
            except Exception as e:
                error_message = f"Falha ao criar {label} nativo: {str(e)}"
                logger.error("%s", error_message)
                errors.append(error_message)

        return created_orders, errors

    def cancel_symbol_protection_orders(self, symbol: str) -> Dict[str, Any]:
        cancelled: list[str] = []
        errors: list[str] = []
        for order in self._safe_fetch_open_orders(symbol):
            if not self._is_protection_order(order):
                continue

            order_id = order.get("id")
            if not order_id:
                continue
            try:
                self.exchange.cancel_order(order_id, symbol)
                cancelled.append(str(order_id))
            except Exception as e:
                error_message = f"Falha ao cancelar ordem de protecao {order_id}: {str(e)}"
                logger.warning("%s", error_message)
                errors.append(error_message)

        return {
            "symbol": symbol,
            "cancelled_order_ids": cancelled,
            "errors": errors,
        }

    def reconcile_symbol_state(self, symbol: str) -> Dict[str, Any]:
        position = self._get_symbol_position(symbol)
        open_orders = self._safe_fetch_open_orders(symbol)
        protection_orders = [order for order in open_orders if self._is_protection_order(order)]
        recent_trades = self._safe_fetch_recent_trades(symbol)

        has_stop_loss = False
        has_take_profit = False
        for order in protection_orders:
            order_type = str(order.get("type") or order.get("orderType") or "").upper()
            info = order.get("info") or {}
            raw_type = str(info.get("origType") or info.get("type") or "").upper()
            effective_type = raw_type or order_type
            if effective_type == "STOP_MARKET":
                has_stop_loss = True
            if effective_type == "TAKE_PROFIT_MARKET":
                has_take_profit = True

        open_position = position is not None
        warnings: list[str] = []
        if open_position and not has_stop_loss:
            warnings.append("Posicao aberta sem stop loss nativo na exchange.")
        if open_position and not has_take_profit:
            warnings.append("Posicao aberta sem take profit nativo na exchange.")

        return {
            "symbol": symbol,
            "environment": self.get_exchange_environment(),
            "status": "healthy" if not warnings else "warning",
            "open_position": open_position,
            "position": position,
            "open_orders_count": len(open_orders),
            "protection_orders_count": len(protection_orders),
            "has_stop_loss": has_stop_loss,
            "has_take_profit": has_take_profit,
            "protection_order_ids": [order.get("id") for order in protection_orders if order.get("id")],
            "recent_trades_count": len(recent_trades),
            "warnings": warnings,
        }

    def recover_symbol_state(self, symbol: Optional[str] = None, source: str = "startup") -> Dict[str, Any]:
        resolved_symbol = symbol or self.symbol
        snapshot = self.get_runtime_snapshot(resolved_symbol) or {}
        before = self.reconcile_symbol_state(resolved_symbol)
        recovery = {
            "symbol": resolved_symbol,
            "environment": self.get_exchange_environment(),
            "source": source,
            "snapshot_found": bool(snapshot),
            "before": before,
            "after": before,
            "restored": False,
            "restored_protection_orders": [],
            "warnings": list(before.get("warnings", [])),
            "errors": [],
        }

        if not before.get("open_position"):
            self._persist_runtime_snapshot(
                {
                    "symbol": resolved_symbol,
                    "status": "closed",
                    "quantity": 0.0,
                    "reconciliation": before,
                    "last_recovery_source": source,
                    "last_recovery_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            recovery["status"] = "no_open_position"
            return recovery

        if not snapshot:
            recovery["status"] = "warning"
            recovery["warnings"].append("Posicao aberta sem snapshot local para restaurar protecoes.")
            return recovery

        missing_stop = not bool(before.get("has_stop_loss"))
        missing_take = not bool(before.get("has_take_profit"))
        desired_stop = snapshot.get("stop_loss")
        desired_take = snapshot.get("take_profit")

        if missing_stop and desired_stop in (None, 0, 0.0):
            recovery["warnings"].append("Snapshot nao tem stop loss para restauracao.")
        if missing_take and desired_take in (None, 0, 0.0):
            recovery["warnings"].append("Snapshot nao tem take profit para restauracao.")

        if (
            not ProductionConfig.BINANCE_RUNTIME_AUTO_RECOVER_PROTECTION
            or ((not missing_stop or desired_stop in (None, 0, 0.0)) and (not missing_take or desired_take in (None, 0, 0.0)))
        ):
            recovery["status"] = "healthy" if before.get("status") == "healthy" else "warning"
            self._persist_runtime_snapshot(
                {
                    "symbol": resolved_symbol,
                    "status": "open",
                    "quantity": float((before.get("position") or {}).get("size") or 0.0),
                    "entry_price": (before.get("position") or {}).get("entry_price"),
                    "reconciliation": before,
                    "last_recovery_source": source,
                    "last_recovery_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            return recovery

        restored_orders, restore_errors = self._create_native_exit_orders(
            symbol=resolved_symbol,
            entry_side=str(snapshot.get("entry_side") or self._infer_entry_side_from_position(before.get("position"))),
            stop_loss=desired_stop if missing_stop else None,
            take_profit=desired_take if missing_take else None,
        )
        after = self.reconcile_symbol_state(resolved_symbol)
        merged_orders = list(snapshot.get("protection_orders") or []) + list(restored_orders)
        persisted_snapshot = {
            "symbol": resolved_symbol,
            "status": "open",
            "quantity": float((after.get("position") or {}).get("size") or 0.0),
            "entry_price": (after.get("position") or {}).get("entry_price") or snapshot.get("entry_price"),
            "stop_loss": desired_stop,
            "take_profit": desired_take,
            "reconciliation": after,
            "protection_orders": merged_orders,
            "last_recovery_source": source,
            "last_recovery_at": datetime.now(timezone.utc).isoformat(),
        }
        self._persist_runtime_snapshot(persisted_snapshot)

        recovery.update(
            {
                "after": after,
                "restored": bool(restored_orders) and not restore_errors,
                "restored_protection_orders": restored_orders,
                "errors": restore_errors,
                "status": "healthy" if after.get("status") == "healthy" and not restore_errors else "warning",
            }
        )
        return recovery

    def _get_user_data_stream(self) -> BinanceFuturesUserDataStream:
        stream = getattr(self, "_user_data_stream", None)
        if stream is not None and bool(getattr(stream, "testnet", False)) == bool(self._exchange_testnet):
            return stream

        if stream is not None:
            try:
                stream.stop()
            except Exception:
                logger.warning("Falha ao encerrar stream privado anterior da Binance.", exc_info=True)

        stream = BinanceFuturesUserDataStream(
            self.exchange,
            testnet=bool(self._exchange_testnet),
            on_event=self._handle_user_stream_event,
        )
        self._user_data_stream = stream
        return stream

    def start_user_data_stream(self, auto_recover: bool = True) -> Dict[str, Any]:
        recovery = None
        if auto_recover:
            recovery = self.recover_symbol_state(self.symbol, source="startup")

        stream = self._get_user_data_stream()
        stream.start()
        ready = stream.wait_until_ready(timeout=15)
        return {
            "ready": bool(ready),
            "stream_status": stream.get_status(),
            "recovery": recovery,
        }

    def stop_user_data_stream(self) -> Dict[str, Any]:
        stream = getattr(self, "_user_data_stream", None)
        if stream is None:
            return {"stopped": False, "reason": "stream_not_started"}
        stream.stop()
        return {"stopped": True, "stream_status": stream.get_status()}

    def get_user_data_stream_status(self) -> Dict[str, Any]:
        stream = getattr(self, "_user_data_stream", None)
        if stream is None:
            return {
                "connected": False,
                "environment": self.get_exchange_environment(),
                "reason": "stream_not_started",
            }
        return stream.get_status()

    def _handle_user_stream_event(self, payload: Dict[str, Any]):
        self._last_user_stream_event = payload
        event_type = str(payload.get("e") or "")
        event_time = payload.get("E")
        touched_symbols = set()

        if event_type == "ORDER_TRADE_UPDATE":
            order_data = payload.get("o") or {}
            symbol = self._normalize_binance_symbol(order_data.get("s"))
            if symbol:
                touched_symbols.add(symbol)
                self._persist_runtime_snapshot(
                    {
                        "symbol": symbol,
                        "last_event_type": event_type,
                        "last_event_at": event_time,
                        "last_client_order_id": order_data.get("c"),
                        "last_order_status": order_data.get("X"),
                        "last_execution_type": order_data.get("x"),
                    }
                )

        if event_type == "ACCOUNT_UPDATE":
            account_data = payload.get("a") or {}
            for position in account_data.get("P") or []:
                symbol = self._normalize_binance_symbol(position.get("s"))
                if not symbol:
                    continue
                touched_symbols.add(symbol)
                self._persist_runtime_snapshot(
                    {
                        "symbol": symbol,
                        "last_event_type": event_type,
                        "last_event_at": event_time,
                        "exchange_position_side": position.get("ps"),
                        "exchange_position_amount": position.get("pa"),
                        "exchange_entry_price": position.get("ep"),
                    }
                )

        for symbol in touched_symbols:
            if not ProductionConfig.BINANCE_RUNTIME_AUTO_RECOVER_PROTECTION:
                continue
            if not self._can_attempt_recovery(symbol):
                continue
            try:
                self.recover_symbol_state(symbol, source=f"user_stream:{event_type.lower()}")
            except Exception as exc:
                logger.warning("Falha ao recuperar estado de %s via user stream: %s", symbol, exc)

    # Ordens

    def create_futures_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ):
        """
        Criar ordem no mercado futuro com stop loss e take profit.
        """
        symbol = symbol or self.symbol
        side = (side or "").lower()
        order_type = (order_type or "market").lower()

        try:
            quantity = float(quantity)
        except (TypeError, ValueError):
            return False, "Quantidade invalida"

        if side not in {"buy", "sell"}:
            return False, "Lado da ordem deve ser 'buy' ou 'sell'"

        if quantity <= 0:
            return False, "Quantidade deve ser maior que zero"

        if not symbol.endswith("/USDT"):
            return False, "Mercado futuro configurado apenas para pares USDT"

        if order_type not in {"market", "limit"}:
            return False, "Tipo de ordem deve ser 'market' ou 'limit'"

        if order_type == "limit":
            if price is None:
                return False, "Preco e obrigatorio para ordem limit"
            try:
                price = float(price)
            except (TypeError, ValueError):
                return False, "Preco invalido"
            if price <= 0:
                return False, "Preco deve ser maior que zero"

        for field_name, field_value in (
            ("stop_loss", stop_loss),
            ("take_profit", take_profit),
        ):
            if field_value is None:
                continue
            try:
                numeric_value = float(field_value)
            except (TypeError, ValueError):
                return False, f"{field_name} invalido"
            if numeric_value <= 0:
                return False, f"{field_name} deve ser maior que zero"
            if field_name == "stop_loss":
                stop_loss = numeric_value
            else:
                take_profit = numeric_value

        try:
            readiness = self.get_live_execution_readiness(
                symbol=symbol,
                timeframe=self.timeframe,
            )
            if not readiness.get("allowed"):
                return False, readiness.get("message", "Execucao live bloqueada")

            entry_client_order_id = self._build_client_order_id("entry", symbol)
            entry_params = self._build_entry_order_params(entry_client_order_id, order_type)
            if order_type == "market":
                order = self.exchange.create_order(
                    symbol=symbol,
                    type="market",
                    side=side,
                    amount=quantity,
                    price=None,
                    params=entry_params,
                )
            else:
                order = self.exchange.create_order(
                    symbol=symbol,
                    type="limit",
                    side=side,
                    amount=quantity,
                    price=price,
                    params=entry_params,
                )

            order_id = order.get("id")
            fill_price = self._resolve_order_fill_price(order, fallback=price)
            filled_quantity = self._resolve_filled_quantity(order, fallback=quantity)
            protection_orders: list[Dict[str, Any]] = []
            protection_errors: list[str] = []

            if order_type == "market" and filled_quantity > 0 and (stop_loss is not None or take_profit is not None):
                protection_orders, protection_errors = self._create_native_exit_orders(
                    symbol=symbol,
                    entry_side=side,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                )
            elif order_type != "market" and (stop_loss is not None or take_profit is not None):
                protection_errors.append(
                    "Protecao nativa nao foi criada automaticamente para ordem limit sem confirmacao de fill."
                )

            reconciliation = self.reconcile_symbol_state(symbol)
            if (
                ProductionConfig.BINANCE_FUTURES_REQUIRE_PROTECTION
                and reconciliation.get("open_position")
                and (stop_loss is not None or take_profit is not None)
                and (
                    (stop_loss is not None and not reconciliation.get("has_stop_loss"))
                    or (take_profit is not None and not reconciliation.get("has_take_profit"))
                )
            ):
                protection_errors.append(
                    "Reconciliação nao confirmou todas as protecoes nativas esperadas na Binance."
                )

            snapshot = self._persist_runtime_snapshot(
                {
                    "symbol": symbol,
                    "status": "open" if reconciliation.get("open_position") else "pending",
                    "entry_side": side,
                    "quantity": round(float(filled_quantity or quantity or 0.0), 6),
                    "entry_price": fill_price,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "entry_client_order_id": entry_client_order_id,
                    "entry_order_id": order_id,
                    "protection_orders": protection_orders,
                    "reconciliation": reconciliation,
                    "last_order_status": order.get("status") or (order.get("info") or {}).get("status"),
                }
            )

            return True, {
                "order_id": order_id,
                "client_order_id": entry_client_order_id,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "filled_quantity": round(float(filled_quantity or 0.0), 6),
                "price": fill_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "environment": self.get_exchange_environment(),
                "protection_orders": protection_orders,
                "protection_errors": protection_errors,
                "reconciliation": reconciliation,
                "runtime_snapshot": snapshot,
            }
        except Exception as e:
            return False, f"Erro ao criar ordem: {str(e)}"

    # Posicoes

    def get_open_positions(self):
        """Obter posicoes abertas."""
        try:
            positions = self.exchange.fetch_positions() or []
            open_positions = []

            for position in positions:
                contracts = position.get("contracts", position.get("size", 0))
                try:
                    contract_size = float(contracts or 0)
                except (TypeError, ValueError):
                    continue

                if contract_size == 0:
                    continue

                open_positions.append(
                    {
                        "symbol": position.get("symbol"),
                        "side": position.get("side"),
                        "size": contracts,
                        "entry_price": position.get("entryPrice"),
                        "mark_price": position.get("markPrice"),
                        "unrealized_pnl": position.get("unrealizedPnl"),
                        "margin": position.get("initialMargin"),
                        "leverage": position.get("leverage", self.leverage),
                    }
                )

            return open_positions
        except Exception as e:
            logger.error("Erro ao obter posicoes: %s", e)
            return []

    def close_position(self, symbol: str, reduce_only: bool = True):
        """Fechar posicao aberta."""
        try:
            target_position = None
            for position in self.get_open_positions():
                if position.get("symbol") == symbol:
                    target_position = position
                    break

            if not target_position:
                return False, "Posicao nao encontrada"

            current_side = str(target_position.get("side", "")).lower()
            close_side = "sell" if current_side in {"long", "buy"} else "buy"
            size = abs(float(target_position.get("size") or 0))

            if size <= 0:
                return False, "Posicao invalida para fechamento"

            cancelled = self.cancel_symbol_protection_orders(symbol)
            close_client_order_id = self._build_client_order_id("close", symbol)
            order = self.exchange.create_order(
                symbol=symbol,
                type="market",
                side=close_side,
                amount=size,
                price=None,
                params={
                    "reduceOnly": bool(reduce_only),
                    "newClientOrderId": close_client_order_id,
                    "newOrderRespType": ProductionConfig.BINANCE_FUTURES_ENTRY_RESPONSE_TYPE,
                },
            )

            reconciliation = self.reconcile_symbol_state(symbol)
            snapshot = self._persist_runtime_snapshot(
                {
                    "symbol": symbol,
                    "status": "closed" if not reconciliation.get("open_position") else "closing",
                    "quantity": 0.0 if not reconciliation.get("open_position") else size,
                    "close_client_order_id": close_client_order_id,
                    "close_order_id": order.get("id"),
                    "reconciliation": reconciliation,
                }
            )
            return True, {
                "closed_position": target_position,
                "close_order": order,
                "client_order_id": close_client_order_id,
                "cancelled_protections": cancelled,
                "reconciliation": reconciliation,
                "runtime_snapshot": snapshot,
            }
        except Exception as e:
            return False, f"Erro ao fechar posicao: {str(e)}"

    # Sinais e execucao

    def generate_futures_signal(self, df: pd.DataFrame, account_balance: float):
        """
        Gerar sinal especifico para futuros com gerenciamento de risco.
        """
        if df is None or df.empty:
            return {"signal": "NEUTRO", "confidence": 0}

        last_row = df.iloc[-1]
        current_price = last_row["close"]
        signal_pipeline = self.evaluate_signal_pipeline(
            df,
            min_confidence=55,
            require_volume=False,
            require_trend=False,
            avoid_ranging=False,
            timeframe=self.timeframe,
            stop_loss_pct=self.stop_loss_pct * 100,
            take_profit_pct=self.take_profit_pct * 100,
        )
        decision = signal_pipeline.get("trade_decision") or {}
        base_signal = signal_pipeline.get("approved_signal") or "NEUTRO"
        confidence = min(max(float(decision.get("confidence", 0.0) or 0.0) * 10.0, 0.0), 100.0)

        signal_data = {
            "signal": base_signal,
            "confidence": confidence,
            "entry_price": current_price,
            "leverage": self.leverage,
            "position_side": None,
            "quantity": 0,
            "stop_loss": None,
            "take_profit": None,
            "risk_allowed": True,
            "risk_reason": "",
            "risk_plan": None,
        }

        risk_plan: Optional[Dict[str, Any]] = None
        if base_signal != "NEUTRO":
            risk_plan = self._get_risk_management_service().evaluate_risk_engine(
                entry_price=current_price,
                stop_loss_pct=self.stop_loss_pct * 100,
                symbol=self.symbol,
                timeframe=self.timeframe,
                account_balance=account_balance,
                runtime_allowed=True,
            )
            signal_data["risk_allowed"] = bool(risk_plan.get("allowed", False))
            signal_data["risk_reason"] = risk_plan.get("risk_reason") or risk_plan.get("reason") or ""
            signal_data["risk_plan"] = risk_plan

        if base_signal == "COMPRA":
            signal_data.update(
                {
                    "position_side": "LONG",
                    "quantity": float((risk_plan or {}).get("quantity") or 0.0),
                    "stop_loss": current_price * (1 - self.stop_loss_pct),
                    "take_profit": current_price * (1 + self.take_profit_pct),
                }
            )
        elif base_signal == "VENDA":
            signal_data.update(
                {
                    "position_side": "SHORT",
                    "quantity": float((risk_plan or {}).get("quantity") or 0.0),
                    "stop_loss": current_price * (1 + self.stop_loss_pct),
                    "take_profit": current_price * (1 - self.take_profit_pct),
                }
            )

        return signal_data

    def execute_futures_trade(self, signal_data: Dict, dry_run: bool = True):
        """
        Executar trade baseado no sinal.
        """
        if signal_data.get("signal") == "NEUTRO":
            return {"success": False, "message": "Sinal neutro, nenhuma acao"}

        position_side = signal_data.get("position_side")
        if position_side not in {"LONG", "SHORT"}:
            return {"success": False, "message": "Lado da posicao invalido"}

        risk_plan = signal_data.get("risk_plan") or {}
        if risk_plan and not bool(risk_plan.get("allowed", False)):
            return {
                "success": False,
                "message": signal_data.get("risk_reason") or "Plano de risco bloqueou a operacao.",
                "details": {"risk_plan": risk_plan},
            }

        symbol = self.symbol
        side = "buy" if position_side == "LONG" else "sell"
        quantity = float(signal_data.get("quantity") or risk_plan.get("quantity") or 0)
        stop_loss = signal_data.get("stop_loss")
        take_profit = signal_data.get("take_profit")

        if quantity <= 0:
            return {"success": False, "message": "Quantidade invalida para execucao"}

        if dry_run:
            return {
                "success": True,
                "message": f"SIMULACAO - {position_side} {quantity} {symbol}",
                "details": {
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "entry_price": signal_data.get("entry_price"),
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "leverage": signal_data.get("leverage"),
                    "confidence": signal_data.get("confidence"),
                    "risk_plan": risk_plan,
                    "environment": self.get_exchange_environment(),
                },
            }

        success, result = self.create_futures_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type="market",
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

        return {
            "success": success,
            "message": "Trade executado com sucesso" if success else "Erro ao executar trade",
            "details": result,
        }

    # Mercado

    def get_funding_rate(self, symbol: str):
        """Obter taxa de funding do simbolo."""
        try:
            funding_rate = self.exchange.fetch_funding_rate(symbol) or {}
            return {
                "symbol": symbol,
                "funding_rate": funding_rate.get("fundingRate"),
                "next_funding_time": funding_rate.get("fundingDatetime"),
            }
        except Exception as e:
            logger.error("Erro ao obter funding rate: %s", e)
            return None

    def calculate_liquidation_price(
        self,
        entry_price: float,
        leverage: int,
        side: str,
        margin_ratio: float = 0.1,
    ):
        """
        Calcular preco de liquidacao para pares USDT.
        """
        if leverage <= 0:
            raise ValueError("Alavancagem deve ser maior que zero")

        if entry_price <= 0:
            raise ValueError("Preco de entrada deve ser maior que zero")

        side_lower = side.lower()
        if side_lower == "long":
            return entry_price * (1 - (1 / leverage) + margin_ratio)
        if side_lower == "short":
            return entry_price * (1 + (1 / leverage) - margin_ratio)
        raise ValueError("Side deve ser 'long' ou 'short'")

    def validate_usdt_pair(self, symbol: str):
        """Validar se o simbolo e um par USDT valido."""
        if not symbol or not symbol.endswith("/USDT"):
            return False

        try:
            markets = self.exchange.load_markets()
            market = markets.get(symbol)
            if not market:
                return False
            return bool(market.get("future") or market.get("type") == "future")
        except Exception:
            return False

    def get_supported_usdt_pairs(self):
        """Obter lista de pares USDT suportados para futuros."""
        try:
            markets = self.exchange.load_markets()
            usdt_futures = []

            for symbol, market in markets.items():
                if not symbol.endswith("/USDT"):
                    continue
                if not market.get("active", True):
                    continue
                if market.get("future") or market.get("type") == "future":
                    usdt_futures.append(symbol)

            return sorted(usdt_futures)
        except Exception as e:
            logger.error("Erro ao obter pares USDT: %s", e)
            return ["BTC/USDT", "ETH/USDT", "XLM/USDT"]
