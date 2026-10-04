from django.db import migrations


SQL = """
CREATE FUNCTION swb_workflow_job_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Workflow history cannot be deleted'; END IF;
  IF NEW.material_id IS DISTINCT FROM OLD.material_id OR
     NEW.created_by_id IS DISTINCT FROM OLD.created_by_id OR
     NEW.request_key IS DISTINCT FROM OLD.request_key OR
     NEW.fingerprint IS DISTINCT FROM OLD.fingerprint OR
     NEW.input IS DISTINCT FROM OLD.input OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Workflow input is immutable';
  END IF;
  IF NEW.version != OLD.version + 1 THEN RAISE EXCEPTION 'Workflow version must advance'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER swb_workflow_job_guard BEFORE UPDATE OR DELETE ON workflows_workflowjob
FOR EACH ROW EXECUTE FUNCTION swb_workflow_job_guard();
CREATE FUNCTION swb_workflow_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Workflow audit events are immutable'; END $$;
CREATE TRIGGER swb_workflow_event_guard BEFORE UPDATE OR DELETE ON workflows_workflowevent
FOR EACH ROW EXECUTE FUNCTION swb_workflow_event_guard();
"""
REVERSE = """
DROP TRIGGER swb_workflow_event_guard ON workflows_workflowevent;
DROP FUNCTION swb_workflow_event_guard();
DROP TRIGGER swb_workflow_job_guard ON workflows_workflowjob;
DROP FUNCTION swb_workflow_job_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("workflows", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
