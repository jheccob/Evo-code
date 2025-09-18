"""
Sistema de banco de dados usando SQLite para persistir dados do trading bot
"""
import sqlite3
import os
import json
from datetime import datetime
from typing import List, Dict, Optional, Any
from utils.timezone_utils import get_brazil_datetime_naive, format_brazil_time

class TradingDatabase:
    def __init__(self, db_path: str = "data/trading_bot.db"):
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
        
        conn.commit()
        conn.close()
    
    def save_trading_signal(self, signal_data: Dict[str, Any]) -> int:
        """Salvar um sinal de trading"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO trading_signals 
            (symbol, timeframe, signal_type, price, rsi, macd_signal, macd_value, 
             signal_strength, volume, created_at_br)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            signal_data.get('symbol'),
            signal_data.get('timeframe'),
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
        
        conn.commit()
        conn.close()

# Instância global do banco
db = TradingDatabase()