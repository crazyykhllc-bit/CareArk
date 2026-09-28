"""Opt-in live smoke test: only generated fictional images, no user records or storage."""
import asyncio
from io import BytesIO

from PIL import Image, ImageDraw

from app.batch_schemas import validate_sources
from app.config import get_settings
from app.services.batch_extraction import BatchExtractor


def source(id, lines):
    image = Image.new('RGB', (1000, 800), 'white')
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(lines):
        draw.text((50, 50 + index * 95), line, fill='black', font_size=34)
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    return {'id': id, 'kind': 'image', 'label': id, 'data': buffer.getvalue()}


async def main():
    sources = [source('sample-a-front', ['FICTIONAL TEST PACKAGE', 'DEMO-A', '10 mg tablets', 'Demo Manufacturer']),
               source('sample-a-back', ['FICTIONAL TEST PACKAGE', 'DEMO-A / Demo Manufacturer', '10 mg tablets', 'Batch: T100', 'Expiry: 2030-01-01']),
               source('sample-report', ['FICTIONAL TEST REPORT', 'Example Hospital', 'Report ID: T200', 'Patient: Test Person', 'Date: 2026-09-06', 'Test item: example value 5.0'])]
    grouping = {'groups': [{'id': 'manual-a', 'kind': 'medication', 'label': 'DEMO-A',
                            'source_ids': ['sample-a-front', 'sample-a-back']}], 'encounters': []}
    try:
        result = await BatchExtractor(get_settings()).extract_batch(sources, grouping)
        validate_sources(result, {s['id'] for s in sources})
        assert any(g.kind == 'medication' and set(g.source_ids) == {'sample-a-front', 'sample-a-back'} for g in result.groups)
        assert any(g.kind == 'document' and 'sample-report' in g.source_ids for g in result.groups)
        print(f'LIVE_SMOKE_OK groups={len(result.groups)} sources=3')
    except Exception as error:
        print(f'LIVE_SMOKE_FAILED {type(error).__name__}: {error}')
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())
