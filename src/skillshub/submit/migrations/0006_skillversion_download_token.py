import secrets

from django.db import migrations, models


def backfill_tokens(apps, schema_editor):
    """已 published 版本生成 download_token。"""
    SkillVersion = apps.get_model("submit", "SkillVersion")
    for v in SkillVersion.objects.filter(status="published", download_token__isnull=True):
        v.download_token = secrets.token_urlsafe(16)
        v.save(update_fields=["download_token"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("submit", "0005_alter_reviewaction_options_alter_skill_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="skillversion",
            name="download_token",
            field=models.CharField(blank=True, help_text="publish 时生成；URL 防爆破用，企业内不绑 user 不限次", max_length=32, null=True, unique=True),
        ),
        migrations.RunPython(backfill_tokens, noop_reverse),
    ]
