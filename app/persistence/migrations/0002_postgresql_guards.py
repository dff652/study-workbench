from django.conf import settings
from django.db import migrations


def install_guards(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        raise RuntimeError("Study Workbench persistence requires PostgreSQL")

    quote = connection.ops.quote_name
    user_model = apps.get_model(settings.AUTH_USER_MODEL)
    active_column = user_model._meta.get_field("is_active").column
    user_table = quote(user_model._meta.db_table)
    user_pk = quote(user_model._meta.pk.column)
    membership_user_column = quote(apps.get_model("persistence", "HouseholdMember")._meta.get_field("user").column)
    actor_active_join = f"""JOIN {user_table} AS u ON u.{user_pk} = m.{membership_user_column}
            WHERE m.household_id = NEW.household_id
              AND m.{membership_user_column} = NEW.actor_id
              AND m.role IN ('owner', 'reviewer')
              AND u.{quote(active_column)} IS TRUE"""

    statements = [
        """
        CREATE FUNCTION swb_reject_immutable_change() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'append-only row in % cannot be updated or deleted', TG_TABLE_NAME
                USING ERRCODE = '23514';
        END;
        $$ LANGUAGE plpgsql
        """,
        """
        CREATE FUNCTION swb_reject_entity_delete() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'entity identities are append-only' USING ERRCODE = '23514';
        END;
        $$ LANGUAGE plpgsql
        """,
        """
        CREATE FUNCTION swb_guard_image_record() RETURNS trigger AS $$
        BEGIN
            PERFORM id FROM swb_household WHERE id = NEW.household_id FOR UPDATE;
            IF NOT FOUND OR jsonb_typeof(NEW.payload) IS DISTINCT FROM 'object' THEN
                RAISE EXCEPTION 'image requires a household and JSON object payload' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """,
        """
        CREATE FUNCTION swb_guard_entity_record() RETURNS trigger AS $$
        DECLARE
            ref_entity_id bigint;
            ref_revision_no integer;
            latest_revision_no integer;
            projection_state text;
        BEGIN
            PERFORM id FROM swb_household WHERE id = NEW.household_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'entity household does not exist' USING ERRCODE = '23503';
            END IF;
            IF jsonb_typeof(NEW.identity) IS DISTINCT FROM 'object' THEN
                RAISE EXCEPTION 'entity identity must be a JSON object' USING ERRCODE = '23514';
            END IF;

            IF TG_OP = 'UPDATE' AND (
                NEW.id IS DISTINCT FROM OLD.id OR
                NEW.household_id IS DISTINCT FROM OLD.household_id OR
                NEW.kind IS DISTINCT FROM OLD.kind OR
                NEW.stable_id IS DISTINCT FROM OLD.stable_id OR
                NEW.identity IS DISTINCT FROM OLD.identity
            ) THEN
                RAISE EXCEPTION 'entity identity fields are immutable' USING ERRCODE = '23514';
            END IF;

            IF NEW.kind = 'learner' AND (NEW.head_revision_id IS NOT NULL OR NEW.published_revision_id IS NOT NULL) THEN
                RAISE EXCEPTION 'learner entities cannot have revisions' USING ERRCODE = '23514';
            END IF;

            IF NEW.head_revision_id IS NOT NULL THEN
                SELECT entity_id, revision_no INTO ref_entity_id, ref_revision_no
                  FROM swb_revisionrecord WHERE revision_id = NEW.head_revision_id;
                IF ref_entity_id IS DISTINCT FROM NEW.id THEN
                    RAISE EXCEPTION 'head revision must belong to its entity' USING ERRCODE = '23514';
                END IF;
                SELECT max(revision_no) INTO latest_revision_no
                  FROM swb_revisionrecord WHERE entity_id = NEW.id;
                IF ref_revision_no IS DISTINCT FROM latest_revision_no THEN
                    RAISE EXCEPTION 'head revision must be the latest revision' USING ERRCODE = '23514';
                END IF;
            ELSIF TG_OP = 'UPDATE' AND OLD.head_revision_id IS NOT NULL THEN
                RAISE EXCEPTION 'an existing head revision cannot be cleared' USING ERRCODE = '23514';
            END IF;

            IF NEW.published_revision_id IS NOT NULL THEN
                SELECT entity_id INTO ref_entity_id
                  FROM swb_revisionrecord WHERE revision_id = NEW.published_revision_id;
                IF ref_entity_id IS DISTINCT FROM NEW.id THEN
                    RAISE EXCEPTION 'published revision must belong to its entity' USING ERRCODE = '23514';
                END IF;
                SELECT state INTO projection_state FROM swb_reviewprojection
                 WHERE revision_id = NEW.published_revision_id FOR SHARE;
                IF projection_state IS DISTINCT FROM 'accepted' THEN
                    RAISE EXCEPTION 'published revision must have an accepted projection' USING ERRCODE = '23514';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """,
        """
        CREATE FUNCTION swb_guard_revision_record() RETURNS trigger AS $$
        DECLARE
            entity_household_id text;
            entity_stable_id text;
            entity_kind text;
            expected_type text;
            prior_entity_id bigint;
            prior_revision_no integer;
            image_household_id text;
            image_stable_id text;
            dependency_head jsonb;
        BEGIN
            SELECT household_id, stable_id, kind
              INTO entity_household_id, entity_stable_id, entity_kind
              FROM swb_entityrecord WHERE id = NEW.entity_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'revision entity does not exist' USING ERRCODE = '23503';
            END IF;
            PERFORM id FROM swb_household WHERE id = entity_household_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'revision household does not exist' USING ERRCODE = '23503';
            END IF;

            expected_type := CASE entity_kind
                WHEN 'knowledge' THEN 'KnowledgeRevision'
                WHEN 'method' THEN 'MethodRevision'
                WHEN 'question_type' THEN 'QuestionTypeRevision'
                WHEN 'question' THEN 'QuestionRevision'
                WHEN 'observation' THEN 'ObservationRevision'
                WHEN 'attempt' THEN 'AttemptRevision'
                WHEN 'assessment' THEN 'AssessmentRevision'
                WHEN 'erratum' THEN 'ErratumRevision'
                WHEN 'region' THEN 'RegionRevision'
                WHEN 'knowledge_question' THEN 'KnowledgeQuestionLinkRevision'
                WHEN 'method_question' THEN 'MethodQuestionLinkRevision'
                WHEN 'question_type_link' THEN 'QuestionTypeLinkRevision'
                ELSE NULL
            END;
            IF expected_type IS NULL THEN
                RAISE EXCEPTION 'learner entities do not have revisions' USING ERRCODE = '23514';
            END IF;

            IF jsonb_typeof(NEW.payload) IS DISTINCT FROM 'object' OR
               jsonb_typeof(NEW.payload -> 'header') IS DISTINCT FROM 'object' THEN
                RAISE EXCEPTION 'revision payload must contain a typed header object' USING ERRCODE = '23514';
            END IF;
            IF NEW.payload ->> '_type' IS DISTINCT FROM expected_type THEN
                RAISE EXCEPTION 'revision payload type does not match entity kind' USING ERRCODE = '23514';
            END IF;
            IF jsonb_typeof(NEW.payload #> '{header,revision_id}') IS DISTINCT FROM 'string' OR
               NEW.payload #>> '{header,revision_id}' IS DISTINCT FROM NEW.revision_id OR
               jsonb_typeof(NEW.payload #> '{header,owner_id}') IS DISTINCT FROM 'string' OR
               NEW.payload #>> '{header,owner_id}' IS DISTINCT FROM entity_stable_id OR
               jsonb_typeof(NEW.payload #> '{header,revision_no}') IS DISTINCT FROM 'number' OR
               NEW.payload #>> '{header,revision_no}' IS DISTINCT FROM NEW.revision_no::text OR
               jsonb_typeof(NEW.payload #> '{header,content_hash}') IS DISTINCT FROM 'string' OR
               NEW.payload #>> '{header,content_hash}' IS DISTINCT FROM NEW.content_hash OR
               jsonb_typeof(NEW.payload #> '{header,previous_revision_id}') IS NULL THEN
                RAISE EXCEPTION 'revision payload header does not match native columns' USING ERRCODE = '23514';
            END IF;
            IF NEW.previous_id IS NULL THEN
                IF NEW.payload #> '{header,previous_revision_id}' IS DISTINCT FROM 'null'::jsonb THEN
                    RAISE EXCEPTION 'revision payload predecessor does not match native row' USING ERRCODE = '23514';
                END IF;
            ELSIF NEW.payload #>> '{header,previous_revision_id}' IS DISTINCT FROM NEW.previous_id THEN
                RAISE EXCEPTION 'revision payload predecessor does not match native row' USING ERRCODE = '23514';
            END IF;

            IF jsonb_typeof(NEW.dependency_heads) IS DISTINCT FROM 'array' THEN
                RAISE EXCEPTION 'dependency heads must be a JSON array' USING ERRCODE = '23514';
            END IF;
            FOR dependency_head IN SELECT value FROM jsonb_array_elements(NEW.dependency_heads)
            LOOP
                IF jsonb_typeof(dependency_head) IS DISTINCT FROM 'object' OR
                   jsonb_typeof(dependency_head -> 'kind') IS DISTINCT FROM 'string' OR
                   jsonb_typeof(dependency_head -> 'stable_id') IS DISTINCT FROM 'string' OR
                   NOT (dependency_head ? 'head_revision_id') OR
                   jsonb_typeof(dependency_head -> 'head_revision_id') NOT IN ('string', 'null') OR
                   dependency_head ->> 'kind' NOT IN (
                       'knowledge', 'method', 'question_type', 'question', 'observation', 'attempt',
                       'assessment', 'erratum', 'region', 'knowledge_question', 'method_question',
                       'question_type_link', 'learner'
                   ) THEN
                    RAISE EXCEPTION 'dependency head has an invalid shape or kind' USING ERRCODE = '23514';
                END IF;
            END LOOP;

            IF entity_kind = 'region' THEN
                IF NEW.original_image_id IS NULL THEN
                    RAISE EXCEPTION 'region revision requires an original image' USING ERRCODE = '23514';
                END IF;
                SELECT household_id, stable_id INTO image_household_id, image_stable_id
                  FROM swb_imagerecord WHERE id = NEW.original_image_id;
                IF image_household_id IS DISTINCT FROM entity_household_id OR
                   NEW.payload ->> 'household_id' IS DISTINCT FROM entity_household_id OR
                   NEW.payload ->> 'image_id' IS DISTINCT FROM image_stable_id THEN
                    RAISE EXCEPTION 'region image must match its household and typed snapshot' USING ERRCODE = '23514';
                END IF;
            ELSIF NEW.original_image_id IS NOT NULL THEN
                RAISE EXCEPTION 'only region revisions may have an original image' USING ERRCODE = '23514';
            END IF;

            IF NEW.revision_no = 1 THEN
                IF NEW.previous_id IS NOT NULL THEN
                    RAISE EXCEPTION 'first revision cannot have a predecessor' USING ERRCODE = '23514';
                END IF;
            ELSE
                IF NEW.previous_id IS NULL THEN
                    RAISE EXCEPTION 'later revision requires its immediate predecessor' USING ERRCODE = '23514';
                END IF;
                SELECT entity_id, revision_no INTO prior_entity_id, prior_revision_no
                  FROM swb_revisionrecord WHERE revision_id = NEW.previous_id;
                IF prior_entity_id IS DISTINCT FROM NEW.entity_id OR
                   prior_revision_no IS DISTINCT FROM NEW.revision_no - 1 THEN
                    RAISE EXCEPTION 'revision predecessor must be same entity and immediately prior' USING ERRCODE = '23514';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """,
        """
        CREATE FUNCTION swb_guard_revision_dependency() RETURNS trigger AS $$
        DECLARE
            source_kind text;
            target_kind text;
            source_household_id text;
            target_household_id text;
            permitted boolean;
        BEGIN
            SELECT se.kind, se.household_id, te.kind, te.household_id
              INTO source_kind, source_household_id, target_kind, target_household_id
              FROM swb_revisionrecord AS sr
              JOIN swb_entityrecord AS se ON se.id = sr.entity_id
              JOIN swb_revisionrecord AS tr ON tr.revision_id = NEW.target_id
              JOIN swb_entityrecord AS te ON te.id = tr.entity_id
             WHERE sr.revision_id = NEW.source_id;
            IF NOT FOUND OR source_household_id IS DISTINCT FROM target_household_id THEN
                RAISE EXCEPTION 'revision dependency must stay within one household' USING ERRCODE = '23514';
            END IF;
            PERFORM id FROM swb_household WHERE id = source_household_id FOR UPDATE;

            permitted := CASE NEW.role
                WHEN 'parent_question' THEN source_kind = 'question' AND target_kind = 'question'
                WHEN 'parent_method' THEN source_kind = 'method' AND target_kind = 'method'
                WHEN 'question_erratum' THEN source_kind = 'question' AND target_kind = 'erratum'
                WHEN 'attempt_question' THEN source_kind = 'attempt' AND target_kind = 'question'
                WHEN 'attempt_observation' THEN source_kind = 'attempt' AND target_kind = 'observation'
                WHEN 'assessment_attempt' THEN source_kind = 'assessment' AND target_kind = 'attempt'
                WHEN 'assessment_question' THEN source_kind = 'assessment' AND target_kind = 'question'
                WHEN 'assessment_erratum' THEN source_kind = 'assessment' AND target_kind = 'erratum'
                WHEN 'erratum_target' THEN source_kind = 'erratum' AND target_kind IN ('question', 'knowledge', 'method')
                WHEN 'link_question' THEN source_kind IN ('knowledge_question', 'method_question', 'question_type_link') AND target_kind = 'question'
                WHEN 'link_knowledge' THEN source_kind = 'knowledge_question' AND target_kind = 'knowledge'
                WHEN 'link_method' THEN source_kind = 'method_question' AND target_kind = 'method'
                WHEN 'link_question_type' THEN source_kind = 'question_type_link' AND target_kind = 'question_type'
                ELSE false
            END;
            IF NOT permitted THEN
                RAISE EXCEPTION 'revision dependency role is not permitted for its source and target kinds' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """,
        """
        CREATE FUNCTION swb_guard_evidence_record() RETURNS trigger AS $$
        DECLARE
            source_kind text;
            source_household_id text;
            image_household_id text;
            image_width_value jsonb;
            image_height_value jsonb;
            image_width numeric;
            image_height numeric;
            region_household_id text;
            region_image_id bigint;
            region_kind text;
            geometry jsonb;
            x0 numeric;
            y0 numeric;
            x1 numeric;
            y1 numeric;
            gap_value jsonb;
        BEGIN
            SELECT e.kind, e.household_id INTO source_kind, source_household_id
              FROM swb_revisionrecord AS r JOIN swb_entityrecord AS e ON e.id = r.entity_id
             WHERE r.revision_id = NEW.source_id;
            SELECT household_id, payload -> 'width', payload -> 'height'
              INTO image_household_id, image_width_value, image_height_value
              FROM swb_imagerecord WHERE id = NEW.image_id;
            IF source_household_id IS DISTINCT FROM image_household_id THEN
                RAISE EXCEPTION 'evidence image and source must share a household' USING ERRCODE = '23514';
            END IF;
            PERFORM id FROM swb_household WHERE id = source_household_id FOR UPDATE;
            IF jsonb_typeof(NEW.gaps) IS DISTINCT FROM 'array' THEN
                RAISE EXCEPTION 'evidence gaps must be a JSON array' USING ERRCODE = '23514';
            END IF;

            IF NEW.slot = 'source' THEN
                IF source_kind NOT IN ('knowledge', 'method', 'question_type', 'question', 'observation', 'erratum') THEN
                    RAISE EXCEPTION 'source evidence is not allowed for this revision kind' USING ERRCODE = '23514';
                END IF;
            ELSIF source_kind <> 'assessment' THEN
                RAISE EXCEPTION 'assessment evidence slots are only allowed on assessments' USING ERRCODE = '23514';
            END IF;

            IF NEW.granularity = 'whole_image' THEN
                IF NEW.region_id IS NOT NULL OR NEW.region_missing IS NOT TRUE OR
                   NOT (NEW.gaps @> '["region_missing"]'::jsonb) THEN
                    RAISE EXCEPTION 'whole-image evidence must mark its missing region' USING ERRCODE = '23514';
                END IF;
            ELSE
                IF NEW.region_id IS NULL OR NEW.region_missing IS NOT FALSE THEN
                    RAISE EXCEPTION 'region evidence requires a known region' USING ERRCODE = '23514';
                END IF;
                SELECT e.kind, e.household_id, r.original_image_id, r.payload -> 'geometry'
                  INTO region_kind, region_household_id, region_image_id, geometry
                  FROM swb_revisionrecord AS r JOIN swb_entityrecord AS e ON e.id = r.entity_id
                 WHERE r.revision_id = NEW.region_id;
                IF region_kind IS DISTINCT FROM 'region' OR
                   region_household_id IS DISTINCT FROM source_household_id OR
                   region_image_id IS DISTINCT FROM NEW.image_id OR
                   jsonb_typeof(geometry) IS DISTINCT FROM 'array' OR
                   jsonb_array_length(geometry) <> 4 THEN
                    RAISE EXCEPTION 'region evidence must reference a same-household region with known geometry' USING ERRCODE = '23514';
                END IF;

                IF jsonb_typeof(image_width_value) IS DISTINCT FROM 'number' OR
                   jsonb_typeof(image_height_value) IS DISTINCT FROM 'number' OR
                   jsonb_typeof(geometry -> 0) IS DISTINCT FROM 'number' OR
                   jsonb_typeof(geometry -> 1) IS DISTINCT FROM 'number' OR
                   jsonb_typeof(geometry -> 2) IS DISTINCT FROM 'number' OR
                   jsonb_typeof(geometry -> 3) IS DISTINCT FROM 'number' THEN
                    RAISE EXCEPTION 'region evidence geometry requires numeric dimensions and coordinates' USING ERRCODE = '23514';
                END IF;
                x0 := (geometry ->> 0)::numeric;
                y0 := (geometry ->> 1)::numeric;
                x1 := (geometry ->> 2)::numeric;
                y1 := (geometry ->> 3)::numeric;
                image_width := (image_width_value #>> '{}')::numeric;
                image_height := (image_height_value #>> '{}')::numeric;
                IF NOT (0 <= x0 AND x0 < x1 AND x1 <= image_width AND
                        0 <= y0 AND y0 < y1 AND y1 <= image_height) THEN
                    RAISE EXCEPTION 'region evidence geometry is degenerate or outside image bounds' USING ERRCODE = '23514';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """,
        f"""
        CREATE FUNCTION swb_guard_review_decision() RETURNS trigger AS $$
        DECLARE
            revision_entity_id bigint;
            revision_household_id text;
            expected_entity_id bigint;
            actual_head_revision_id varchar(160);
            actual_published_revision_id varchar(160);
            revision_dependency_heads jsonb;
            actual_projection_decision_id uuid;
            expected_decision_revision_id varchar(160);
            dependency_head jsonb;
            expected_dependency_head text;
            actual_dependency_head varchar(160);
            dependency_found boolean;
        BEGIN
            PERFORM id FROM swb_household WHERE id = NEW.household_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'review household does not exist' USING ERRCODE = '23503';
            END IF;
            SELECT e.id, e.household_id, e.head_revision_id, e.published_revision_id, r.dependency_heads
              INTO revision_entity_id, revision_household_id, actual_head_revision_id,
                   actual_published_revision_id, revision_dependency_heads
              FROM swb_revisionrecord AS r JOIN swb_entityrecord AS e ON e.id = r.entity_id
             WHERE r.revision_id = NEW.revision_id;
            SELECT entity_id INTO expected_entity_id
              FROM swb_revisionrecord WHERE revision_id = NEW.expected_head_id;
            IF revision_household_id IS DISTINCT FROM NEW.household_id OR
               expected_entity_id IS DISTINCT FROM revision_entity_id OR
               NEW.expected_head_id IS DISTINCT FROM actual_head_revision_id THEN
                RAISE EXCEPTION 'review target, expected head, and household must agree' USING ERRCODE = '23514';
            END IF;
            SELECT decision_id INTO actual_projection_decision_id
              FROM swb_reviewprojection WHERE revision_id = NEW.revision_id FOR UPDATE;
            IF NOT FOUND OR actual_projection_decision_id IS DISTINCT FROM NEW.expected_decision_id THEN
                RAISE EXCEPTION 'review expected decision must match the current projection decision' USING ERRCODE = '23514';
            END IF;
            IF NEW.expected_decision_id IS NOT NULL THEN
                SELECT revision_id INTO expected_decision_revision_id
                  FROM swb_reviewdecision WHERE id = NEW.expected_decision_id;
                IF expected_decision_revision_id IS DISTINCT FROM NEW.revision_id THEN
                    RAISE EXCEPTION 'expected decision must target the same revision' USING ERRCODE = '23514';
                END IF;
            END IF;
            IF NEW.action IN ('accept', 'reject') AND NEW.revision_id IS DISTINCT FROM actual_head_revision_id THEN
                RAISE EXCEPTION 'accept/reject target must be the current head revision' USING ERRCODE = '23514';
            END IF;
            IF NEW.action = 'withdraw' AND NEW.revision_id IS DISTINCT FROM actual_published_revision_id THEN
                RAISE EXCEPTION 'withdraw target must be the published revision' USING ERRCODE = '23514';
            END IF;
            IF NEW.expected_dependencies IS DISTINCT FROM revision_dependency_heads THEN
                RAISE EXCEPTION 'review dependency vector must match the stored revision vector' USING ERRCODE = '23514';
            END IF;
            IF jsonb_typeof(NEW.expected_dependencies) IS DISTINCT FROM 'array' THEN
                RAISE EXCEPTION 'expected dependencies must be a JSON array' USING ERRCODE = '23514';
            END IF;
            PERFORM m.id FROM swb_householdmember AS m
                {actor_active_join}
            FOR SHARE OF m, u;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'review actor must be an active household owner or reviewer' USING ERRCODE = '23514';
            END IF;
            IF NEW.action = 'accept' THEN
                FOR dependency_head IN SELECT value FROM jsonb_array_elements(NEW.expected_dependencies)
                LOOP
                    IF jsonb_typeof(dependency_head) IS DISTINCT FROM 'object' OR
                       jsonb_typeof(dependency_head -> 'kind') IS DISTINCT FROM 'string' OR
                       jsonb_typeof(dependency_head -> 'stable_id') IS DISTINCT FROM 'string' OR
                       NOT (dependency_head ? 'head_revision_id') OR
                       (jsonb_typeof(dependency_head -> 'head_revision_id') IS DISTINCT FROM 'string' AND
                        jsonb_typeof(dependency_head -> 'head_revision_id') IS DISTINCT FROM 'null') THEN
                        RAISE EXCEPTION 'expected dependency has an invalid shape' USING ERRCODE = '23514';
                    END IF;
                    IF dependency_head -> 'head_revision_id' = 'null'::jsonb THEN
                        expected_dependency_head := NULL;
                    ELSE
                        expected_dependency_head := dependency_head ->> 'head_revision_id';
                    END IF;
                    SELECT head_revision_id INTO actual_dependency_head
                      FROM swb_entityrecord
                     WHERE household_id = NEW.household_id
                       AND kind = dependency_head ->> 'kind'
                       AND stable_id = dependency_head ->> 'stable_id';
                    dependency_found := FOUND;
                    IF NOT dependency_found OR actual_dependency_head IS DISTINCT FROM expected_dependency_head THEN
                        RAISE EXCEPTION 'captured dependency head is missing or stale' USING ERRCODE = '23514';
                    END IF;
                END LOOP;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """,
        f"""
        CREATE FUNCTION swb_guard_request_receipt() RETURNS trigger AS $$
        BEGIN
            PERFORM id FROM swb_household WHERE id = NEW.household_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'receipt household does not exist' USING ERRCODE = '23503';
            END IF;
            PERFORM m.id FROM swb_householdmember AS m
                {actor_active_join}
            FOR SHARE OF m, u;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'receipt actor must be an active household owner or reviewer' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """,
        """
        CREATE FUNCTION swb_guard_review_projection() RETURNS trigger AS $$
        DECLARE
            decision_revision_id varchar(160);
            decision_action text;
            decision_expected_id uuid;
            revision_household_id text;
        BEGIN
            SELECT e.household_id INTO revision_household_id
              FROM swb_revisionrecord AS r JOIN swb_entityrecord AS e ON e.id = r.entity_id
             WHERE r.revision_id = CASE WHEN TG_OP = 'DELETE' THEN OLD.revision_id ELSE NEW.revision_id END;
            PERFORM id FROM swb_household WHERE id = revision_household_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'projection revision household does not exist' USING ERRCODE = '23503';
            END IF;
            IF TG_OP = 'DELETE' THEN
                IF OLD.decision_id IS NOT NULL THEN
                    RAISE EXCEPTION 'audited review projection cannot be deleted' USING ERRCODE = '23514';
                END IF;
                PERFORM id FROM swb_entityrecord
                 WHERE published_revision_id = OLD.revision_id FOR SHARE;
                IF FOUND THEN
                    RAISE EXCEPTION 'published review projection cannot be deleted' USING ERRCODE = '23514';
                END IF;
                RETURN OLD;
            END IF;

            IF TG_OP = 'UPDATE' AND NEW.revision_id IS DISTINCT FROM OLD.revision_id THEN
                RAISE EXCEPTION 'review projection revision identity is immutable' USING ERRCODE = '23514';
            END IF;
            IF NEW.decision_id IS NOT NULL THEN
                SELECT revision_id, action, expected_decision_id
                  INTO decision_revision_id, decision_action, decision_expected_id
                  FROM swb_reviewdecision WHERE id = NEW.decision_id;
                IF decision_revision_id IS DISTINCT FROM NEW.revision_id THEN
                    RAISE EXCEPTION 'projection decision must target its revision' USING ERRCODE = '23514';
                END IF;
                IF (NEW.state = 'accepted' AND decision_action <> 'accept') OR
                   (NEW.state = 'rejected' AND decision_action <> 'reject') OR
                   (NEW.state = 'withdrawn' AND decision_action <> 'withdraw') OR
                   NEW.state NOT IN ('accepted', 'rejected', 'withdrawn') THEN
                    RAISE EXCEPTION 'projection state must match its decision action' USING ERRCODE = '23514';
                END IF;
                IF TG_OP = 'INSERT' AND decision_expected_id IS NOT NULL THEN
                    RAISE EXCEPTION 'first projection decision must have no predecessor' USING ERRCODE = '23514';
                ELSIF TG_OP = 'UPDATE' AND NEW.decision_id IS DISTINCT FROM OLD.decision_id THEN
                    IF OLD.decision_id IS NOT NULL AND NEW.decision_id IS NULL THEN
                        RAISE EXCEPTION 'review projection decision cursor cannot be cleared' USING ERRCODE = '23514';
                    END IF;
                    IF decision_expected_id IS DISTINCT FROM OLD.decision_id THEN
                        RAISE EXCEPTION 'projection decision must extend its current decision' USING ERRCODE = '23514';
                    END IF;
                END IF;
            ELSIF NEW.state IN ('accepted', 'rejected', 'withdrawn') THEN
                RAISE EXCEPTION 'reviewed projection state requires a matching decision' USING ERRCODE = '23514';
            ELSIF TG_OP = 'UPDATE' AND OLD.decision_id IS NOT NULL THEN
                RAISE EXCEPTION 'review projection decision cursor cannot be cleared' USING ERRCODE = '23514';
            END IF;
            IF NEW.state <> 'accepted' THEN
                PERFORM id FROM swb_entityrecord
                 WHERE published_revision_id = NEW.revision_id FOR SHARE;
                IF FOUND THEN
                    RAISE EXCEPTION 'published revision projection must remain accepted' USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """,
    ]
    for statement in statements:
        schema_editor.execute(statement, params=None)

    triggers = [
        ("swb_immutable_image", "swb_imagerecord", "swb_reject_immutable_change", "BEFORE UPDATE OR DELETE"),
        ("swb_immutable_revision", "swb_revisionrecord", "swb_reject_immutable_change", "BEFORE UPDATE OR DELETE"),
        ("swb_immutable_dependency", "swb_revisiondependency", "swb_reject_immutable_change", "BEFORE UPDATE OR DELETE"),
        ("swb_immutable_evidence", "swb_evidencerecord", "swb_reject_immutable_change", "BEFORE UPDATE OR DELETE"),
        ("swb_immutable_decision", "swb_reviewdecision", "swb_reject_immutable_change", "BEFORE UPDATE OR DELETE"),
        ("swb_immutable_receipt", "swb_requestreceipt", "swb_reject_immutable_change", "BEFORE UPDATE OR DELETE"),
        ("swb_entity_scope", "swb_entityrecord", "swb_guard_entity_record", "BEFORE INSERT OR UPDATE"),
        ("swb_entity_no_delete", "swb_entityrecord", "swb_reject_entity_delete", "BEFORE DELETE"),
        ("swb_image_scope", "swb_imagerecord", "swb_guard_image_record", "BEFORE INSERT"),
        ("swb_revision_typed", "swb_revisionrecord", "swb_guard_revision_record", "BEFORE INSERT"),
        ("swb_dependency_typed", "swb_revisiondependency", "swb_guard_revision_dependency", "BEFORE INSERT"),
        ("swb_evidence_typed", "swb_evidencerecord", "swb_guard_evidence_record", "BEFORE INSERT"),
        ("swb_decision_actor", "swb_reviewdecision", "swb_guard_review_decision", "BEFORE INSERT"),
        ("swb_receipt_actor", "swb_requestreceipt", "swb_guard_request_receipt", "BEFORE INSERT"),
        (
            "swb_projection_valid",
            "swb_reviewprojection",
            "swb_guard_review_projection",
            "BEFORE INSERT OR UPDATE OR DELETE",
        ),
    ]
    for trigger_name, table_name, function_name, event in triggers:
        schema_editor.execute(
            f"CREATE TRIGGER {quote(trigger_name)} {event} ON {quote(table_name)} "
            f"FOR EACH ROW EXECUTE FUNCTION {quote(function_name)}()"
        )


def remove_guards(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return
    quote = connection.ops.quote_name
    triggers = [
        ("swb_immutable_image", "swb_imagerecord"),
        ("swb_immutable_revision", "swb_revisionrecord"),
        ("swb_immutable_dependency", "swb_revisiondependency"),
        ("swb_immutable_evidence", "swb_evidencerecord"),
        ("swb_immutable_decision", "swb_reviewdecision"),
        ("swb_immutable_receipt", "swb_requestreceipt"),
        ("swb_entity_scope", "swb_entityrecord"),
        ("swb_entity_no_delete", "swb_entityrecord"),
        ("swb_image_scope", "swb_imagerecord"),
        ("swb_revision_typed", "swb_revisionrecord"),
        ("swb_dependency_typed", "swb_revisiondependency"),
        ("swb_evidence_typed", "swb_evidencerecord"),
        ("swb_decision_actor", "swb_reviewdecision"),
        ("swb_receipt_actor", "swb_requestreceipt"),
        ("swb_projection_valid", "swb_reviewprojection"),
    ]
    for trigger_name, table_name in triggers:
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {quote(trigger_name)} ON {quote(table_name)}")
    for function_name in (
        "swb_guard_review_projection",
        "swb_guard_request_receipt",
        "swb_guard_review_decision",
        "swb_guard_evidence_record",
        "swb_guard_revision_dependency",
        "swb_guard_revision_record",
        "swb_guard_entity_record",
        "swb_guard_image_record",
        "swb_reject_entity_delete",
        "swb_reject_immutable_change",
    ):
        schema_editor.execute(f"DROP FUNCTION IF EXISTS {quote(function_name)}()")


class Migration(migrations.Migration):
    dependencies = [
        ("persistence", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [migrations.RunPython(install_guards, remove_guards)]
