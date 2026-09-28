import os
import sqlite3
import subprocess
import sys


def migrate(path, revision):
    env = {**os.environ, 'DATABASE_URL': 'sqlite:///' + str(path).replace('\\', '/')}
    result = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', revision], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_empty_and_existing_database_upgrade_without_recreating_originals(tmp_path):
    old = tmp_path / 'old.db'
    migrate(old, '0001')
    with sqlite3.connect(old) as db:
        columns = [x[1] for x in db.execute('pragma table_info(documents)')]
        assert 'encounter_id' not in columns
        assert not db.execute("select name from sqlite_master where name='upload_batches'").fetchall()
        db.execute("insert into users (id,email,password_hash,role,is_active,created_at,updated_at) values (?,?,?,?,?,?,?)",
                   ('1'*32, 'preserved@example.test', 'hash', 'user', 1, '2026-09-06', '2026-09-06'))
    migrate(old, 'head')
    migrate(old, 'head')
    fresh = tmp_path / 'fresh.db'
    migrate(fresh, 'head')
    with sqlite3.connect(old) as db, sqlite3.connect(fresh) as new:
        assert db.execute('select email from users').fetchone()[0] == 'preserved@example.test'
        assert db.execute('select version_num from alembic_version').fetchone()[0] == '0016'
        for table in ['documents', 'medications', 'source_units', 'upload_batches', 'encounters',
                      'receipt_details', 'metric_definitions', 'metric_entries', 'test_sessions',
                      'test_session_sources', 'document_revisions', 'medication_revisions',
                      'metric_entry_revisions', 'related_encounters', 'care_topics',
                      'care_topic_encounters', 'care_topic_exclusions', 'care_suggestions', 'care_revisions']:
            assert list(db.execute(f'pragma table_info({table})')) == list(new.execute(f'pragma table_info({table})'))
        document_columns = {x[1] for x in db.execute('pragma table_info(documents)')}
        lab_columns = {x[1] for x in db.execute('pragma table_info(lab_results)')}
        assert {'type_specific_data', 'patient_scope', 'deleted_at'} <= document_columns
        assert 'deleted_at' in {x[1] for x in db.execute('pragma table_info(medications)')}
        assert {'condition', 'source_unit_id', 'result_type', 'review_status', 'test_session_id'} <= lab_columns
        metric_columns = {x[1] for x in db.execute('pragma table_info(metric_entries)')}
        assert {'raw_value', 'value1', 'value2', 'idempotency_key', 'voided_at'} <= metric_columns
        assert 'version' in {x[1] for x in db.execute('pragma table_info(receipt_details)')}
        assert 'dashboard_customized' in {x[1] for x in db.execute('pragma table_info(users)')}
        assert {'managed_by_id', 'profile_name'} <= {x[1] for x in db.execute('pragma table_info(users)')}
        assert 'active_profile_id' in {x[1] for x in db.execute('pragma table_info(sessions)')}
        assert 'dashboard_visible' in {x[1] for x in db.execute('pragma table_info(metric_definitions)')}
        encounter_columns = {x[1]: x for x in db.execute('pragma table_info(encounters)')}
        assert encounter_columns['date'][3] == 0
