from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    create_access_token,
    get_current_user,
    hash_password,
     verify_password,
)
from app.database import AsyncSessionLocal, Base, engine, get_db
from app.models import (
    CheckResult,
    Incident,
    Monitor,
    NotificationChannel,
    Plan,
    User,
)
from app.schemas import (
    AuthRequest,
    CheckResultOut,
    DeleteOkResponse,
    IncidentOut,
    MonitorCreate,
    MonitorOut,
    MonitorUpdate,
    NotificationChannelCreate,
    NotificationChannelOut,
    PlanOut,
    PublicMonitorStatus,
    PublicStatusPageOut,
    TokenResponse,
    UpdateUserPlanRequest,
    UptimeOut,
    UserOut,
)


async def seed_initial_data(db: AsyncSession) -> None:
    """Tự động khởi tạo 3 gói dịch vụ (Free, Pro, Business) và tài khoản Admin."""
    plans_count = await db.scalar(select(func.count(Plan.id)))
    if not plans_count or plans_count == 0:
        default_plans = [
            Plan(id=1, name="Free", max_monitors=5, min_interval=60, price=0),
            Plan(id=2, name="Pro", max_monitors=20, min_interval=30, price=199000),
            Plan(id=3, name="Business", max_monitors=100, min_interval=10, price=499000),
        ]
        db.add_all(default_plans)
        await db.commit()

    admin_exists = await db.scalar(
        select(User).where(User.email == "admin@monitoring.local")
    )
    if not admin_exists:
        admin_user = User(
            email="admin@monitoring.local",
            password_hash=hash_password("admin123"),
            role="admin",
            plan_id=3,
        )
        db.add(admin_user)
        await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tạo đầy đủ 7 bảng trong Postgres nếu chưa có
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed dữ liệu gói dịch vụ & tài khoản admin
    async with AsyncSessionLocal() as session:
        await seed_initial_data(session)

    yield
    await engine.dispose()


app = FastAPI(
    title="Monitoring Platform - Backend API (TV2)",
    description="API quản lý người dùng, gói dịch vụ, monitors, kết quả kiểm tra, uptime và sự cố.",
    version="1.0.0",
    lifespan=lifespan,
)

# Bật CORS cho phép Frontend (TV3) gọi từ mọi origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== HELPER KIỂM TRA QUYỀN SỞ HỮU MONITOR ====================
async def get_owned_monitor_or_404(
    monitor_id: int,
    current_user: User,
    db: AsyncSession,
) -> Monitor:
    result = await db.execute(select(Monitor).where(Monitor.id == monitor_id))
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy monitor",
        )
    if current_user.role != "admin" and monitor.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền truy cập monitor này",
        )
    return monitor


async def calculate_monitor_uptime(
    monitor_id: int,
    hours: int,
    db: AsyncSession,
) -> UptimeOut:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    result = await db.execute(
        select(CheckResult).where(
            CheckResult.monitor_id == monitor_id,
            CheckResult.checked_at >= since,
        )
    )
    rows = result.scalars().all()
    total_checks = len(rows)
    if total_checks == 0:
        return UptimeOut(uptime_percent=100.0, avg_response_ms=None, total_checks=0)

    up_count = sum(1 for r in rows if r.status == "up")
    uptime_percent = round((up_count / total_checks) * 100.0, 2)

    latencies = [r.response_time_ms for r in rows if r.response_time_ms is not None]
    avg_response_ms = (
        round(sum(latencies) / len(latencies), 2) if latencies else None
    )

    return UptimeOut(
        uptime_percent=uptime_percent,
        avg_response_ms=avg_response_ms,
        total_checks=total_checks,
    )


