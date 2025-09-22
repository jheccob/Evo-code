
import ccxt
import os

class ExchangeConfig:
    """Configuração de exchanges que funcionam no Brasil"""
    
    # Exchanges recomendados para Brasil
    SUPPORTED_EXCHANGES = {
        'bybit': {
            'name': 'Bybit',
            'futures_supported': True,
            'brazil_accessible': True,
            'usdt_pairs': True,
            'description': 'Exchange principal recomendado para Brasil'
        },
        'okx': {
            'name': 'OKX',
            'futures_supported': True,
            'brazil_accessible': True,
            'usdt_pairs': True,
            'description': 'Alternativa confiável com bom volume'
        },
        'kucoin': {
            'name': 'KuCoin',
            'futures_supported': True,
            'brazil_accessible': True,
            'usdt_pairs': True,
            'description': 'Boa opção para iniciantes'
        },
        'mexc': {
            'name': 'MEXC',
            'futures_supported': True,
            'brazil_accessible': True,
            'usdt_pairs': True,
            'description': 'Grande variedade de pares'
        }
    }
    
    @classmethod
    def get_exchange_instance(cls, exchange_name='bybit', testnet=True):
        """Criar instância do exchange configurado para Brasil"""
        
        if exchange_name not in cls.SUPPORTED_EXCHANGES:
            raise ValueError(f"Exchange {exchange_name} não suportado")
        
        exchange_class = getattr(ccxt, exchange_name)
        
        config = {
            'enableRateLimit': True,
            'sandbox': testnet,
            'rateLimit': 1000,
            'timeout': 30000,
        }
        
        # Configurações específicas por exchange
        if exchange_name == 'bybit':
            config.update({
                'options': {
                    'defaultType': 'future',  # Para futuros
                    'recvWindow': 5000,
                }
            })
        elif exchange_name == 'okx':
            config.update({
                'options': {
                    'defaultType': 'swap',  # Para futuros perpétuos
                }
            })
        elif exchange_name == 'kucoin':
            config.update({
                'options': {
                    'defaultType': 'future',
                }
            })
        
        # Adicionar credenciais se disponíveis
        api_key = os.getenv(f'{exchange_name.upper()}_API_KEY')
        secret = os.getenv(f'{exchange_name.upper()}_SECRET')
        passphrase = os.getenv(f'{exchange_name.upper()}_PASSPHRASE')  # Para alguns exchanges
        
        if api_key and secret:
            config['apiKey'] = api_key
            config['secret'] = secret
            if passphrase:
                config['password'] = passphrase
        
        return exchange_class(config)
    
    @classmethod
    def get_usdt_pairs(cls, exchange_name='bybit'):
        """Obter pares USDT disponíveis"""
        try:
            exchange = cls.get_exchange_instance(exchange_name)
            markets = exchange.load_markets()
            
            usdt_pairs = []
            for symbol, market in markets.items():
                if (symbol.endswith('/USDT') and 
                    market.get('active', True) and
                    market.get('type') in ['future', 'swap']):
                    usdt_pairs.append(symbol)
            
            return sorted(usdt_pairs)
        except Exception as e:
            print(f"Erro ao carregar pares: {e}")
            return ["BTC/USDT", "ETH/USDT", "XLM/USDT"]  # Fallback
    
    @classmethod
    def test_connection(cls, exchange_name='bybit'):
        """Testar conexão com exchange"""
        try:
            exchange = cls.get_exchange_instance(exchange_name)
            ticker = exchange.fetch_ticker('BTC/USDT')
            return True, f"✅ Conexão com {exchange_name} funcionando! BTC: ${ticker['last']:.2f}"
        except Exception as e:
            return False, f"❌ Erro ao conectar com {exchange_name}: {str(e)}"
    
    @classmethod
    def get_recommended_for_brazil(cls):
        """Retornar exchange recomendado para Brasil"""
        return 'bybit'
