from django.conf import settings
from django.db import migrations


def install_guards(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        raise RuntimeError("Study Workbench study records require PostgreSQL")
    quote = connection.ops.quote_name
    user_model = apps.get_model(settings.AUTH_USER_MODEL)
    member_model = apps.get_model("persistence", "HouseholdMember")
    user_table, user_pk = quote(user_model._meta.db_table), quote(user_model._meta.pk.column)
    active = quote(user_model._meta.get_field("is_active").column)
    member_table = quote(member_model._meta.db_table)
    household_col = quote(member_model._meta.get_field("household").column)
    member_user_col = quote(member_model._meta.get_field("user").column)

    def authorized(actor_column):
        return f"""EXISTS (SELECT 1 FROM {member_table} AS m
            JOIN {user_table} AS u ON u.{user_pk}=m.{member_user_col}
            WHERE m.{household_col}=hid AND m.{member_user_col}=NEW.{actor_column}
              AND m.role IN ('owner','reviewer') AND u.{active} IS TRUE)"""

    sql = f"""
    CREATE FUNCTION swb_guard_study_schedule() RETURNS trigger AS $$
    DECLARE hid text; learner_kind text; learner_house text; target_kind text;
        target_house text; target_entity bigint; published text; head text; projection_state text;
    BEGIN
        IF TG_OP <> 'INSERT' THEN
            RAISE EXCEPTION 'study schedule identity is immutable' USING ERRCODE='23514';
        END IF;
        hid := NEW.household_id;
        PERFORM id FROM swb_household WHERE id=NEW.household_id FOR UPDATE;
        SELECT household_id,kind INTO learner_house,learner_kind
            FROM swb_entityrecord WHERE id=NEW.learner_id;
        SELECT e.household_id,e.kind,e.id,e.published_revision_id,e.head_revision_id,rp.state
            INTO target_house,target_kind,target_entity,published,head,projection_state
            FROM swb_revisionrecord r JOIN swb_entityrecord e ON e.id=r.entity_id
            JOIN swb_reviewprojection rp ON rp.revision_id=r.revision_id
            WHERE r.revision_id=NEW.target_question_revision_id;
        IF learner_house IS DISTINCT FROM NEW.household_id OR learner_kind IS DISTINCT FROM 'learner'
            OR target_house IS DISTINCT FROM NEW.household_id OR target_kind IS DISTINCT FROM 'question'
            OR published IS DISTINCT FROM NEW.target_question_revision_id
            OR projection_state IS DISTINCT FROM 'accepted' THEN
            RAISE EXCEPTION 'study schedule requires same-household learner and current accepted question' USING ERRCODE='23514';
        END IF;
        IF NOT {authorized('created_by_id')} THEN
            RAISE EXCEPTION 'study schedule actor is not authorized' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE FUNCTION swb_guard_schedule_revision() RETURNS trigger AS $$
    DECLARE hid text; learner_entity bigint; target_revision text; latest_id bigint;
        latest_no integer; latest_action text; attempt_house text; attempt_kind text;
        attempt_head text; attempt_state text; attempt_learner text; attempt_question text;
    BEGIN
        SELECT household_id,learner_id,target_question_revision_id INTO hid,learner_entity,target_revision
            FROM study_studyschedule WHERE id=NEW.schedule_id FOR UPDATE;
        PERFORM id FROM swb_household WHERE id=hid FOR UPDATE;
        SELECT id,revision_no,action INTO latest_id,latest_no,latest_action
            FROM study_schedulerevision WHERE schedule_id=NEW.schedule_id ORDER BY revision_no DESC LIMIT 1;
        IF NEW.previous_id IS DISTINCT FROM latest_id OR NEW.revision_no IS DISTINCT FROM COALESCE(latest_no,0)+1 THEN
            RAISE EXCEPTION 'schedule revisions must append the current version' USING ERRCODE='23514';
        END IF;
        IF (NEW.revision_no=1 AND NEW.action IS DISTINCT FROM 'planned') OR
           (NEW.revision_no>1 AND (latest_action NOT IN ('planned','rescheduled') OR NEW.action='planned')) THEN
            RAISE EXCEPTION 'schedule action is not valid for its current state' USING ERRCODE='23514';
        END IF;
        IF NEW.action='completed' THEN
            SELECT e.household_id,e.kind,e.head_revision_id,r.payload->>'state',
                e.identity->>'learner_id',r.payload->>'question_revision_id'
                INTO attempt_house,attempt_kind,attempt_head,attempt_state,attempt_learner,attempt_question
                FROM swb_revisionrecord r JOIN swb_entityrecord e ON e.id=r.entity_id
                WHERE r.revision_id=NEW.completed_attempt_revision_id;
            IF NEW.completed_attempt_revision_id IS NULL OR attempt_house IS DISTINCT FROM hid
                OR attempt_kind IS DISTINCT FROM 'attempt'
                OR attempt_head IS DISTINCT FROM NEW.completed_attempt_revision_id
                OR attempt_state IS DISTINCT FROM 'active'
                OR attempt_learner IS DISTINCT FROM (SELECT stable_id FROM swb_entityrecord WHERE id=learner_entity)
                OR attempt_question IS DISTINCT FROM target_revision THEN
                RAISE EXCEPTION 'schedule completion must bind a current same-learner exact-question active attempt' USING ERRCODE='23514';
            END IF;
        ELSIF NEW.completed_attempt_revision_id IS NOT NULL THEN
            RAISE EXCEPTION 'only a completion event may reference an attempt' USING ERRCODE='23514';
        END IF;
        IF NOT {authorized('recorded_by_id')} THEN
            RAISE EXCEPTION 'schedule event actor is not authorized' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE FUNCTION swb_guard_variant_provenance() RETURNS trigger AS $$
    DECLARE hid text; q_house text; q_kind text; q_head text; q_origin text; q_state text;
        parent_house text; parent_kind text; parent_head text; parent_published text; parent_state text;
        method_house text; method_kind text; method_head text; method_published text; method_state text;
        ref_id text;
    BEGIN
        IF TG_OP <> 'INSERT' THEN
            RAISE EXCEPTION 'variant provenance is immutable' USING ERRCODE='23514';
        END IF;
        hid := NEW.household_id;
        PERFORM id FROM swb_household WHERE id=hid FOR UPDATE;
        SELECT household_id,kind,head_revision_id INTO q_house,q_kind,q_head
            FROM swb_entityrecord WHERE id=NEW.question_id;
        SELECT swb_revisionrecord.payload #>> '{{header,origin}}',swb_reviewprojection.state INTO q_origin,q_state
            FROM swb_revisionrecord JOIN swb_reviewprojection USING (revision_id)
            WHERE revision_id=q_head;
        SELECT e.household_id,e.kind,e.head_revision_id,e.published_revision_id,rp.state
            INTO parent_house,parent_kind,parent_head,parent_published,parent_state
            FROM swb_revisionrecord r JOIN swb_entityrecord e ON e.id=r.entity_id
            JOIN swb_reviewprojection rp ON rp.revision_id=r.revision_id
            WHERE r.revision_id=NEW.parent_question_revision_id;
        SELECT e.household_id,e.kind,e.head_revision_id,e.published_revision_id,rp.state
            INTO method_house,method_kind,method_head,method_published,method_state
            FROM swb_revisionrecord r JOIN swb_entityrecord e ON e.id=r.entity_id
            JOIN swb_reviewprojection rp ON rp.revision_id=r.revision_id
            WHERE r.revision_id=NEW.target_method_revision_id;
        IF q_house IS DISTINCT FROM hid OR q_kind IS DISTINCT FROM 'question'
            OR q_head IS DISTINCT FROM (SELECT revision_id FROM swb_revisionrecord WHERE entity_id=NEW.question_id ORDER BY revision_no DESC LIMIT 1)
            OR q_origin IS DISTINCT FROM 'ai' OR q_state IS DISTINCT FROM 'draft'
            OR parent_house IS DISTINCT FROM hid OR parent_kind IS DISTINCT FROM 'question'
            OR parent_published IS DISTINCT FROM NEW.parent_question_revision_id OR parent_state IS DISTINCT FROM 'accepted'
            OR method_house IS DISTINCT FROM hid OR method_kind IS DISTINCT FROM 'method'
            OR method_published IS DISTINCT FROM NEW.target_method_revision_id OR method_state IS DISTINCT FROM 'accepted'
            OR jsonb_typeof(NEW.source_revision_ids) IS DISTINCT FROM 'array'
            OR jsonb_array_length(NEW.source_revision_ids)=0 THEN
            RAISE EXCEPTION 'variant requires an AI draft and current accepted same-household sources' USING ERRCODE='23514';
        END IF;
        IF (NEW.source_revision_ids ? NEW.parent_question_revision_id) IS NOT TRUE
            OR (NEW.source_revision_ids ? NEW.target_method_revision_id) IS NOT TRUE THEN
            RAISE EXCEPTION 'variant provenance must include its parent and method source revisions' USING ERRCODE='23514';
        END IF;
        IF EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.source_revision_ids) AS refs(value)
            WHERE jsonb_typeof(refs.value) IS DISTINCT FROM 'string')
            OR jsonb_array_length(NEW.source_revision_ids) <> (SELECT count(DISTINCT value)
                FROM jsonb_array_elements_text(NEW.source_revision_ids) AS refs(value)) THEN
            RAISE EXCEPTION 'variant sources must be a unique list of revision IDs' USING ERRCODE='23514';
        END IF;
        FOR ref_id IN SELECT jsonb_array_elements_text(NEW.source_revision_ids)
        LOOP
            IF NOT EXISTS (SELECT 1 FROM swb_revisionrecord r JOIN swb_entityrecord e ON e.id=r.entity_id
                WHERE r.revision_id=ref_id AND e.household_id=hid) THEN
                RAISE EXCEPTION 'variant source revision is outside its household' USING ERRCODE='23514';
            END IF;
        END LOOP;
        IF NOT {authorized('created_by_id')} THEN
            RAISE EXCEPTION 'variant provenance actor is not authorized' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER study_schedule_guard BEFORE INSERT OR UPDATE OR DELETE ON study_studyschedule
        FOR EACH ROW EXECUTE FUNCTION swb_guard_study_schedule();
    CREATE TRIGGER study_schedule_revision_insert BEFORE INSERT ON study_schedulerevision
        FOR EACH ROW EXECUTE FUNCTION swb_guard_schedule_revision();
    CREATE TRIGGER study_schedule_revision_immutable BEFORE UPDATE OR DELETE ON study_schedulerevision
        FOR EACH ROW EXECUTE FUNCTION swb_reject_immutable_change();
    CREATE TRIGGER study_variant_insert BEFORE INSERT ON study_variantprovenance
        FOR EACH ROW EXECUTE FUNCTION swb_guard_variant_provenance();
    CREATE TRIGGER study_variant_immutable BEFORE UPDATE OR DELETE ON study_variantprovenance
        FOR EACH ROW EXECUTE FUNCTION swb_reject_immutable_change();
    """
    with connection.cursor() as cursor:
        cursor.execute(sql)


def remove_guards(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            DROP TRIGGER study_variant_immutable ON study_variantprovenance;
            DROP TRIGGER study_variant_insert ON study_variantprovenance;
            DROP TRIGGER study_schedule_revision_immutable ON study_schedulerevision;
            DROP TRIGGER study_schedule_revision_insert ON study_schedulerevision;
            DROP TRIGGER study_schedule_guard ON study_studyschedule;
            DROP FUNCTION swb_guard_variant_provenance();
            DROP FUNCTION swb_guard_schedule_revision();
            DROP FUNCTION swb_guard_study_schedule();
        """)


class Migration(migrations.Migration):
    dependencies = [
        ("persistence", "0004_business_receipts"),
        ("study", "0001_initial"),
    ]
    operations = [migrations.RunPython(install_guards, remove_guards)]
