import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


SQL = """
CREATE FUNCTION swb_guard_teaching_diagram() RETURNS trigger AS $$
DECLARE latest bigint; latest_no integer; q_house text; q_kind text;
BEGIN
    PERFORM id FROM swb_household WHERE id=NEW.household_id FOR UPDATE;
    SELECT e.household_id,e.kind INTO q_house,q_kind FROM swb_revisionrecord r
        JOIN swb_entityrecord e ON e.id=r.entity_id WHERE r.revision_id=NEW.question_revision_id;
    IF q_house IS DISTINCT FROM NEW.household_id OR q_kind IS DISTINCT FROM 'question' THEN
        RAISE EXCEPTION 'diagram requires same-household question revision' USING ERRCODE='23514';
    END IF;
    SELECT id,revision_no INTO latest,latest_no FROM printing_teachingdiagramrevision
        WHERE question_revision_id=NEW.question_revision_id AND placement=NEW.placement ORDER BY revision_no DESC LIMIT 1;
    IF NEW.previous_id IS DISTINCT FROM latest OR NEW.revision_no IS DISTINCT FROM COALESCE(latest_no,0)+1 THEN
        RAISE EXCEPTION 'diagram must append the current placement version' USING ERRCODE='23514';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM swb_householdmember m JOIN auth_user u ON u.id=m.user_id
        WHERE m.household_id=NEW.household_id AND m.user_id=NEW.created_by_id
        AND m.role IN ('owner','reviewer') AND u.is_active) THEN
        RAISE EXCEPTION 'diagram author is not authorized' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER swb_diagram_insert BEFORE INSERT ON printing_teachingdiagramrevision
    FOR EACH ROW EXECUTE FUNCTION swb_guard_teaching_diagram();
CREATE TRIGGER swb_diagram_immutable BEFORE UPDATE OR DELETE ON printing_teachingdiagramrevision
    FOR EACH ROW EXECUTE FUNCTION swb_reject_immutable_change();
"""
REVERSE = """
DROP TRIGGER swb_diagram_immutable ON printing_teachingdiagramrevision;
DROP TRIGGER swb_diagram_insert ON printing_teachingdiagramrevision;
DROP FUNCTION swb_guard_teaching_diagram();
"""


class Migration(migrations.Migration):
    dependencies = [('printing', '0002_append_guards'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name='TeachingDiagramRevision', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('placement', models.CharField(choices=[('question', '题面图'), ('answer', '解析图')], max_length=16)),
            ('revision_no', models.PositiveIntegerField()), ('content', models.JSONField()), ('basis', models.TextField()),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ('household', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='persistence.household')),
            ('previous', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, to='printing.teachingdiagramrevision')),
            ('question_revision', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='persistence.revisionrecord')),
        ], options={'constraints': [
            models.UniqueConstraint(fields=('question_revision', 'placement', 'revision_no'), name='swb_diagram_version'),
            models.CheckConstraint(condition=models.Q(revision_no__gt=0), name='swb_diagram_positive'),
            models.CheckConstraint(condition=models.Q(placement__in=('question', 'answer')), name='swb_diagram_placement'),
        ]}),
        migrations.RunSQL(SQL, REVERSE),
    ]
