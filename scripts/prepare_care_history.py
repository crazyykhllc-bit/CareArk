"""Prepare non-destructive legacy organization suggestions.

Dry-run by default. No medical text, identifiers, or file names are printed.
"""

import argparse
import asyncio

from sqlalchemy import select

from app.db import SessionLocal
from app.models import User
from app.services.care_suggestions import prepare_suggestions


async def main(apply: bool):
    totals = {'accounts': 0, 'eligible_documents': 0, 'candidate_count': 0, 'created': 0}
    async with SessionLocal() as db:
        owners = (await db.scalars(select(User.id))).all()
        for owner_id in owners:
            result = await prepare_suggestions(db, owner_id, apply=apply)
            totals['accounts'] += 1
            for key in ('eligible_documents', 'candidate_count', 'created'):
                totals[key] += result[key]
    print(('APPLY' if apply else 'DRY RUN') + ' ' + ' '.join(f'{key}={value}' for key, value in totals.items()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='store the proposals without changing documents')
    args = parser.parse_args()
    asyncio.run(main(args.apply))
