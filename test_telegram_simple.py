
#!/usr/bin/env python3
"""
Teste simples do bot Telegram - Versão Produção
"""

import asyncio
import logging
from services.telegram_service import ProfessionalTelegramService
from config.production_config import ProductionConfig

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_bot():
    """Teste do bot profissional"""
    try:
        logger.info("🧪 Testando bot profissional...")
        
        # Validar configuração
        if not ProductionConfig.validate_config():
            logger.error("❌ Configuração inválida!")
            return False
        
        # Criar e inicializar serviço
        service = ProfessionalTelegramService()
        
        success = await service.initialize()
        if not success:
            logger.error("❌ Falha na inicialização")
            return False
        
        # Testar conexão
        try:
            me = await service.bot.get_me()
            logger.info(f"✅ Bot conectado: @{me.username}")
            logger.info(f"📝 Nome: {me.first_name}")
            logger.info(f"🆔 ID: {me.id}")
            
            # Enviar mensagem de teste (se chat ID configurado)
            if ProductionConfig.TELEGRAM_CHAT_ID != "SEU_CHAT_ID_AQUI":
                await service.bot.send_message(
                    ProductionConfig.TELEGRAM_CHAT_ID,
                    "✅ **Bot Teste Profissional**\n\n"
                    "🤖 Bot funcionando perfeitamente!\n"
                    "🚀 Sistema pronto para produção!\n\n"
                    "Digite `/start` para começar!",
                    parse_mode='Markdown'
                )
                logger.info("📤 Mensagem de teste enviada!")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Erro na conexão: {e}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Erro no teste: {e}")
        return False

if __name__ == '__main__':
    result = asyncio.run(test_bot())
    if result:
        logger.info("🎉 Teste concluído com sucesso!")
    else:
        logger.error("💥 Teste falhou!")
