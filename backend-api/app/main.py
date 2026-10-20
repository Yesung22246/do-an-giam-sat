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
    CheckRollup,
    CheckStatus,
    Incident,
    Monitor,
    NotificationChannel,
    Plan,
    User,
    utcnow,
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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

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


# ==================== HÀM COMPUTE_UPTIME (ĐỒNG BỘ 100% VỚI TV1) ====================
async def calculate_monitor_uptime(
    monitor_id: int,
    window_hours: int,
    session: AsyncSession,
    now: Optional[datetime] = None,
) -> UptimeOut:
    """
    Bê nguyên thuật toán compute_uptime từ monitoring-core/app/uptime.py của TV1:
    Cộng dồn từ cả check_results (dữ liệu thô gần đây) và check_rollups (dữ liệu
    đã gom theo giờ) để kết quả đúng kể cả với cửa sổ dài (vd 30 ngày).
    """
    since = (now or utcnow()) - timedelta(hours=window_hours)

    # --- Nguồn 1: dữ liệu thô gần đây ---
    raw_total = await session.scalar(
        select(func.count(CheckResult.id)).where(
            CheckResult.monitor_id == monitor_id,
            CheckResult.checked_at >= since,
        )
    ) or 0
    raw_up = await session.scalar(
        select(func.count(CheckResult.id)).where(
            CheckResult.monitor_id == monitor_id,
            CheckResult.checked_at >= since,
            CheckResult.status == CheckStatus.UP,
        )
    ) or 0
    raw_resp_sum = await session.scalar(
        select(func.sum(CheckResult.response_time_ms)).where(
            CheckResult.monitor_id == monitor_id,
            CheckResult.checked_at >= since,
            CheckResult.status == CheckStatus.UP,
        )
    ) or 0.0

    # --- Nguồn 2: dữ liệu đã gom theo giờ ---
    roll_total = await session.scalar(
        select(func.sum(CheckRollup.total_checks)).where(
            CheckRollup.monitor_id == monitor_id,
            CheckRollup.bucket_start >= since,
        )
    ) or 0
    roll_up = await session.scalar(
        select(func.sum(CheckRollup.up_checks)).where(
            CheckRollup.monitor_id == monitor_id,
            CheckRollup.bucket_start >= since,
        )
    ) or 0
    roll_resp_sum = await session.scalar(
        select(
            func.sum(CheckRollup.avg_response_ms * CheckRollup.up_checks)
        ).where(
            CheckRollup.monitor_id == monitor_id,
            CheckRollup.bucket_start >= since,
            CheckRollup.avg_response_ms.is_not(None),
        )
    ) or 0.0

    total = int(raw_total) + int(roll_total)
    up = int(raw_up) + int(roll_up)
    resp_sum = float(raw_resp_sum or 0.0) + float(roll_resp_sum or 0.0)

    percent = round(100.0 * up / total, 3) if total else 100.0
    avg_ms = round(resp_sum / up, 1) if up else None

    return UptimeOut(
        uptime_percent=percent,
        avg_response_ms=avg_ms,
        total_checks=total,
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
        plan_id=1,
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


# ==================== B. MONITORS CRUD ====================
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
    plan = await db.scalar(select(Plan).where(Plan.id == current_user.plan_id))
    if not plan:
        plan = Plan(id=1, name="Free", max_monitors=5, min_interval=60, price=0)

    current_count = await db.scalar(
        select(func.count(Monitor.id)).where(Monitor.owner_id == current_user.id)
    )
    if (current_count or 0) >= plan.max_monitors:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Đã đạt giới hạn số lượng monitor tối đa của gói {plan.name} ({plan.max_monitors} monitors)",
        )

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


# ==================== C. RESULTS, UPTIME & INCIDENTS (GỘP CẢ ROLLUPS) ====================
@app.get("/monitors/{id}/results", response_model=List[CheckResultOut])
async def get_monitor_results(
    id: int,
    hours: int = Query(24, ge=1, le=720),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Gộp cả check_rollups (dữ liệu lịch sử cũ đã gom theo giờ) và check_results
    (dữ liệu thô gần đây) theo thứ tự thời gian tăng dần để vẽ biểu đồ.
    """
    await get_owned_monitor_or_404(id, current_user, db)
    since = utcnow() - timedelta(hours=hours)

    rollup_res = await db.execute(
        select(CheckRollup)
        .where(
            CheckRollup.monitor_id == id,
            CheckRollup.bucket_start >= since,
        )
        .order_by(CheckRollup.bucket_start.asc())
    )
    rollup_rows = list(rollup_res.scalars().all())

    raw_res = await db.execute(
        select(CheckResult)
        .where(
            CheckResult.monitor_id == id,
            CheckResult.checked_at >= since,
        )
        .order_by(CheckResult.checked_at.asc())
    )
    raw_rows = list(raw_res.scalars().all())

    combined_results: List[CheckResultOut] = []

    for r in rollup_rows:
        synthetic_status = "up" if r.up_checks > 0 or r.down_checks == 0 else "down"
        if r.down_checks > r.up_checks:
            synthetic_status = "down"
        combined_results.append(
            CheckResultOut(
                id=-r.id,
                monitor_id=r.monitor_id,
                checked_at=r.bucket_start,
                status=synthetic_status,
                response_time_ms=r.avg_response_ms,
                status_code=None,
                ssl_days_left=None,
                error=None,
            )
        )

    for r in raw_rows:
        status_str = r.status.value if hasattr(r.status, "value") else str(r.status)
        combined_results.append(
            CheckResultOut(
                id=r.id,
                monitor_id=r.monitor_id,
                checked_at=r.checked_at,
                status=status_str,
                response_time_ms=r.response_time_ms,
                status_code=r.status_code,
                ssl_days_left=r.ssl_days_left,
                error=r.error,
            )
        )

    combined_results.sort(key=lambda item: item.checked_at)
    return combined_results


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


# ==================== D. PUBLIC STATUS PAGE ====================
@app.get("/status/{public_id}", response_model=PublicStatusPageOut)
async def get_public_status(
    public_id: str,
    db: AsyncSession = Depends(get_db),
):
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
        if latest_check:
            current_status = (
                latest_check.status.value
                if hasattr(latest_check.status, "value")
                else str(latest_check.status)
            )
        else:
            current_status = "unknown"

        if current_status == "down":
            down_count += 1

        uptime_info = await calculate_monitor_uptime(m.id, 24, db)

        status_items.append(
            PublicMonitorStatus(
                id=m.id,
                name=m.name,
                type=m.type.value if hasattr(m.type, "value") else str(m.type),
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


# ==================== E. API PHỤ TRỢ ====================
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
