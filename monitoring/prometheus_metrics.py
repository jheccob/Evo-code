
from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry
from datetime import datetime
import time

class TradingBotMetrics:
    """Métricas profissionais para monitoramento"""
    
    def __init__(self):
        self.registry = CollectorRegistry()
        
        # Contadores
        self.total_analyses = Counter(
            'trading_bot_analyses_total',
            'Total de análises realizadas',
            ['user_plan', 'symbol'],
            registry=self.registry
        )
        
        self.telegram_messages = Counter(
            'telegram_messages_total',
            'Total de mensagens do Telegram',
            ['command', 'status'],
            registry=self.registry
        )
        
        # Histogramas (latência)
        self.analysis_duration = Histogram(
            'analysis_duration_seconds',
            'Tempo de execução das análises',
            ['symbol'],
            registry=self.registry
        )
        
        # Gauges (valores atuais)
        self.active_users = Gauge(
            'active_users',
            'Usuários ativos',
            registry=self.registry
        )
        
        self.premium_users = Gauge(
            'premium_users_total',
            'Total de usuários premium',
            registry=self.registry
        )
    
    def track_analysis(self, user_plan: str, symbol: str, duration: float):
        """Rastrear análise"""
        self.total_analyses.labels(user_plan=user_plan, symbol=symbol).inc()
        self.analysis_duration.labels(symbol=symbol).observe(duration)
    
    def track_telegram_message(self, command: str, status: str):
        """Rastrear mensagem do Telegram"""
        self.telegram_messages.labels(command=command, status=status).inc()
    
    def update_user_counts(self, active: int, premium: int):
        """Atualizar contadores de usuários"""
        self.active_users.set(active)
        self.premium_users.set(premium)
