
# 🔐 Configuração da Binance - Guia Completo

## 📋 Pré-requisitos

1. **Conta na Binance**: Crie uma conta em [binance.com](https://binance.com)
2. **Verificação KYC**: Complete a verificação de identidade
3. **Habilitar Futuros**: Ative a conta de futuros na Binance

## 🔑 Obtendo suas Credenciais API

### Passo 1: Acessar Gerenciamento de API
1. Faça login na Binance
2. Vá para **Perfil** → **Segurança API**
3. Clique em **Criar API**

### Passo 2: Configurar Permissões
✅ **Permissões Necessárias:**
- [x] Ler Dados do Spot e Margem
- [x] Habilitar Futuros
- [x] Ler Dados de Futuros *(essencial)*
- [ ] ~~Trading~~ *(não necessário para análise)*

⚠️ **NÃO habilite Trading** a menos que queira execução automática

### Passo 3: Restrições de IP (Recomendado)
- Adicione os IPs do Replit para maior segurança
- Ou deixe em branco (menos seguro)

## 🔒 Configurando no Replit

### Método 1: Replit Secrets (Recomendado)
1. Clique no ícone **🔒 Secrets** na barra lateral esquerda
2. Adicione as seguintes variáveis:

```
BINANCE_API_KEY = sua_api_key_aqui_sem_aspas
BINANCE_SECRET = seu_secret_key_aqui_sem_aspas
```

### Método 2: Arquivo .env (Alternativo)
Crie um arquivo `.env` na raiz do projeto:

```env
BINANCE_API_KEY=sua_api_key_aqui
BINANCE_SECRET=seu_secret_key_aqui
```

## 🧪 Testando a Configuração

### Teste Rápido no Console:
```python
import os
from config.exchange_config import ExchangeConfig

# Testar conexão
success, message = ExchangeConfig.test_connection('binance')
print(message)
```

### Teste no Dashboard:
1. Execute o dashboard (`streamlit run app.py`)
2. Na barra lateral, clique em **🧪 Testar Conexão Binance**
3. Verifique se aparece: ✅ "Binance funcionando com credenciais!"

## 📊 Exemplo de Uso no Código

```python
import ccxt
import os
from config.exchange_config import ExchangeConfig

# Método 1: Usar nossa configuração
exchange = ExchangeConfig.get_exchange_instance('binance')

# Método 2: Configuração manual (como seu exemplo)
exchange = ccxt.binance({
    "apiKey": os.getenv('BINANCE_API_KEY'),
    "secret": os.getenv('BINANCE_SECRET'),
    "enableRateLimit": True,
    "options": {
        "defaultType": "future"  # Garantir que é Futuros
    }
})

# Testar
try:
    markets = exchange.load_markets()
    balance = exchange.fetch_balance()
    print("✅ Conectado com sucesso!")
    print(f"Saldo USDT: ${balance['USDT']['total']:.2f}")
except Exception as e:
    print(f"❌ Erro: {e}")
```

## 🔐 Segurança

### ✅ Boas Práticas:
- Use apenas permissões necessárias
- Configure restrições de IP
- Monitore o uso da API
- Nunca compartilhe suas chaves

### ❌ Não faça:
- Não coloque credenciais diretamente no código
- Não habilite permissões de trading sem necessidade
- Não compartilhe suas chaves API

## 🚨 Troubleshooting

### Erro: "API key format invalid"
- Verifique se copiou a chave completa
- Remova espaços em branco
- Certifique-se que não há quebras de linha

### Erro: "Signature for this request is not valid"
- Verifique se o SECRET está correto
- Certifique-se que o horário do sistema está correto

### Erro: "IP address not allowed"
- Configure o IP do Replit nas restrições
- Ou remova restrições de IP temporariamente

## 📞 Suporte

Se encontrar problemas:
1. Verifique os logs do console
2. Teste no **🧪 Testar Conexão Binance**
3. Consulte a documentação da Binance API

---

🔥 **Pronto!** Agora você pode usar seus dados reais da Binance no bot!
