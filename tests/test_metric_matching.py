from decimal import Decimal

from app.services import metric_matching
from app.services.metric_matching import lab_matches_metric, parse_strict_number


def test_numeric_parser_accepts_only_complete_plain_or_scientific_numbers():
    assert parse_strict_number('0') == Decimal('0')
    assert parse_strict_number(' -1.25e2 ') == Decimal('-125')
    for value in ['1+', '120/80', '<5.6', '阴性', '', None, 'NaN', 'Infinity']:
        assert parse_strict_number(value) is None


def test_fasting_glucose_requires_analyte_and_actual_fasting_condition():
    assert lab_matches_metric('fasting_glucose', 'glucose', '葡萄糖', '空腹')
    assert lab_matches_metric('fasting_glucose', None, '空腹血糖', 'fasting')
    assert not lab_matches_metric('fasting_glucose', 'glucose', '葡萄糖', None)
    assert not lab_matches_metric('fasting_glucose', None, 'GLU', '餐后')


def test_short_ambiguous_aliases_do_not_use_substring_matching():
    assert lab_matches_metric('triglycerides', 'triglycerides', '甘油三酯', None)
    assert lab_matches_metric('triglycerides', None, 'TG', None)
    assert not lab_matches_metric('triglycerides', None, 'ALTG', None)
    assert lab_matches_metric('blood_lipids', 'ldl_c', '低密度脂蛋白胆固醇', None)
    assert lab_matches_metric('blood_lipids', None, 'HDL-C', None)
    assert not lab_matches_metric('blood_lipids', None, 'non-HDL-C', None)


def test_report_abbreviations_and_blood_pressure_pair_match_known_metrics():
    assert lab_matches_metric('fasting_glucose', 'GLU', '血糖', '空腹')
    assert lab_matches_metric('serum_creatinine', 'CREA', '血肌酐', None)
    assert lab_matches_metric('ogtt_glucose', 'GLU', '葡萄糖', None)
    assert lab_matches_metric('ogtt_insulin', 'INS', '胰岛素', None)
    assert lab_matches_metric('blood_pressure', 'BP', '收缩压 / 舒张压', None)
    assert callable(getattr(metric_matching, 'parse_strict_pair', None))
    assert metric_matching.parse_strict_pair('113 / 71') == (Decimal('113'), Decimal('71'))
    assert metric_matching.parse_strict_pair('113/71 mmHg') is None
