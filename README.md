# Trading Bot

## Modo 24/7 em nuvem

O caminho recomendado para producao e rodar apenas o bot Telegram em um unico processo Python.

Variaveis minimas:

- `TELEGRAM_BOT_TOKEN`
- `ADMIN_USERS` opcional

Comando:

```powershell
python start_telegram_bot.py
```

Nesse modo, `TELEGRAM_CHAT_ID` nao e obrigatorio. Ele so e usado pelos recursos de alertas outbound do dashboard.

## Deploy no Railway

O repositorio agora inclui `railway.json` com:

- build via Railpack
- instalacao por `requirements_railway.txt`
- start command `python start_telegram_bot.py`
- restart policy `ON_FAILURE`

Passos:

1. Crie um projeto no Railway a partir deste repositorio.
2. Use este servico como worker privado; nao exponha dominio publico para ele.
3. Configure as variaveis no Railway:
   - `TELEGRAM_BOT_TOKEN` obrigatoria
   - `ADMIN_USERS` opcional
   - `PYTHONUNBUFFERED=1` recomendado
   - `TELEGRAM_CHAT_ID` opcional
4. Faça o deploy e acompanhe os logs.

Com isso, o Railway deve subir o bot diretamente pelo entrypoint `start_telegram_bot.py`.

Observacao:

- O worker usa um conjunto reduzido de dependencias em `requirements_railway.txt`, separado do dashboard.
- `ON_FAILURE` foi escolhido para funcionar tambem em planos que nao suportam `ALWAYS`.
- O processo agora sai com codigo diferente de zero em falha real, permitindo restart automatico pelo Railway.
- Para operacao realmente 24/7, prefira um plano pago do Railway. Em Free/trial, o restart policy tem limitacoes.

## Dashboard

O dashboard Streamlit e opcional e deve rodar separado do bot 24/7.

```powershell
streamlit run app.py
```

Nao e recomendado iniciar polling do bot a partir do dashboard.
