from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import DataQualityIssue, IngestRun
from app.schemas import DataQualityResponse, IssueOut

router = APIRouter(tags=["data-quality"])


@router.get("/data-quality", response_model=DataQualityResponse)
def data_quality(
    issue_type: str | None = Query(None, description="Filter issues by type"),
    limit: int = Query(100, ge=1, le=1000),
    session: Session = Depends(get_session),
):
    """Everything the latest ingest fixed, flagged, or discarded — the feed is
    treated as untrusted, and nothing is corrected silently."""
    run = session.execute(
        select(IngestRun).order_by(IngestRun.id.desc()).limit(1)
    ).scalar_one_or_none()
    if run is None:
        return DataQualityResponse(ingested=False)

    counts = dict(
        session.execute(
            select(DataQualityIssue.issue_type, func.count())
            .where(DataQualityIssue.run_id == run.id)
            .group_by(DataQualityIssue.issue_type)
        ).all()
    )
    issues_stmt = (
        select(DataQualityIssue)
        .where(DataQualityIssue.run_id == run.id)
        .order_by(DataQualityIssue.id)
        .limit(limit)
    )
    if issue_type:
        issues_stmt = issues_stmt.where(DataQualityIssue.issue_type == issue_type)
    issues = session.execute(issues_stmt).scalars().all()

    return DataQualityResponse(
        ingested=True,
        run_id=run.id,
        ran_at=run.ran_at,
        summary=run.summary,
        issue_counts={k: int(v) for k, v in counts.items()},
        issues=[
            IssueOut(
                source=i.source,
                record_id=i.record_id,
                issue_type=i.issue_type,
                detail=i.detail,
            )
            for i in issues
        ],
    )
