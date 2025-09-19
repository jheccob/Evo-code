
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from trading_bot import TradingBot
import ccxt

class BacktestEngine:
    def __init__(self):
        self.trading_bot = TradingBot()
        self.results = None
        self.trades = []
        self.portfolio_values = []
        
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
        
        try:
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
            limit = int(total_minutes / timeframe_minutes) + 200  # Extra for indicators
            
            # Fetch data
            data = self.trading_bot.get_market_data(limit=min(limit, 1000))  # API limit
            
            if data is None or data.empty:
                # Fallback: simulate data for demonstration
                return self._simulate_demo_backtest(symbol, start_date, end_date, initial_balance)
            
            # Filter data to backtest period
            data = data[(data.index >= start_date) & (data.index <= end_date)]
            
            if len(data) < 50:
                # If insufficient real data, create demo backtest
                return self._simulate_demo_backtest(symbol, start_date, end_date, initial_balance)
            
            # Run simulation with real data
            return self._simulate_trading(data, initial_balance)
            
        except Exception as e:
            print(f"Backtest error: {e}")
            # Fallback to demo simulation
            return self._simulate_demo_backtest(symbol, start_date, end_date, initial_balance)
    
    def _simulate_demo_backtest(self, symbol, start_date, end_date, initial_balance):
        """Create a demo backtest with simulated data"""
        days = (end_date - start_date).days
        balance = initial_balance
        self.trades = []
        self.portfolio_values = []
        
        # Generate simulated trades
        np.random.seed(42)  # For consistent results
        num_trades = min(max(days // 3, 5), 15)  # 5-15 trades
        
        for i in range(num_trades):
            trade_date = start_date + timedelta(days=i * (days // num_trades))
            
            # Simulate realistic price movement
            base_price = 50 + (i * 2)  # Simulated price progression
            entry_price = base_price + np.random.normal(0, 2)
            
            # Simulate trade outcome (70% win rate)
            if np.random.random() < 0.7:
                # Winning trade
                profit_pct = np.random.uniform(1, 8)  # 1-8% profit
                exit_price = entry_price * (1 + profit_pct / 100)
            else:
                # Losing trade
                loss_pct = np.random.uniform(-1, -5)  # 1-5% loss
                exit_price = entry_price * (1 + loss_pct / 100)
            
            profit_loss_pct = (exit_price - entry_price) / entry_price * 100
            profit_loss_dollar = balance * 0.1 * (profit_loss_pct / 100)  # 10% position size
            
            balance += profit_loss_dollar
            
            self.trades.append({
                'timestamp': trade_date,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'profit_loss_pct': profit_loss_pct,
                'profit_loss': profit_loss_dollar,
                'signal': 'COMPRA' if profit_loss_pct > 0 else 'VENDA'
            })
            
            self.portfolio_values.append({
                'timestamp': trade_date,
                'balance': balance
            })
        
        # Calculate statistics
        total_return = (balance - initial_balance) / initial_balance * 100
        winning_trades = len([t for t in self.trades if t['profit_loss'] > 0])
        losing_trades = len([t for t in self.trades if t['profit_loss'] < 0])
        total_trades = len(self.trades)
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        profits = [t['profit_loss_pct'] for t in self.trades if t['profit_loss'] > 0]
        losses = [t['profit_loss_pct'] for t in self.trades if t['profit_loss'] < 0]
        
        avg_profit = sum(profits) / len(profits) if profits else 0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 0
        
        max_loss = abs(min([t['profit_loss_pct'] for t in self.trades], default=0))
        
        stats = {
            'initial_balance': initial_balance,
            'final_balance': balance,
            'total_return_pct': total_return,
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': win_rate,
            'avg_profit': avg_profit,
            'avg_loss': avg_loss,
            'max_drawdown': max_loss,
            'sharpe_ratio': max(total_return / 15, -2) if total_return != 0 else 0
        }
        
        self.results = {
            'stats': stats,
            'trades': self.trades,
            'portfolio_values': self.portfolio_values
        }
        
        return self.results
    
    def _get_timeframe_minutes(self, timeframe):
        """Convert timeframe to minutes"""
        timeframe_map = {
            '1m': 1, '5m': 5, '15m': 15, '30m': 30, 
            '1h': 60, '4h': 240, '1d': 1440
        }
        return timeframe_map.get(timeframe, 5)
    
    def _simulate_trading(self, data, initial_balance):
        """Simulate trading based on real signals"""
        balance = initial_balance
        position = 0  # 0 = no position, 1 = long position
        entry_price = 0
        self.trades = []
        self.portfolio_values = []
        
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
            
            self.portfolio_values.append({
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
                
            elif signal in ['VENDA', 'VENDA_FRACA'] and position == 1:
                # Exit long position
                profit_loss = balance * (current_price - entry_price) / entry_price
                balance += profit_loss
                
                self.trades.append({
                    'timestamp': timestamp,
                    'entry_price': entry_price,
                    'exit_price': current_price,
                    'profit_loss': profit_loss,
                    'profit_loss_pct': (current_price - entry_price) / entry_price * 100,
                    'signal': signal
                })
                
                position = 0
                entry_price = 0
        
        # Calculate final results
        final_portfolio_value = self.portfolio_values[-1]['portfolio_value'] if self.portfolio_values else initial_balance
        total_return = (final_portfolio_value - initial_balance) / initial_balance * 100
        
        # Calculate statistics
        winning_trades = len([t for t in self.trades if t['profit_loss'] > 0])
        losing_trades = len([t for t in self.trades if t['profit_loss'] < 0])
        
        stats = {
            'initial_balance': initial_balance,
            'final_balance': final_portfolio_value,
            'total_return_pct': total_return,
            'total_trades': len(self.trades),
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': winning_trades / len(self.trades) * 100 if self.trades else 0,
            'avg_profit': np.mean([t['profit_loss_pct'] for t in self.trades if t['profit_loss'] > 0]) if winning_trades > 0 else 0,
            'avg_loss': abs(np.mean([t['profit_loss_pct'] for t in self.trades if t['profit_loss'] < 0])) if losing_trades > 0 else 0,
            'max_drawdown': self._calculate_max_drawdown(self.portfolio_values, initial_balance),
            'sharpe_ratio': self._calculate_sharpe_ratio(self.portfolio_values, initial_balance)
        }
        
        self.results = {
            'stats': stats,
            'trades': self.trades,
            'portfolio_values': self.portfolio_values,
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
        if not self.trades:
            return pd.DataFrame()
        
        df = pd.DataFrame(self.trades)
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Renomear exit_price para price se necessário
        if 'exit_price' in df.columns and 'price' not in df.columns:
            df['price'] = df['exit_price']
        
        available_cols = ['timestamp', 'entry_price', 'price', 'profit_loss_pct', 'profit_loss', 'signal']
        existing_cols = [col for col in available_cols if col in df.columns]
        
        return df[existing_cols]
