#!/usr/bin/env python3
"""Report the Qt enum accesses still written in the unscoped Qt5 spelling.

Qt6 removed the unscoped forms: `Qt.AlignCenter` has to be written
`Qt.AlignmentFlag.AlignCenter`. PyQt5 5.15 already accepts the scoped spelling with identical
values, so the whole rewrite lands on the shipping binding, one module at a time, and this
reports what is left.

Two populations, and they are not equally safe:

    class-keyed     `QHeaderView.Fixed`  -- the class is written down, so the scope that
                                            replaces it is decided by lookup and cannot be wrong
    instance-level  `v_header.Fixed`     -- the class is not written down. `Fixed` is 2 under
                                            QHeaderView.ResizeMode and 0 under QSizePolicy.Policy,
                                            so naming the wrong scope silently changes behaviour

The class-keyed report is exact. The instance-level report is a heuristic over member names for
a human to work through: it cannot tell what type a receiver holds, and it turns up the
occasional false positive.

Resolves against whichever binding is installed, so it still answers after the switch - where a
clean tree reports nothing, because Qt6 exposes no unscoped names to find.

Usage:
    python misc/check_qt_enums.py [--sites] [--mapping] [--instance] [--check]

    --sites      list every class-keyed site as file:line with its replacement
    --mapping    list the symbol -> scoped-symbol mapping instead of per-file counts
    --instance   list the instance-level candidates instead of the class-keyed report
    --check      exit non-zero while any class-keyed site remains
"""

import argparse
import ast
import collections
import os
import sys

try:
    from PyQt5 import QtCore, QtGui, QtWidgets
    from PyQt5.QtCore import Qt
    BINDING = 'PyQt5'
except ImportError:
    from PyQt6 import QtCore, QtGui, QtWidgets
    from PyQt6.QtCore import Qt
    BINDING = 'PyQt6'

# PyQt5's nested enum scopes are sip.enumtype objects rather than enum.Enum subclasses, and
# dir() does not list their members - so the member universe comes from each class's own
# attributes, not from the scopes.
ENUMTYPE = type(Qt.AlignmentFlag)  # sip.enumtype under PyQt5, enum.EnumType under PyQt6
QT_MODULES = (QtCore, QtGui, QtWidgets)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def qt_classes():
    """Every Qt class reachable from the three modules the application uses, by name."""
    out = {}
    for module in QT_MODULES:
        for name in dir(module):
            cls = getattr(module, name)
            if isinstance(cls, type) and (name.startswith('Q') or name == 'Qt'):
                out.setdefault(name, cls)
    return out


def enum_scopes(cls):
    """The nested enum scopes declared on cls, as (name, scope) pairs."""
    out = []
    for name in dir(cls):
        if name.startswith('_'):
            continue
        try:
            attr = getattr(cls, name)
        except Exception:
            continue
        if isinstance(attr, ENUMTYPE):
            out.append((name, attr))
    return out


def build_index(classes):
    """Map each unscoped enum access to the scopes that expose it with the same value.

    Returns (unscoped, members, scope_names): `unscoped` keyed by (class name, member) for the
    class-keyed pass, `members` keyed by member alone for the instance-level pass, and every
    scope name, which is what tells an already-scoped access apart from an unscoped one.
    """
    unscoped = {}
    members = collections.defaultdict(lambda: collections.defaultdict(set))
    scope_names = set()
    for cls_name, cls in classes.items():
        scopes = enum_scopes(cls)
        scope_names.update(name for name, _ in scopes)
        if not scopes:
            continue
        for member in dir(cls):
            if member.startswith('_'):
                continue
            try:
                direct = getattr(cls, member)
            except Exception:
                continue
            if isinstance(direct, type) or callable(direct):
                continue
            hits = []
            for scope_name, scope in scopes:
                if not hasattr(scope, member):
                    continue
                try:
                    same = int(getattr(scope, member)) == int(direct)
                except (TypeError, ValueError):
                    continue
                if same:
                    hits.append(scope_name)
            if hits:
                unscoped[(cls_name, member)] = hits
                for scope_name in hits:
                    members[member][(scope_name, int(direct))].add(cls_name)
    return unscoped, members, scope_names


