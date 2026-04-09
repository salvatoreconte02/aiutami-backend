"""
Step 2 del refactor task-pluggable.

Session.context passa da enum (SessionContext.MURDER_MYSTERY = "MURDER_MYSTERY")
a CharField libero validato contro apps.tasks.registry. Le righe esistenti con
valore "MURDER_MYSTERY" (uppercase) vengono rinominate a "murder_mystery"
(lowercase) per allinearsi alla chiave del registry.

Vedi docs/plans/2026-04-08-task-pluggable-architecture.md §5 Step 2.
"""

from django.db import migrations, models


def forwards_rename_context(apps, schema_editor):
    Session = apps.get_model("ai_sessions", "Session")
    Session.objects.filter(context="MURDER_MYSTERY").update(context="murder_mystery")


def backwards_rename_context(apps, schema_editor):
    Session = apps.get_model("ai_sessions", "Session")
    Session.objects.filter(context="murder_mystery").update(context="MURDER_MYSTERY")


class Migration(migrations.Migration):

    dependencies = [
        ("ai_sessions", "0005_session_report_text_sessionvote"),
    ]

    operations = [
        migrations.AlterField(
            model_name="session",
            name="context",
            field=models.CharField(max_length=64),
        ),
        migrations.RunPython(forwards_rename_context, backwards_rename_context),
    ]
