import sqlite3

from tests.test_batch_migrations import migrate


def test_upgrade_from_0011_keeps_existing_visit_dates_ids_and_cross_hospital_links(tmp_path):
    db_path = tmp_path / 'existing.db'
    migrate(db_path, '0011')
    owner, event, document, relation = ('1'*32, '2'*32, '3'*32, '4'*32)
    with sqlite3.connect(db_path) as db:
        db.execute("insert into users (id,email,password_hash,role,is_active,created_at,updated_at) values (?,?,?,?,?,?,?)",
                   (owner,'synthetic@example.test','hash','user',1,'2026-01-01','2026-01-01'))
        db.execute("insert into encounters (id,owner_id,title,hospital,date,patient_identity,evidence,version,created_at,updated_at) values (?,?,?,?,?,?,?,?,?,?)",
                   (event,owner,'合成旧就诊','甲医院','2026-01-02',None,'[]',1,'2026-01-01','2026-01-01'))
        db.execute("insert into documents (id,owner_id,document_type,title,encounter_id,key_information,extraction_metadata,type_specific_data,patient_scope,version,created_at,updated_at) values (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (document,owner,'检验报告','合成报告',None,'[]','{}','{}','self',1,'2026-01-01','2026-01-01'))
        db.execute("insert into related_encounters (id,owner_id,document_id,encounter_id,created_at,updated_at) values (?,?,?,?,?,?)",
                   (relation,owner,document,event,'2026-01-01','2026-01-01'))
    migrate(db_path, 'head')
    migrate(db_path, 'head')
    with sqlite3.connect(db_path) as db:
        row = db.execute('select id,title,date,event_kind,date_basis from encounters').fetchone()
        assert row == (event,'合成旧就诊','2026-01-02','other','user_confirmed')
        assert db.execute('select encounter_id from documents').fetchone()[0] is None
        assert db.execute('select id,document_id,encounter_id from related_encounters').fetchone() == (relation,document,event)
        assert db.execute('select version_num from alembic_version').fetchone()[0] == '0016'
        for table in ('care_topics','care_topic_encounters','care_topic_exclusions','care_suggestions','care_revisions'):
            assert db.execute(f'select count(*) from {table}').fetchone()[0] == 0
