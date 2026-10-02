from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0003_ai_guards"),
    ]

    operations = [
        migrations.AlterField(
            model_name="modelbudgetreservation",
            name="state",
            field=models.CharField(choices=[("held", "已预留"), ("settled", "已结算"),
                ("unknown", "结果未知"), ("released", "已释放")], default="held", max_length=12),
        ),
        migrations.AlterField(
            model_name="modelconfig",
            name="outbound_scope",
            field=models.CharField(choices=[("reviewed_text", "仅外发已选的已发布文字"),
                ("selected_regions", "已选文字及主动选择的图像区域")], default="reviewed_text", max_length=24),
        ),
        migrations.AlterField(
            model_name="modelrun",
            name="status",
            field=models.CharField(choices=[("queued", "排队中"), ("running", "运行中"),
                ("awaiting_review", "待人工复核"), ("failed", "失败"), ("cancelled", "已取消"),
                ("stale", "已过期"), ("applied", "已应用")], default="queued", max_length=20),
        ),
        migrations.AlterField(
            model_name="modelrun",
            name="task_kind",
            field=models.CharField(choices=[("question", "题干识别草稿"), ("knowledge", "知识草稿"),
                ("assessment", "作答评价草稿"), ("variant", "变式题草稿")], max_length=16),
        ),
    ]
