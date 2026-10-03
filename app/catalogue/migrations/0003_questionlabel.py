from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


SQL = """
CREATE FUNCTION swb_guard_question_label() RETURNS trigger AS $$
DECLARE hid text; question_kind text; question_head text; review_state text;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'derived question labels are append-only' USING ERRCODE='23514';
    END IF;
    SELECT e.household_id INTO hid FROM swb_revisionrecord r
        JOIN swb_entityrecord e ON e.id=r.entity_id WHERE r.revision_id=NEW.revision_id;
    PERFORM id FROM swb_household WHERE id=hid FOR UPDATE;
    SELECT e.household_id,e.kind,e.head_revision_id,rp.state
        INTO hid,question_kind,question_head,review_state
        FROM swb_revisionrecord r JOIN swb_entityrecord e ON e.id=r.entity_id
        JOIN swb_reviewprojection rp ON rp.revision_id=r.revision_id
        WHERE r.revision_id=NEW.revision_id;
    IF question_kind IS DISTINCT FROM 'question'
        OR question_head IS DISTINCT FROM NEW.revision_id
        OR review_state IS DISTINCT FROM 'draft'
        OR btrim(NEW.original_number)='' THEN
        RAISE EXCEPTION 'derived label requires a numbered draft question head' USING ERRCODE='23514';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM swb_householdmember m JOIN auth_user u ON u.id=m.user_id
        WHERE m.household_id=hid AND m.user_id=NEW.created_by_id
        AND m.role IN ('owner','reviewer') AND u.is_active) THEN
        RAISE EXCEPTION 'derived label actor is not an active household writer' USING ERRCODE='23514';
    END IF;
    IF EXISTS (SELECT 1 FROM workbench_web_questionsource
        WHERE revision_id=NEW.revision_id AND original_number IS DISTINCT FROM NEW.original_number) THEN
        RAISE EXCEPTION 'derived label differs from its source number' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER swb_question_label_guard BEFORE INSERT OR UPDATE OR DELETE
    ON catalogue_questionlabel FOR EACH ROW EXECUTE FUNCTION swb_guard_question_label();
"""

REVERSE = """
DROP TRIGGER swb_question_label_guard ON catalogue_questionlabel;
DROP FUNCTION swb_guard_question_label();
"""


class Migration(migrations.Migration):
    dependencies = [
        ('catalogue', '0002_lineage_guards'),
        ('workbench_web', '0002_source_guards'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name='QuestionLabel',
            fields=[
                ('revision', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,
                    primary_key=True, serialize=False, to='persistence.revisionrecord')),
                ('original_number', models.CharField(max_length=80)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                    to=settings.AUTH_USER_MODEL)),
            ],
            options={'constraints': [models.CheckConstraint(condition=~models.Q(original_number=''),
                name='swb_question_label_number_required')]},
        ),
        migrations.RunSQL(SQL, REVERSE),
    ]
