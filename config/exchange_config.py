
import ccxt
import os

class ExchangeConfig:
    """Configuração de exchanges com suporte a credenciais pessoais"""
    
    @classmethod
    def normalize_symbol(cls, symbol, market_info=None):
        """
        Normaliza símbolos de futuros para uso no sistema
        BTC/USDT:USDT -> BTC/USDT (mas mantém metadata de que é future)
        """
        if ':' in symbol:
            # Para futuros, remover o sufixo depois dos dois pontos
            base_symbol = symbol.split(':')[0]
            return {
                'symbol': base_symbol,
                'raw_symbol': symbol,
                'is_future': True,
                'quote': 'USDT'
            }
        else:
            return {
                'symbol': symbol,
                'raw_symbol': symbol,
                'is_future': False,
                'quote': 'USDT' if symbol.endswith('/USDT') else 'USD'
            }
    
    # Exchanges suportados com credenciais
    SUPPORTED_EXCHANGES = {
        'binance': {
            'name': 'Binance',
            'futures_supported': True,
            'brazil_accessible': True,
            'usdt_pairs': True,
            'requires_credentials': True,
            'description': 'Binance - Exchange global com futuros e spot (requer API Key)'
        },
        'okx': {
            'name': 'OKX',
            'futures_supported': True,
            'brazil_accessible': True,
            'usdt_pairs': True,
            'requires_credentials': False,
            'description': 'OKX - Exchange para dados públicos sem credenciais'
        }
    }
    
    @classmethod
    def get_exchange_instance(cls, exchange_name='binance', testnet=False):
        """Criar instância do exchange configurado"""
        
        if exchange_name not in cls.SUPPORTED_EXCHANGES:
            raise ValueError(f"Exchange {exchange_name} não suportado")
        
        exchange_class = getattr(ccxt, exchange_name)
        
        # Configuração base
        config = {
            'enableRateLimit': True,
            'sandbox': testnet,
            'timeout': 30000,
            'headers': {
                'User-Agent': 'TradingBot-Professional/1.0'
            }
        }
        
        # Configurações específicas por exchange
        if exchange_name == 'binance':
            config.update({
                'rateLimit': 1200,
                'options': {
                    'defaultType': 'future',  # Garantir que usa futuros
                    'adjustForTimeDifference': True,
                    'recvWindow': 10000,
                }
            })
            
            # Credenciais da Binance via Secrets
            api_key = os.getenv('BINANCE_API_KEY')
            secret = os.getenv('BINANCE_SECRET')
            
            if api_key and secret:
                config['apiKey'] = api_key
                config['secret'] = secret
                print(f"✅ Binance configurada com credenciais (API Key: {api_key[:10]}...)")
            else:
                print("⚠️  Credenciais Binance não encontradas nos Secrets")
                print("💡 Configure BINANCE_API_KEY e BINANCE_SECRET nos Secrets")
                
        elif exchange_name == 'okx':
            config.update({
                'rateLimit': 1200,
                'options': {
                    'defaultType': 'swap',  # Para futuros perpétuos
                    'adjustForTimeDifference': True,
                    'recvWindow': 10000,
                }
            })
            
            # Credenciais OKX (opcionais)
            api_key = os.getenv('OKX_API_KEY')
            secret = os.getenv('OKX_SECRET')
            passphrase = os.getenv('OKX_PASSPHRASE')
            
            if api_key and secret:
                config['apiKey'] = api_key
                config['secret'] = secret
                if passphrase:
                    config['password'] = passphrase
        
        return exchange_class(config)
    
    @classmethod
    def is_valid_usdt_pair(cls, symbol):
        """Validar se um símbolo USDT é válido"""
        if not symbol or not isinstance(symbol, str):
            return False
        
        # Lista de pares conhecidos como válidos no OKX
        valid_pairs = {
            "BTC/USDT", "ETH/USDT", "XLM/USDT", "ADA/USDT", "SOL/USDT",
            "DOGE/USDT", "LTC/USDT", "AVAX/USDT", "MATIC/USDT", "DOT/USDT",
            "LINK/USDT", "UNI/USDT", "ATOM/USDT", "FTM/USDT", "NEAR/USDT"
        }
        
        return symbol in valid_pairs

    @classmethod
    def get_usdt_pairs(cls, exchange_name='okx'):
        """Obter pares USDT disponíveis no OKX"""
        try:
            exchange = cls.get_exchange_instance('okx')
            markets = exchange.load_markets()
            
            pairs = []
            normalized_symbols = set()  # Evitar duplicados
            
            for symbol, market in markets.items():
                # Priorizar futuros USDT no OKX
                if (market.get('active', True) and
                    market.get('type') in ['future', 'swap']):
                    # Futuros USDT podem vir como BTC/USDT:USDT
                    if ':USDT' in symbol or (symbol.endswith('/USDT') and market.get('type') in ['future', 'swap']):
                        normalized = cls.normalize_symbol(symbol, market)
                        # Validar se é um par conhecido
                        if (normalized['symbol'] not in normalized_symbols and 
                            cls.is_valid_usdt_pair(normalized['symbol'])):
                            pairs.append(normalized['symbol'])
                            normalized_symbols.add(normalized['symbol'])
                # Incluir spot USDT apenas se não há future equivalente
                elif (symbol.endswith('/USDT') and 
                      market.get('type') == 'spot' and
                      symbol not in normalized_symbols and
                      cls.is_valid_usdt_pair(symbol)):
                    pairs.append(symbol)
                    normalized_symbols.add(symbol)
            
            return sorted(pairs)
        except Exception as e:
            print(f"Erro ao carregar pares OKX: {e}")
            # Fallback com pares populares que realmente existem no OKX
            return ["BTC/USDT", "ETH/USDT", "XLM/USDT", "ADA/USDT", "SOL/USDT", "DOGE/USDT", "LTC/USDT", "AVAX/USDT"]
    
    @classmethod
    def get_usdt_pairs_with_metadata(cls, exchange_name='okx'):
        """Obter pares USDT com metadados completos (para uso interno do sistema)"""
        try:
            exchange = cls.get_exchange_instance(exchange_name)
            markets = exchange.load_markets()
            
            pairs = {}  # Dict com symbol -> metadata
            normalized_symbols = set()  # Evitar duplicados
            
            for symbol, market in markets.items():
                # Para Coinbase, usar pares USD spot
                if exchange_name == 'coinbase':
                    if (symbol.endswith('/USD') and 
                        market.get('active', True) and
                        market.get('type') == 'spot'):
                        normalized = cls.normalize_symbol(symbol, market)
                        pairs[normalized['symbol']] = normalized
                        normalized_symbols.add(normalized['symbol'])
                else:
                    # Para outros exchanges, priorizar futuros USDT
                    if (market.get('active', True) and
                        market.get('type') in ['future', 'swap']):
                        # Futuros USDT podem vir como BTC/USDT:USDT
                        if ':USDT' in symbol or (symbol.endswith('/USDT') and market.get('type') in ['future', 'swap']):
                            normalized = cls.normalize_symbol(symbol, market)
                            if normalized['symbol'] not in normalized_symbols:
                                pairs[normalized['symbol']] = normalized
                                normalized_symbols.add(normalized['symbol'])
                    # Incluir spot USDT apenas se não há future equivalente
                    elif (symbol.endswith('/USDT') and 
                          market.get('type') == 'spot' and
                          symbol not in normalized_symbols):
                        normalized = cls.normalize_symbol(symbol, market)
                        pairs[normalized['symbol']] = normalized
                        normalized_symbols.add(normalized['symbol'])
            
            return pairs
        except Exception as e:
            print(f"Erro ao carregar pares com metadata: {e}")
            # Fallback baseado no exchange
            if exchange_name == 'coinbase':
                fallback = ["BTC/USD", "ETH/USD", "XLM/USD"]
            else:
                fallback = ["BTC/USDT", "ETH/USDT", "XLM/USDT", "ADA/USDT", "DOT/USDT"]
            
            # Fallback com pares que realmente existem
            fallback = ["BTC/USDT", "ETH/USDT", "XLM/USDT", "ADA/USDT", "SOL/USDT", "DOGE/USDT", "LTC/USDT", "AVAX/USDT"]
            return {symbol: cls.normalize_symbol(symbol) for symbol in fallback}
    
    @classmethod
    def get_trading_symbol(cls, display_symbol, exchange_name='okx'):
        """
        Converte símbolo de exibição para símbolo de trading
        BTC/USDT -> BTC/USDT:USDT (para futuros no OKX)
        """
        pairs_metadata = cls.get_usdt_pairs_with_metadata(exchange_name)
        
        if display_symbol in pairs_metadata:
            metadata = pairs_metadata[display_symbol]
            return metadata['raw_symbol']  # Retorna símbolo original para trading
        
        return display_symbol  # Fallback
    
    @classmethod
    def test_connection(cls, exchange_name='binance'):
        """Testar conexão com exchange"""
        try:
            exchange = cls.get_exchange_instance(exchange_name)
            
            # Test market data access
            markets = exchange.load_markets()
            
            # Procurar por BTC/USDT
            test_symbols = ['BTC/USDT', 'BTCUSDT']
            future_symbol = None
            spot_symbol = None
            
            for symbol in test_symbols:
                if symbol in markets:
                    market = markets[symbol]
                    if market.get('active', False):
                        if market.get('type') in ['future', 'swap']:
                            future_symbol = symbol
                            break
                        elif market.get('type') == 'spot':
                            spot_symbol = symbol
            
            # Test future first
            test_symbol = future_symbol or spot_symbol or 'BTC/USDT'
            
            try:
                ticker = exchange.fetch_ticker(test_symbol)
                
                # Check if we have credentials
                has_credentials = bool(exchange.apiKey and exchange.secret)
                
                if exchange_name == 'binance':
                    if has_credentials:
                        # Test account access
                        try:
                            balance = exchange.fetch_balance()
                            return True, f"✅ Binance funcionando com credenciais! BTC/USDT: ${ticker['last']:.2f} | Saldo USDT: ${balance.get('USDT', {}).get('total', 0):.2f}"
                        except Exception as e:
                            return True, f"✅ Binance conectado! BTC/USDT: ${ticker['last']:.2f} | ⚠️ Erro na conta: {str(e)[:50]}"
                    else:
                        return False, f"❌ Binance precisa de credenciais. Configure BINANCE_API_KEY e BINANCE_SECRET"
                else:
                    return True, f"✅ {cls.SUPPORTED_EXCHANGES[exchange_name]['name']} funcionando! BTC/USDT: ${ticker['last']:.2f}"
                    
            except Exception as e:
                return False, f"❌ Erro ao buscar dados do mercado: {str(e)}"
                
        except Exception as e:
            return False, f"❌ Erro ao conectar com {exchange_name}: {str(e)}"
    
    @classmethod
    def get_recommended_for_brazil(cls):
        """Retornar exchange recomendado para Brasil"""
        # Verificar se há credenciais Binance
        if os.getenv('BINANCE_API_KEY') and os.getenv('BINANCE_SECRET'):
            return 'binance'
        return 'okx'
    
    @classmethod
    def get_binance_example_config(cls):
        """Retorna exemplo de configuração para Binance"""
        return """
# === Configuração Binance Futuros ===
# Configure no Replit Secrets (🔒):
# 
# BINANCE_API_KEY = "sua_api_key_aqui"
# BINANCE_SECRET = "seu_api_secret_aqui"
#
# Exemplo de código:
import ccxt
import os

exchange = ccxt.binance({
    "apiKey": os.getenv('BINANCE_API_KEY'),
    "secret": os.getenv('BINANCE_SECRET'),
    "enableRateLimit": True,
    "options": {
        "defaultType": "future"  # Garantir que é Futuros
    }
})

# Testar conexão
try:
    markets = exchange.load_markets()
    balance = exchange.fetch_balance()
    print("✅ Binance conectada com sucesso!")
    print(f"Saldo USDT: {balance.get('USDT', {}).get('total', 0)}")
except Exception as e:
    print(f"❌ Erro: {e}")
"""
