
import asyncio
import logging
import hashlib
import hmac
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import aioredis
from telegram import Bot, Update, WebhookInfo
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import TelegramError, RetryAfter, TimedOut
from sqlalchemy.orm import Session

from config.production_config import ProductionConfig
from database.models import User, Analysis
from services.rate_limiter import RateLimiter
from services.analytics_service import AnalyticsService
from services.billing_service import BillingService

logger = logging.getLogger(__name__)

class ProfessionalTelegramService:
    def __init__(self):
        self.bot = None
        self.application = None
        self.redis_client = None
        self.rate_limiter = RateLimiter()
        self.analytics = AnalyticsService()
        self.billing = BillingService()
        
    async def initialize(self):
        """Inicializar serviço profissional"""
        try:
            # Validar configuração
            ProductionConfig.validate_config()
            
            # Configurar Redis para cache
            self.redis_client = await aioredis.from_url(ProductionConfig.REDIS_URL)
            
            # Configurar bot
            self.bot = Bot(token=ProductionConfig.TELEGRAM_BOT_TOKEN)
            self.application = Application.builder().token(ProductionConfig.TELEGRAM_BOT_TOKEN).build()
            
            # Configurar webhooks para produção
            if ProductionConfig.TELEGRAM_WEBHOOK_URL:
                await self.setup_webhook()
            
            # Registrar handlers
            self.register_handlers()
            
            logger.info("Serviço Telegram profissional inicializado com sucesso")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao inicializar serviço: {e}")
            return False
    
    async def setup_webhook(self):
        """Configurar webhook para produção"""
        webhook_url = f"{ProductionConfig.TELEGRAM_WEBHOOK_URL}/webhook"
        
        await self.bot.set_webhook(
            url=webhook_url,
            secret_token=ProductionConfig.TELEGRAM_SECRET_TOKEN,
            allowed_updates=["message", "callback_query"]
        )
        
        logger.info(f"Webhook configurado: {webhook_url}")
    
    def register_handlers(self):
        """Registrar handlers com middleware profissional"""
        # Middleware para rate limiting e analytics
        async def middleware(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user_id = update.effective_user.id if update.effective_user else None
            
            # Rate limiting
            if user_id and not await self.rate_limiter.check_rate_limit(user_id):
                await update.message.reply_text(
                    "⚠️ Muitas solicitações. Tente novamente em alguns minutos."
                )
                return
            
            # Analytics
            await self.analytics.track_interaction(user_id, update.message.text if update.message else "")
            
        # Commands com middleware
        self.application.add_handler(CommandHandler("start", self.enhanced_start_command))
        self.application.add_handler(CommandHandler("analise", self.enhanced_analyze_command))
        self.application.add_handler(CommandHandler("premium", self.premium_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        
        # Admin commands
        self.application.add_handler(CommandHandler("admin_stats", self.admin_stats))
        self.application.add_handler(CommandHandler("admin_users", self.admin_users))
        self.application.add_handler(CommandHandler("admin_broadcast", self.admin_broadcast))
    
    async def enhanced_start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando start aprimorado"""
        user = update.effective_user
        
        # Salvar usuário no banco
        db_user = await self.get_or_create_user(user.id, user.username, user.first_name)
        
        # Mensagem personalizada baseada no plano
        if db_user.plan == 'premium':
            welcome_msg = f"""
🚀 **Bem-vindo de volta, {user.first_name}!**

💎 **Status Premium Ativo**
✅ Análises ilimitadas
✅ Alertas em tempo real
✅ Suporte prioritário

📊 **Total de análises:** {db_user.total_analyses}
"""
        else:
            analyses_today = await self.get_analyses_today(user.id)
            welcome_msg = f"""
👋 **Olá, {user.first_name}!**

🆓 **Plano Free Ativo**
📊 Análises hoje: {analyses_today}/3
🎯 Análises total: {db_user.total_analyses}

💡 **Comandos:**
• `/analise BTC/USDT` - Analisar crypto
• `/premium` - Upgrade para Premium
• `/help` - Ver todos comandos
"""
        
        await update.message.reply_text(welcome_msg, parse_mode='Markdown')
        
        # Analytics
        await self.analytics.track_user_start(user.id)
    
    async def enhanced_analyze_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando de análise profissional com cache e otimizações"""
        start_time = datetime.now()
        user_id = update.effective_user.id
        
        try:
            # Verificar permissões
            if not await self.check_analysis_permission(user_id):
                await update.message.reply_text(
                    "⚠️ **Limite atingido**\n\n"
                    "Upgrade para Premium e tenha análises ilimitadas!\n"
                    "Use `/premium` para mais informações."
                )
                return
            
            # Validar símbolo
            if not context.args:
                await update.message.reply_text(
                    "❌ **Uso:** `/analise BTC/USDT`\n\n"
                    "📈 **Símbolos disponíveis:**\n"
                    "• BTC/USDT, ETH/USDT, ADA/USDT\n"
                    "• SOL/USDT, MATIC/USDT, DOT/USDT"
                )
                return
            
            symbol = context.args[0].upper()
            
            # Verificar cache Redis
            cache_key = f"analysis:{symbol}:{datetime.now().minute//5}"
            cached_result = await self.redis_client.get(cache_key)
            
            if cached_result:
                await update.message.reply_text(cached_result.decode(), parse_mode='Markdown')
                await self.record_analysis(user_id, symbol, execution_time=0.1)
                return
            
            # Mensagem de loading
            loading_msg = await update.message.reply_text(f"🔄 **Analisando {symbol}...**")
            
            # Realizar análise
            analysis_result = await self.perform_professional_analysis(symbol)
            
            # Salvar no cache
            await self.redis_client.setex(cache_key, 300, analysis_result)
            
            # Atualizar mensagem
            await loading_msg.edit_text(analysis_result, parse_mode='Markdown')
            
            # Registrar análise
            execution_time = (datetime.now() - start_time).total_seconds()
            await self.record_analysis(user_id, symbol, execution_time=execution_time)
            
        except Exception as e:
            logger.error(f"Erro na análise: {e}")
            await update.message.reply_text(
                "❌ **Erro temporário**\n\n"
                "Tente novamente em alguns segundos."
            )
    
    async def perform_professional_analysis(self, symbol: str) -> str:
        """Análise técnica profissional otimizada"""
        # Implementar análise técnica avançada
        # (usando trading_bot.py existente como base)
        
        return f"""
📊 **Análise Profissional - {symbol}**

💰 **Preço:** $45,230.50 (+2.34%)
📈 **Volume 24h:** $2.1B

🔍 **Indicadores Técnicos:**
• **RSI (14):** 58.3 (Neutro)
• **MACD:** 0.0234 (Positivo)
• **MA 20/50:** Cruzamento dourado
• **Bollinger:** Próximo da média

🎯 **Sinal:** 🟢 **COMPRA MODERADA**

⚠️ **Disclaimer:** Análise para fins informativos apenas.
        """
    
    async def check_analysis_permission(self, user_id: int) -> bool:
        """Verificar se usuário pode fazer análise"""
        # Implementar lógica de permissão baseada no plano
        return True  # Placeholder
    
    async def record_analysis(self, user_id: int, symbol: str, execution_time: float):
        """Registrar análise no banco de dados"""
        # Implementar registro no banco
        pass
    
    async def get_or_create_user(self, telegram_id: int, username: str, first_name: str):
        """Obter ou criar usuário no banco"""
        # Implementar lógica de usuário
        pass
    
    async def get_analyses_today(self, user_id: int) -> int:
        """Obter número de análises hoje"""
        # Implementar contagem
        return 0
    
    async def premium_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando premium com integração de billing"""
        user_id = update.effective_user.id
        
        # Verificar status atual
        is_premium = await self.billing.is_user_premium(user_id)
        
        if is_premium:
            subscription = await self.billing.get_active_subscription(user_id)
            message = f"""
💎 **Status Premium Ativo**

📅 **Válido até:** {subscription.current_period_end.strftime('%d/%m/%Y')}
✅ **Benefícios ativos:**
• Análises ilimitadas
• Alertas em tempo real
• Suporte prioritário
• Análises avançadas

💳 **Gerenciar assinatura:** /manage_subscription
"""
        else:
            payment_link = await self.billing.create_payment_link(user_id)
            message = f"""
🚀 **Upgrade para Premium**

💰 **R$ {ProductionConfig.PREMIUM_PRICE_MONTHLY}/mês**

✅ **Benefícios:**
• 🔥 Análises ilimitadas
• ⚡ Alertas em tempo real
• 📊 Indicadores avançados
• 💬 Suporte VIP
• 📈 Backtesting

🔗 **Link de pagamento:** {payment_link}

💳 Pagamento seguro via Stripe
"""
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def admin_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Estatísticas administrativas"""
        if not await self.is_admin(update.effective_user.id):
            return
        
        stats = await self.analytics.get_system_stats()
        
        message = f"""
📊 **Estatísticas do Sistema**

👥 **Usuários:**
• Total: {stats['total_users']}
• Premium: {stats['premium_users']}
• Ativos hoje: {stats['active_today']}

📈 **Análises:**
• Hoje: {stats['analyses_today']}
• Este mês: {stats['analyses_month']}
• Tempo médio: {stats['avg_response_time']:.2f}s

💰 **Revenue:**
• Mensal: R$ {stats['monthly_revenue']:.2f}
• Taxa conversão: {stats['conversion_rate']:.1f}%
"""
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def is_admin(self, user_id: int) -> bool:
        """Verificar se usuário é admin"""
        # Implementar verificação de admin
        return user_id in [1035830659]  # Seu chat ID
    
    async def start_production_service(self):
        """Iniciar serviço em modo produção"""
        if ProductionConfig.TELEGRAM_WEBHOOK_URL:
            # Modo webhook para produção
            await self.application.initialize()
            await self.application.start()
        else:
            # Modo polling para desenvolvimento
            await self.application.run_polling()
