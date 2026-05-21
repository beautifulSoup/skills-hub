"""Add FULLTEXT INDEX on submit_skills(name, description) for catalog search.

T9 D2: mysql 走 FULLTEXT (NATURAL LANGUAGE MODE);
        sqlite vendor 跳过 (TEST_USE_SQLITE 模式仍能跑 migrate)。

atomic=False 因 mysql DDL 不能在事务内跑 (参考 T6 0002 模式)。
"""
from django.db import migrations


def add_fulltext_index(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    schema_editor.execute(
        "ALTER TABLE submit_skills "
        "ADD FULLTEXT INDEX ft_skills_name_desc (name, description) WITH PARSER ngram"
    )


def remove_fulltext_index(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    schema_editor.execute(
        "ALTER TABLE submit_skills DROP INDEX ft_skills_name_desc"
    )


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ("submit", "0003_review_action"),
    ]

    operations = [
        migrations.RunPython(add_fulltext_index, remove_fulltext_index),
    ]
