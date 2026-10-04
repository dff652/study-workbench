from django.db import migrations


IMMUTABLE = ("solutionrevision", "solutionconfirmation", "solutionasset", "solutionoutputevent")
SQL = """
CREATE FUNCTION swb_solution_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Solution content and evidence history are immutable'; END $$;
""" + "\n".join(
    f"CREATE TRIGGER swb_{table}_guard BEFORE UPDATE OR DELETE ON solutions_{table} "
    "FOR EACH ROW EXECUTE FUNCTION swb_solution_history_guard();" for table in IMMUTABLE
) + """
CREATE FUNCTION swb_solution_output_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Solution output history cannot be deleted'; END IF;
  IF NEW.revision_id IS DISTINCT FROM OLD.revision_id OR
     NEW.requested_by_id IS DISTINCT FROM OLD.requested_by_id OR
     NEW.request_key IS DISTINCT FROM OLD.request_key OR
     NEW.fingerprint IS DISTINCT FROM OLD.fingerprint OR
     NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Solution output inputs are immutable';
  END IF;
  IF NEW.version != OLD.version + 1 THEN RAISE EXCEPTION 'Solution output version must advance'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER swb_solution_output_guard BEFORE UPDATE OR DELETE ON solutions_solutionoutput
FOR EACH ROW EXECUTE FUNCTION swb_solution_output_guard();
"""
REVERSE = """
DROP TRIGGER swb_solution_output_guard ON solutions_solutionoutput;
DROP FUNCTION swb_solution_output_guard();
""" + "\n".join(f"DROP TRIGGER swb_{table}_guard ON solutions_{table};" for table in IMMUTABLE) + "\nDROP FUNCTION swb_solution_history_guard();"


class Migration(migrations.Migration):
    dependencies = [("solutions", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
