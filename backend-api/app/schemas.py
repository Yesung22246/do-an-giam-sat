from datetime import datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, EmailStr, ConfigDict, Field


# ==================== AUTH & USER SCHEMAS ====================
class AuthRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=4)


class TokenResponse(BaseModel):
    token: str


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    max_monitors: int
    min_interval: int
    price: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: str
    plan_id: int
    created_at: datetime
    plan: Optional[PlanOut] = None


class UpdateUserPlanRequest(BaseModel):
    plan_id: int


# ==================== MONITOR SCHEMAS ====================
class MonitorCreate(BaseModel):
    name: str = Field(..., min_length=1)
    type: Literal["http", "tcp", "ssl"]
    target: str = Field(..., min_length=1)
    port: Optional[int] = None
    interval_seconds: int = 60
    timeout_seconds: float = 10.0
    expected_status: Optional[int] = 200
    retries: int = 3
    ssl_warn_days: int = 14
    enabled: bool = True


class MonitorUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[Literal["http", "tcp", "ssl"]] = None
    target: Optional[str] = None
    port: Optional[int] = None
    interval_seconds: Optional[int] = None
    timeout_seconds: Optional[float] = None
    expected_status: Optional[int] = None
    retries: Optional[int] = None
    ssl_warn_days: Optional[int] = None
    enabled: Optional[bool] = None


class MonitorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: Optional[int] = None
    name: str
    type: str
    target: str
    port: Optional[int] = None
    interval_seconds: int
    timeout_seconds: float
    expected_status: Optional[int] = None
    retries: int
    ssl_warn_days: int
    enabled: bool
    created_at: datetime


class DeleteOkResponse(BaseModel):
    ok: bool = True


# ==================== RESULTS, UPTIME & INCIDENTS ====================
class CheckResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    monitor_id: int
    checked_at: datetime
    status: str
    response_time_ms: Optional[float] = None
    status_code: Optional[int] = None
    ssl_days_left: Optional[int] = None
    error: Optional[str] = None


class UptimeOut(BaseModel):
    uptime_percent: float
    avg_response_ms: Optional[float] = None
    total_checks: int


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    monitor_id: int
    state: str
    started_at: datetime
    resolved_at: Optional[datetime] = None
    cause: Optional[str] = None
    severity: str


# ==================== PUBLIC STATUS PAGE ====================
class PublicMonitorStatus(BaseModel):
    id: int
    name: str
    type: str
    target: str
    current_status: str
    uptime_percent_24h: float
    avg_response_ms_24h: Optional[float] = None
    last_checked_at: Optional[datetime] = None


class PublicStatusPageOut(BaseModel):
    public_id: str
    overall_status: str
    monitors: List[PublicMonitorStatus]


# ==================== NOTIFICATION CHANNELS ====================
class NotificationChannelCreate(BaseModel):
    type: str = "telegram"
    target: str = Field(..., min_length=1, description="Telegram chat_id")


class NotificationChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    type: str
    target: str
