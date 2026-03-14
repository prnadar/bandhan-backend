"""
Reports + Admin router.
POST /api/v1/reports                    — file a report
GET  /api/v1/admin/reports              — admin: list reports
PUT  /api/v1/admin/reports/{id}         — admin: resolve report
GET  /api/v1/admin/trust-score/{user_id} — recalculate trust score
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import get_logger
from app.core.security import get_current_user, require_admin
from app.models.report import Report, ReportCategory, ReportStatus
from app.schemas.common import APIResponse, PaginatedResponse

router = APIRouter(tags=["reports"])
logger = get_logger(__name__)


class ReportCreate:
    pass


from pydantic import BaseModel


class ReportCreateRequest(BaseModel):
    reported_user_id: uuid.UUID
    category: ReportCategory
    description: str | None = None
    evidence: list[str] = []  # S3 keys or message IDs


class ReportResolveRequest(BaseModel):
    status: ReportStatus
    admin_notes: str | None = None
    action_taken: str | None = None


@router.post("/reports", response_model=APIResponse[dict])
async def file_report(
    payload: ReportCreateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
):
    reporter_id = uuid.UUID(current_user["sub"])

    report = Report(
        tenant_id=uuid.uuid4(),  # resolved in Sprint 2
        reporter_id=reporter_id,
        reported_user_id=payload.reported_user_id,
        category=payload.category,
        description=payload.description,
        evidence=payload.evidence,
    )
    db.add(report)
    await db.flush()

    # Check if reported user has 3+ open reports → auto-suspend
    count_result = await db.execute(
        select(func.count()).where(
            Report.reported_user_id == payload.reported_user_id,
            Report.status == ReportStatus.OPEN,
            Report.deleted_at.is_(None),
        )
    )
    open_count = count_result.scalar()
    if open_count >= 3:
        logger.warning(
            "auto_suspend_threshold_reached",
            reported_user=str(payload.reported_user_id),
            report_count=open_count,
        )
        # TODO Sprint 2: set user.is_active = False, send notification

    logger.info("report_filed", reporter=str(reporter_id), reported=str(payload.reported_user_id))
    return APIResponse(success=True, data={"report_id": str(report.id)})


@router.get("/admin/reports", response_model=PaginatedResponse[dict])
async def list_reports(
    page: int = 1,
    limit: int = 50,
    status_filter: ReportStatus | None = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    admin: Annotated[dict, Depends(require_admin)] = None,
):
    offset = (page - 1) * limit
    query = select(Report).where(Report.deleted_at.is_(None))
    if status_filter:
        query = query.where(Report.status == status_filter)

    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar()

    result = await db.execute(
        query.order_by(Report.created_at.desc()).offset(offset).limit(limit)
    )
    reports = result.scalars().all()

    return PaginatedResponse.create(
        [{"id": str(r.id), "category": r.category, "status": r.status} for r in reports],
        total,
        page,
        limit,
    )


@router.put("/admin/reports/{report_id}", response_model=APIResponse[None])
async def resolve_report(
    report_id: uuid.UUID,
    payload: ReportResolveRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[dict, Depends(require_admin)],
):
    result = await db.execute(
        select(Report).where(Report.id == report_id, Report.deleted_at.is_(None))
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    report.status = payload.status
    report.admin_notes = payload.admin_notes
    report.action_taken = payload.action_taken
    report.admin_id = uuid.UUID(admin["sub"])

    from datetime import datetime, timezone
    report.resolved_at = datetime.now(timezone.utc)

    logger.info("report_resolved", report_id=str(report_id), action=payload.action_taken)
    return APIResponse(success=True)
