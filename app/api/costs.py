from collections import defaultdict
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import Field

from app.currency import canonical_currency
from app.db import get_db
from app.dependencies import get_current_user
from app.models import Document, ReceiptDetail, User
from app.schemas import StrictModel


router = APIRouter(prefix='/api/costs')


class ReceiptStatusUpdate(StrictModel):
    expected_version: int = Field(ge=1)
    status: Literal['active', 'duplicate', 'voided']
    duplicate_of_id: UUID | None = None


async def receipt_rows(db, owner_id):
    return (await db.execute(
        select(Document, ReceiptDetail)
        .outerjoin(ReceiptDetail, (ReceiptDetail.document_id == Document.id) &
                   (ReceiptDetail.owner_id == owner_id))
        .where(Document.owner_id == owner_id, Document.deleted_at.is_(None),
               or_(ReceiptDetail.id.is_not(None), Document.document_type.ilike('%发票%'),
                   Document.document_type.ilike('%收费%')))
    )).all()


def effective_amount(document, receipt):
    if receipt and receipt.total_amount is not None:
        return receipt.total_amount
    return document.amount


def row_json(document, receipt):
    amount = effective_amount(document, receipt)
    return {
        'id': str(receipt.id) if receipt else None,
        'document_id': str(document.id), 'title': document.title,
        'primary_date': document.primary_date.isoformat() if document.primary_date else None,
        'hospital': document.hospital, 'amount': str(amount) if amount is not None else None,
        'currency': canonical_currency(receipt.currency) if receipt else 'CNY',
        'receipt_number': receipt.receipt_number if receipt else None,
        'insurance_amount': str(receipt.insurance_amount) if receipt and receipt.insurance_amount is not None else None,
        'personal_amount': str(receipt.personal_amount) if receipt and receipt.personal_amount is not None else None,
        'status': receipt.status if receipt else 'active',
        'version': receipt.version if receipt else None,
        'line_items': receipt.line_items if receipt else [],
    }


def is_excluded(receipt):
    return bool(receipt and (receipt.status in {'duplicate', 'voided'} or receipt.duplicate_of_id is not None))


@router.get('/summary')
async def cost_summary(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await receipt_rows(db, user.id)
    active = [(doc, receipt) for doc, receipt in rows if not is_excluded(receipt)]
    buckets = defaultdict(lambda: {'total': Decimal('0'), 'known_count': 0, 'unknown_count': 0})
    payments = defaultdict(lambda: {'insurance_total': Decimal('0'), 'insurance_count': 0,
                                    'personal_total': Decimal('0'), 'personal_count': 0})
    years = defaultdict(lambda: defaultdict(lambda: {'total': Decimal('0'), 'known_count': 0, 'unknown_count': 0}))
    undated = {'known_count': 0, 'unknown_count': 0}
    for document, receipt in active:
        currency = canonical_currency(receipt.currency) if receipt else 'CNY'
        amount = effective_amount(document, receipt)
        target = buckets[currency]
        yearly = years[str(document.primary_date.year) if document.primary_date else 'undated'][currency]
        key = 'known_count' if amount is not None else 'unknown_count'
        target[key] += 1
        yearly[key] += 1
        if amount is not None:
            target['total'] += amount
            yearly['total'] += amount
        if receipt:
            for field in ('insurance', 'personal'):
                value = getattr(receipt, f'{field}_amount')
                if value is not None:
                    payments[currency][f'{field}_total'] += value
                    payments[currency][f'{field}_count'] += 1
        if not document.primary_date:
            undated[key] += 1
    serialize = lambda currency, value: {'currency': currency, 'total': f"{value['total']:.2f}",
                                          'known_count': value['known_count'],
                                          'unknown_count': value['unknown_count']}
    return {
        'receipts': {'total': len(active), 'known_amount': sum(1 for doc, rec in active if effective_amount(doc, rec) is not None),
                     'unknown_amount': sum(1 for doc, rec in active if effective_amount(doc, rec) is None)},
        'totals_by_currency': [serialize(currency, value) for currency, value in sorted(buckets.items())],
        'payments_by_currency': [
            {'currency': currency, **{key: f'{value[key]:.2f}' if key.endswith('_total') else value[key]
                                  for key in ('insurance_total', 'insurance_count', 'personal_total', 'personal_count')}}
            for currency, value in sorted(payments.items())
        ],
        'years': [{'year': year, 'totals': [serialize(currency, value) for currency, value in sorted(values.items())]}
                  for year, values in sorted(years.items(), reverse=True)],
        'undated': undated, 'excluded_count': len(rows) - len(active),
    }


@router.get('/receipts')
async def list_receipts(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
                        limit: int = Query(50, ge=1, le=100), cursor: int = Query(0, ge=0),
                        year: int | None = None, hospital: str | None = None,
                        unknown_amount: bool | None = None, include_excluded: bool = False):
    rows = await receipt_rows(db, user.id)
    if not include_excluded:
        rows = [(doc, receipt) for doc, receipt in rows if not is_excluded(receipt)]
    if year is not None:
        rows = [(doc, receipt) for doc, receipt in rows if doc.primary_date and doc.primary_date.year == year]
    if hospital:
        rows = [(doc, receipt) for doc, receipt in rows if doc.hospital == hospital]
    if unknown_amount is not None:
        rows = [(doc, receipt) for doc, receipt in rows
                if (effective_amount(doc, receipt) is None) == unknown_amount]
    rows.sort(key=lambda row: (row[0].primary_date is not None, row[0].primary_date,
                               row[0].created_at, str(row[0].id)), reverse=True)
    page = rows[cursor:cursor + limit]
    next_cursor = cursor + limit if cursor + limit < len(rows) else None
    return {'items': [row_json(doc, receipt) for doc, receipt in page], 'next_cursor': next_cursor,
            'total': len(rows)}


@router.patch('/receipts/{receipt_id}')
async def update_receipt_status(receipt_id: UUID, data: ReceiptStatusUpdate,
                                user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    receipt = await db.scalar(select(ReceiptDetail).where(ReceiptDetail.id == receipt_id,
        ReceiptDetail.owner_id == user.id).with_for_update())
    if not receipt:
        raise HTTPException(404, '票据不存在')
    if receipt.version != data.expected_version:
        raise HTTPException(409, '票据状态已更新，请刷新')
    duplicate_of = None
    if data.status == 'duplicate':
        if not data.duplicate_of_id or data.duplicate_of_id == receipt.id:
            raise HTTPException(422, '请选择当前用户的另一张原始票据')
        duplicate_of = await db.scalar(select(ReceiptDetail).where(ReceiptDetail.id == data.duplicate_of_id,
            ReceiptDetail.owner_id == user.id, ReceiptDetail.status == 'active'))
        if not duplicate_of:
            raise HTTPException(422, '作为原件的票据不存在或不可用')
    receipt.status = data.status
    receipt.duplicate_of_id = duplicate_of.id if duplicate_of else None
    receipt.version += 1
    await db.commit()
    document = await db.get(Document, receipt.document_id)
    return row_json(document, receipt)
