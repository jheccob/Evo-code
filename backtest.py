
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from trading_bot import TradingBot
import ccxt
from utils.logger import backtest_logger

class BacktestEngine:
    def __init__(self):
        self.trading_bot = TradingBot()
        self.results = None
        
    def run_backtest(self, symbol, timeframe, start_date, end_date, initial_balance=10000, 
                    rsi_period=9, rsi_min=20, rsi_max=80):
        """
        Run backtest for a given symbol and parameters
        
        Args:
            symbol: Trading pair (e.g., 'XLM-USD')
            timeframe: Candle timeframe (e.g., '5m', '1h')
            start_date: Start date for backtest
            end_date: End date for backtest
            initial_balance: Starting balance for backtest
            rsi_period: RSI calculation period
            rsi_min: RSI oversold threshold
            rsi_max: RSI overbought threshold
        """
        
        try:
            backtest_logger.info(f"Iniciando backtest para {symbol} de {start_date} até {end_date}")
            
            # Configure trading bot
            self.trading_bot.update_config(
                symbol=symbol,
                timeframe=timeframe,
                rsi_period=rsi_period,
                rsi_min=rsi_min,
                rsi_max=rsi_max
            )
            
            # Get historical data
            # Calculate how many candles we need
            timeframe_minutes = self._get_timeframe_minutes(timeframe)
            total_minutes = (end_date - start_date).total_seconds() / 60
            limit = int(total_minutes / timeframe_minutes) + 100  # Extra for indicators
            
            # Fetch data - limit to API constraints
            data = self.trading_bot.get_market_data(limit=min(limit, 1000))
            
            if data is None or data.empty:
                raise Exception("Nenhum dado recebido para backtesting")
            
            backtest_logger.info(f"Dados obtidos: {len(data)} candles")
            
            # Filter data to backtest period if we have enough data
            if len(data) > 50:
                # Use all available data if date filtering results in too little data
                filtered_data = data[(data.index >= start_date) & (data.index <= end_date)]
                if len(filtered_data) >= 50:
                    data = filtered_data
                else:
                    backtest_logger.warning("Dados insuficientes no período selecionado, usando todos os dados disponíveis")
            
            if len(data) < 50:
                raise Exception("Dados insuficientes para backtesting (mínimo 50 candles)")
            
            # Run simulation
            results = self._simulate_trading(data, initial_balance)
            backtest_logger.info("Backtest concluído com sucesso")
            return results
            
        except Exception as e:
            backtest_logger.error(f"Erro no backtest: {str(e)}")
            raise Exception(f"Backtest falhou: {str(e)}")
    
    def _get_timeframe_minutes(self, timeframe):
        """Convert timeframe to minutes"""
        timeframe_map = {
            '1m': 1, '5m': 5, '15m': 15, '30m': 30,
            '1h': 60, '4h': 240, '6h': 360, '1d': 1440
        }
        return timeframe_map.get(timeframe, 5)
    
    def _simulate_trading(self, data, initial_balance):
        """
        Simulate trading based on signals with improved logic
        """
        balance = initial_balance
        position = 0  # 0 = no position, 1 = long position
        entry_price = 0
        trades = []
        portfolio_values = []
        
        max_position_size = 0.95  # Use 95% of balance per trade
        
        for i in range(len(data)):
            current_candle = data.iloc[i]
            current_price = current_candle['close']
            signal = current_candle.get('signal', 'NEUTRO')
            timestamp = data.index[i]
            
            # Calculate portfolio value
            if position == 0:
                portfolio_value = balance
            else:
                # Calculate current value of position
                position_value = balance * (current_price / entry_price)
                portfolio_value = position_value
            
            portfolio_values.append({
                'timestamp': timestamp,
                'price': current_price,
                'portfolio_value': portfolio_value,
                'signal': signal,
                'position': position
            })
            
            # Trading logic with improved entry/exit
            if signal in ['COMPRA', 'COMPRA_FRACA'] and position == 0 and balance > 0:
                # Enter long position
                position = 1
                entry_price = current_price
                
                trades.append({
                    'timestamp': timestamp,
                    'type': 'BUY',
                    'price': current_price,
                    'signal': signal,
                    'balance_before': balance
                })
                
            elif signal in ['VENDA', 'VENDA_FRACA'] and position == 1:
                # Exit long position
                # Calculate profit/loss
                price_change_pct = (current_price - entry_price) / entry_price
                new_balance = balance * (1 + price_change_pct)
                profit_loss = new_balance - balance
                
                trades.append({
                    'timestamp': timestamp,
                    'type': 'SELL',
                    'price': current_price,
                    'signal': signal,
                    'entry_price': entry_price,
                    'profit_loss': profit_loss,
                    'profit_loss_pct': price_change_pct * 100,
                    'balance_after': new_balance
                })
                
                balance = new_balance
                position = 0
                entry_price = 0
        
        # Close any open position at the end
        if position == 1:
            final_price = data.iloc[-1]['close']
            price_change_pct = (final_price - entry_price) / entry_price
            final_balance = balance * (1 + price_change_pct)
            profit_loss = final_balance - balance
            
            trades.append({
                'timestamp': data.index[-1],
                'type': 'SELL',
                'price': final_price,
                'signal': 'CLOSE_FINAL',
                'entry_price': entry_price,
                'profit_loss': profit_loss,
                'profit_loss_pct': price_change_pct * 100,
                'balance_after': final_balance
            })
            balance = final_balance
        
        # Calculate final results
        final_portfolio_value = balance
        total_return = (final_portfolio_value - initial_balance) / initial_balance * 100
        
        # Calculate statistics
        sell_trades = [t for t in trades if t['type'] == 'SELL']
        winning_trades = [t for t in sell_trades if t['profit_loss'] > 0]
        losing_trades = [t for t in sell_trades if t['profit_loss'] <= 0]
        
        total_trades = len(sell_trades)
        win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0
        
        avg_profit = np.mean([t['profit_loss_pct'] for t in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([abs(t['profit_loss_pct']) for t in losing_trades]) if losing_trades else 0
        
        stats = {
            'initial_balance': initial_balance,
            'final_balance': final_portfolio_value,
            'total_return_pct': total_return,
            'total_trades': total_trades,
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': win_rate,
            'avg_profit': avg_profit,
            'avg_loss': avg_loss,
            'max_drawdown': self._calculate_max_drawdown(portfolio_values, initial_balance),
            'sharpe_ratio': self._calculate_sharpe_ratio(portfolio_values, initial_balance),
            'profit_factor': self._calculate_profit_factor(winning_trades, losing_trades)
        }
        
        self.results = {
            'stats': stats,
            'trades': trades,
            'portfolio_values': portfolio_values,
            'data': data
        }
        
        return self.results
    
    def _calculate_max_drawdown(self, portfolio_values, initial_balance):
        """Calculate maximum drawdown"""
        if not portfolio_values:
            return 0
        
        values = [p['portfolio_value'] for p in portfolio_values]
        peak = initial_balance
        max_drawdown = 0
        
        for value in values:
            if value > peak:
                peak = value
            drawdown = (peak - value) / peak * 100
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        return max_drawdown
    
    def _calculate_sharpe_ratio(self, portfolio_values, initial_balance):
        """Calculate Sharpe ratio"""
        if len(portfolio_values) < 2:
            return 0
        
        values = [p['portfolio_value'] for p in portfolio_values]
        returns = [(values[i] - values[i-1]) / values[i-1] for i in range(1, len(values)) if values[i-1] != 0]
        
        if not returns or len(returns) < 2:
            return 0
        
        avg_return = np.mean(returns)
        std_return = np.std(returns)
        
        if std_return == 0:
            return 0
        
        # Annualized Sharpe ratio
        periods_per_year = 252  # Trading days
        sharpe = (avg_return / std_return) * np.sqrt(periods_per_year)
        return sharpe
    
    def _calculate_profit_factor(self, winning_trades, losing_trades):
        """Calculate profit factor (gross profits / gross losses)"""
        total_profits = sum([t['profit_loss'] for t in winning_trades]) if winning_trades else 0
        total_losses = abs(sum([t['profit_loss'] for t in losing_trades])) if losing_trades else 0
        
        if total_losses == 0:
            return float('inf') if total_profits > 0 else 0
        
        return total_profits / total_losses
    
    def get_trade_summary_df(self):
        """Get trades as DataFrame for display"""
        if not self.results or not self.results['trades']:
            return pd.DataFrame()
        
        trades = self.results['trades']
        sell_trades = [t for t in trades if t['type'] == 'SELL']
        
        if not sell_trades:
            return pd.DataFrame()
        
        df = pd.DataFrame(sell_trades)
        
        # Ensure we have all required columns
        required_columns = ['timestamp', 'entry_price', 'price', 'profit_loss_pct', 'profit_loss', 'signal']
        for col in required_columns:
            if col not in df.columns:
                df[col] = 0 if col in ['profit_loss_pct', 'profit_loss'] else 'N/A'
        
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        return df[required_columns]
