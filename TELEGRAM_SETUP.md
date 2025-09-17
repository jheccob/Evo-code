
# 📱 Configuração do Bot Telegram

## 🚀 Como configurar o Bot do Telegram

### 1. Criar um Bot no Telegram

1. Abra o Telegram e procure por `@BotFather`
2. Digite `/start` para iniciar
3. Digite `/newbot` para criar um novo bot
4. Escolha um nome para seu bot (ex: "Meu Trading Bot")
5. Escolha um username único (ex: "meutradingbot_bot")
6. Copie o **Token** que o BotFather vai te enviar

### 2. Obter seu Chat ID

#### Para Chat Privado:
1. Procure por `@userinfobot` no Telegram
2. Digite `/start`
3. O bot vai retornar seu **Chat ID** (um número positivo)

#### Para Grupo:
1. Adicione seu bot ao grupo
2. Adicione `@userinfobot` ao grupo
3. Digite `/start`
4. O bot vai retornar o **Chat ID** do grupo (um número negativo)

### 3. Configurar no seu App

#### Opção 1: Arquivo de Configuração (Recomendado)
1. Abra o arquivo `config/telegram_config.py`
2. Substitua `SEU_BOT_TOKEN_AQUI` pelo token do seu bot
3. Substitua `SEU_CHAT_ID_AQUI` pelo seu chat ID
4. Salve o arquivo

#### Opção 2: Interface do App
1. Execute o app
2. Na barra lateral, ative "Telegram Alerts"
3. Cole o Bot Token e Chat ID
4. Clique em "Configurar Telegram"

### 4. Testar a Configuração

1. No app, clique em "Teste de Mensagem"
2. Você deve receber uma mensagem no Telegram
3. Se não receber, verifique:
   - Token está correto
   - Chat ID está correto
   - Bot foi iniciado com `/start`

## 🔧 Exemplo de Configuração

```python
# config/telegram_config.py
TELEGRAM_BOT_TOKEN = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"
TELEGRAM_CHAT_ID = "123456789"  # Chat privado
# TELEGRAM_CHAT_ID = "-1001234567890"  # Grupo
```

## ⚠️ Segurança

- **NUNCA** compartilhe seu bot token
- Mantenha o arquivo `config/telegram_config.py` privado
- Use variáveis de ambiente em produção

## 🆘 Problemas Comuns

1. **"Bot não responde"**: Verifique se digitou `/start` para o bot
2. **"Unauthorized"**: Token incorreto
3. **"Chat not found"**: Chat ID incorreto
4. **"Forbidden"**: Bot foi bloqueado ou removido do grupo

## 📞 Suporte

Se ainda tiver problemas, verifique:
- Console do app para mensagens de erro
- Se o bot está ativo no Telegram
- Se as permissões do grupo estão corretas
