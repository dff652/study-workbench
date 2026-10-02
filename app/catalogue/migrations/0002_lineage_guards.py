from django.db import migrations


SQL = r"""
CREATE FUNCTION swb_guard_question_lineage() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    source_count integer;
    source_distinct integer;
    target_count integer;
    target_distinct integer;
    revision_key text;
    source_stable_id text;
    source_household text;
    source_kind text;
    target_identity jsonb;
    target_payload jsonb;
    target_head text;
    target_published text;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'question lineage is append-only';
    END IF;
    PERFORM id FROM swb_household WHERE id=NEW.household_id FOR UPDATE;
    IF jsonb_typeof(NEW.source_revision_ids) IS DISTINCT FROM 'array'
       OR jsonb_typeof(NEW.target_revision_ids) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'question lineage revisions must be ordered arrays';
    END IF;
    SELECT count(*),count(DISTINCT value) INTO source_count,source_distinct
        FROM jsonb_array_elements_text(NEW.source_revision_ids) AS values(value);
    SELECT count(*),count(DISTINCT value) INTO target_count,target_distinct
        FROM jsonb_array_elements_text(NEW.target_revision_ids) AS values(value);
    IF source_count <> source_distinct OR target_count <> target_distinct
       OR target_count < 1 OR
       (NEW.action='split' AND (source_count <> 1 OR target_count < 2)) OR
       (NEW.action='merge' AND (source_count < 2 OR target_count <> 1)) THEN
        RAISE EXCEPTION 'question lineage has invalid or duplicate revision ordering';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM swb_householdmember m JOIN auth_user u ON u.id=m.user_id
        WHERE m.household_id=NEW.household_id AND m.user_id=NEW.actor_id
          AND m.role IN ('owner','reviewer') AND u.is_active
    ) THEN
        RAISE EXCEPTION 'question lineage actor is not authorized';
    END IF;
    FOR revision_key IN SELECT value FROM jsonb_array_elements_text(NEW.source_revision_ids) AS values(value) LOOP
        SELECT e.stable_id,e.household_id,e.kind INTO source_stable_id,source_household,source_kind
            FROM swb_revisionrecord r JOIN swb_entityrecord e ON e.id=r.entity_id
            WHERE r.revision_id=revision_key AND e.head_revision_id=r.revision_id;
        IF source_household IS DISTINCT FROM NEW.household_id OR source_kind IS DISTINCT FROM 'question' THEN
            RAISE EXCEPTION 'question lineage source must be a current same-household question revision';
        END IF;
    END LOOP;
    FOR revision_key IN SELECT value FROM jsonb_array_elements_text(NEW.target_revision_ids) AS values(value) LOOP
        SELECT e.identity,r.payload,e.head_revision_id,e.published_revision_id
            INTO target_identity,target_payload,target_head,target_published
            FROM swb_revisionrecord r JOIN swb_entityrecord e ON e.id=r.entity_id
            WHERE r.revision_id=revision_key AND e.household_id=NEW.household_id AND e.kind='question';
        IF target_identity IS NULL OR target_head IS DISTINCT FROM revision_key OR target_published IS NOT NULL
           OR target_payload->>'review_state' IS DISTINCT FROM 'draft' THEN
            RAISE EXCEPTION 'question lineage target must be a draft head in the same household';
        END IF;
        IF NEW.action='split' THEN
            SELECT e.stable_id INTO source_stable_id FROM swb_revisionrecord r
                JOIN swb_entityrecord e ON e.id=r.entity_id
                WHERE r.revision_id=(NEW.source_revision_ids->>0);
            IF target_identity->>'parent_question_id' IS DISTINCT FROM source_stable_id
               OR target_payload->>'parent_question_revision_id' IS DISTINCT FROM (NEW.source_revision_ids->>0) THEN
                RAISE EXCEPTION 'split target must pin its exact source question revision as parent';
            END IF;
        ELSIF target_identity->>'parent_question_id' IS NOT NULL
           OR target_payload->>'parent_question_revision_id' IS NOT NULL THEN
            RAISE EXCEPTION 'merged target cannot claim a single parent question';
        END IF;
    END LOOP;
    RETURN NEW;
END $$;
CREATE TRIGGER swb_question_lineage_insert BEFORE INSERT OR UPDATE OR DELETE ON catalogue_questionlineage
    FOR EACH ROW EXECUTE FUNCTION swb_guard_question_lineage();
"""

REVERSE = """
DROP TRIGGER swb_question_lineage_insert ON catalogue_questionlineage;
DROP FUNCTION swb_guard_question_lineage();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("catalogue", "0001_initial"),
        ("persistence", "0004_business_receipts"),
    ]

    operations = [migrations.RunSQL(SQL, REVERSE)]
