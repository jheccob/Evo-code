
import os
from typing import Optional

class ProductionConfig:
    """Configuração profissional para produção"""
    
    # Database Configuration
    DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://user:password@localhost:5432/trading_bot')
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')
    
    # Trading Configuration
    MAX_CONCURRENT_ANALYSES = int(os.getenv('MAX_CONCURRENT_ANALYSES', '100'))
    RATE_LIMIT_PER_MINUTE = int(os.getenv('RATE_LIMIT_PER_MINUTE', '60'))
    ANALYSIS_TIMEOUT = int(os.getenv('ANALYSIS_TIMEOUT', '30'))
    
    # Telegram Bot Configuration
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    TELEGRAM_WEBHOOK_URL = os.getenv('TELEGRAM_WEBHOOK_URL')
    TELEGRAM_SECRET_TOKEN = os.getenv('TELEGRAM_SECRET_TOKEN')
    
    # Monitoring & Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    SENTRY_DSN = os.getenv('SENTRY_DSN')
    
    # Pricing & Billing
    PREMIUM_PRICE_MONTHLY = float(os.getenv('PREMIUM_PRICE_MONTHLY', '29.90'))
    STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')
    STRIPE_PUBLIC_KEY = os.getenv('STRIPE_PUBLIC_KEY')
    STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')
    
    # Security
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY')
    ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')
    
    # Performance
    CACHE_TTL_SECONDS = int(os.getenv('CACHE_TTL_SECONDS', '300'))
    MAX_WORKERS = int(os.getenv('MAX_WORKERS', '4'))
    
    @classmethod
    def validate_config(cls) -> bool:
        """Validar configurações essenciais"""
        required_vars = [
            'TELEGRAM_BOT_TOKEN',
            'DATABASE_URL',
            'JWT_SECRET_KEY'
        ]
        
        missing = [var for var in required_vars if not getattr(cls, var)]
        
        if missing:
            raise ValueError(f"Variáveis de ambiente obrigatórias não configuradas: {missing}")
        
        return True
