import sqlite3
import pytest

from tests.test_batch_migrations import migrate


def test_upload_context_migration_preserves_legacy_batch_and_enforces_intent_unique(tmp_path):
    path = tmp_path / 'upload-context.db'
    migrate(path, '0014')
    owner, batch = '1'*32, '2'*32
    with sqlite3.connect(path) as db:
        db.execute('insert into users (id,email,password_hash,role,is_active,created_at,updated_at) values (?,?,?,?,?,?,?)',
            (owner,'synthetic@example.test','hash','user',1,'2026-01-01','2026-01-01'))
        db.execute('insert into upload_batches (id,owner_id,status,version,grouping,retry_count,created_at,updated_at) values (?,?,?,?,?,?,?,?)',
            (batch,owner,'receiving',3,'{}',0,'2026-01-01','2026-01-01'))
    migrate(path, 'head')
    migrate(path, 'head')
    with sqlite3.connect(path) as db:
        assert db.execute('select id,version,care_context_id from upload_batches').fetchone() == (batch,3,None)
        assert db.execute('select version_num from alembic_version').fetchone()[0] == '0016'
        query = 'insert into upload_care_contexts (id,owner_id,intent_key,mode,created_at,updated_at) values (?,?,?,?,?,?)'
        db.execute(query,('3'*32,owner,'shared-intent','new_topic','2026-01-01','2026-01-01'))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(query,('4'*32,owner,'shared-intent','new_topic','2026-01-01','2026-01-01'))
        assert db.execute('select count(*) from care_topics').fetchone()[0] == 0
