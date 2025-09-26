
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
    
    # Exchanges suportados - foco em WebSocket público
    SUPPORTED_EXCHANGES = {
        'binance': {
            'name': 'Binance WebSocket Público',
            'futures_supported': True,
            'brazil_accessible': True,
            'usdt_pairs': True,
            'requires_credentials': False,
            'description': 'Binance - WebSocket público sem necessidade de credenciais'
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
            
            print("✅ Binance WebSocket Público configurado - sem necessidade de credenciais")
            print("📡 Usando dados públicos em tempo real via WebSocket")
        
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
        """Testar conexão WebSocket público da Binance"""
        try:
            print("🔄 Testando WebSocket público da Binance Futures...")
            
            # Testar endpoints públicos da Binance
            import requests
            
            endpoints_test = [
                {
                    'name': 'Binance API Spot',
                    'url': 'https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT'
                },
                {
                    'name': 'Binance API Futures',
                    'url': 'https://fapi.binance.com/fapi/v1/ticker/price?symbol=BTCUSDT'
                },
                {
                    'name': 'Binance US (Backup)',
                    'url': 'https://api.binance.us/api/v3/ticker/price?symbol=BTCUSDT'
                }
            ]
            
            working_endpoints = []
            
            for endpoint in endpoints_test:
                try:
                    response = requests.get(endpoint['url'], timeout=5)
                    if response.status_code == 200:
                        data = response.json()
                        if 'price' in data:
                            price = float(data['price'])
                            working_endpoints.append(f"✅ {endpoint['name']}: ${price:,.2f}")
                    else:
                        working_endpoints.append(f"⚠️ {endpoint['name']}: HTTP {response.status_code}")
                except Exception as e:
                    working_endpoints.append(f"❌ {endpoint['name']}: {str(e)[:30]}...")
            
            # Testar WebSocket endpoint
            try:
                ws_test_response = requests.get('https://fstream.binance.com', timeout=5)
                ws_status = f"✅ WebSocket endpoint disponível" if ws_test_response.status_code == 200 else f"⚠️ WebSocket: HTTP {ws_test_response.status_code}"
                working_endpoints.append(ws_status)
            except:
                working_endpoints.append("❌ WebSocket endpoint não acessível")
            
            # Se pelo menos um endpoint funcionar, considerar como sucesso
            success_count = len([e for e in working_endpoints if e.startswith('✅')])
            
            if success_count > 0:
                result_msg = f"🌐 WebSocket Público da Binance: {success_count}/{len(endpoints_test)} endpoints funcionando\n"
                result_msg += "\n".join(working_endpoints)
                result_msg += "\n\n📡 Sistema configurado para usar dados públicos sem credenciais!"
                return True, result_msg
            else:
                result_msg = "❌ Nenhum endpoint público da Binance acessível:\n"
                result_msg += "\n".join(working_endpoints)
                return False, result_msg
                
        except Exception as e:
            return False, f"❌ Erro ao testar WebSocket público: {str(e)}"
    
    @classmethod
    def get_recommended_for_brazil(cls):
        """Retornar exchange recomendado para Brasil"""
        # Sempre usar Binance WebSocket público
        return 'binance'
    
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
