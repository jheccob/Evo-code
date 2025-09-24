
import ccxt
import os

class ExchangeConfig:
    """Configuração de exchanges que funcionam no Brasil"""
    
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
    
    # Exchanges recomendados para Brasil
    SUPPORTED_EXCHANGES = {
        'okx': {
            'name': 'OKX',
            'futures_supported': True,
            'brazil_accessible': True,
            'usdt_pairs': True,
            'description': 'Exchange principal recomendado para futuros USDT no Brasil'
        },
        'coinbase': {
            'name': 'Coinbase',
            'futures_supported': False,
            'brazil_accessible': True,
            'usdt_pairs': False,
            'usd_pairs': True,
            'description': 'Coinbase - exchange confiável para spot trading'
        },
        'bybit': {
            'name': 'Bybit',
            'futures_supported': True,
            'brazil_accessible': False,  # Bloqueado geograficamente
            'usdt_pairs': True,
            'description': 'Exchange bloqueado no Brasil via CloudFront'
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
    def get_exchange_instance(cls, exchange_name='okx', testnet=False):
        """Criar instância do exchange configurado para Brasil"""
        
        if exchange_name not in cls.SUPPORTED_EXCHANGES:
            raise ValueError(f"Exchange {exchange_name} não suportado")
        
        exchange_class = getattr(ccxt, exchange_name)
        
        config = {
            'enableRateLimit': True,
            'sandbox': testnet,
            'rateLimit': 1200,
            'timeout': 60000,
            'options': {
                'adjustForTimeDifference': True,
                'recvWindow': 10000,
            },
            'headers': {
                'User-Agent': 'TradingBot-Brazil/1.0'
            }
        }
        
        # Configurações específicas por exchange
        if exchange_name == 'coinbase':
            config.update({
                'options': {
                    'defaultType': 'spot',  # Apenas spot trading
                },
                'rateLimit': 2000,  # Coinbase tem limites mais restritivos
            })
        elif exchange_name == 'bybit':
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
    def get_usdt_pairs(cls, exchange_name='okx'):
        """Obter pares USDT disponíveis com metadados completos"""
        try:
            exchange = cls.get_exchange_instance(exchange_name)
            markets = exchange.load_markets()
            
            pairs = []
            normalized_symbols = set()  # Evitar duplicados
            
            for symbol, market in markets.items():
                # Para Coinbase, usar pares USD spot
                if exchange_name == 'coinbase':
                    if (symbol.endswith('/USD') and 
                        market.get('active', True) and
                        market.get('type') == 'spot'):
                        pairs.append(symbol)
                        normalized_symbols.add(symbol)
                else:
                    # Para outros exchanges, priorizar futuros USDT
                    if (market.get('active', True) and
                        market.get('type') in ['future', 'swap']):
                        # Futuros USDT podem vir como BTC/USDT:USDT
                        if ':USDT' in symbol or (symbol.endswith('/USDT') and market.get('type') in ['future', 'swap']):
                            normalized = cls.normalize_symbol(symbol, market)
                            if normalized['symbol'] not in normalized_symbols:
                                pairs.append(normalized['symbol'])
                                normalized_symbols.add(normalized['symbol'])
                    # Incluir spot USDT apenas se não há future equivalente
                    elif (symbol.endswith('/USDT') and 
                          market.get('type') == 'spot' and
                          symbol not in normalized_symbols):
                        pairs.append(symbol)
                        normalized_symbols.add(symbol)
            
            return sorted(pairs)
        except Exception as e:
            print(f"Erro ao carregar pares: {e}")
            # Fallback baseado no exchange - símbolos normalizados
            if exchange_name == 'coinbase':
                return ["BTC/USD", "ETH/USD", "XLM/USD"]
            else:
                return ["BTC/USDT", "ETH/USDT", "XLM/USDT", "ADA/USDT", "DOT/USDT"]
    
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
    def test_connection(cls, exchange_name='okx'):
        """Testar conexão com exchange"""
        try:
            exchange = cls.get_exchange_instance(exchange_name)
            
            if exchange_name == 'coinbase':
                test_pair = 'BTC/USD'
                ticker = exchange.fetch_ticker(test_pair)
                return True, f"✅ Conexão com {exchange_name} funcionando! BTC: ${ticker['last']:.2f} USD"
            else:
                # Para exchanges de futuros, validar que podemos acessar ambos os formatos
                markets = exchange.load_markets()
                
                # Procurar por futuros BTC/USDT
                future_symbol = None
                spot_symbol = None
                
                for symbol, market in markets.items():
                    if market.get('active', False):
                        if 'BTC' in symbol and 'USDT' in symbol:
                            if market.get('type') in ['future', 'swap']:
                                future_symbol = symbol
                                break
                            elif market.get('type') == 'spot':
                                spot_symbol = symbol
                
                # Testar future primeiro
                if future_symbol:
                    try:
                        ticker = exchange.fetch_ticker(future_symbol)
                        normalized = cls.normalize_symbol(future_symbol)
                        return True, f"✅ {exchange_name} funcionando! BTC/USDT Futuros: ${ticker['last']:.2f} (par: {normalized['symbol']})"
                    except Exception as e:
                        print(f"Erro no future {future_symbol}: {e}")
                
                # Fallback para spot
                if spot_symbol:
                    try:
                        ticker = exchange.fetch_ticker(spot_symbol)
                        return True, f"✅ {exchange_name} funcionando! BTC/USDT Spot: ${ticker['last']:.2f}"
                    except Exception as e:
                        print(f"Erro no spot {spot_symbol}: {e}")
                
                return False, f"❌ Nenhum par BTC/USDT encontrado em {exchange_name}"
                
        except Exception as e:
            return False, f"❌ Erro ao conectar com {exchange_name}: {str(e)}"
    
    @classmethod
    def get_recommended_for_brazil(cls):
        """Retornar exchange recomendado para Brasil"""
        return 'okx'
