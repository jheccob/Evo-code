import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from trading_bot import TradingBot
import ccxt

class BacktestEngine:
    def __init__(self):
        self.trading_bot = TradingBot()
        self.results = None
        
    def run_backtest(self, symbol, timeframe, start_date, end_date, initial_balance=10000, 
                    rsi_period=9, rsi_min=20, rsi_max=80):
        """
        Run backtest for a given symbol and parameters
        
        Args:
            symbol: Trading pair (e.g., 'BTC/USDT')
            timeframe: Candle timeframe (e.g., '5m', '1h')
            start_date: Start date for backtest
            end_date: End date for backtest
            initial_balance: Starting balance for backtest
            rsi_period: RSI calculation period
            rsi_min: RSI oversold threshold
            rsi_max: RSI overbought threshold
        """
        
        # Configure trading bot
        self.trading_bot.update_config(
            symbol=symbol,
            timeframe=timeframe,
            rsi_period=rsi_period,
            rsi_min=rsi_min,
            rsi_max=rsi_max
        )
        
        # Get historical data
        try:
            # Calculate how many candles we need
            timeframe_minutes = self._get_timeframe_minutes(timeframe)
            total_minutes = (end_date - start_date).total_seconds() / 60
            limit = int(total_minutes / timeframe_minutes) + 200  # Extra for indicators
            
            # Fetch data
            data = self.trading_bot.get_market_data(limit=min(limit, 1000))  # API limit
            
            if data is None or data.empty:
                raise Exception("No data received for backtesting")
            
            # Filter data to backtest period
            data = data[(data.index >= start_date) & (data.index <= end_date)]
            
            if len(data) < 50:
                raise Exception("Insufficient data for backtesting period")
            
            # Run simulation
            return self._simulate_trading(data, initial_balance)
            
        except Exception as e:
            raise Exception(f"Backtest failed: {str(e)}")
    
    def _get_timeframe_minutes(self, timeframe):
        """Convert timeframe to minutes"""
        if timeframe == '1m':
            return 1
        elif timeframe == '5m':
            return 5
        elif timeframe == '15m':
            return 15
        elif timeframe == '30m':
            return 30
        elif timeframe == '1h':
            return 60
        elif timeframe == '4h':
            return 240
        elif timeframe == '1d':
            return 1440
        else:
            return 5  # Default
    
    def _simulate_trading(self, data, initial_balance):
        """
        Simulate trading based on signals
        """
        balance = initial_balance
        position = 0  # 0 = no position, 1 = long position
        entry_price = 0
        trades = []
        portfolio_values = []
        
        for i in range(len(data)):
            current_candle = data.iloc[i]
            current_price = current_candle['close']
            signal = current_candle['signal']
            timestamp = data.index[i]
            
            # Calculate portfolio value
            if position == 0:
                portfolio_value = balance
            else:
                portfolio_value = balance + (balance * (current_price - entry_price) / entry_price)
            
            portfolio_values.append({
                'timestamp': timestamp,
                'price': current_price,
                'portfolio_value': portfolio_value,
                'signal': signal,
                'position': position
            })
            
            # Trading logic
            if signal in ['COMPRA', 'COMPRA_FRACA'] and position == 0:
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
                profit_loss = balance * (current_price - entry_price) / entry_price
                balance += profit_loss
                
                trades.append({
                    'timestamp': timestamp,
                    'type': 'SELL',
                    'price': current_price,
                    'signal': signal,
                    'entry_price': entry_price,
                    'profit_loss': profit_loss,
                    'profit_loss_pct': (current_price - entry_price) / entry_price * 100,
                    'balance_after': balance
                })
                
                position = 0
                entry_price = 0
        
        # Calculate final results
        final_portfolio_value = portfolio_values[-1]['portfolio_value'] if portfolio_values else initial_balance
        total_return = (final_portfolio_value - initial_balance) / initial_balance * 100
        
        # Calculate statistics
        winning_trades = [t for t in trades if t['type'] == 'SELL' and t['profit_loss'] > 0]
        losing_trades = [t for t in trades if t['type'] == 'SELL' and t['profit_loss'] < 0]
        
        stats = {
            'initial_balance': initial_balance,
            'final_balance': final_portfolio_value,
            'total_return_pct': total_return,
            'total_trades': len([t for t in trades if t['type'] == 'SELL']),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': len(winning_trades) / len([t for t in trades if t['type'] == 'SELL']) * 100 if trades else 0,
            'avg_profit': np.mean([t['profit_loss_pct'] for t in winning_trades]) if winning_trades else 0,
            'avg_loss': np.mean([t['profit_loss_pct'] for t in losing_trades]) if losing_trades else 0,
            'max_drawdown': self._calculate_max_drawdown(portfolio_values, initial_balance),
            'sharpe_ratio': self._calculate_sharpe_ratio(portfolio_values, initial_balance)
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
        """Calculate Sharpe ratio (simplified)"""
        if len(portfolio_values) < 2:
            return 0
        
        values = [p['portfolio_value'] for p in portfolio_values]
        returns = [(values[i] - values[i-1]) / values[i-1] for i in range(1, len(values))]
        
        if not returns:
            return 0
        
        avg_return = np.mean(returns)
        std_return = np.std(returns)
        
        if std_return == 0:
            return 0
        
        # Annualized Sharpe ratio (assuming daily returns)
        sharpe = (avg_return / std_return) * np.sqrt(252)
        return sharpe
    
    def get_trade_summary_df(self):
        """Get trades as DataFrame for display"""
        if not self.results or not self.results['trades']:
            return pd.DataFrame()
        
        trades = self.results['trades']
        sell_trades = [t for t in trades if t['type'] == 'SELL']
        
        if not sell_trades:
            return pd.DataFrame()
        
        df = pd.DataFrame(sell_trades)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        return df[['timestamp', 'entry_price', 'price', 'profit_loss_pct', 'profit_loss', 'signal']]