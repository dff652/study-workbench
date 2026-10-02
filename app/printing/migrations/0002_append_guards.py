from django.db import migrations


SQL = """
CREATE FUNCTION swb_guard_teacher_answer() RETURNS trigger AS $$
DECLARE latest bigint; latest_no integer; q_house text; q_kind text;
BEGIN
    PERFORM id FROM swb_household WHERE id=NEW.household_id FOR UPDATE;
    SELECT e.household_id,e.kind INTO q_house,q_kind FROM swb_revisionrecord r
        JOIN swb_entityrecord e ON e.id=r.entity_id WHERE r.revision_id=NEW.question_revision_id;
    IF q_house IS DISTINCT FROM NEW.household_id OR q_kind IS DISTINCT FROM 'question' THEN
        RAISE EXCEPTION 'answer requires same-household question revision' USING ERRCODE='23514';
    END IF;
    SELECT id,revision_no INTO latest,latest_no FROM printing_teacheranswerrevision
        WHERE question_revision_id=NEW.question_revision_id ORDER BY revision_no DESC LIMIT 1;
    IF NEW.previous_id IS DISTINCT FROM latest OR NEW.revision_no IS DISTINCT FROM COALESCE(latest_no,0)+1 THEN
        RAISE EXCEPTION 'answer must append the current version' USING ERRCODE='23514';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM swb_householdmember m JOIN auth_user u ON u.id=m.user_id
        WHERE m.household_id=NEW.household_id AND m.user_id=NEW.created_by_id
        AND m.role IN ('owner','reviewer') AND u.is_active) THEN
        RAISE EXCEPTION 'answer author is not authorized' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE FUNCTION swb_guard_answer_decision() RETURNS trigger AS $$
DECLARE hid text; latest bigint;
BEGIN
    SELECT household_id INTO hid FROM printing_teacheranswerrevision WHERE id=NEW.answer_id;
    PERFORM id FROM swb_household WHERE id=hid FOR UPDATE;
    SELECT id INTO latest FROM printing_answerdecision WHERE answer_id=NEW.answer_id ORDER BY id DESC LIMIT 1;
    IF NEW.previous_id IS DISTINCT FROM latest OR NOT EXISTS
        (SELECT 1 FROM swb_householdmember m JOIN auth_user u ON u.id=m.user_id
         WHERE m.household_id=hid AND m.user_id=NEW.actor_id AND m.role IN ('owner','reviewer') AND u.is_active) THEN
        RAISE EXCEPTION 'answer review must append with an authorized actor' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER swb_answer_insert BEFORE INSERT ON printing_teacheranswerrevision
    FOR EACH ROW EXECUTE FUNCTION swb_guard_teacher_answer();
CREATE TRIGGER swb_answer_review_insert BEFORE INSERT ON printing_answerdecision
    FOR EACH ROW EXECUTE FUNCTION swb_guard_answer_decision();
CREATE TRIGGER swb_answer_immutable BEFORE UPDATE OR DELETE ON printing_teacheranswerrevision
    FOR EACH ROW EXECUTE FUNCTION swb_reject_immutable_change();
CREATE TRIGGER swb_answer_review_immutable BEFORE UPDATE OR DELETE ON printing_answerdecision
    FOR EACH ROW EXECUTE FUNCTION swb_reject_immutable_change();
CREATE TRIGGER swb_print_immutable BEFORE UPDATE OR DELETE ON printing_exportsnapshot
    FOR EACH ROW EXECUTE FUNCTION swb_reject_immutable_change();
"""
REVERSE = """
DROP TRIGGER swb_print_immutable ON printing_exportsnapshot;
DROP TRIGGER swb_answer_review_immutable ON printing_answerdecision;
DROP TRIGGER swb_answer_immutable ON printing_teacheranswerrevision;
DROP TRIGGER swb_answer_review_insert ON printing_answerdecision;
DROP TRIGGER swb_answer_insert ON printing_teacheranswerrevision;
DROP FUNCTION swb_guard_answer_decision();
DROP FUNCTION swb_guard_teacher_answer();
"""


class Migration(migrations.Migration):
    dependencies=[('printing','0001_initial'),('persistence','0002_postgresql_guards')]
    operations=[migrations.RunSQL(SQL,REVERSE)]
