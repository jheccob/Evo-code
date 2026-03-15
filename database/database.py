"""
Sistema de banco de dados usando SQLite para persistir dados do trading bot
"""
import sqlite3
import os
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from utils.timezone_utils import get_brazil_datetime_naive, format_brazil_time
from config import AppConfig, ProductionConfig


def build_strategy_version(
    symbol: str,
    timeframe: str,
    rsi_period: Optional[int] = None,
    rsi_min: Optional[int] = None,
    rsi_max: Optional[int] = None,
    stop_loss_pct: float = 0.0,
    take_profit_pct: float = 0.0,
    require_volume: bool = False,
    require_trend: bool = False,
    avoid_ranging: bool = False,
) -> str:
    safe_symbol = (symbol or "UNKNOWN").replace("/", "").upper()
    safe_timeframe = timeframe or "na"
    rsi_period = int(rsi_period or 0)
    rsi_min = int(rsi_min or 0)
    rsi_max = int(rsi_max or 0)
    stop_loss_pct = float(stop_loss_pct or 0.0)
    take_profit_pct = float(take_profit_pct or 0.0)

    return (
        f"{safe_symbol}-{safe_timeframe}-"
        f"rsi{rsi_period}-{rsi_min}-{rsi_max}-"
        f"sl{stop_loss_pct:.2f}-tp{take_profit_pct:.2f}-"
        f"v{int(bool(require_volume))}-t{int(bool(require_trend))}-"
        f"r{int(bool(avoid_ranging))}"
    )

