"""Keep unlabeled faces with a single identifiable drug until human review."""

from app.batch_schemas import BatchExtraction


_UNKNOWN_NAMES = {'待核对药品', '其他药品', '未知药品', '药品待确认'}


def _unknown(group):
    if group.kind != 'medication' or len(group.medications) != 1 or group.lab_results:
        return False
    item = group.medications[0]
    return (item.name.strip() in _UNKNOWN_NAMES and
            not any((item.generic_name, item.brand_name, item.strength, item.dosage_form,
                     item.manufacturer, item.approval_number, item.route,
                     item.existing_medication_id)))


def _combine_packages(target, source):
    if len(target.packages) == len(source.packages) == 1:
        existing, added = target.packages[0], source.packages[0]
        fields = ('batch_number', 'expiry_date', 'quantity_raw')
        if all(not getattr(existing, field) or not getattr(added, field) or
               getattr(existing, field) == getattr(added, field) for field in fields):
            for field in fields:
                if not getattr(existing, field):
                    setattr(existing, field, getattr(added, field))
            existing.source_ids = list(dict.fromkeys([*existing.source_ids, *added.source_ids]))
            return
    target.packages.extend(source.packages)


def associate_unidentified_medication_faces(result: BatchExtraction, grouping: dict) -> BatchExtraction:
    """Provisionally attach nameless package faces when exactly one drug is identifiable.

    Explicit user groups and ambiguous mixed-drug uploads always remain untouched.
    The result remains unreviewed, and the uncertainty is shown in review_items.
    """
    manual_ids = {sid for hint in grouping.get('groups', []) for sid in hint.get('source_ids', [])}
    known = [g for g in result.groups if g.kind == 'medication' and len(g.medications) == 1
             and not _unknown(g) and g.medications[0].name.strip() not in _UNKNOWN_NAMES]
    if len(known) != 1:
        return result
    target = known[0]
    if set(target.source_ids) & manual_ids:
        return result
    removable = []
    for group in result.groups:
        if group is target or not _unknown(group) or set(group.source_ids) & manual_ids:
            continue
        if (group.encounter_id and target.encounter_id and group.encounter_id != target.encounter_id or
                group.patient_identity and target.patient_identity and
                group.patient_identity.strip() != target.patient_identity.strip()):
            continue
        if any(other is not group and other is not target and
               set(other.source_ids) & set(group.source_ids) for other in result.groups):
            continue
        target.source_ids = list(dict.fromkeys([*target.source_ids, *group.source_ids]))
        target.evidence.extend(group.evidence)
        target.document.key_information = list(dict.fromkeys([
            *target.document.key_information, *group.document.key_information]))
        target.document.source_refs.extend(group.document.source_refs)
        if group.document.parsed_content:
            original = target.document.parsed_content or ''
            if group.document.parsed_content not in original:
                target.document.parsed_content = '\n\n'.join(filter(None, [original, group.document.parsed_content]))
        _combine_packages(target.medications[0], group.medications[0])
        target.review_items.extend(group.review_items)
        target.review_items.append('同批次无药名的包装面已暂归入本药品；请对照原图人工核对，若为另一药品请拆分。')
        removable.append(group)
    if removable:
        result.groups = [group for group in result.groups if group not in removable]
    return result
