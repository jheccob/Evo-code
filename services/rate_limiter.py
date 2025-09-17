
import time
import asyncio
from typing import Dict, Optional
from datetime import datetime, timedelta
import aioredis
from config.production_config import ProductionConfig

class RateLimiter:
    """Sistema profissional de rate limiting"""
    
    def __init__(self):
        self.redis_client = None
        self.limits = {
            'free': {'requests': 3, 'window': 3600},    # 3 por hora
            'premium': {'requests': 1000, 'window': 3600},  # 1000 por hora
            'admin': {'requests': 10000, 'window': 3600}    # 10000 por hora
        }
    
    async def initialize(self):
        """Inicializar conexão Redis"""
        self.redis_client = await aioredis.from_url(ProductionConfig.REDIS_URL)
    
    async def check_rate_limit(self, user_id: int, user_plan: str = 'free') -> bool:
        """Verificar rate limit para usuário"""
        if not self.redis_client:
            await self.initialize()
        
        limit_config = self.limits.get(user_plan, self.limits['free'])
        window_start = int(time.time() // limit_config['window']) * limit_config['window']
        
        key = f"rate_limit:{user_id}:{window_start}"
        
        # Incrementar contador
        current_requests = await self.redis_client.incr(key)
        
        # Definir expiração
        if current_requests == 1:
            await self.redis_client.expire(key, limit_config['window'])
        
        return current_requests <= limit_config['requests']
    
    async def get_remaining_requests(self, user_id: int, user_plan: str = 'free') -> int:
        """Obter requests restantes"""
        if not self.redis_client:
            await self.initialize()
        
        limit_config = self.limits.get(user_plan, self.limits['free'])
        window_start = int(time.time() // limit_config['window']) * limit_config['window']
        
        key = f"rate_limit:{user_id}:{window_start}"
        current_requests = await self.redis_client.get(key)
        
        if not current_requests:
            return limit_config['requests']
        
        return max(0, limit_config['requests'] - int(current_requests))
