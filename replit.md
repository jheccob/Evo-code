# Trading Bot Dashboard

## Overview

This is a Python-based cryptocurrency trading bot application with Telegram integration, built using Streamlit for the web interface. The system provides technical analysis of cryptocurrency markets using indicators like RSI and MACD, sends trading signals via Telegram, and includes user management with premium subscription tiers. The bot supports backtesting capabilities and real-time market data analysis from various exchanges.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Frontend Architecture
- **Streamlit Dashboard**: Main web interface for configuration, monitoring, and visualization
- **Plotly Integration**: Interactive charts for displaying market data and technical indicators
- **Real-time Updates**: Live data streaming and signal monitoring through the web interface

### Backend Architecture
- **Trading Engine**: Core bot logic for signal generation using technical indicators (RSI, MACD, SMA, EMA)
- **Exchange Integration**: Uses CCXT library for multi-exchange support (Coinbase Pro as primary)
- **Modular Design**: Separated concerns with dedicated modules for indicators, backtesting, and user management
- **Asynchronous Processing**: Async/await patterns for handling Telegram communications and API calls

### Technical Analysis System
- **Indicator Engine**: Centralized calculation of technical indicators (RSI, MACD, moving averages)
- **Signal Generation**: Rule-based system for buy/sell/hold signals based on configurable thresholds
- **Backtest Engine**: Historical performance testing with customizable parameters
- **Market Data Pipeline**: Real-time OHLCV data fetching with rate limiting and error handling

### User Management & Authentication
- **Tier-based Access**: Free and premium user tiers with different feature limits
- **JSON-based Storage**: User data persistence with local file storage
- **Admin System**: Administrative controls for user management and broadcasting

### Data Storage Solutions
- **SQLite Database**: Primary storage for trading signals, user data, and configuration settings
- **JSON Configuration**: Settings and user preferences stored in structured JSON format
- **Time Series Data**: Market data with Brazilian timezone handling and formatting utilities

## External Dependencies

### Trading & Market Data
- **CCXT Library**: Multi-exchange cryptocurrency trading library for market data
- **Coinbase Pro API**: Primary exchange for market data and trading operations
- **Pandas & NumPy**: Data manipulation and numerical analysis for indicator calculations

### Communication & Notifications
- **Telegram Bot API**: Real-time notifications and user interaction through Telegram
- **Python-telegram-bot**: Telegram bot framework for command handling and message processing

### Web Interface & Visualization
- **Streamlit**: Web application framework for the dashboard interface
- **Plotly**: Interactive charting library for market data visualization

### Payment Processing (Production)
- **Stripe Integration**: Subscription billing for premium features
- **Payment Links**: Automated subscription management and billing

### Monitoring & Performance
- **Prometheus Metrics**: System monitoring and performance tracking
- **Redis**: Rate limiting and caching (production environment)
- **Logging System**: Comprehensive logging with file and console output

### Development & Deployment
- **SQLAlchemy**: Database ORM for data modeling and relationships
- **Alembic**: Database migration management
- **FastAPI**: Production API framework (alternative deployment)
- **PostgreSQL**: Production database option with async support
- **Replit Environment**: Successfully configured for Replit with all dependencies installed
- **Streamlit Deployment**: Configured for autoscale deployment on port 5000

## Replit Environment Setup (September 21, 2025)

### Setup Completed
- ✅ Python dependencies installed via uv package manager
- ✅ Streamlit configuration verified (.streamlit/config.toml configured for 0.0.0.0:5000)
- ✅ SQLite database working with existing data (102 trading signals)
- ✅ Trading Dashboard workflow running successfully
- ✅ Deployment configuration set for autoscale
- ✅ All core imports and functionality verified

### Current Status
- **Frontend**: Streamlit dashboard running on port 5000
- **Database**: SQLite working with historical trading data
- **API Integration**: CCXT library configured for Coinbase Pro
- **Telegram**: Service available but requires user configuration
- **Deployment**: Ready for production deployment