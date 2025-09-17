
import stripe
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict
from config.production_config import ProductionConfig
from database.models import User, Subscription

logger = logging.getLogger(__name__)

class BillingService:
    """Sistema profissional de billing com Stripe"""
    
    def __init__(self):
        stripe.api_key = ProductionConfig.STRIPE_SECRET_KEY
        self.webhook_secret = ProductionConfig.STRIPE_WEBHOOK_SECRET
    
    async def create_payment_link(self, user_id: int) -> str:
        """Criar link de pagamento"""
        try:
            # Criar customer no Stripe
            customer = stripe.Customer.create(
                metadata={'telegram_user_id': str(user_id)}
            )
            
            # Criar sessão de checkout
            session = stripe.checkout.Session.create(
                customer=customer.id,
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'brl',
                        'product_data': {
                            'name': 'Trading Bot Premium',
                            'description': 'Análises ilimitadas + Alertas em tempo real'
                        },
                        'unit_amount': int(ProductionConfig.PREMIUM_PRICE_MONTHLY * 100),
                        'recurring': {'interval': 'month'}
                    },
                    'quantity': 1,
                }],
                mode='subscription',
                success_url='https://yourbot.replit.app/success',
                cancel_url='https://yourbot.replit.app/cancel',
                metadata={'telegram_user_id': str(user_id)}
            )
            
            return session.url
            
        except Exception as e:
            logger.error(f"Erro ao criar link de pagamento: {e}")
            return "Erro ao gerar link de pagamento"
    
    async def handle_webhook(self, payload: str, signature: str) -> bool:
        """Processar webhook do Stripe"""
        try:
            event = stripe.Webhook.construct_event(
                payload, signature, self.webhook_secret
            )
            
            if event['type'] == 'checkout.session.completed':
                await self.handle_subscription_created(event['data']['object'])
            
            elif event['type'] == 'invoice.payment_succeeded':
                await self.handle_payment_succeeded(event['data']['object'])
            
            elif event['type'] == 'customer.subscription.deleted':
                await self.handle_subscription_cancelled(event['data']['object'])
            
            return True
            
        except Exception as e:
            logger.error(f"Erro no webhook: {e}")
            return False
    
    async def handle_subscription_created(self, session):
        """Processar nova assinatura"""
        user_id = int(session['metadata']['telegram_user_id'])
        subscription_id = session['subscription']
        
        # Atualizar usuário para premium
        # Implementar lógica de banco de dados
        
        logger.info(f"Nova assinatura criada para usuário {user_id}")
    
    async def is_user_premium(self, user_id: int) -> bool:
        """Verificar se usuário é premium"""
        # Implementar verificação no banco
        return False  # Placeholder
    
    async def get_active_subscription(self, user_id: int) -> Optional[Subscription]:
        """Obter assinatura ativa do usuário"""
        # Implementar busca no banco
        return None  # Placeholder
