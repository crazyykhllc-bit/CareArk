from app.models import Base


def test_all_private_tables_are_owned():
    private_tables = {
        "documents",
        "attachments",
        "lab_results",
        "medications",
        "medication_sources",
        "medication_events",
        "extraction_jobs",
        "extraction_drafts",
        "upload_batches", "batch_files", "source_units", "document_sources", "encounters", "medication_packages",
    }

    assert private_tables <= set(Base.metadata.tables)
    for table_name in private_tables:
        assert "owner_id" in Base.metadata.tables[table_name].columns


def test_medication_key_is_unique_per_owner():
    constraints = Base.metadata.tables["medications"].constraints
    assert any(
        constraint.name == "uq_medication_owner_drug_key"
        for constraint in constraints
    )
