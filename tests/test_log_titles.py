"""Regression tests for titles reaching the log as text.

Diagnosing a metadata run means reading gallery titles out of happypanda.log, and a title
encoded before it is formatted arrives there as a bytes repr instead: the ASCII survives,
every CJK character becomes an escape, and the whole line is wrapped in b''. The log
handlers are UTF-8, so the argument has to reach them as a str.
"""

import ast
import io
import logging
import os
from unittest import mock

import pytest

from version.database import db


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_DIR = os.path.join(REPO, 'version')

LOG_CALLS = {'log_i', 'log_d', 'log_w', 'log_e', 'log_c'}
LOG_METHODS = {'info', 'debug', 'warning', 'error', 'critical', 'exception'}

JP_TITLE = '漫画のタイトル'


# --- The message a log call actually emits ----------------------------------------------

def test_a_query_logs_its_arguments_as_text(caplog):
    """A CJK value in a database query reaches the record as characters, not as b'...'."""
    with mock.patch.object(db.DBBase, '_DB_CONN', mock.MagicMock()), \
            mock.patch.object(db.DBBase, '_AUTO_COMMIT', True):
        with caplog.at_level(logging.DEBUG, logger='version.database.db'):
            db.DBBase.execute(db.DBBase, 'SELECT 1 FROM series WHERE title=?', (JP_TITLE,))

    messages = [r.getMessage() for r in caplog.records]
    assert any(JP_TITLE in m for m in messages), messages
    assert not any("b'" in m for m in messages), messages


# --- No log call anywhere may encode its argument ----------------------------------------

def _python_sources():
    for root, _, files in os.walk(VERSION_DIR):
        if '__pycache__' in root:
            continue
        for name in files:
            if name.endswith('.py'):
                yield os.path.join(root, name)


def _is_log_call(node):
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in LOG_CALLS
    return isinstance(func, ast.Attribute) and func.attr in LOG_METHODS


def _encodes_an_argument(node):
    """Any `.encode(...)` reachable from one of this call's arguments."""
    for arg in list(node.args) + [kw.value for kw in node.keywords]:
        for inner in ast.walk(arg):
            if (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == 'encode'):
                return True
    return False


@pytest.mark.parametrize('path', sorted(_python_sources()),
                         ids=lambda p: os.path.relpath(p, VERSION_DIR).replace(os.sep, '/'))
def test_no_log_call_encodes_its_argument(path):
    """`log_i(title.encode(...))` puts a bytes repr in the log rather than the title."""
    # utf-8-sig: several modules here carry a BOM, which ast rejects as non-printable.
    tree = ast.parse(io.open(path, encoding='utf-8-sig').read(), filename=path)
    offenders = [node.lineno for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and _is_log_call(node)
                 and _encodes_an_argument(node)]
    rel = os.path.relpath(path, REPO).replace(os.sep, '/')
    assert not offenders, '{} encodes a logged value on line(s) {}'.format(rel, offenders)