def base_most(classes, names):
    """The names in `names` that no other name in it derives from.

    A scope is inherited by every subclass, so `NoEditTriggers` reports ten owners where there
    is really one - QAbstractItemView, which the other nine descend from.
    """
    kept = []
    for name in names:
        cls = classes[name]
        if not any(other != name and issubclass(cls, classes[other]) for other in names):
            kept.append(name)
    return sorted(kept)


def source_files():
    """Every module the migration covers: the application, plus the GUI smoke gate."""
    out = []
    for root, dirs, names in os.walk(os.path.join(REPO, 'version')):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        out.extend(os.path.join(root, n) for n in names if n.endswith('.py'))
    out.append(os.path.join(REPO, 'misc', 'gui_smoke.py'))
    return sorted(out)


def read_tree(path):
    # 7 of the modules carry a UTF-8 BOM, which ast.parse rejects as a syntax error.
    with open(path, 'r', encoding='utf-8-sig') as f:
        src = f.read()
    return ast.parse(src, filename=path)


def qt_aliases(tree, classes):
    """Local name -> Qt class name, for the classes a module imported under another name."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or '').startswith(('PyQt5', 'PyQt6')):
            for alias in node.names:
                if alias.asname and alias.name in classes:
                    out[alias.asname] = alias.name
    return out


def declared_classes(tree):
    """Every class this module declares, including nested ones."""
    return {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}


def scope_aliases(tree, classes, scope_names):
    """Local names bound to a Qt enum scope, as in `Behaviour = QAbstractItemView.Behaviour`.

    A long rescoped line is often shortened this way, and reading a member off such a name is
    already scoped - not the unscoped access the member name alone makes it look like.
    """
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Attribute):
            continue
        owner = node.value.value
        if not isinstance(owner, ast.Name) or owner.id not in classes:
            continue
        if node.value.attr not in scope_names:
            continue
        out.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return out


def receiver_root(node):
    """The leftmost name of an attribute chain, or None if it does not start with one."""
    while isinstance(node, (ast.Attribute, ast.Call, ast.Subscript)):
        node = node.func if isinstance(node, ast.Call) else node.value
    return node.id if isinstance(node, ast.Name) else None


def scoped_sites():
    """Every `QClass.Scope.NAME` written in the tree, as (path, line, class, scope, member).

    The migration's output: what a rescoped site is supposed to look like. Nothing here proves
    the scope is the *right* one for the receiver, only that it is a scope that exists.
    """
    classes = qt_classes()
    out = []
    for path in source_files():
        rel = os.path.relpath(path, REPO).replace(os.sep, '/')
        try:
            tree = read_tree(path)
        except (OSError, SyntaxError):
            continue
        aliases = qt_aliases(tree, classes)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute) or not isinstance(node.value, ast.Attribute):
                continue
            middle = node.value
            root = middle.value
            if not isinstance(root, ast.Name):
                continue
            cls_name = root.id if root.id in classes else aliases.get(root.id)
            if cls_name:
                out.append((rel, node.lineno, cls_name, middle.attr, node.attr))
    return out


def scan():
    classes = qt_classes()
    unscoped, members, scope_names = build_index(classes)

    class_keyed = []            # (path, line, "QClass.NAME", "QClass.Scope.NAME", ambiguous)
    instance_level = []         # (path, line, source text, candidate scopes)
    failures = []

    for path in source_files():
        rel = os.path.relpath(path, REPO).replace(os.sep, '/')
        try:
            tree = read_tree(path)
        except (OSError, SyntaxError) as e:
            failures.append((rel, str(e)))
            continue
        aliases = qt_aliases(tree, classes)
        local_classes = declared_classes(tree)
        scoped_by_alias = scope_aliases(tree, classes, scope_names)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            receiver = node.value
            cls_name = None
            if isinstance(receiver, ast.Name):
                cls_name = receiver.id if receiver.id in classes else aliases.get(receiver.id)
            elif isinstance(receiver, ast.Attribute) and receiver.attr in classes:
                cls_name = receiver.attr          # a module- or package-qualified class
            if cls_name:
                hits = unscoped.get((cls_name, node.attr))
                if hits:
                    class_keyed.append((rel, node.lineno, f'{cls_name}.{node.attr}',
                                        f'{cls_name}.{hits[0]}.{node.attr}', len(hits) > 1))
                continue
            candidates = members.get(node.attr)
            if not candidates:
                continue
            if isinstance(receiver, ast.Name) and receiver.id in scoped_by_alias:
                continue                          # read off a local alias of an enum scope
            if isinstance(receiver, ast.Attribute) and (receiver.attr in scope_names
                                                        or receiver.attr in local_classes):
                continue                          # already scoped, or one of this project's enums
            root = receiver_root(receiver)
            if root in local_classes or root in sys.stdlib_module_names:
                continue
            if root and os.path.exists(os.path.join(REPO, 'version', root + '.py')):
                continue                          # an application module's own constant
            owners = [(scope_name, value, base_most(classes, names))
                      for (scope_name, value), names in sorted(candidates.items())]
            instance_level.append((rel, node.lineno, ast.unparse(node), owners))

    return class_keyed, instance_level, failures


def report_class_keyed(sites, show_sites, show_mapping):
    mapping = {}
    for _, _, old, new, _ in sites:
        mapping.setdefault(old, new)
    ambiguous = [s for s in sites if s[4]]

    if show_sites:
        for rel, line, old, new, amb in sites:
            print(f'  {rel}:{line}  {old} -> {new}' + ('   AMBIGUOUS' if amb else ''))
        print()
    if show_mapping:
        for old, new in sorted(mapping.items()):
            print(f'  {old} -> {new}')
        print()

    per_file = collections.Counter(s[0] for s in sites)
    print('unscoped enum sites, class-keyed (exact)')
    for rel, count in sorted(per_file.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f'  {count:5}  {rel}')
    print(f'  {len(sites):5}  TOTAL across {len(mapping)} distinct symbols')
    if ambiguous:
        print(f'\n  {len(ambiguous)} site(s) whose member sits in more than one scope '
              'at the same value - pick by hand:')
        for rel, line, old, _, _ in ambiguous:
            print(f'    {rel}:{line}  {old}')


def report_instance_level(sites):
    per_file = collections.Counter(s[0] for s in sites)
    print('instance-level candidates (heuristic - the receiver\'s class is not written down)')
    for rel, count in sorted(per_file.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f'  {count:5}  {rel}')
    print(f'  {len(sites):5}  TOTAL')
    print('\n  A site whose candidates disagree on the value is marked SAME NAME, DIFFERENT '
          'VALUE:\n  there the receiver\'s class decides the behaviour, so read it before '
          'choosing.\n')
    for rel, line, text, owners in sites:
        values = {value for _, value, _ in owners}
        flag = '   SAME NAME, DIFFERENT VALUE' if len(values) > 1 else ''
        print(f'  {rel}:{line}  {text}{flag}')
        for scope_name, value, names in owners:
            print(f'      {scope_name} = {value}   on {", ".join(names)}')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--sites', action='store_true',
                        help='list every class-keyed site with its replacement')
    parser.add_argument('--mapping', action='store_true',
                        help='list the symbol -> scoped-symbol mapping')
    parser.add_argument('--instance', action='store_true',
                        help='list the instance-level candidates instead')
    parser.add_argument('--check', action='store_true',
                        help='exit non-zero while any class-keyed site remains')
    args = parser.parse_args()

    class_keyed, instance_level, failures = scan()

    for rel, error in failures:
        print(f'COULD NOT PARSE {rel}: {error}', file=sys.stderr)

    if args.instance:
        report_instance_level(instance_level)
    else:
        report_class_keyed(class_keyed, args.sites, args.mapping)
        print(f'\n  {len(instance_level)} instance-level candidate(s) as well '
              '- see --instance')

    if failures:
        return 2
    return 1 if args.check and class_keyed else 0


if __name__ == '__main__':
    sys.exit(main())
