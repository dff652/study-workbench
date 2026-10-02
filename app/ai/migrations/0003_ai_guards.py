"""Enforce append-only AI configuration, immutable run inputs, and budget identity."""
from django.db import migrations


SQL = r"""
CREATE FUNCTION swb_guard_ai_modelconfig() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE current_revision integer;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'AI model configuration versions are append-only' USING ERRCODE='23514';
    END IF;
    PERFORM id FROM swb_household WHERE id=NEW.household_id FOR UPDATE;
    IF NOT EXISTS (
        SELECT 1 FROM swb_householdmember m JOIN auth_user u ON u.id=m.user_id
        WHERE m.household_id=NEW.household_id AND m.user_id=NEW.created_by_id
          AND m.role='owner' AND u.is_active
    ) THEN
        RAISE EXCEPTION 'AI model configuration actor must be an active household owner' USING ERRCODE='23514';
    END IF;
    SELECT COALESCE(max(revision_no),0) INTO current_revision
        FROM ai_modelconfig WHERE household_id=NEW.household_id;
    IF NEW.revision_no <> current_revision + 1 THEN
        RAISE EXCEPTION 'AI model configuration version must increase by one' USING ERRCODE='23514';
    END IF;
    IF NEW.cloud_enabled AND NOT NEW.non_billable_gateway
       AND NEW.input_price_per_million=0 AND NEW.output_price_per_million=0 AND NEW.reserved_per_call=0 THEN
        RAISE EXCEPTION 'enabled AI configuration needs prices or an explicit non-billable gateway' USING ERRCODE='23514';
    END IF;
    IF NEW.cloud_enabled AND NEW.outbound_scope='selected_regions' AND NEW.reserved_per_call<=0 THEN
        RAISE EXCEPTION 'image-enabled AI configuration needs a positive per-call reserve' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END $$;

CREATE FUNCTION swb_guard_ai_modelrun() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    source_id text;
    q_id text;
    reg_id text;
    row_kind text;
    row_head text;
    row_published text;
    row_state text;
    row_payload jsonb;
    attempt_household text;
    attempt_kind text;
    attempt_head text;
    attempt_state text;
    attempt_payload jsonb;
    config_household text;
    config_enabled boolean;
    config_scope text;
    source_count integer;
    question_count integer;
    region_count integer;
    valid_count integer;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'AI model runs are retained' USING ERRCODE='23514';
    ELSIF TG_OP = 'INSERT' THEN
        PERFORM id FROM swb_household WHERE id=NEW.household_id FOR UPDATE;
        IF NOT EXISTS (
            SELECT 1 FROM swb_householdmember m JOIN auth_user u ON u.id=m.user_id
            WHERE m.household_id=NEW.household_id AND m.user_id=NEW.actor_id
              AND m.role IN ('owner','reviewer') AND u.is_active
        ) THEN
            RAISE EXCEPTION 'AI model run actor is not an active writable household member' USING ERRCODE='23514';
        END IF;
        SELECT household_id,cloud_enabled,outbound_scope INTO config_household,config_enabled,config_scope
            FROM ai_modelconfig WHERE id=NEW.config_id;
        IF config_household IS DISTINCT FROM NEW.household_id OR config_enabled IS DISTINCT FROM TRUE
           OR NEW.config_id IS DISTINCT FROM (
               SELECT id FROM ai_modelconfig WHERE household_id=NEW.household_id ORDER BY revision_no DESC LIMIT 1
           ) THEN
            RAISE EXCEPTION 'AI model run must pin the current enabled same-household configuration' USING ERRCODE='23514';
        END IF;
        IF jsonb_typeof(NEW.config_snapshot) IS DISTINCT FROM 'object'
           OR NEW.config_snapshot ?| ARRAY['api_key','key','secret','token','authorization'] THEN
            RAISE EXCEPTION 'AI model run configuration snapshot is invalid or contains a secret' USING ERRCODE='23514';
        END IF;
        IF jsonb_typeof(NEW.source_revision_ids) IS DISTINCT FROM 'array'
           OR jsonb_typeof(NEW.question_revision_ids) IS DISTINCT FROM 'array'
           OR jsonb_typeof(NEW.selected_region_revision_ids) IS DISTINCT FROM 'array' THEN
            RAISE EXCEPTION 'AI model run inputs must be arrays' USING ERRCODE='23514';
        END IF;
        source_count := jsonb_array_length(NEW.source_revision_ids);
        question_count := jsonb_array_length(NEW.question_revision_ids);
        region_count := jsonb_array_length(NEW.selected_region_revision_ids);
        IF source_count < 1 OR source_count > 10 OR question_count > 10 OR region_count > 20
           OR NEW.status <> 'queued' OR NEW.response IS NOT NULL OR NEW.started_at IS NOT NULL
           OR NEW.reserved_cost <> 0 THEN
            RAISE EXCEPTION 'AI model run has invalid initial state or input count' USING ERRCODE='23514';
        END IF;
        SELECT count(DISTINCT value) INTO valid_count
            FROM jsonb_array_elements_text(NEW.source_revision_ids) AS values(value);
        IF valid_count <> source_count THEN
            RAISE EXCEPTION 'AI model run source revisions must be unique' USING ERRCODE='23514';
        END IF;
        SELECT count(DISTINCT value) INTO valid_count
            FROM jsonb_array_elements_text(NEW.question_revision_ids) AS values(value);
        IF valid_count <> question_count THEN
            RAISE EXCEPTION 'AI model run question revisions must be unique' USING ERRCODE='23514';
        END IF;
        SELECT count(DISTINCT value) INTO valid_count
            FROM jsonb_array_elements_text(NEW.selected_region_revision_ids) AS values(value);
        IF valid_count <> region_count THEN
            RAISE EXCEPTION 'AI model run image regions must be unique' USING ERRCODE='23514';
        END IF;
        FOR source_id IN SELECT value FROM jsonb_array_elements_text(NEW.source_revision_ids) AS values(value) LOOP
            SELECT e.kind,e.head_revision_id,e.published_revision_id,p.state,r.payload
                INTO row_kind,row_head,row_published,row_state,row_payload
                FROM swb_revisionrecord r JOIN swb_entityrecord e ON e.id=r.entity_id
                JOIN swb_reviewprojection p ON p.revision_id=r.revision_id
                WHERE r.revision_id=source_id AND e.household_id=NEW.household_id;
            IF row_kind IS NULL OR row_head IS DISTINCT FROM source_id OR
               NOT (
                   COALESCE(row_published=source_id AND row_state='accepted',FALSE) OR
                   (NEW.task_kind='question' AND row_kind='question' AND row_state='draft'
                    AND (row_payload->>'printed_text' IS NULL OR row_payload->>'printed_text'=''))
               ) THEN
                RAISE EXCEPTION 'AI model source must be a current published revision or permitted blank question draft' USING ERRCODE='23514';
            END IF;
            IF row_kind NOT IN ('question','knowledge','method') THEN
                RAISE EXCEPTION 'AI model source kind is not allowed' USING ERRCODE='23514';
            END IF;
        END LOOP;
        FOR q_id IN SELECT value FROM jsonb_array_elements_text(NEW.question_revision_ids) AS values(value) LOOP
            SELECT e.kind,e.head_revision_id,e.published_revision_id,p.state,r.payload
                INTO row_kind,row_head,row_published,row_state,row_payload
                FROM swb_revisionrecord r JOIN swb_entityrecord e ON e.id=r.entity_id
                JOIN swb_reviewprojection p ON p.revision_id=r.revision_id
                WHERE r.revision_id=q_id AND e.household_id=NEW.household_id;
            IF row_kind IS DISTINCT FROM 'question' OR row_head IS DISTINCT FROM q_id OR NOT (
                COALESCE(row_published=q_id AND row_state='accepted',FALSE) OR
                (NEW.task_kind='question' AND row_state='draft'
                    AND (row_payload->>'printed_text' IS NULL OR row_payload->>'printed_text'=''))
            ) THEN
                RAISE EXCEPTION 'AI task question must be a current exact accepted revision (or blank OCR draft)' USING ERRCODE='23514';
            END IF;
        END LOOP;
        IF NEW.task_kind IN ('question','assessment') AND
           (question_count <> 1 OR source_count <> 1 OR NEW.source_revision_ids->>0 IS DISTINCT FROM NEW.question_revision_ids->>0) THEN
            RAISE EXCEPTION 'AI task must pin its single question as its sole text source' USING ERRCODE='23514';
        END IF;
        IF NEW.task_kind='knowledge' THEN
            IF question_count < 1 OR source_count <> question_count THEN
                RAISE EXCEPTION 'AI knowledge task must use its selected questions as its only sources' USING ERRCODE='23514';
            END IF;
            FOR q_id IN SELECT value FROM jsonb_array_elements_text(NEW.question_revision_ids) AS values(value) LOOP
                IF NOT NEW.source_revision_ids ? q_id THEN
                    RAISE EXCEPTION 'AI knowledge sources must match its selected questions' USING ERRCODE='23514';
                END IF;
            END LOOP;
        END IF;
        IF NEW.task_kind='variant' THEN
            IF question_count <> 1 OR source_count <> 1 OR NOT EXISTS (
                SELECT 1 FROM swb_revisionrecord r JOIN swb_entityrecord e ON e.id=r.entity_id
                WHERE r.revision_id=NEW.source_revision_ids->>0 AND e.kind='method'
                  AND e.household_id=NEW.household_id AND e.head_revision_id=r.revision_id
                  AND e.published_revision_id=r.revision_id
            ) THEN
                RAISE EXCEPTION 'AI variant task needs one exact question and one exact method' USING ERRCODE='23514';
            END IF;
        END IF;
        IF NEW.task_kind='assessment' THEN
            IF NEW.attempt_revision_id IS NULL THEN
                RAISE EXCEPTION 'AI assessment task needs one active attempt' USING ERRCODE='23514';
            END IF;
            SELECT e.household_id,e.kind,e.head_revision_id,r.payload->>'state',r.payload
                INTO attempt_household,attempt_kind,attempt_head,attempt_state,attempt_payload
                FROM swb_revisionrecord r JOIN swb_entityrecord e ON e.id=r.entity_id
                WHERE r.revision_id=NEW.attempt_revision_id;
            IF attempt_household IS DISTINCT FROM NEW.household_id OR attempt_kind IS DISTINCT FROM 'attempt'
               OR attempt_head IS DISTINCT FROM NEW.attempt_revision_id OR attempt_state IS DISTINCT FROM 'active'
               OR attempt_payload->>'question_revision_id' IS DISTINCT FROM NEW.question_revision_ids->>0 THEN
                RAISE EXCEPTION 'AI assessment attempt must be current, active, and fixed to the selected question' USING ERRCODE='23514';
            END IF;
        ELSIF NEW.attempt_revision_id IS NOT NULL OR NEW.include_attempt_text THEN
            RAISE EXCEPTION 'only assessment tasks may include an attempt' USING ERRCODE='23514';
        END IF;
        IF region_count > 0 AND config_scope IS DISTINCT FROM 'selected_regions' THEN
            RAISE EXCEPTION 'AI model configuration does not permit image regions' USING ERRCODE='23514';
        END IF;
        IF NEW.task_kind='question' AND EXISTS (
            SELECT 1 FROM swb_reviewprojection p WHERE p.revision_id=NEW.question_revision_ids->>0 AND p.state='draft'
        ) AND region_count=0 THEN
            RAISE EXCEPTION 'blank OCR question draft requires an explicitly selected image region' USING ERRCODE='23514';
        END IF;
        FOR reg_id IN SELECT value FROM jsonb_array_elements_text(NEW.selected_region_revision_ids) AS values(value) LOOP
            SELECT e.kind,e.head_revision_id INTO row_kind,row_head
                FROM swb_revisionrecord r JOIN swb_entityrecord e ON e.id=r.entity_id
                WHERE r.revision_id=reg_id AND e.household_id=NEW.household_id;
            IF row_kind IS DISTINCT FROM 'region' OR row_head IS DISTINCT FROM reg_id THEN
                RAISE EXCEPTION 'AI model region must be a current same-household exact revision' USING ERRCODE='23514';
            END IF;
            IF NEW.task_kind='assessment' THEN
                IF NOT EXISTS (
                    SELECT 1 FROM swb_revisiondependency d JOIN swb_evidencerecord ev ON ev.source_id=d.target_id
                    WHERE d.source_id=NEW.attempt_revision_id AND d.role='attempt_observation'
                      AND ev.region_id=reg_id AND ev.purpose IN ('handwriting','formula','diagram')
                ) THEN
                    RAISE EXCEPTION 'AI assessment region is not selected attempt evidence' USING ERRCODE='23514';
                END IF;
            ELSIF NOT EXISTS (
                SELECT 1 FROM swb_evidencerecord ev
                WHERE ev.region_id=reg_id AND (
                    EXISTS (SELECT 1 FROM jsonb_array_elements_text(NEW.source_revision_ids) AS s(value)
                        WHERE s.value=ev.source_id) OR
                    EXISTS (SELECT 1 FROM jsonb_array_elements_text(NEW.question_revision_ids) AS q(value)
                        WHERE q.value=ev.source_id)
                )
            ) THEN
                RAISE EXCEPTION 'AI model region is not evidence for a selected source' USING ERRCODE='23514';
            END IF;
        END LOOP;
        RETURN NEW;
    END IF;

    IF ROW(NEW.household_id,NEW.actor_id,NEW.config_id,NEW.config_snapshot,NEW.task_kind,
           NEW.question_revision_ids,NEW.attempt_revision_id,NEW.source_revision_ids,
           NEW.selected_region_revision_ids,NEW.include_attempt_text,NEW.expected_heads,
           NEW.expected_dependencies,NEW.review_pointers,NEW.prompt_version,NEW.schema_version,
           NEW.request_key,NEW.fingerprint,NEW.created_at)
       IS DISTINCT FROM ROW(OLD.household_id,OLD.actor_id,OLD.config_id,OLD.config_snapshot,OLD.task_kind,
           OLD.question_revision_ids,OLD.attempt_revision_id,OLD.source_revision_ids,
           OLD.selected_region_revision_ids,OLD.include_attempt_text,OLD.expected_heads,
           OLD.expected_dependencies,OLD.review_pointers,OLD.prompt_version,OLD.schema_version,
           OLD.request_key,OLD.fingerprint,OLD.created_at) THEN
        RAISE EXCEPTION 'AI model run identity and selected inputs are immutable' USING ERRCODE='23514';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
        (OLD.status='queued' AND NEW.status IN ('running','failed','cancelled','stale')) OR
        (OLD.status='running' AND NEW.status IN ('awaiting_review','failed','cancelled','stale')) OR
        (OLD.status='awaiting_review' AND NEW.status IN ('applied','cancelled','stale'))
    ) THEN
        RAISE EXCEPTION 'invalid AI model run status transition' USING ERRCODE='23514';
    END IF;
    IF NEW.execution_requested_at IS DISTINCT FROM OLD.execution_requested_at AND NOT (
        OLD.status='queued' AND NEW.status='queued' AND OLD.execution_requested_at IS NULL
        AND NEW.execution_requested_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'AI execution request can only be recorded once while queued' USING ERRCODE='23514';
    END IF;
    IF NEW.status='running' AND (NEW.started_at IS NULL OR NEW.call_started_at IS NULL OR NEW.lease_expires_at IS NULL) THEN
        RAISE EXCEPTION 'running AI task requires a worker lease' USING ERRCODE='23514';
    END IF;
    IF NEW.status IN ('awaiting_review','failed','cancelled','stale','applied') AND NEW.completed_at IS NULL THEN
        RAISE EXCEPTION 'completed AI task requires a completion timestamp' USING ERRCODE='23514';
    END IF;
    IF NEW.status='applied' AND jsonb_array_length(NEW.output_revision_ids)=0 THEN
        RAISE EXCEPTION 'applied AI task requires output revisions' USING ERRCODE='23514';
    END IF;
    IF NEW.reserved_cost < 0 OR (NEW.estimated_cost IS NOT NULL AND NEW.estimated_cost < 0) THEN
        RAISE EXCEPTION 'AI task cost cannot be negative' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END $$;

CREATE FUNCTION swb_guard_ai_budgetreservation() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE run_household text; run_config uuid; run_status text; run_reserve numeric;
BEGIN
    IF TG_OP='DELETE' THEN
        RAISE EXCEPTION 'AI budget reservations are retained' USING ERRCODE='23514';
    ELSIF TG_OP='INSERT' THEN
        SELECT household_id,config_id,status,reserved_cost INTO run_household,run_config,run_status,run_reserve
            FROM ai_modelrun WHERE id=NEW.run_id FOR UPDATE;
        IF run_household IS NULL OR run_config IS DISTINCT FROM NEW.config_id OR run_status IS DISTINCT FROM 'running'
           OR NEW.reserved_calls <> 1 OR NEW.actual_calls <> 0 OR NEW.state <> 'held'
           OR NEW.reserved_cost IS DISTINCT FROM run_reserve THEN
            RAISE EXCEPTION 'AI budget reservation does not match an active worker claim' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END IF;
    IF ROW(NEW.run_id,NEW.config_id,NEW.reserved_calls,NEW.reserved_cost,NEW.created_at)
       IS DISTINCT FROM ROW(OLD.run_id,OLD.config_id,OLD.reserved_calls,OLD.reserved_cost,OLD.created_at) THEN
        RAISE EXCEPTION 'AI budget reservation identity is immutable' USING ERRCODE='23514';
    END IF;
    IF NEW.state IS DISTINCT FROM OLD.state AND NOT (
        (OLD.state='held' AND NEW.state IN ('settled','unknown','released')) OR
        (OLD.state='unknown' AND NEW.state='settled')
    ) THEN
        RAISE EXCEPTION 'invalid AI budget reservation transition' USING ERRCODE='23514';
    END IF;
    IF NEW.actual_calls > NEW.reserved_calls OR NEW.actual_cost < 0 OR NEW.reserved_cost < 0 THEN
        RAISE EXCEPTION 'invalid AI budget reservation usage' USING ERRCODE='23514';
    END IF;
    IF NEW.state='settled' AND (NEW.actual_calls <> 1 OR NEW.settled_at IS NULL) THEN
        RAISE EXCEPTION 'settled AI budget reservation needs one recorded call' USING ERRCODE='23514';
    END IF;
    IF NEW.state IN ('unknown','released') AND NEW.settled_at IS NULL THEN
        RAISE EXCEPTION 'closed AI budget reservation needs a settlement timestamp' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER swb_ai_modelconfig_insert BEFORE INSERT OR UPDATE OR DELETE ON ai_modelconfig
    FOR EACH ROW EXECUTE FUNCTION swb_guard_ai_modelconfig();
CREATE TRIGGER swb_ai_modelrun_guard BEFORE INSERT OR UPDATE OR DELETE ON ai_modelrun
    FOR EACH ROW EXECUTE FUNCTION swb_guard_ai_modelrun();
CREATE TRIGGER swb_ai_budgetreservation_guard BEFORE INSERT OR UPDATE OR DELETE ON ai_budgetreservation
    FOR EACH ROW EXECUTE FUNCTION swb_guard_ai_budgetreservation();
"""

REVERSE = r"""
DROP TRIGGER swb_ai_budgetreservation_guard ON ai_budgetreservation;
DROP TRIGGER swb_ai_modelrun_guard ON ai_modelrun;
DROP TRIGGER swb_ai_modelconfig_insert ON ai_modelconfig;
DROP FUNCTION swb_guard_ai_budgetreservation();
DROP FUNCTION swb_guard_ai_modelrun();
DROP FUNCTION swb_guard_ai_modelconfig();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("ai", "0002_modelrun_execution_requested_at"),
        ("persistence", "0004_business_receipts"),
    ]

    operations = [migrations.RunSQL(SQL, REVERSE)]
