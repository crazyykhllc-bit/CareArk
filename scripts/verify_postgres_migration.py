"""Run inside the app container; migrations touch only a new, temporary database."""
import os
import subprocess
import sys
import uuid

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.config import get_settings


def main():
    base = make_url(get_settings().database_url).set(drivername='postgresql+psycopg')
    name = 'batch_migration_test_' + uuid.uuid4().hex
    admin = create_engine(base, isolation_level='AUTOCOMMIT')
    test_url = base.set(database=name)
    engine = None
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        env = {**os.environ, 'DATABASE_URL': test_url.render_as_string(hide_password=False)}
        for revision in ['0001', 'head', 'head']:
            subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', revision], env=env, check=True)
            if revision == '0001':
                engine = create_engine(test_url)
                with engine.begin() as db:
                    db.execute(text("INSERT INTO users (id,email,password_hash,role,is_active,created_at,updated_at) "
                                    "VALUES (:id,'migration@example.test','unused','user',true,now(),now())"), {'id': uuid.uuid4()})
        with engine.connect() as db:
            assert db.scalar(text('SELECT count(*) FROM users')) == 1
            assert db.scalar(text('SELECT version_num FROM alembic_version')) == '0002'
        schema = inspect(engine)
        assert 'encounter_id' in {c['name'] for c in schema.get_columns('documents')}
        assert {'upload_batches', 'source_units', 'medication_packages'} <= set(schema.get_table_names())
        print('POSTGRES_MIGRATION_OK existing row preserved; repeated upgrade safe')
    finally:
        if engine:
            engine.dispose()
        # name is created above with a fixed prefix and UUID, never user data.
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}"'))
        admin.dispose()


if __name__ == '__main__':
    main()
