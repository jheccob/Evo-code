
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Float, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import uuid

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(String(50), unique=True, nullable=False)
    username = Column(String(100))
    first_name = Column(String(100))
    plan = Column(String(20), default='free')
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    premium_until = Column(DateTime)
    total_analyses = Column(Integer, default=0)
    
    # Relationships
    analyses = relationship("Analysis", back_populates="user")
    subscriptions = relationship("Subscription", back_populates="user")

class Analysis(Base):
    __tablename__ = 'analyses'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    symbol = Column(String(20), nullable=False)
    signal = Column(String(20))
    price = Column(Float)
    rsi = Column(Float)
    macd = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)
    execution_time = Column(Float)  # Tempo em segundos
    
    # Relationships
    user = relationship("User", back_populates="analyses")

class Subscription(Base):
    __tablename__ = 'subscriptions'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    stripe_subscription_id = Column(String(100), unique=True)
    status = Column(String(20))
    current_period_start = Column(DateTime)
    current_period_end = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="subscriptions")

class SystemMetrics(Base):
    __tablename__ = 'system_metrics'
    
    id = Column(Integer, primary_key=True)
    metric_name = Column(String(100), nullable=False)
    value = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow)

class ApiUsage(Base):
    __tablename__ = 'api_usage'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    endpoint = Column(String(100))
    timestamp = Column(DateTime, default=datetime.utcnow)
    response_time = Column(Float)
    status_code = Column(Integer)