# ==================== A. AUTH ROUTES ====================
@app.post("/auth/register", response_model=TokenResponse)
async def register(payload: AuthRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.scalar(
        select(User).where(User.email == payload.email.lower().strip())
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email này đã được đăng ký",
        )

    new_user = User(
        email=payload.email.lower().strip(),
        password_hash=hash_password(payload.password),
        role="customer",
        plan_id=1,  # Mặc định gói Free
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    token = create_access_token(
        user_id=new_user.id, email=new_user.email, role=new_user.role
    )
    return TokenResponse(token=token)


@app.post("/auth/login", response_model=TokenResponse)
async def login(payload: AuthRequest, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(
        select(User).where(User.email == payload.email.lower().strip())
    )
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email hoặc mật khẩu không chính xác",
        )

    token = create_access_token(
        user_id=user.id, email=user.email, role=user.role
    )
    return TokenResponse(token=token)


@app.get("/auth/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


# ==================== B. MONITORS CRUD (CÓ KIỂM TRA GIỚI HẠN GÓI) ====================
@app.get("/monitors", response_model=List[MonitorOut])
async def list_monitors(
    all: bool = Query(False, description="Admin có thể truyền ?all=true để xem toàn bộ"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role == "admin" and all:
        stmt = select(Monitor).order_by(Monitor.id.asc())
    else:
        stmt = (
            select(Monitor)
            .where(Monitor.owner_id == current_user.id)
            .order_by(Monitor.id.asc())
        )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@app.post("/monitors", response_model=MonitorOut, status_code=status.HTTP_201_CREATED)
async def create_monitor(
    payload: MonitorCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 1. Lấy thông tin gói dịch vụ của user
    plan = await db.scalar(select(Plan).where(Plan.id == current_user.plan_id))
    if not plan:
        plan = Plan(id=1, name="Free", max_monitors=5, min_interval=60, price=0)

    # 2. Kiểm tra số lượng monitor hiện tại so với max_monitors của gói
    current_count = await db.scalar(
        select(func.count(Monitor.id)).where(Monitor.owner_id == current_user.id)
    )
    if (current_count or 0) >= plan.max_monitors:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Đã đạt giới hạn số lượng monitor tối đa của gói {plan.name} ({plan.max_monitors} monitors)",
        )

    # 3. Kiểm tra tần suất kiểm tra so với min_interval của gói
    if payload.interval_seconds < plan.min_interval:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Chu kỳ kiểm tra ({payload.interval_seconds}s) nhanh hơn giới hạn tối thiểu của gói {plan.name} ({plan.min_interval}s)",
        )

    monitor = Monitor(
        owner_id=current_user.id,
        name=payload.name,
        type=payload.type,
        target=payload.target,
        port=payload.port,
        interval_seconds=payload.interval_seconds,
        timeout_seconds=payload.timeout_seconds,
        expected_status=payload.expected_status,
        retries=payload.retries,
        ssl_warn_days=payload.ssl_warn_days,
        enabled=payload.enabled,
    )
    db.add(monitor)
    await db.commit()
    await db.refresh(monitor)
    return monitor


@app.get("/monitors/{id}", response_model=MonitorOut)
async def get_monitor(
    id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_owned_monitor_or_404(id, current_user, db)


@app.put("/monitors/{id}", response_model=MonitorOut)
async def update_monitor(
    id: int,
    payload: MonitorUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    monitor = await get_owned_monitor_or_404(id, current_user, db)

    # Kiểm tra giới hạn min_interval nếu có thay đổi interval_seconds
    if payload.interval_seconds is not None:
        owner_user = await db.scalar(select(User).where(User.id == monitor.owner_id))
        plan_id = owner_user.plan_id if owner_user else current_user.plan_id
        plan = await db.scalar(select(Plan).where(Plan.id == plan_id))
        if plan and payload.interval_seconds < plan.min_interval:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Chu kỳ kiểm tra ({payload.interval_seconds}s) nhanh hơn giới hạn tối thiểu của gói {plan.name} ({plan.min_interval}s)",
            )

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(monitor, field, value)

    await db.commit()
    await db.refresh(monitor)
    return monitor


@app.delete("/monitors/{id}", response_model=DeleteOkResponse)
async def delete_monitor(
    id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    monitor = await get_owned_monitor_or_404(id, current_user, db)
    await db.delete(monitor)
    await db.commit()
    return DeleteOkResponse(ok=True)


# ==================== C. RESULTS, UPTIME & INCIDENTS ====================
@app.get("/monitors/{id}/results", response_model=List[CheckResultOut])
async def get_monitor_results(
    id: int,
    hours: int = Query(24, ge=1, le=720),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_monitor_or_404(id, current_user, db)
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    stmt = (
        select(CheckResult)
        .where(
            CheckResult.monitor_id == id,
            CheckResult.checked_at >= since,
        )
        .order_by(CheckResult.checked_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@app.get("/monitors/{id}/uptime", response_model=UptimeOut)
async def get_monitor_uptime(
    id: int,
    hours: int = Query(24, ge=1, le=720),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_monitor_or_404(id, current_user, db)
    return await calculate_monitor_uptime(id, hours, db)


@app.get("/incidents", response_model=List[IncidentOut])
async def get_incidents(
    monitor_id: Optional[int] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if monitor_id is not None:
        await get_owned_monitor_or_404(monitor_id, current_user, db)
        stmt = (
            select(Incident)
            .where(Incident.monitor_id == monitor_id)
            .order_by(Incident.started_at.desc())
        )
    else:
        if current_user.role == "admin":
            stmt = select(Incident).order_by(Incident.started_at.desc())
        else:
            stmt = (
                select(Incident)
                .join(Monitor, Incident.monitor_id == Monitor.id)
                .where(Monitor.owner_id == current_user.id)
                .order_by(Incident.started_at.desc())
            )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ==================== D. PUBLIC STATUS PAGE (KHÔNG CẦN TOKEN) ====================
@app.get("/status/{public_id}", response_model=PublicStatusPageOut)
async def get_public_status(
    public_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Trang trạng thái công khai:
    - Nếu public_id là số nguyên: tìm tất cả monitor đang bật của user_id = public_id;
      nếu user đó không có monitor, fallback tìm monitor có id = public_id.
    - Nếu public_id là 'all' hoặc 'default': hiển thị toàn bộ monitors đang bật.
    """
    monitors: List[Monitor] = []
    if public_id.isdigit():
        num_id = int(public_id)
        res = await db.execute(
            select(Monitor)
            .where(Monitor.owner_id == num_id, Monitor.enabled.is_(True))
            .order_by(Monitor.id.asc())
        )
        monitors = list(res.scalars().all())
        if not monitors:
            res_single = await db.execute(
                select(Monitor).where(
                    Monitor.id == num_id, Monitor.enabled.is_(True)
                )
            )
            monitors = list(res_single.scalars().all())
    else:
        res = await db.execute(
            select(Monitor)
            .where(Monitor.enabled.is_(True))
            .order_by(Monitor.id.asc())
        )
        monitors = list(res.scalars().all())

    status_items: List[PublicMonitorStatus] = []
    down_count = 0

    for m in monitors:
        latest_res = await db.execute(
            select(CheckResult)
            .where(CheckResult.monitor_id == m.id)
            .order_by(CheckResult.checked_at.desc())
            .limit(1)
        )
        latest_check = latest_res.scalar_one_or_none()
        current_status = latest_check.status if latest_check else "unknown"
        if current_status == "down":
            down_count += 1

        uptime_info = await calculate_monitor_uptime(m.id, 24, db)

        status_items.append(
            PublicMonitorStatus(
                id=m.id,
                name=m.name,
                type=m.type,
                target=m.target,
                current_status=current_status,
                uptime_percent_24h=uptime_info.uptime_percent,
                avg_response_ms_24h=uptime_info.avg_response_ms,
                last_checked_at=latest_check.checked_at if latest_check else None,
            )
        )

    if not status_items or down_count == 0:
        overall = "operational"
    elif down_count == len(status_items):
        overall = "down"
    else:
        overall = "degraded"

    return PublicStatusPageOut(
        public_id=public_id,
        overall_status=overall,
        monitors=status_items,
    )


# ==================== E. API PHỤ TRỢ: PLANS, USERS & TELEGRAM CHANNELS ====================
@app.get("/plans", response_model=List[PlanOut])
async def list_plans(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Plan).order_by(Plan.id.asc()))
    return list(result.scalars().all())


@app.put("/users/{id}/plan", response_model=UserOut)
async def change_user_plan(
    id: int,
    payload: UpdateUserPlanRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != "admin" and current_user.id != id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Không có quyền thay đổi gói dịch vụ của người dùng khác",
        )

    plan = await db.scalar(select(Plan).where(Plan.id == payload.plan_id))
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gói dịch vụ không tồn tại",
        )

    target_user = await db.scalar(select(User).where(User.id == id))
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Người dùng không tồn tại",
        )

    target_user.plan_id = payload.plan_id
    await db.commit()
    await db.refresh(target_user)
    return target_user


@app.get("/notification-channels", response_model=List[NotificationChannelOut])
async def list_notification_channels(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(NotificationChannel)
        .where(NotificationChannel.user_id == current_user.id)
        .order_by(NotificationChannel.id.asc())
    )
    return list(result.scalars().all())


@app.post(
    "/notification-channels",
    response_model=NotificationChannelOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_notification_channel(
    payload: NotificationChannelCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    channel = NotificationChannel(
        user_id=current_user.id,
        type=payload.type,
        target=payload.target.strip(),
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return channel


@app.delete("/notification-channels/{id}", response_model=DeleteOkResponse)
async def delete_notification_channel(
    id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    channel = await db.scalar(
        select(NotificationChannel).where(NotificationChannel.id == id)
    )
    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy kênh nhận cảnh báo",
        )
    if current_user.role != "admin" and channel.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Không có quyền xóa kênh cảnh báo này",
        )
    await db.delete(channel)
    await db.commit()
    return DeleteOkResponse(ok=True)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "backend-api"}
