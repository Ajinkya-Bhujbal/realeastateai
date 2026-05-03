"""
Database models - Lead, Message, Property, FollowUpSchedule
"""
import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from db import Base


class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    phone = Column(String(20), nullable=True)
    email = Column(String(200), nullable=True)
    source = Column(String(50), default="manual")  # housing, 99acres, magicbricks, manual
    status = Column(String(30), default="new")  # new, contacted, interested, converted, lost
    budget_min = Column(Float, nullable=True)
    budget_max = Column(Float, nullable=True)
    preferred_location = Column(String(300), nullable=True)
    property_type = Column(String(50), nullable=True)  # apartment, villa, plot
    configuration = Column(String(50), nullable=True)  # 1 BHK, 2 BHK, etc.
    price = Column(String(50), nullable=True)  # parsed string like Rs 5200000 or ₹ 18.0k
    tag = Column(String(100), default="NEW")  # NEW, visited, interested, not interested, or custom
    notes = Column(Text, nullable=True)
    # Chat tracking
    last_message_at = Column(DateTime, nullable=True)
    unread_count = Column(Integer, default=0)
    auto_reply_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    messages = relationship("Message", back_populates="lead", cascade="all, delete-orphan")
    followups = relationship("FollowUpSchedule", back_populates="lead", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False)
    direction = Column(String(10), default="out")  # in, out
    channel = Column(String(20), default="whatsapp")  # whatsapp, email, sms
    content = Column(Text, nullable=False)
    status = Column(String(20), default="sent")  # sent, delivered, read, failed
    is_read = Column(Boolean, default=False)  # has agent seen this message
    is_auto_replied = Column(Boolean, default=False)  # was auto-reply sent for this
    wa_message_id = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    lead = relationship("Lead", back_populates="messages")


class Property(Base):
    __tablename__ = "properties"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(300), nullable=False)
    location = Column(String(300), nullable=False)
    price = Column(Float, nullable=False)
    property_type = Column(String(50), default="apartment")  # apartment, villa, plot, office
    bedrooms = Column(Integer, nullable=True)
    area_sqft = Column(Float, nullable=True)
    description = Column(Text, nullable=True)
    amenities = Column(Text, nullable=True)  # comma-separated
    builder = Column(String(200), nullable=True)
    status = Column(String(30), default="available")  # available, sold, upcoming
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class FollowUpSchedule(Base):
    __tablename__ = "followup_schedules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False)
    frequency_hours = Column(Integer, default=24)  # follow-up every N hours
    next_followup_at = Column(DateTime, nullable=False)
    message_template = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    max_followups = Column(Integer, default=5)
    followups_sent = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    lead = relationship("Lead", back_populates="followups")
