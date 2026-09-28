"""Validate compact batch plans before requesting bounded document details."""
from app.batch_schemas import BatchExtraction, ResultGroup, validate_sources
from app.services.extraction import ExtractionError


def invalid_plan():
    return ExtractionError('资料分组规划不完整或未保持手动关联，请重试识别', code='invalid_merge_plan', retryable=False)


def validate_plan(plan, source_ids, grouping):
    group_ids=[g.id for g in plan.groups]
    visit_ids=[v.id for v in plan.encounters]
    if len(set(group_ids))!=len(group_ids) or len(set(visit_ids))!=len(visit_ids):raise invalid_plan()
    used=set()
    for group in plan.groups:
        ids=set(group.source_ids)
        if len(ids)!=len(group.source_ids) or not ids<=source_ids:raise invalid_plan()
        if group.encounter_id and group.encounter_id not in visit_ids:raise invalid_plan()
        used|=ids
    excluded=[x.source_id for x in plan.excluded_sources]
    if len(set(excluded))!=len(excluded) or set(excluded)&used or used|set(excluded)!=source_ids:raise invalid_plan()
    for hint in grouping.get('groups',[]):
        if not any(g.kind==hint['kind'] and set(g.source_ids)==set(hint['source_ids']) for g in plan.groups):raise invalid_plan()
    for hint in grouping.get('encounters',[]):
        selected=set(hint['source_ids'])
        visits={g.encounter_id for g in plan.groups if set(g.source_ids)&selected}
        if len(visits)!=1 or None in visits:raise invalid_plan()


def assemble_result(plan, details, transcriptions, labels, source_ids):
    if len(details)!=len(plan.groups):raise invalid_plan()
    groups=[]
    for planned, detail in zip(plan.groups, details):
        if detail.kind!=planned.kind or set(detail.source_ids)!=set(planned.source_ids) or len(detail.source_ids)!=len(planned.source_ids):raise invalid_plan()
        group=ResultGroup.model_validate(detail.model_dump(mode='json'))
        group.id=planned.id
        group.encounter_id=planned.encounter_id
        group.source_ids=list(planned.source_ids)
        texts=[]
        for sid in planned.source_ids:
            row=transcriptions[sid]
            texts.append('['+labels[sid]+']\n'+row.content)
            if row.visual_notes:texts.append('\n'.join(row.visual_notes))
            group.review_items.extend(row.review_items)
        group.document.parsed_content='\n\n'.join(texts)
        group.review_items=list(dict.fromkeys(group.review_items))
        for med in group.medications:med.existing_medication_id=None
        groups.append(group)
    for visit in plan.encounters:visit.existing_encounter_id=None
    result=BatchExtraction(groups=groups,encounters=plan.encounters,excluded_sources=plan.excluded_sources,review_items=plan.review_items,reviewed=False)
    try:validate_sources(result,source_ids)
    except ValueError as error:raise invalid_plan() from error
    return result
