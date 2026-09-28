from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user
from app.hospitals import hospital_key
from app.models import Document, LabResult, User
from app.services.metric_summaries import build_metric_summaries, select_dashboard_metrics


router = APIRouter(prefix='/api')


@router.get('/overview')
async def overview(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Document.document_type, Document.primary_date, Document.hospital,
                                    Document.patient_scope)
                             .where(Document.owner_id == user.id, Document.deleted_at.is_(None)))).all()
    types = Counter(row.document_type for row in rows)
    months = Counter(row.primary_date.strftime('%Y-%m') for row in rows if row.primary_date)
    dates = [row.primary_date for row in rows if row.primary_date]
    hospitals = {hospital_key(row.hospital) for row in rows if hospital_key(row.hospital)}
    metric_catalog = await build_metric_summaries(db, user.id)
    metrics = await select_dashboard_metrics(db, user.id, metric_catalog)
    unconfirmed_labs = (await db.execute(select(LabResult.id).join(
        Document, Document.id == LabResult.document_id).where(
            LabResult.owner_id == user.id, Document.owner_id == user.id, Document.deleted_at.is_(None),
            Document.patient_scope == 'unconfirmed',
            LabResult.review_status == 'confirmed'))).all()
    from app.services.test_session_grouping import candidate_metadata
    candidate_groups = {item['suggestion_key'] for item in (await candidate_metadata(db, user.id)).values()
                        if item['suggestion_key']}
    return {
        'documents': {'total': len(rows), 'dated': len(dates), 'undated': len(rows) - len(dates)},
        'hospitals': len(hospitals),
        'latest_date': max(dates).isoformat() if dates else None,
        'types': [{'type': key, 'count': value} for key, value in sorted(types.items(), reverse=True)],
        'months': [{'month': key, 'count': value} for key, value in sorted(months.items(), reverse=True)],
        'metrics': metrics,
        'metric_catalog': metric_catalog,
        'ownership': {
            'unconfirmed_documents': sum(row.patient_scope == 'unconfirmed' for row in rows),
            'unconfirmed_lab_results': len(unconfirmed_labs),
        },
        'pending_test_group_count': len(candidate_groups),
    }
