from django.db import migrations


SQL = """
CREATE FUNCTION swb_guard_retention_policy() RETURNS trigger AS $$
DECLARE latest_id bigint; latest_no integer;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'retention policy revisions are append-only' USING ERRCODE='23514';
    END IF;
    PERFORM id FROM swb_household WHERE id=NEW.household_id FOR UPDATE;
    SELECT id,revision_no INTO latest_id,latest_no FROM operations_retentionpolicyrevision
        WHERE household_id=NEW.household_id ORDER BY revision_no DESC LIMIT 1;
    IF NEW.previous_id IS DISTINCT FROM latest_id
        OR NEW.revision_no IS DISTINCT FROM COALESCE(latest_no,0)+1 THEN
        RAISE EXCEPTION 'retention policy must append the current version' USING ERRCODE='23514';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM swb_householdmember m JOIN auth_user u ON u.id=m.user_id
        WHERE m.household_id=NEW.household_id AND m.user_id=NEW.created_by_id
        AND m.role='owner' AND u.is_active) THEN
        RAISE EXCEPTION 'retention policy actor is not an active owner' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION swb_guard_export_archive() RETURNS trigger AS $$
DECLARE snapshot_house text;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'export archive rows are immutable' USING ERRCODE='23514';
    END IF;
    PERFORM id FROM swb_household WHERE id=NEW.household_id FOR UPDATE;
    SELECT household_id INTO snapshot_house FROM printing_exportsnapshot WHERE id=NEW.snapshot_id;
    IF snapshot_house IS DISTINCT FROM NEW.household_id THEN
        RAISE EXCEPTION 'export archive must match its snapshot household' USING ERRCODE='23514';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM swb_householdmember m JOIN auth_user u ON u.id=m.user_id
        WHERE m.household_id=NEW.household_id AND m.user_id=NEW.archived_by_id
        AND m.role='owner' AND u.is_active) THEN
        RAISE EXCEPTION 'export archive actor is not an active owner' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION swb_guard_export_retirement() RETURNS trigger AS $$
DECLARE snapshot_house text; archive_house text; archive_key text;
    archive_manifest text; archive_hash text; archive_files jsonb;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'export retirement rows are immutable' USING ERRCODE='23514';
    END IF;
    PERFORM id FROM swb_household WHERE id=NEW.household_id FOR UPDATE;
    SELECT household_id INTO snapshot_house FROM printing_exportsnapshot WHERE id=NEW.snapshot_id;
    SELECT household_id,archive_storage_key,manifest_sha256,archive_sha256,file_hashes
        INTO archive_house,archive_key,archive_manifest,archive_hash,archive_files
        FROM operations_exportarchiverecord WHERE snapshot_id=NEW.snapshot_id;
    IF snapshot_house IS DISTINCT FROM NEW.household_id OR archive_house IS DISTINCT FROM NEW.household_id
        OR NEW.archive_storage_key IS DISTINCT FROM archive_key
        OR NEW.manifest_sha256 IS DISTINCT FROM archive_manifest
        OR NEW.archive_sha256 IS DISTINCT FROM archive_hash
        OR NEW.file_hashes IS DISTINCT FROM archive_files THEN
        RAISE EXCEPTION 'export retirement must preserve its verified archive record' USING ERRCODE='23514';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM swb_householdmember m JOIN auth_user u ON u.id=m.user_id
        WHERE m.household_id=NEW.household_id AND m.user_id=NEW.retired_by_id
        AND m.role='owner' AND u.is_active) THEN
        RAISE EXCEPTION 'export retirement actor is not an active owner' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION swb_guard_work_timing() RETURNS trigger AS $$
DECLARE question_house text; question_kind text; question_published text; review_state text;
    attempt_house text; attempt_kind text; attempt_head text; attempt_state text;
    attempt_question text;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'work timing rows are append-only' USING ERRCODE='23514';
    END IF;
    PERFORM id FROM swb_household WHERE id=NEW.household_id FOR UPDATE;
    SELECT e.household_id,e.kind,e.published_revision_id,rp.state
        INTO question_house,question_kind,question_published,review_state
        FROM swb_revisionrecord r JOIN swb_entityrecord e ON e.id=r.entity_id
        JOIN swb_reviewprojection rp ON rp.revision_id=r.revision_id
        WHERE r.revision_id=NEW.question_revision_id;
    IF question_house IS DISTINCT FROM NEW.household_id OR question_kind IS DISTINCT FROM 'question'
        OR question_published IS DISTINCT FROM NEW.question_revision_id OR review_state IS DISTINCT FROM 'accepted' THEN
        RAISE EXCEPTION 'work timing requires an exact current accepted question revision' USING ERRCODE='23514';
    END IF;
    IF NEW.attempt_revision_id IS NOT NULL THEN
        SELECT e.household_id,e.kind,e.head_revision_id,r.payload->>'state',
            r.payload->>'question_revision_id'
            INTO attempt_house,attempt_kind,attempt_head,attempt_state,attempt_question
            FROM swb_revisionrecord r JOIN swb_entityrecord e ON e.id=r.entity_id
            WHERE r.revision_id=NEW.attempt_revision_id;
        IF attempt_house IS DISTINCT FROM NEW.household_id OR attempt_kind IS DISTINCT FROM 'attempt'
            OR attempt_head IS DISTINCT FROM NEW.attempt_revision_id OR attempt_state IS DISTINCT FROM 'active'
            OR attempt_question IS DISTINCT FROM NEW.question_revision_id THEN
            RAISE EXCEPTION 'work timing attempt must be current and match the exact question revision' USING ERRCODE='23514';
        END IF;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM swb_householdmember m JOIN auth_user u ON u.id=m.user_id
        WHERE m.household_id=NEW.household_id AND m.user_id=NEW.recorded_by_id
        AND m.role IN ('owner','reviewer') AND u.is_active) THEN
        RAISE EXCEPTION 'work timing actor is not an active household editor' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER swb_retention_policy_insert BEFORE INSERT ON operations_retentionpolicyrevision
    FOR EACH ROW EXECUTE FUNCTION swb_guard_retention_policy();
CREATE TRIGGER swb_retention_policy_immutable BEFORE UPDATE OR DELETE ON operations_retentionpolicyrevision
    FOR EACH ROW EXECUTE FUNCTION swb_reject_immutable_change();
CREATE TRIGGER swb_export_archive_insert BEFORE INSERT ON operations_exportarchiverecord
    FOR EACH ROW EXECUTE FUNCTION swb_guard_export_archive();
CREATE TRIGGER swb_export_archive_immutable BEFORE UPDATE OR DELETE ON operations_exportarchiverecord
    FOR EACH ROW EXECUTE FUNCTION swb_reject_immutable_change();
CREATE TRIGGER swb_export_retirement_insert BEFORE INSERT ON operations_exportretirementrecord
    FOR EACH ROW EXECUTE FUNCTION swb_guard_export_retirement();
CREATE TRIGGER swb_export_retirement_immutable BEFORE UPDATE OR DELETE ON operations_exportretirementrecord
    FOR EACH ROW EXECUTE FUNCTION swb_reject_immutable_change();
CREATE TRIGGER swb_work_timing_insert BEFORE INSERT ON operations_worktiming
    FOR EACH ROW EXECUTE FUNCTION swb_guard_work_timing();
CREATE TRIGGER swb_work_timing_immutable BEFORE UPDATE OR DELETE ON operations_worktiming
    FOR EACH ROW EXECUTE FUNCTION swb_reject_immutable_change();
"""

REVERSE = """
DROP TRIGGER swb_work_timing_immutable ON operations_worktiming;
DROP TRIGGER swb_work_timing_insert ON operations_worktiming;
DROP TRIGGER swb_export_retirement_immutable ON operations_exportretirementrecord;
DROP TRIGGER swb_export_retirement_insert ON operations_exportretirementrecord;
DROP TRIGGER swb_export_archive_immutable ON operations_exportarchiverecord;
DROP TRIGGER swb_export_archive_insert ON operations_exportarchiverecord;
DROP TRIGGER swb_retention_policy_immutable ON operations_retentionpolicyrevision;
DROP TRIGGER swb_retention_policy_insert ON operations_retentionpolicyrevision;
DROP FUNCTION swb_guard_work_timing();
DROP FUNCTION swb_guard_export_retirement();
DROP FUNCTION swb_guard_export_archive();
DROP FUNCTION swb_guard_retention_policy();
"""


class Migration(migrations.Migration):
    dependencies = [("operations", "0001_initial"), ("persistence", "0002_postgresql_guards")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
