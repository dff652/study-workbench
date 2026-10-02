"""Keep original import provenance immutable and household/type scoped."""
from django.conf import settings
from django.db import migrations


def install(apps, schema_editor):
    quote = schema_editor.connection.ops.quote_name
    user = apps.get_model(settings.AUTH_USER_MODEL)
    user_table, user_pk = quote(user._meta.db_table), quote(user._meta.pk.column)
    active_column = quote(user._meta.get_field("is_active").column)
    user_column = quote(apps.get_model("persistence", "HouseholdMember")._meta.get_field("user").column)
    sql = f"""
    CREATE FUNCTION swb_guard_legacy_batch() RETURNS trigger AS $$
    BEGIN
        PERFORM id FROM swb_household WHERE id = NEW.household_id FOR UPDATE;
        IF NOT EXISTS (SELECT 1 FROM swb_householdmember m JOIN {user_table} u ON u.{user_pk} = m.{user_column}
            WHERE m.household_id = NEW.household_id AND m.{user_column} = NEW.imported_by_id
            AND m.role IN ('owner', 'reviewer') AND u.{active_column} IS TRUE) THEN
            RAISE EXCEPTION 'import requires an active household writer' USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM swb_requestreceipt r WHERE r.id = NEW.receipt_id
            AND r.household_id = NEW.household_id AND r.actor_id = NEW.imported_by_id AND r.operation = 'stage'
            AND r.request_key = 'legacy-import:' || NEW.source_digest) OR
            NEW.manifest->>'household_id' IS DISTINCT FROM NEW.household_id OR
            NEW.manifest->>'dataset_key' IS DISTINCT FROM NEW.dataset_key OR
            NEW.manifest->>'source_digest' IS DISTINCT FROM NEW.source_digest OR
            NEW.manifest->'counts' IS DISTINCT FROM NEW.counts OR
            jsonb_typeof(NEW.manifest->'index_rows') IS DISTINCT FROM 'array' THEN
            RAISE EXCEPTION 'import manifest/receipt scope mismatch' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END; $$ LANGUAGE plpgsql;

    CREATE FUNCTION swb_guard_legacy_entry() RETURNS trigger AS $$
    DECLARE
        scope text;
        batch_manifest jsonb;
        source_row jsonb;
        method_id text;
    BEGIN
        SELECT household_id, manifest INTO scope, batch_manifest FROM swb_legacyimportbatch WHERE id = NEW.batch_id;
        PERFORM id FROM swb_household WHERE id = scope FOR UPDATE;
        source_row := batch_manifest->'index_rows'->(NEW.ordinal - 1);
        IF source_row IS NULL OR source_row->>'book' IS DISTINCT FROM NEW.book OR
            source_row->>'num' IS DISTINCT FROM NEW.number OR source_row->'raw' IS DISTINCT FROM NEW.raw OR
            source_row->'photo_tokens' IS DISTINCT FROM NEW.photo_tokens OR
            source_row->>'question_revision_id' IS DISTINCT FROM NEW.question_revision_id OR
            source_row->>'primary_method_revision_id' IS DISTINCT FROM NEW.primary_method_revision_id OR
            source_row->'aux_method_revision_ids' IS DISTINCT FROM NEW.auxiliary_method_revision_ids THEN
            RAISE EXCEPTION 'entry must match original manifest row' USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM swb_revisionrecord r JOIN swb_entityrecord e ON e.id = r.entity_id
            WHERE r.revision_id = NEW.question_revision_id AND e.household_id = scope AND e.kind = 'question') OR
            NOT EXISTS (SELECT 1 FROM swb_revisionrecord r JOIN swb_entityrecord e ON e.id = r.entity_id
            WHERE r.revision_id = NEW.primary_method_revision_id AND e.household_id = scope AND e.kind = 'method') THEN
            RAISE EXCEPTION 'entry revision has wrong household/type' USING ERRCODE = '23514';
        END IF;
        FOR method_id IN SELECT jsonb_array_elements_text(NEW.auxiliary_method_revision_ids) LOOP
            IF NOT EXISTS (SELECT 1 FROM swb_revisionrecord r JOIN swb_entityrecord e ON e.id = r.entity_id
                WHERE r.revision_id = method_id AND e.household_id = scope AND e.kind = 'method') THEN
                RAISE EXCEPTION 'auxiliary method has wrong household/type' USING ERRCODE = '23514';
            END IF;
        END LOOP;
        RETURN NEW;
    END; $$ LANGUAGE plpgsql;

    CREATE TRIGGER swb_import_batch_insert BEFORE INSERT ON swb_legacyimportbatch
        FOR EACH ROW EXECUTE FUNCTION swb_guard_legacy_batch();
    CREATE TRIGGER swb_import_entry_insert BEFORE INSERT ON swb_legacyindexentry
        FOR EACH ROW EXECUTE FUNCTION swb_guard_legacy_entry();
    CREATE TRIGGER swb_import_batch_immutable BEFORE UPDATE OR DELETE ON swb_legacyimportbatch
        FOR EACH ROW EXECUTE FUNCTION swb_reject_immutable_change();
    CREATE TRIGGER swb_import_entry_immutable BEFORE UPDATE OR DELETE ON swb_legacyindexentry
        FOR EACH ROW EXECUTE FUNCTION swb_reject_immutable_change();
    """
    schema_editor.execute(sql)


def uninstall(apps, schema_editor):
    schema_editor.execute("""
        DROP TRIGGER swb_import_batch_insert ON swb_legacyimportbatch;
        DROP TRIGGER swb_import_entry_insert ON swb_legacyindexentry;
        DROP TRIGGER swb_import_batch_immutable ON swb_legacyimportbatch;
        DROP TRIGGER swb_import_entry_immutable ON swb_legacyindexentry;
        DROP FUNCTION swb_guard_legacy_batch();
        DROP FUNCTION swb_guard_legacy_entry();
    """)


class Migration(migrations.Migration):
    dependencies = [("imports", "0001_initial")]
    operations = [migrations.RunPython(install, uninstall)]
