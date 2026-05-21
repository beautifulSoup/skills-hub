"""Migration 0004 函数级测试 (verify vendor 行为)。"""
from importlib import import_module
from unittest.mock import MagicMock


def _load_funcs():
    """文件名以数字开头不能 from ... import,用 importlib。"""
    mod = import_module("skillshub.submit.migrations.0004_skills_fulltext_index")
    return mod.add_fulltext_index, mod.remove_fulltext_index


def test_add_fulltext_skips_non_mysql():
    add_fn, _ = _load_funcs()
    schema_editor = MagicMock()
    schema_editor.connection.vendor = "sqlite"
    add_fn(apps=None, schema_editor=schema_editor)
    schema_editor.execute.assert_not_called()


def test_add_fulltext_runs_on_mysql_with_ngram_parser():
    add_fn, _ = _load_funcs()
    schema_editor = MagicMock()
    schema_editor.connection.vendor = "mysql"
    add_fn(apps=None, schema_editor=schema_editor)
    schema_editor.execute.assert_called_once()
    sql = schema_editor.execute.call_args.args[0]
    assert "FULLTEXT INDEX ft_skills_name_desc (name, description)" in sql
    assert "WITH PARSER ngram" in sql


def test_remove_fulltext_skips_non_mysql():
    _, rem_fn = _load_funcs()
    schema_editor = MagicMock()
    schema_editor.connection.vendor = "sqlite"
    rem_fn(apps=None, schema_editor=schema_editor)
    schema_editor.execute.assert_not_called()
