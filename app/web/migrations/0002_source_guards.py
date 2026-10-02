from django.db import migrations

SQL = r'''
CREATE FUNCTION swb_web_source_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_TABLE_NAME IN ('workbench_web_pagepreview','workbench_web_questionsource') AND TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION 'web source evidence is append-only';
  END IF;
  IF TG_TABLE_NAME = 'workbench_web_materialpage' THEN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'source pages cannot be deleted'; END IF;
    IF TG_OP = 'UPDATE' AND (NEW.material_id,NEW.image_id,NEW.original_name,NEW.id) IS DISTINCT FROM (OLD.material_id,OLD.image_id,OLD.original_name,OLD.id) THEN
      RAISE EXCEPTION 'source identity cannot change';
    END IF;
    IF (SELECT household_id FROM workbench_web_materialset WHERE id=NEW.material_id) IS DISTINCT FROM (SELECT household_id FROM swb_imagerecord WHERE id=NEW.image_id) THEN
      RAISE EXCEPTION 'page and image households differ';
    END IF;
  END IF;
  IF TG_TABLE_NAME = 'workbench_web_questionsource' AND TG_OP = 'INSERT' THEN
    IF NOT EXISTS (SELECT 1 FROM swb_revisionrecord r JOIN swb_entityrecord e ON e.id=r.entity_id JOIN workbench_web_materialset m ON m.id=NEW.material_id WHERE r.revision_id=NEW.revision_id AND e.kind='question' AND e.household_id=m.household_id) THEN
      RAISE EXCEPTION 'question source household or kind mismatch';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER swb_web_preview_guard BEFORE INSERT OR UPDATE OR DELETE ON workbench_web_pagepreview FOR EACH ROW EXECUTE FUNCTION swb_web_source_guard();
CREATE TRIGGER swb_web_question_guard BEFORE INSERT OR UPDATE OR DELETE ON workbench_web_questionsource FOR EACH ROW EXECUTE FUNCTION swb_web_source_guard();
CREATE TRIGGER swb_web_page_guard BEFORE INSERT OR UPDATE OR DELETE ON workbench_web_materialpage FOR EACH ROW EXECUTE FUNCTION swb_web_source_guard();
'''
REVERSE = '''DROP TRIGGER swb_web_preview_guard ON workbench_web_pagepreview;
DROP TRIGGER swb_web_question_guard ON workbench_web_questionsource;
DROP TRIGGER swb_web_page_guard ON workbench_web_materialpage;
DROP FUNCTION swb_web_source_guard();'''


class Migration(migrations.Migration):
    dependencies=[('workbench_web','0001_initial')]
    operations=[migrations.RunSQL(SQL,REVERSE)]
