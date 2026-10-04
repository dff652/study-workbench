"""Extend the exact existing source guard for one bounded material draft task."""
from importlib import import_module
from django.db import migrations, models

_original = import_module("app.ai.migrations.0003_ai_guards").SQL
_start = _original.index("CREATE FUNCTION swb_guard_ai_modelrun()")
_end = _original.index("END $$;", _start) + len("END $$;")
OLD = _original[_start:_end].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
NEW = OLD.replace("NEW.task_kind='question'", "NEW.task_kind IN ('question','material')").replace(
    "NEW.task_kind IN ('question','assessment')", "NEW.task_kind IN ('question','material','assessment')")


class Migration(migrations.Migration):
    dependencies = [("ai", "0005_external_processing_consent")]
    operations = [
        migrations.RemoveConstraint(model_name="modelrun", name="ai_modelrun_task_valid"),
        migrations.AddConstraint(model_name="modelrun", constraint=models.CheckConstraint(
            condition=models.Q(task_kind__in=("material", "question", "knowledge", "assessment", "variant")),
            name="ai_modelrun_task_valid")),
        migrations.AlterField(model_name="modelrun", name="task_kind", field=models.CharField(
            choices=[("material", "资料内容草稿"), ("question", "题干识别草稿"), ("knowledge", "知识草稿"),
                     ("assessment", "作答评价草稿"), ("variant", "变式题草稿")], max_length=16)),
        migrations.RunSQL(NEW, OLD),
    ]
