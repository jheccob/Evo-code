#!/usr/bin/env python3
"""
Trading Bot - Versão Profissional para Produção
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime
import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

# Configuração de logging profissional
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Imports dos serviços
from services.telegram_service import ProfessionalTelegramService
from services.rate_limiter import RateLimiter
from services.billing_service import BillingService
from monitoring.prometheus_metrics import TradingBotMetrics
from config.production_config import ProductionConfig

# Mock classes if telegram not available
try:
    from telegram import Update
    from telegram.ext import Application
except ImportError:
    class Update:
        pass
    class Application:
        pass

# Variáveis globais
telegram_service = None
billing_service = None
metrics = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerenciamento do ciclo de vida da aplicação"""
    global telegram_service, billing_service, metrics

    logger.info("🚀 Iniciando Trading Bot Professional")

    try:
        # Inicializar serviços
        telegram_service = ProfessionalTelegramService()
        billing_service = BillingService()
        metrics = TradingBotMetrics()

        # Inicializar Telegram service
        success = await telegram_service.initialize()
        if not success:
            raise Exception("Falha ao inicializar serviço Telegram")

        logger.info("✅ Todos os serviços inicializados com sucesso")

        yield

    except Exception as e:
        logger.error(f"❌ Erro na inicialização: {e}")
        raise
    finally:
        logger.info("🛑 Encerrando Trading Bot Professional")

# FastAPI app para webhooks e API
app = FastAPI(
    title="Trading Bot Professional API",
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0"
    }

@app.post("/webhook")
async def telegram_webhook(request: Request):
    """Webhook do Telegram"""
    try:
        # Verificar secret token
        secret_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if secret_token != ProductionConfig.TELEGRAM_SECRET_TOKEN:
            raise HTTPException(status_code=403, detail="Invalid secret token")

        # Processar update
        body = await request.body()
        update = Update.de_json(body.decode('utf-8'), telegram_service.bot)

        # Processar update de forma assíncrona
        asyncio.create_task(telegram_service.application.process_update(update))

        return JSONResponse({"status": "ok"})

    except Exception as e:
        logger.error(f"Erro no webhook: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    """Webhook do Stripe"""
    try:
        payload = await request.body()
        signature = request.headers.get("Stripe-Signature")

        success = await billing_service.handle_webhook(payload, signature)

        if success:
            return JSONResponse({"status": "ok"})
        else:
            raise HTTPException(status_code=400, detail="Invalid webhook")

    except Exception as e:
        logger.error(f"Erro no webhook Stripe: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/metrics")
async def get_metrics():
    """Endpoint de métricas Prometheus"""
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from fastapi.responses import Response

    return Response(
        generate_latest(metrics.registry),
        media_type=CONTENT_TYPE_LATEST
    )

async def signal_handler(signum, frame):
    """Handler para sinais do sistema"""
    logger.info(f"Recebido sinal {signum}, encerrando...")

    # Cleanup
    if telegram_service:
        await telegram_service.application.stop()

    sys.exit(0)

async def main():
    """Função principal"""
    try:
        # Configurar handlers de sinal
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Validar configuração
        ProductionConfig.validate_config()

        logger.info("🎯 Trading Bot Professional - Modo Produção")
        logger.info("📊 Configurações validadas com sucesso")

        # Iniciar servidor FastAPI
        config = uvicorn.Config(
            app=app,
            host="0.0.0.0",
            port=5000,
            log_level="info",
            access_log=True
        )

        server = uvicorn.Server(config)
        await server.serve()

    except Exception as e:
        logger.error(f"❌ Erro fatal: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())