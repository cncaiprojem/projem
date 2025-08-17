from __future__ import annotations

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from datetime import datetime

from .models import Base


# Note: Tool model is now defined in app.models.tool - this is legacy
# Rename to avoid conflicts with the canonical Tool model
class ToolLegacy(Base):
    __tablename__ = "tools_legacy"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    type = Column(String(50), nullable=False)
    diameter_mm = Column(Float, nullable=True)
    flute_count = Column(Integer, nullable=True)
    flute_len_mm = Column(Float, nullable=True)
    overall_len_mm = Column(Float, nullable=True)
    shank_dia_mm = Column(Float, nullable=True)
    stickout_mm = Column(Float, nullable=True)
    material = Column(String(20), nullable=True)
    coating = Column(String(100), nullable=True)
    toolbit_json_path = Column(String(1024), nullable=True)
    sha256 = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Holder(Base):
    __tablename__ = "holders"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    type = Column(String(100), nullable=True)
    gauge_len_mm = Column(Float, nullable=True)
    collision_model_path = Column(String(1024), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ToolPreset(Base):
    __tablename__ = "tool_presets"
    id = Column(Integer, primary_key=True)
    machine_id = Column(Integer, nullable=False)
    tool_id = Column(Integer, ForeignKey("tools.id", ondelete="CASCADE"), nullable=False)
    holder_id = Column(Integer, ForeignKey("holders.id", ondelete="SET NULL"), nullable=True)
    pocket_no = Column(Integer, nullable=False)
    length_offset = Column(Float, nullable=True)
    diameter_offset = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("machine_id", "pocket_no", name="uix_tool_presets_machine_pocket"),
    )


class ShopPackage(Base):
    __tablename__ = "shop_packages"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    pdf_path = Column(String(1024), nullable=False)
    pdf_sha256 = Column(String(64), nullable=False)
    version = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by = Column(String(200), nullable=True)