class TradingDatabase:
    def __init__(self, db_path: str = AppConfig.DB_PATH):
        self.db_path = db_path
        # Criar diretório se não existir
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.init_database()
    
    def get_connection(self):
        """Criar conexão com banco de dados"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Para retornar dicionários
        return conn
    
    def init_database(self):
        """Inicializar estrutura do banco de dados"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Tabela para sinais de trading
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trading_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                strategy_version TEXT,
                signal_type TEXT NOT NULL,  -- 'buy', 'sell', 'hold'
                price REAL NOT NULL,
                rsi REAL,
                macd_signal TEXT,
                macd_value REAL,
                signal_strength REAL,
                volume REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at_br TEXT,  -- Horário brasileiro formatado
                sent_telegram BOOLEAN DEFAULT FALSE
            )
        ''')
        
        # Tabela para configurações
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Tabela para histórico de análises
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS analysis_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                analysis_data TEXT,  -- JSON com dados da análise
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at_br TEXT
            )
        ''')
        
        # Tabela para estatísticas de performance
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS performance_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period TEXT NOT NULL,  -- 'daily', 'weekly', 'monthly'
                date TEXT NOT NULL,
                total_signals INTEGER DEFAULT 0,
                buy_signals INTEGER DEFAULT 0,
                sell_signals INTEGER DEFAULT 0,
                accuracy REAL DEFAULT 0.0,
                profit_loss REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS backtest_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                strategy_version TEXT,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                initial_balance REAL NOT NULL,
                final_balance REAL NOT NULL,
                net_profit REAL NOT NULL,
                total_return_pct REAL NOT NULL,
                total_trades INTEGER NOT NULL DEFAULT 0,
                winning_trades INTEGER NOT NULL DEFAULT 0,
                losing_trades INTEGER NOT NULL DEFAULT 0,
                win_rate REAL NOT NULL DEFAULT 0.0,
                max_drawdown REAL NOT NULL DEFAULT 0.0,
                sharpe_ratio REAL NOT NULL DEFAULT 0.0,
                profit_factor REAL NOT NULL DEFAULT 0.0,
                avg_profit REAL NOT NULL DEFAULT 0.0,
                avg_loss REAL NOT NULL DEFAULT 0.0,
                expectancy_pct REAL NOT NULL DEFAULT 0.0,
                rsi_period INTEGER,
                rsi_min INTEGER,
                rsi_max INTEGER,
                stop_loss_pct REAL DEFAULT 0.0,
                take_profit_pct REAL DEFAULT 0.0,
                fee_rate REAL DEFAULT 0.0,
                slippage REAL DEFAULT 0.0,
                position_size_pct REAL DEFAULT 1.0,
                require_volume BOOLEAN DEFAULT FALSE,
                require_trend BOOLEAN DEFAULT FALSE,
                avoid_ranging BOOLEAN DEFAULT FALSE,
                validation_split_pct REAL DEFAULT 0.0,
                in_sample_end TEXT,
                out_of_sample_start TEXT,
                in_sample_return_pct REAL DEFAULT 0.0,
                in_sample_profit_factor REAL DEFAULT 0.0,
                in_sample_win_rate REAL DEFAULT 0.0,
                in_sample_total_trades INTEGER DEFAULT 0,
                out_of_sample_return_pct REAL DEFAULT 0.0,
                out_of_sample_profit_factor REAL DEFAULT 0.0,
                out_of_sample_win_rate REAL DEFAULT 0.0,
                out_of_sample_total_trades INTEGER DEFAULT 0,
                out_of_sample_expectancy_pct REAL DEFAULT 0.0,
                out_of_sample_passed BOOLEAN DEFAULT FALSE,
                walk_forward_windows INTEGER DEFAULT 0,
                walk_forward_passed BOOLEAN DEFAULT FALSE,
                walk_forward_pass_rate_pct REAL DEFAULT 0.0,
                walk_forward_avg_oos_return_pct REAL DEFAULT 0.0,
                walk_forward_avg_oos_profit_factor REAL DEFAULT 0.0,
                walk_forward_avg_oos_expectancy_pct REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at_br TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS backtest_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                strategy_version TEXT,
                entry_timestamp TEXT,
                exit_timestamp TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                profit_loss_pct REAL NOT NULL,
                profit_loss REAL NOT NULL,
                signal TEXT NOT NULL,
                side TEXT,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES backtest_runs(id) ON DELETE CASCADE
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                strategy_version TEXT,
                signal TEXT NOT NULL,
                side TEXT NOT NULL,
                source TEXT NOT NULL,
                entry_timestamp TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss_pct REAL NOT NULL DEFAULT 0.0,
                take_profit_pct REAL NOT NULL DEFAULT 0.0,
                stop_loss_price REAL,
                take_profit_price REAL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                outcome TEXT NOT NULL DEFAULT 'OPEN',
                close_reason TEXT,
                exit_timestamp TEXT,
                exit_price REAL,
                result_pct REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at_br TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS strategy_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                strategy_version TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                rsi_period INTEGER,
                rsi_min INTEGER,
                rsi_max INTEGER,
                stop_loss_pct REAL DEFAULT 0.0,
                take_profit_pct REAL DEFAULT 0.0,
                require_volume BOOLEAN DEFAULT FALSE,
                require_trend BOOLEAN DEFAULT FALSE,
                avoid_ranging BOOLEAN DEFAULT FALSE,
                source_run_id INTEGER,
                notes TEXT,
                promoted_at_br TEXT,
                deactivated_at_br TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at_br TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at_br TEXT
            )
        ''')

        self._ensure_column(cursor, 'trading_signals', 'strategy_version', 'TEXT')
        self._ensure_column(cursor, 'backtest_runs', 'strategy_version', 'TEXT')
        self._ensure_column(cursor, 'backtest_trades', 'strategy_version', 'TEXT')
        self._ensure_column(cursor, 'paper_trades', 'strategy_version', 'TEXT')
        self._ensure_column(cursor, 'backtest_runs', 'avoid_ranging', 'BOOLEAN DEFAULT FALSE')
        self._ensure_column(cursor, 'paper_trades', 'planned_risk_pct', 'REAL DEFAULT 0.0')
        self._ensure_column(cursor, 'paper_trades', 'planned_risk_amount', 'REAL DEFAULT 0.0')
        self._ensure_column(cursor, 'paper_trades', 'planned_position_notional', 'REAL DEFAULT 0.0')
        self._ensure_column(cursor, 'paper_trades', 'planned_quantity', 'REAL DEFAULT 0.0')
        self._ensure_column(cursor, 'paper_trades', 'account_reference_balance', 'REAL DEFAULT 0.0')
        self._ensure_column(cursor, 'backtest_runs', 'validation_split_pct', 'REAL DEFAULT 0.0')
        self._ensure_column(cursor, 'backtest_runs', 'in_sample_end', 'TEXT')
        self._ensure_column(cursor, 'backtest_runs', 'out_of_sample_start', 'TEXT')
        self._ensure_column(cursor, 'backtest_runs', 'in_sample_return_pct', 'REAL DEFAULT 0.0')
        self._ensure_column(cursor, 'backtest_runs', 'in_sample_profit_factor', 'REAL DEFAULT 0.0')
        self._ensure_column(cursor, 'backtest_runs', 'in_sample_win_rate', 'REAL DEFAULT 0.0')
        self._ensure_column(cursor, 'backtest_runs', 'in_sample_total_trades', 'INTEGER DEFAULT 0')
        self._ensure_column(cursor, 'backtest_runs', 'out_of_sample_return_pct', 'REAL DEFAULT 0.0')
        self._ensure_column(cursor, 'backtest_runs', 'out_of_sample_profit_factor', 'REAL DEFAULT 0.0')
        self._ensure_column(cursor, 'backtest_runs', 'out_of_sample_win_rate', 'REAL DEFAULT 0.0')
        self._ensure_column(cursor, 'backtest_runs', 'out_of_sample_total_trades', 'INTEGER DEFAULT 0')
        self._ensure_column(cursor, 'backtest_runs', 'out_of_sample_expectancy_pct', 'REAL DEFAULT 0.0')
        self._ensure_column(cursor, 'backtest_runs', 'out_of_sample_passed', 'BOOLEAN DEFAULT FALSE')
        self._ensure_column(cursor, 'backtest_runs', 'walk_forward_windows', 'INTEGER DEFAULT 0')
        self._ensure_column(cursor, 'backtest_runs', 'walk_forward_passed', 'BOOLEAN DEFAULT FALSE')
        self._ensure_column(cursor, 'backtest_runs', 'walk_forward_pass_rate_pct', 'REAL DEFAULT 0.0')
        self._ensure_column(cursor, 'backtest_runs', 'walk_forward_avg_oos_return_pct', 'REAL DEFAULT 0.0')
        self._ensure_column(cursor, 'backtest_runs', 'walk_forward_avg_oos_profit_factor', 'REAL DEFAULT 0.0')
        self._ensure_column(cursor, 'backtest_runs', 'walk_forward_avg_oos_expectancy_pct', 'REAL DEFAULT 0.0')
        self._ensure_column(cursor, 'strategy_profiles', 'source_run_id', 'INTEGER')
        self._ensure_column(cursor, 'strategy_profiles', 'avoid_ranging', 'BOOLEAN DEFAULT FALSE')
        self._ensure_column(cursor, 'strategy_profiles', 'notes', 'TEXT')
        self._ensure_column(cursor, 'strategy_profiles', 'promoted_at_br', 'TEXT')
        self._ensure_column(cursor, 'strategy_profiles', 'deactivated_at_br', 'TEXT')
        self._ensure_column(cursor, 'strategy_profiles', 'updated_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
        self._ensure_column(cursor, 'strategy_profiles', 'updated_at_br', 'TEXT')

        conn.commit()
        conn.close()

    def _ensure_column(self, cursor, table_name: str, column_name: str, column_definition: str):
        """Adicionar coluna em instalacoes antigas sem destruir o banco existente."""
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing_columns = {row[1] for row in cursor.fetchall()}
        if column_name not in existing_columns:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")

    def save_strategy_profile(self, profile_data: Dict[str, Any]) -> int:
        """Criar ou atualizar um perfil/versionamento de estrategia."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            symbol = profile_data.get('symbol')
            timeframe = profile_data.get('timeframe')
            strategy_version = profile_data.get('strategy_version')

            cursor.execute(
                '''
                SELECT id FROM strategy_profiles
                WHERE symbol = ? AND timeframe = ? AND strategy_version = ?
                ORDER BY id DESC
                LIMIT 1
                ''',
                (symbol, timeframe, strategy_version),
            )
            existing = cursor.fetchone()
            now_br = format_brazil_time()

            values = {
                'status': profile_data.get('status', 'draft'),
                'rsi_period': profile_data.get('rsi_period'),
                'rsi_min': profile_data.get('rsi_min'),
                'rsi_max': profile_data.get('rsi_max'),
                'stop_loss_pct': profile_data.get('stop_loss_pct', 0.0),
                'take_profit_pct': profile_data.get('take_profit_pct', 0.0),
                'require_volume': int(bool(profile_data.get('require_volume', False))),
                'require_trend': int(bool(profile_data.get('require_trend', False))),
                'avoid_ranging': int(bool(profile_data.get('avoid_ranging', False))),
                'source_run_id': profile_data.get('source_run_id'),
                'notes': profile_data.get('notes'),
                'promoted_at_br': profile_data.get('promoted_at_br'),
                'deactivated_at_br': profile_data.get('deactivated_at_br'),
                'updated_at_br': now_br,
            }

            if existing:
                cursor.execute(
                    '''
                    UPDATE strategy_profiles
                    SET status = ?, rsi_period = ?, rsi_min = ?, rsi_max = ?,
                        stop_loss_pct = ?, take_profit_pct = ?, require_volume = ?, require_trend = ?, avoid_ranging = ?,
                        source_run_id = ?, notes = ?, promoted_at_br = ?, deactivated_at_br = ?,
                        updated_at = CURRENT_TIMESTAMP, updated_at_br = ?
                    WHERE id = ?
                    ''',
                    (
                        values['status'],
                        values['rsi_period'],
                        values['rsi_min'],
                        values['rsi_max'],
                        values['stop_loss_pct'],
                        values['take_profit_pct'],
                        values['require_volume'],
                        values['require_trend'],
                        values['avoid_ranging'],
                        values['source_run_id'],
                        values['notes'],
                        values['promoted_at_br'],
                        values['deactivated_at_br'],
                        values['updated_at_br'],
                        existing['id'],
                    ),
                )
                profile_id = existing['id']
            else:
                cursor.execute(
                    '''
                    INSERT INTO strategy_profiles (
                        symbol, timeframe, strategy_version, status, rsi_period, rsi_min, rsi_max,
                        stop_loss_pct, take_profit_pct, require_volume, require_trend, avoid_ranging, source_run_id,
                        notes, promoted_at_br, deactivated_at_br, created_at_br, updated_at_br
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        symbol,
                        timeframe,
                        strategy_version,
                        values['status'],
                        values['rsi_period'],
                        values['rsi_min'],
                        values['rsi_max'],
                        values['stop_loss_pct'],
                        values['take_profit_pct'],
                        values['require_volume'],
                        values['require_trend'],
                        values['avoid_ranging'],
                        values['source_run_id'],
                        values['notes'],
                        values['promoted_at_br'],
                        values['deactivated_at_br'],
                        now_br,
                        now_br,
                    ),
                )
                profile_id = cursor.lastrowid

            conn.commit()
            return profile_id
        finally:
            conn.close()

    def get_strategy_profiles(
        self,
        symbol: str = None,
        timeframe: str = None,
        status: str = None,
        limit: int = 50,
    ) -> List[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT * FROM strategy_profiles
            WHERE (? IS NULL OR symbol = ?)
              AND (? IS NULL OR timeframe = ?)
              AND (? IS NULL OR status = ?)
            ORDER BY
              CASE WHEN status = 'active' THEN 0 ELSE 1 END,
              COALESCE(updated_at, created_at) DESC
            LIMIT ?
            ''',
            (symbol, symbol, timeframe, timeframe, status, status, limit),
        )
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def get_active_strategy_profile(self, symbol: str, timeframe: str) -> Optional[Dict]:
        profiles = self.get_strategy_profiles(symbol=symbol, timeframe=timeframe, status='active', limit=1)
        return profiles[0] if profiles else None

    def get_backtest_run_promotion_readiness(self, run_id: int) -> Dict[str, Any]:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM backtest_runs WHERE id = ?', (run_id,))
            run = cursor.fetchone()
        finally:
            conn.close()

        if not run:
            return {
                "ready": False,
                "reasons": ["Backtest nao encontrado."],
                "run": None,
            }

        run = dict(run)
        reasons = []
        total_trades = int(run.get('total_trades', 0) or 0)
        total_return_pct = float(run.get('total_return_pct', 0.0) or 0.0)
        profit_factor = float(run.get('profit_factor', 0.0) or 0.0)
        expectancy_pct = float(run.get('expectancy_pct', 0.0) or 0.0)
        max_drawdown = float(run.get('max_drawdown', 0.0) or 0.0)
        out_of_sample_passed = bool(run.get('out_of_sample_passed', False))
        walk_forward_windows = int(run.get('walk_forward_windows', 0) or 0)
        walk_forward_passed = bool(run.get('walk_forward_passed', False))

        if total_trades < ProductionConfig.MIN_BACKTEST_TRADES_FOR_PROMOTION:
            reasons.append(
                f"Amostra de backtest insuficiente: {total_trades} trades "
                f"(minimo {ProductionConfig.MIN_BACKTEST_TRADES_FOR_PROMOTION})."
            )
        if total_return_pct <= 0:
            reasons.append("Retorno total do backtest nao positivo.")
        if profit_factor < ProductionConfig.MIN_PROMOTION_PROFIT_FACTOR:
            reasons.append(
                f"Profit factor abaixo do minimo: {profit_factor:.2f} "
                f"(minimo {ProductionConfig.MIN_PROMOTION_PROFIT_FACTOR:.2f})."
            )
        if expectancy_pct <= 0:
            reasons.append("Expectancy do backtest nao positiva.")
        if max_drawdown > ProductionConfig.MAX_PROMOTION_DRAWDOWN:
            reasons.append(
                f"Drawdown acima do limite: {max_drawdown:.2f}% "
                f"(maximo {ProductionConfig.MAX_PROMOTION_DRAWDOWN:.2f}%)."
            )
        if not out_of_sample_passed:
            reasons.append("Setup nao passou na validacao fora da amostra.")
        if walk_forward_windows > 0 and not walk_forward_passed:
            reasons.append("Setup nao passou no walk-forward.")

        return {
            "ready": not reasons,
            "reasons": reasons,
            "run": run,
            "thresholds": {
                "min_backtest_trades": ProductionConfig.MIN_BACKTEST_TRADES_FOR_PROMOTION,
                "min_profit_factor": ProductionConfig.MIN_PROMOTION_PROFIT_FACTOR,
                "max_drawdown": ProductionConfig.MAX_PROMOTION_DRAWDOWN,
            },
        }

    def activate_strategy_profile(self, profile_id: int) -> Optional[Dict]:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM strategy_profiles WHERE id = ?', (profile_id,))
            profile = cursor.fetchone()
            if not profile:
                return None

            now_br = format_brazil_time()
            cursor.execute(
                '''
                UPDATE strategy_profiles
                SET status = 'inactive',
                    updated_at = CURRENT_TIMESTAMP,
                    updated_at_br = ?
                WHERE symbol = ? AND timeframe = ? AND status = 'active' AND id != ?
                ''',
                (now_br, profile['symbol'], profile['timeframe'], profile_id),
            )
            cursor.execute(
                '''
                UPDATE strategy_profiles
                SET status = 'active',
                    promoted_at_br = ?,
                    deactivated_at_br = NULL,
                    updated_at = CURRENT_TIMESTAMP,
                    updated_at_br = ?
                WHERE id = ?
                ''',
                (now_br, now_br, profile_id),
            )
            conn.commit()
        finally:
            conn.close()

        return self.get_strategy_profiles(limit=1, symbol=profile['symbol'], timeframe=profile['timeframe'], status='active')[0]

    def deactivate_strategy_profile(self, profile_id: int, reason: str = None) -> Optional[Dict]:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM strategy_profiles WHERE id = ?', (profile_id,))
            profile = cursor.fetchone()
            if not profile:
                return None

            notes = reason if reason else profile['notes']
            now_br = format_brazil_time()
            cursor.execute(
                '''
                UPDATE strategy_profiles
                SET status = 'disabled',
                    notes = ?,
                    deactivated_at_br = ?,
                    updated_at = CURRENT_TIMESTAMP,
                    updated_at_br = ?
                WHERE id = ?
                ''',
                (notes, now_br, now_br, profile_id),
            )
            conn.commit()
        finally:
            conn.close()

        profiles = self.get_strategy_profiles(limit=1, symbol=profile['symbol'], timeframe=profile['timeframe'])
        return profiles[0] if profiles else None

    def promote_backtest_run(self, run_id: int, notes: str = None, require_ready: bool = True) -> Optional[Dict]:
        if require_ready:
            readiness = self.get_backtest_run_promotion_readiness(run_id)
            if not readiness.get('ready'):
                return None

        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM backtest_runs WHERE id = ?', (run_id,))
        run = cursor.fetchone()
        conn.close()
        if not run:
            return None

        run = dict(run)
        strategy_version = run.get('strategy_version') or build_strategy_version(
            symbol=run.get('symbol'),
            timeframe=run.get('timeframe'),
            rsi_period=run.get('rsi_period'),
            rsi_min=run.get('rsi_min'),
            rsi_max=run.get('rsi_max'),
            stop_loss_pct=run.get('stop_loss_pct', 0.0),
            take_profit_pct=run.get('take_profit_pct', 0.0),
            require_volume=bool(run.get('require_volume', False)),
            require_trend=bool(run.get('require_trend', False)),
            avoid_ranging=bool(run.get('avoid_ranging', False)),
        )
        profile_id = self.save_strategy_profile(
            {
                'symbol': run.get('symbol'),
                'timeframe': run.get('timeframe'),
                'strategy_version': strategy_version,
                'status': 'active',
                'rsi_period': run.get('rsi_period'),
                'rsi_min': run.get('rsi_min'),
                'rsi_max': run.get('rsi_max'),
                'stop_loss_pct': run.get('stop_loss_pct', 0.0),
                'take_profit_pct': run.get('take_profit_pct', 0.0),
                'require_volume': bool(run.get('require_volume', False)),
                'require_trend': bool(run.get('require_trend', False)),
                'avoid_ranging': bool(run.get('avoid_ranging', False)),
                'source_run_id': run_id,
                'notes': notes,
                'promoted_at_br': format_brazil_time(),
            }
        )
        return self.activate_strategy_profile(profile_id)
    
    def save_trading_signal(self, signal_data: Dict[str, Any]) -> int:
        """Salvar um sinal de trading"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO trading_signals 
            (symbol, timeframe, strategy_version, signal_type, price, rsi, macd_signal, macd_value, 
             signal_strength, volume, created_at_br)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            signal_data.get('symbol'),
            signal_data.get('timeframe'),
            signal_data.get('strategy_version'),
            signal_data.get('signal'),
            signal_data.get('price'),
            signal_data.get('rsi'),
            signal_data.get('macd_signal'),
            signal_data.get('macd_value'),
            signal_data.get('signal_strength', 0.0),
            signal_data.get('volume'),
            format_brazil_time()
        ))
        
        signal_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return signal_id

    def create_paper_trade(self, trade_data: Dict[str, Any]) -> int:
        """Criar um paper trade para acompanhamento de outcome do sinal."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            columns = [
                'symbol', 'timeframe', 'strategy_version', 'signal', 'side', 'source', 'entry_timestamp', 'entry_price',
                'stop_loss_pct', 'take_profit_pct', 'stop_loss_price', 'take_profit_price',
                'planned_risk_pct', 'planned_risk_amount', 'planned_position_notional', 'planned_quantity',
                'account_reference_balance',
                'status', 'outcome', 'close_reason', 'exit_timestamp', 'exit_price', 'result_pct',
                'created_at_br'
            ]
            values = {
                'symbol': trade_data.get('symbol'),
                'timeframe': trade_data.get('timeframe'),
                'strategy_version': trade_data.get('strategy_version'),
                'signal': trade_data.get('signal'),
                'side': trade_data.get('side'),
                'source': trade_data.get('source', 'system'),
                'entry_timestamp': trade_data.get('entry_timestamp'),
                'entry_price': trade_data.get('entry_price'),
                'stop_loss_pct': trade_data.get('stop_loss_pct', 0.0),
                'take_profit_pct': trade_data.get('take_profit_pct', 0.0),
                'stop_loss_price': trade_data.get('stop_loss_price'),
                'take_profit_price': trade_data.get('take_profit_price'),
                'planned_risk_pct': trade_data.get('planned_risk_pct', 0.0),
                'planned_risk_amount': trade_data.get('planned_risk_amount', 0.0),
                'planned_position_notional': trade_data.get('planned_position_notional', 0.0),
                'planned_quantity': trade_data.get('planned_quantity', 0.0),
                'account_reference_balance': trade_data.get('account_reference_balance', 0.0),
                'status': trade_data.get('status', 'OPEN'),
                'outcome': trade_data.get('outcome', 'OPEN'),
                'close_reason': trade_data.get('close_reason'),
                'exit_timestamp': trade_data.get('exit_timestamp'),
                'exit_price': trade_data.get('exit_price'),
                'result_pct': trade_data.get('result_pct', 0.0),
                'created_at_br': format_brazil_time(),
            }
            placeholders = ', '.join(['?'] * len(columns))
            cursor.execute(
                f"INSERT INTO paper_trades ({', '.join(columns)}) VALUES ({placeholders})",
                tuple(values[column] for column in columns),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def get_open_paper_trades(self, symbol: str = None, timeframe: str = None, strategy_version: str = None) -> List[Dict]:
        """Buscar paper trades ainda abertos."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM paper_trades
            WHERE status = 'OPEN'
              AND (? IS NULL OR symbol = ?)
              AND (? IS NULL OR timeframe = ?)
              AND (? IS NULL OR strategy_version = ?)
            ORDER BY entry_timestamp ASC
        ''', (symbol, symbol, timeframe, timeframe, strategy_version, strategy_version))
        trades = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return trades

    def get_open_portfolio_risk_summary(
        self,
        symbol: str = None,
        timeframe: str = None,
        strategy_version: str = None,
    ) -> Dict[str, Any]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT
                COUNT(*) AS open_trades,
                COALESCE(SUM(planned_risk_pct), 0) AS total_open_risk_pct,
                COALESCE(SUM(planned_risk_amount), 0) AS total_open_risk_amount,
                COALESCE(SUM(planned_position_notional), 0) AS total_open_position_notional
            FROM paper_trades
            WHERE status = 'OPEN'
              AND (? IS NULL OR symbol = ?)
              AND (? IS NULL OR timeframe = ?)
              AND (? IS NULL OR strategy_version = ?)
            ''',
            (symbol, symbol, timeframe, timeframe, strategy_version, strategy_version),
        )
        summary = dict(cursor.fetchone())
        conn.close()
        return summary

    def get_daily_paper_guardrail_summary(
        self,
        symbol: str = None,
        timeframe: str = None,
        strategy_version: str = None,
        session_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        reference_dt = session_date or get_brazil_datetime_naive()
        if hasattr(reference_dt, "to_pydatetime"):
            reference_dt = reference_dt.to_pydatetime()
        day_start = reference_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT
                id,
                outcome,
                result_pct,
                planned_position_notional,
                account_reference_balance,
                exit_timestamp
            FROM paper_trades
            WHERE status = 'CLOSED'
              AND exit_timestamp IS NOT NULL
              AND exit_timestamp >= ?
              AND exit_timestamp < ?
              AND (? IS NULL OR symbol = ?)
              AND (? IS NULL OR timeframe = ?)
              AND (? IS NULL OR strategy_version = ?)
            ORDER BY exit_timestamp DESC
            ''',
            (
                day_start.isoformat(),
                day_end.isoformat(),
                symbol,
                symbol,
                timeframe,
                timeframe,
                strategy_version,
                strategy_version,
            ),
        )
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()

        reference_balance = max(
            float(row.get("account_reference_balance", 0.0) or 0.0) for row in rows
        ) if rows else float(ProductionConfig.PAPER_ACCOUNT_BALANCE)
        if reference_balance <= 0:
            reference_balance = float(ProductionConfig.PAPER_ACCOUNT_BALANCE)

        realized_pnl = sum(
            float(row.get("planned_position_notional", 0.0) or 0.0) * float(row.get("result_pct", 0.0) or 0.0) / 100
            for row in rows
        )
        realized_pnl_pct = (realized_pnl / reference_balance * 100) if reference_balance else 0.0

        consecutive_losses = 0
        for row in rows:
            if row.get("outcome") == "LOSS":
                consecutive_losses += 1
                continue
            if row.get("outcome") in {"WIN", "FLAT"}:
                break

        wins = sum(1 for row in rows if row.get("outcome") == "WIN")
        losses = sum(1 for row in rows if row.get("outcome") == "LOSS")
        flats = sum(1 for row in rows if row.get("outcome") == "FLAT")

        return {
            "session_date": day_start.date().isoformat(),
            "closed_trades": len(rows),
            "wins": wins,
            "losses": losses,
            "flats": flats,
            "realized_pnl": round(realized_pnl, 2),
            "realized_pnl_pct": round(realized_pnl_pct, 4),
            "reference_balance": round(reference_balance, 2),
            "consecutive_losses": consecutive_losses,
        }

    def get_recent_paper_trades(
        self,
        limit: int = 50,
        symbol: str = None,
        timeframe: str = None,
        strategy_version: str = None,
    ) -> List[Dict]:
        """Buscar paper trades recentes, abertos ou fechados."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM paper_trades
            WHERE (? IS NULL OR symbol = ?)
              AND (? IS NULL OR timeframe = ?)
              AND (? IS NULL OR strategy_version = ?)
            ORDER BY created_at DESC
            LIMIT ?
        ''', (symbol, symbol, timeframe, timeframe, strategy_version, strategy_version, limit))
        trades = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return trades

    def close_paper_trade(
        self,
        trade_id: int,
        exit_timestamp: str,
        exit_price: float,
        outcome: str,
        close_reason: str,
        result_pct: float,
    ):
        """Fechar paper trade com outcome calculado."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE paper_trades
            SET status = 'CLOSED',
                outcome = ?,
                close_reason = ?,
                exit_timestamp = ?,
                exit_price = ?,
                result_pct = ?
            WHERE id = ?
        ''', (outcome, close_reason, exit_timestamp, exit_price, result_pct, trade_id))
        conn.commit()
        conn.close()

    def get_paper_trade_summary(
        self,
        symbol: str = None,
        timeframe: str = None,
        strategy_version: str = None,
    ) -> Dict[str, Any]:
        """Resumo agregado de paper trades para medir edge live/paper."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT
                COUNT(*) AS total_trades,
                COALESCE(SUM(CASE WHEN status = 'OPEN' THEN 1 ELSE 0 END), 0) AS open_trades,
                COALESCE(SUM(CASE WHEN status = 'CLOSED' THEN 1 ELSE 0 END), 0) AS closed_trades,
                COALESCE(SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END), 0) AS wins,
                COALESCE(SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END), 0) AS losses,
                COALESCE(SUM(CASE WHEN outcome = 'FLAT' THEN 1 ELSE 0 END), 0) AS flats,
                COALESCE(AVG(CASE WHEN status = 'CLOSED' THEN result_pct END), 0) AS avg_result_pct,
                COALESCE(AVG(CASE WHEN outcome = 'WIN' THEN result_pct END), 0) AS avg_win_pct,
                COALESCE(AVG(CASE WHEN outcome = 'LOSS' THEN result_pct END), 0) AS avg_loss_pct,
                COALESCE(SUM(CASE WHEN status = 'CLOSED' AND result_pct > 0 THEN result_pct ELSE 0 END), 0) AS gross_profit_pct,
                COALESCE(SUM(CASE WHEN status = 'CLOSED' AND result_pct < 0 THEN ABS(result_pct) ELSE 0 END), 0) AS gross_loss_pct,
                COALESCE(SUM(CASE WHEN status = 'CLOSED' THEN result_pct ELSE 0 END), 0) AS total_result_pct
            FROM paper_trades
            WHERE (? IS NULL OR symbol = ?)
              AND (? IS NULL OR timeframe = ?)
              AND (? IS NULL OR strategy_version = ?)
        ''', (symbol, symbol, timeframe, timeframe, strategy_version, strategy_version))
        summary = dict(cursor.fetchone())
        closed = summary.get('closed_trades', 0) or 0
        wins = summary.get('wins', 0) or 0
        summary['win_rate'] = round((wins / closed * 100), 2) if closed else 0.0
        gross_profit = float(summary.get('gross_profit_pct', 0.0) or 0.0)
        gross_loss = float(summary.get('gross_loss_pct', 0.0) or 0.0)
        if gross_loss > 0:
            summary['profit_factor'] = round(gross_profit / gross_loss, 4)
        elif gross_profit > 0:
            summary['profit_factor'] = float('inf')
        else:
            summary['profit_factor'] = 0.0
        conn.close()
        return summary
    
    def get_recent_signals(self, limit: int = 100, symbol: str = None) -> List[Dict]:
        """Buscar sinais recentes"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        query = '''
            SELECT * FROM trading_signals 
            WHERE (? IS NULL OR symbol = ?)
            ORDER BY created_at DESC 
            LIMIT ?
        '''
        cursor.execute(query, (symbol, symbol, limit))
        signals = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        return signals
    
    def get_signals_by_date_range(self, start_date: str, end_date: str, symbol: str = None) -> List[Dict]:
        """Buscar sinais por período"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        query = '''
            SELECT * FROM trading_signals 
            WHERE created_at BETWEEN ? AND ?
            AND (? IS NULL OR symbol = ?)
            ORDER BY created_at DESC
        '''
        cursor.execute(query, (start_date, end_date, symbol, symbol))
        signals = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        return signals
    
    def save_setting(self, key: str, value: Any):
        """Salvar configuração"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO settings (key, value)
            VALUES (?, ?)
        ''', (key, json.dumps(value) if isinstance(value, (dict, list)) else str(value)))
        
        conn.commit()
        conn.close()
    
    def get_setting(self, key: str, default: Any = None) -> Any:
        """Buscar configuração"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
        result = cursor.fetchone()
        
        conn.close()
        
        if result:
            value = result['value']
            # Tentar fazer parse de JSON
            try:
                return json.loads(value)
            except:
                return value
        return default
    
    def save_analysis(self, symbol: str, timeframe: str, analysis_data: Dict):
        """Salvar dados de análise"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO analysis_history (symbol, timeframe, analysis_data, created_at_br)
            VALUES (?, ?, ?, ?)
        ''', (symbol, timeframe, json.dumps(analysis_data), format_brazil_time()))
        
        conn.commit()
        conn.close()
    
    def save_backtest_result(self, run_data: Dict[str, Any], trades: List[Dict[str, Any]]) -> int:
        """Salvar um backtest completo com resumo e trades."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()

            column_values = {
                'symbol': run_data.get('symbol'),
                'timeframe': run_data.get('timeframe'),
                'strategy_version': run_data.get('strategy_version'),
                'start_date': run_data.get('start_date'),
                'end_date': run_data.get('end_date'),
                'initial_balance': run_data.get('initial_balance'),
                'final_balance': run_data.get('final_balance'),
                'net_profit': run_data.get('net_profit'),
                'total_return_pct': run_data.get('total_return_pct'),
                'total_trades': run_data.get('total_trades', 0),
                'winning_trades': run_data.get('winning_trades', 0),
                'losing_trades': run_data.get('losing_trades', 0),
                'win_rate': run_data.get('win_rate', 0.0),
                'max_drawdown': run_data.get('max_drawdown', 0.0),
                'sharpe_ratio': run_data.get('sharpe_ratio', 0.0),
                'profit_factor': run_data.get('profit_factor', 0.0),
                'avg_profit': run_data.get('avg_profit', 0.0),
                'avg_loss': run_data.get('avg_loss', 0.0),
                'expectancy_pct': run_data.get('expectancy_pct', 0.0),
                'rsi_period': run_data.get('rsi_period'),
                'rsi_min': run_data.get('rsi_min'),
                'rsi_max': run_data.get('rsi_max'),
                'stop_loss_pct': run_data.get('stop_loss_pct', 0.0),
                'take_profit_pct': run_data.get('take_profit_pct', 0.0),
                'fee_rate': run_data.get('fee_rate', 0.0),
                'slippage': run_data.get('slippage', 0.0),
                'position_size_pct': run_data.get('position_size_pct', 1.0),
                'require_volume': int(bool(run_data.get('require_volume', False))),
                'require_trend': int(bool(run_data.get('require_trend', False))),
                'avoid_ranging': int(bool(run_data.get('avoid_ranging', False))),
                'validation_split_pct': run_data.get('validation_split_pct', 0.0),
                'in_sample_end': run_data.get('in_sample_end'),
                'out_of_sample_start': run_data.get('out_of_sample_start'),
                'in_sample_return_pct': run_data.get('in_sample_return_pct', 0.0),
                'in_sample_profit_factor': run_data.get('in_sample_profit_factor', 0.0),
                'in_sample_win_rate': run_data.get('in_sample_win_rate', 0.0),
                'in_sample_total_trades': run_data.get('in_sample_total_trades', 0),
                'out_of_sample_return_pct': run_data.get('out_of_sample_return_pct', 0.0),
                'out_of_sample_profit_factor': run_data.get('out_of_sample_profit_factor', 0.0),
                'out_of_sample_win_rate': run_data.get('out_of_sample_win_rate', 0.0),
                'out_of_sample_total_trades': run_data.get('out_of_sample_total_trades', 0),
                'out_of_sample_expectancy_pct': run_data.get('out_of_sample_expectancy_pct', 0.0),
                'out_of_sample_passed': int(bool(run_data.get('out_of_sample_passed', False))),
                'walk_forward_windows': run_data.get('walk_forward_windows', 0),
                'walk_forward_passed': int(bool(run_data.get('walk_forward_passed', False))),
                'walk_forward_pass_rate_pct': run_data.get('walk_forward_pass_rate_pct', 0.0),
                'walk_forward_avg_oos_return_pct': run_data.get('walk_forward_avg_oos_return_pct', 0.0),
                'walk_forward_avg_oos_profit_factor': run_data.get('walk_forward_avg_oos_profit_factor', 0.0),
                'walk_forward_avg_oos_expectancy_pct': run_data.get('walk_forward_avg_oos_expectancy_pct', 0.0),
                'created_at_br': format_brazil_time(),
            }
            columns = list(column_values.keys())
            placeholders = ', '.join(['?'] * len(columns))
            cursor.execute(
                f"INSERT INTO backtest_runs ({', '.join(columns)}) VALUES ({placeholders})",
                tuple(column_values[column] for column in columns),
            )

            run_id = cursor.lastrowid

            trade_rows = [
                (
                    run_id,
                    run_data.get('symbol'),
                    run_data.get('timeframe'),
                    run_data.get('strategy_version'),
                    self._normalize_timestamp(trade.get('entry_timestamp')),
                    self._normalize_timestamp(trade.get('timestamp')),
                    trade.get('entry_price'),
                    trade.get('price'),
                    trade.get('profit_loss_pct'),
                    trade.get('profit_loss'),
                    trade.get('signal'),
                    trade.get('side'),
                    trade.get('reason'),
                )
                for trade in trades
            ]

            if trade_rows:
                cursor.executemany('''
                    INSERT INTO backtest_trades (
                        run_id, symbol, timeframe, strategy_version, entry_timestamp, exit_timestamp, entry_price, exit_price,
                        profit_loss_pct, profit_loss, signal, side, reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', trade_rows)

            conn.commit()
            return run_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_backtest_runs(
        self,
        limit: int = 50,
        symbol: str = None,
        timeframe: str = None,
        strategy_version: str = None,
    ) -> List[Dict]:
        """Buscar execucoes recentes de backtest."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM backtest_runs
            WHERE (? IS NULL OR symbol = ?)
              AND (? IS NULL OR timeframe = ?)
              AND (? IS NULL OR strategy_version = ?)
            ORDER BY created_at DESC
            LIMIT ?
        ''', (symbol, symbol, timeframe, timeframe, strategy_version, strategy_version, limit))
        rows = [dict(row) for row in cursor.fetchall()]

        conn.close()
        return rows

    def get_backtest_trades(self, run_id: int) -> List[Dict]:
        """Buscar trades de uma execucao especifica."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM backtest_trades
            WHERE run_id = ?
            ORDER BY exit_timestamp ASC
        ''', (run_id,))
        trades = [dict(row) for row in cursor.fetchall()]

        conn.close()
        return trades

    def get_backtest_performance_summary(
        self,
        symbol: str = None,
        timeframe: str = None,
        strategy_version: str = None,
    ) -> Dict[str, Any]:
        """Retornar agregados de backtest por simbolo/timeframe."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT
                COUNT(*) AS total_runs,
                COALESCE(SUM(total_trades), 0) AS total_trades,
                COALESCE(AVG(total_return_pct), 0) AS avg_return_pct,
                COALESCE(AVG(win_rate), 0) AS avg_win_rate,
                COALESCE(AVG(profit_factor), 0) AS avg_profit_factor,
                COALESCE(AVG(expectancy_pct), 0) AS avg_expectancy_pct,
                COALESCE(AVG(out_of_sample_return_pct), 0) AS avg_out_of_sample_return_pct,
                COALESCE(AVG(out_of_sample_profit_factor), 0) AS avg_out_of_sample_profit_factor,
                COALESCE(AVG(out_of_sample_expectancy_pct), 0) AS avg_out_of_sample_expectancy_pct,
                COALESCE(SUM(CASE WHEN out_of_sample_passed = 1 THEN 1 ELSE 0 END), 0) AS passed_oos_runs,
                COALESCE(AVG(walk_forward_pass_rate_pct), 0) AS avg_walk_forward_pass_rate_pct,
                COALESCE(AVG(walk_forward_avg_oos_return_pct), 0) AS avg_walk_forward_oos_return_pct,
                COALESCE(AVG(walk_forward_avg_oos_profit_factor), 0) AS avg_walk_forward_oos_profit_factor,
                COALESCE(SUM(CASE WHEN walk_forward_passed = 1 THEN 1 ELSE 0 END), 0) AS passed_walk_forward_runs,
                COALESCE(AVG(max_drawdown), 0) AS avg_max_drawdown,
                COALESCE(SUM(net_profit), 0) AS total_net_profit,
                COALESCE(MAX(total_return_pct), 0) AS best_return_pct,
                COALESCE(MIN(total_return_pct), 0) AS worst_return_pct
            FROM backtest_runs
            WHERE (? IS NULL OR symbol = ?)
              AND (? IS NULL OR timeframe = ?)
              AND (? IS NULL OR strategy_version = ?)
        ''', (symbol, symbol, timeframe, timeframe, strategy_version, strategy_version))
        summary = dict(cursor.fetchone())

        cursor.execute('''
            SELECT
                symbol,
                timeframe,
                COUNT(*) AS total_runs,
                COALESCE(SUM(total_trades), 0) AS total_trades,
                ROUND(COALESCE(AVG(total_return_pct), 0), 2) AS avg_return_pct,
                ROUND(COALESCE(AVG(win_rate), 0), 2) AS avg_win_rate,
                ROUND(COALESCE(AVG(profit_factor), 0), 2) AS avg_profit_factor,
                ROUND(COALESCE(AVG(expectancy_pct), 0), 2) AS avg_expectancy_pct,
                ROUND(COALESCE(AVG(out_of_sample_return_pct), 0), 2) AS avg_out_of_sample_return_pct,
                ROUND(COALESCE(AVG(out_of_sample_profit_factor), 0), 2) AS avg_out_of_sample_profit_factor,
                ROUND(COALESCE(AVG(out_of_sample_expectancy_pct), 0), 2) AS avg_out_of_sample_expectancy_pct,
                COALESCE(SUM(CASE WHEN out_of_sample_passed = 1 THEN 1 ELSE 0 END), 0) AS passed_oos_runs,
                ROUND(COALESCE(AVG(walk_forward_pass_rate_pct), 0), 2) AS avg_walk_forward_pass_rate_pct,
                ROUND(COALESCE(AVG(walk_forward_avg_oos_return_pct), 0), 2) AS avg_walk_forward_oos_return_pct,
                ROUND(COALESCE(AVG(walk_forward_avg_oos_profit_factor), 0), 2) AS avg_walk_forward_oos_profit_factor,
                COALESCE(SUM(CASE WHEN walk_forward_passed = 1 THEN 1 ELSE 0 END), 0) AS passed_walk_forward_runs,
                ROUND(COALESCE(AVG(max_drawdown), 0), 2) AS avg_max_drawdown,
                ROUND(COALESCE(SUM(net_profit), 0), 2) AS total_net_profit
            FROM backtest_runs
            WHERE (? IS NULL OR symbol = ?)
              AND (? IS NULL OR timeframe = ?)
              AND (? IS NULL OR strategy_version = ?)
            GROUP BY symbol, timeframe
            ORDER BY avg_return_pct DESC, total_runs DESC
        ''', (symbol, symbol, timeframe, timeframe, strategy_version, strategy_version))
        summary['breakdown_by_market'] = [dict(row) for row in cursor.fetchall()]

        conn.close()
        return summary

    def get_edge_monitor_summary(
        self,
        symbol: str = None,
        timeframe: str = None,
        strategy_version: str = None,
    ) -> Dict[str, Any]:
        """Comparar baseline de backtest com performance paper/live do mesmo mercado."""
        active_profile = None
        if strategy_version is None and symbol and timeframe:
            active_profile = self.get_active_strategy_profile(symbol=symbol, timeframe=timeframe)
            if active_profile:
                strategy_version = active_profile.get('strategy_version')

        backtest_summary = self.get_backtest_performance_summary(
            symbol=symbol,
            timeframe=timeframe,
            strategy_version=strategy_version,
        )
        paper_summary = self.get_paper_trade_summary(
            symbol=symbol,
            timeframe=timeframe,
            strategy_version=strategy_version,
        )

        has_backtest = int(backtest_summary.get('total_runs', 0) or 0) > 0
        has_live_trades = int(paper_summary.get('closed_trades', 0) or 0) > 0

        use_oos_baseline = has_backtest and (
            float(backtest_summary.get('avg_out_of_sample_profit_factor', 0.0) or 0.0) > 0
            or int(backtest_summary.get('passed_oos_runs', 0) or 0) > 0
        )

        baseline_label = "OOS" if use_oos_baseline else "Backtest"
        baseline_return_pct = float(
            backtest_summary.get('avg_out_of_sample_return_pct' if use_oos_baseline else 'avg_return_pct', 0.0) or 0.0
        )
        baseline_profit_factor = float(
            backtest_summary.get('avg_out_of_sample_profit_factor' if use_oos_baseline else 'avg_profit_factor', 0.0) or 0.0
        )
        baseline_expectancy_pct = float(
            backtest_summary.get('avg_out_of_sample_expectancy_pct' if use_oos_baseline else 'avg_expectancy_pct', 0.0) or 0.0
        )

        paper_profit_factor = paper_summary.get('profit_factor', 0.0)
        if paper_profit_factor == float('inf'):
            paper_profit_factor = 999.0
        paper_profit_factor = float(paper_profit_factor or 0.0)
        paper_avg_result_pct = float(paper_summary.get('avg_result_pct', 0.0) or 0.0)
        paper_total_result_pct = float(paper_summary.get('total_result_pct', 0.0) or 0.0)
        closed_trades = int(paper_summary.get('closed_trades', 0) or 0)

        if baseline_profit_factor > 0:
            profit_factor_alignment_pct = round((paper_profit_factor / baseline_profit_factor) * 100, 2)
        else:
            profit_factor_alignment_pct = 0.0

        expectancy_gap_pct = round(paper_avg_result_pct - baseline_expectancy_pct, 4)
        return_gap_pct = round(paper_total_result_pct - baseline_return_pct, 4)

        if not has_backtest:
            status = "no_backtest"
            status_message = "Sem baseline de backtest para comparar o edge live."
        elif not has_live_trades:
            status = "awaiting_live_data"
            status_message = "Aguardando paper trades fechados para validar o edge live."
        elif closed_trades < ProductionConfig.MIN_PAPER_TRADES_FOR_EDGE_VALIDATION:
            status = "insufficient_live_data"
            status_message = (
                "Amostra paper ainda pequena para concluir sobre degradacao. "
                f"Minimo atual: {ProductionConfig.MIN_PAPER_TRADES_FOR_EDGE_VALIDATION} trades fechados."
            )
        else:
            paper_pf_floor = max(1.0, baseline_profit_factor * 0.85) if baseline_profit_factor > 0 else 1.0
            expectancy_floor = baseline_expectancy_pct * 0.7 if baseline_expectancy_pct > 0 else baseline_expectancy_pct - 0.1

            if paper_profit_factor < 1.0 or paper_total_result_pct <= 0 or (
                baseline_profit_factor > 0 and paper_profit_factor < baseline_profit_factor * 0.8
            ):
                status = "degraded"
                status_message = "Paper trade abaixo do baseline. Edge em degradacao."
            elif paper_profit_factor >= paper_pf_floor and paper_avg_result_pct >= expectancy_floor:
                status = "aligned"
                status_message = "Paper trade alinhado com o baseline. Edge live sustentado."
            else:
                status = "watchlist"
                status_message = "Paper trade ainda inconclusivo. Continuar monitorando."

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "strategy_version": strategy_version,
            "baseline_source": baseline_label,
            "baseline_return_pct": round(baseline_return_pct, 4),
            "baseline_profit_factor": round(baseline_profit_factor, 4),
            "baseline_expectancy_pct": round(baseline_expectancy_pct, 4),
            "paper_closed_trades": closed_trades,
            "paper_win_rate": round(float(paper_summary.get('win_rate', 0.0) or 0.0), 2),
            "paper_avg_result_pct": round(paper_avg_result_pct, 4),
            "paper_total_result_pct": round(paper_total_result_pct, 4),
            "paper_profit_factor": round(paper_profit_factor, 4),
            "profit_factor_alignment_pct": profit_factor_alignment_pct,
            "expectancy_gap_pct": expectancy_gap_pct,
            "return_gap_pct": return_gap_pct,
            "status": status,
            "status_message": status_message,
            "has_backtest": has_backtest,
            "has_live_trades": has_live_trades,
            "active_profile": active_profile,
        }

    def get_strategy_governance_summary(
        self,
        symbol: str = None,
        timeframe: str = None,
        active_only: bool = False,
        limit: int = 50,
    ) -> Dict[str, Any]:
        status_filter = 'active' if active_only else None
        profiles = self.get_strategy_profiles(
            symbol=symbol,
            timeframe=timeframe,
            status=status_filter,
            limit=limit,
        )

        rows = []
        counts = {
            "approved": 0,
            "observing": 0,
            "blocked": 0,
            "ready_for_paper": 0,
            "needs_work": 0,
            "disabled": 0,
        }

        for profile in profiles:
            readiness = None
            if profile.get('source_run_id'):
                readiness = self.get_backtest_run_promotion_readiness(profile['source_run_id'])

            edge_summary = self.get_edge_monitor_summary(
                symbol=profile.get('symbol'),
                timeframe=profile.get('timeframe'),
                strategy_version=profile.get('strategy_version'),
            )

            governance_status = "observing"
            governance_message = "Setup ativo em acompanhamento."
            if profile.get('status') == 'disabled':
                governance_status = "disabled"
                governance_message = "Setup desativado."
            elif profile.get('status') != 'active':
                if readiness and readiness.get('ready'):
                    governance_status = "ready_for_paper"
                    governance_message = "Setup apto para ativacao em paper."
                else:
                    governance_status = "needs_work"
                    governance_message = "Setup ainda nao atingiu os criterios minimos."
            else:
                edge_status = edge_summary.get('status')
                if edge_status == 'aligned':
                    governance_status = "approved"
                    governance_message = "Setup aprovado em paper com edge alinhado ao baseline."
                elif edge_status in {'awaiting_live_data', 'insufficient_live_data', 'watchlist'}:
                    governance_status = "observing"
                    governance_message = edge_summary.get('status_message') or "Setup ativo, aguardando confirmacao em paper."
                elif edge_status in {'degraded', 'no_backtest'}:
                    governance_status = "blocked"
                    governance_message = edge_summary.get('status_message') or "Setup bloqueado por degradacao."

            counts[governance_status] = counts.get(governance_status, 0) + 1
            rows.append(
                {
                    "profile_id": profile.get('id'),
                    "symbol": profile.get('symbol'),
                    "timeframe": profile.get('timeframe'),
                    "strategy_version": profile.get('strategy_version'),
                    "profile_status": profile.get('status'),
                    "governance_status": governance_status,
                    "governance_message": governance_message,
                    "source_run_id": profile.get('source_run_id'),
                    "paper_closed_trades": edge_summary.get('paper_closed_trades', 0),
                    "baseline_profit_factor": edge_summary.get('baseline_profit_factor', 0.0),
                    "paper_profit_factor": edge_summary.get('paper_profit_factor', 0.0),
                    "edge_status": edge_summary.get('status'),
                    "readiness_ready": bool(readiness.get('ready')) if readiness else None,
                    "readiness_reasons": readiness.get('reasons', []) if readiness else [],
                    "updated_at_br": profile.get('updated_at_br') or profile.get('created_at_br'),
                }
            )

        return {
            "profiles": rows,
            "counts": counts,
            "total_profiles": len(rows),
        }

    def get_statistics(self) -> Dict[str, Any]:
        """Buscar estatísticas gerais"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        stats = {}
        
        # Total de sinais
        cursor.execute('SELECT COUNT(*) as total FROM trading_signals')
        stats['total_signals'] = cursor.fetchone()['total']
        
        # Sinais por tipo
        cursor.execute('''
            SELECT signal_type, COUNT(*) as count 
            FROM trading_signals 
            GROUP BY signal_type
        ''')
        signal_types = {row['signal_type']: row['count'] for row in cursor.fetchall()}
        stats['signal_types'] = signal_types
        
        # Sinais por símbolo
        cursor.execute('''
            SELECT symbol, COUNT(*) as count 
            FROM trading_signals 
            GROUP BY symbol 
            ORDER BY count DESC 
            LIMIT 10
        ''')
        stats['top_symbols'] = [dict(row) for row in cursor.fetchall()]
        
        # Sinais recentes (últimas 24h)
        cursor.execute('''
            SELECT COUNT(*) as count 
            FROM trading_signals 
            WHERE created_at >= datetime('now', '-1 day')
        ''')
        stats['signals_24h'] = cursor.fetchone()['count']

        cursor.execute('SELECT COUNT(*) as total FROM backtest_runs')
        stats['total_backtests'] = cursor.fetchone()['total']

        cursor.execute('SELECT COUNT(*) as total FROM paper_trades')
        stats['total_paper_trades'] = cursor.fetchone()['total']

        cursor.execute("SELECT COUNT(*) as total FROM paper_trades WHERE status = 'OPEN'")
        stats['open_paper_trades'] = cursor.fetchone()['total']
        
        conn.close()
        return stats
    
    def cleanup_old_data(self, days_to_keep: int = 30):
        """Limpar dados antigos"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Remover sinais antigos
        cursor.execute('''
            DELETE FROM trading_signals 
            WHERE created_at < datetime('now', '-{} days')
        '''.format(days_to_keep))
        
        # Remover análises antigas
        cursor.execute('''
            DELETE FROM analysis_history 
            WHERE created_at < datetime('now', '-{} days')
        '''.format(days_to_keep))

        cursor.execute('''
            DELETE FROM backtest_trades
            WHERE run_id IN (
                SELECT id FROM backtest_runs
                WHERE created_at < datetime('now', '-{} days')
            )
        '''.format(days_to_keep))

        cursor.execute('''
            DELETE FROM backtest_runs
            WHERE created_at < datetime('now', '-{} days')
        '''.format(days_to_keep))

        cursor.execute('''
            DELETE FROM paper_trades
            WHERE created_at < datetime('now', '-{} days')
        '''.format(days_to_keep))
        
        conn.commit()
        conn.close()

    def _normalize_timestamp(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        if hasattr(value, 'isoformat'):
            return value.isoformat()
        return str(value)

# Instância global do banco
db = TradingDatabase()
