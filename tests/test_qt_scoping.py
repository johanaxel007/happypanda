"""The Qt6 enum spelling resolves, under whichever binding is installed.

Qt6 removed the unscoped enum forms, so every `Qt.AlignCenter` becomes
`Qt.AlignmentFlag.AlignCenter`. A mistake in that rewrite fails **lazily** - an AttributeError
at the moment a menu opens or a widget paints, three dialogs into a run, and nothing in the
suite would have said a word. These tests resolve every rescoped site up front instead, so a
wrong scope name is a red suite rather than a crash a user finds.

They are deliberately binding-agnostic: the same file gates the rewrite while it lands on
PyQt5, and proves it still holds after the switch to PyQt6.

Only the spelling is checked. Whether a scope is the *right* one for the object it was read off
- `Fixed` is 2 under QHeaderView.ResizeMode and 0 under QSizePolicy.Policy - depends on a
receiver's type that is not written down, and no static check can settle it. See
`misc/check_qt_enums.py --instance`.
"""

import check_qt_enums

BINDING = check_qt_enums.BINDING
CLASSES = check_qt_enums.qt_classes()
SITES = check_qt_enums.scoped_sites()

INSTANCE_SCOPED = check_qt_enums.instance_scoped_sites()
SCOPE_OWNERS = check_qt_enums.scope_owners(CLASSES)

UNSCOPED_SITES, INSTANCE_SITES, PARSE_FAILURES = check_qt_enums.scan()
USED_CLASSES = ({site[2] for site in SITES}
                | {site.qt_class for site in UNSCOPED_SITES})


def test_the_scan_finds_sites_to_check():
    """A scanner that quietly returned nothing would make every test below vacuous."""
    assert not PARSE_FAILURES, f'the scan could not parse: {PARSE_FAILURES}'
    assert len(SITES) > 400, f'only {len(SITES)} scoped enum sites found - has the scan broken?'
    assert len(INSTANCE_SCOPED) > 50, (
        f'only {len(INSTANCE_SCOPED)} receiver-keyed sites found - has the scan broken?')
    assert any(s.self_class for s in INSTANCE_SCOPED), 'no `self` receiver could be resolved'


def test_every_receiver_keyed_scope_exists():
    """`v_header.ResizeMode.Fixed` - the scope and member are real, on some Qt class.

    The receiver's type is not in the source, so this cannot say the scope is the right one for
    *that* object. It does catch a misspelled scope or member, which is the way a mechanical
    rewrite goes wrong.
    """
    unknown = []
    for site in INSTANCE_SCOPED:
        owners = SCOPE_OWNERS.get(site.scope, [])
        if not any(hasattr(getattr(CLASSES[owner], site.scope), site.member) for owner in owners):
            unknown.append(f'{site.path}:{site.line}  '
                           f'{site.receiver}.{site.scope}.{site.member}')
    assert not unknown, (f'{len(unknown)} receiver-keyed site(s) name a scope or member that '
                         f'exists nowhere under {BINDING}:\n  ' + '\n  '.join(unknown))


def test_a_self_receiver_carries_the_scope_it_reads():
    """Where the receiver is `self`, the enclosing class pins the type - so check it properly.

    A third of the receiver-keyed sites are `self.<Scope>.<MEMBER>` inside a widget subclass
    whose Qt base can be resolved from its bases. For those the scope has to exist on that base,
    not merely somewhere in Qt.
    """
    wrong = []
    for site in INSTANCE_SCOPED:
        if not site.self_class:
            continue
        cls = CLASSES[site.self_class]
        try:
            getattr(getattr(cls, site.scope), site.member)
        except AttributeError:
            wrong.append(f'{site.path}:{site.line}  self.{site.scope}.{site.member} - '
                         f'{site.self_class} carries no such scope or member')
    assert not wrong, (f'{len(wrong)} `self` site(s) read a scope their own class does not '
                       'have:\n  ' + '\n  '.join(wrong))


def test_no_unscoped_enum_site_is_left():
    """Qt6 removed these spellings outright, so each one is an import-time failure after the switch.

    The instance-level half of the scan is a heuristic and is reported rather than asserted -
    `misc/check_qt_enums.py --instance` prints it - but the class-keyed half is exact.
    """
    shown = [f'{s.path}:{s.line}  {s.old}' for s in UNSCOPED_SITES[:20]]
    assert not UNSCOPED_SITES, (
        f'{len(UNSCOPED_SITES)} site(s) still use the unscoped Qt5 enum spelling:\n  '
        + '\n  '.join(shown))


def test_every_scoped_site_resolves():
    unresolved = []
    for path, line, cls_name, scope, member in SITES:
        try:
            getattr(getattr(CLASSES[cls_name], scope), member)
        except AttributeError:
            unresolved.append(f'{path}:{line}  {cls_name}.{scope}.{member}')
    assert not unresolved, (f'{len(unresolved)} enum site(s) do not resolve under {BINDING}:\n  '
                            + '\n  '.join(unresolved))


def colliding_members(classes):
    """Member names a class resolves at two different values through two of its own scopes.

    Returns a list of description strings, empty when no class does.
    """
    out = []
    for cls_name, cls in sorted(classes.items()):
        scopes = check_qt_enums.enum_scopes(cls)
        if len(scopes) < 2:
            continue
        by_member = {}
        for scope_name, scope in scopes:
            for member in dir(cls):
                if member.startswith('_') or not hasattr(scope, member):
                    continue
                try:
                    value = int(getattr(scope, member))
                except (TypeError, ValueError):
                    continue
                by_member.setdefault(member, {}).setdefault(value, []).append(scope_name)
        for member, values in by_member.items():
            if len(values) > 1:
                out.append(f'{cls_name}.{member}: '
                           + ', '.join(f'{"/".join(s)}={v}' for v, s in sorted(values.items())))
    return out


def test_a_member_name_is_unambiguous_within_its_class():
    """The property that makes the class-keyed rewrite safe, asserted against the binding.

    Naming the class pins the value: no Qt class resolves one member name at two different
    values through two of its own scopes, so any scope that resolves the member is the right
    one. This is the assumption the whole rescoping rests on, and it is a fact about the
    installed binding rather than about this codebase - so it is worth re-asserting on every
    Qt or binding upgrade, which is when it could stop being true.
    """
    collisions = colliding_members({name: CLASSES[name] for name in USED_CLASSES})
    assert not collisions, (f'{len(collisions)} ambiguous member name(s) under {BINDING} - '
                            'naming the class no longer pins the value:\n  '
                            + '\n  '.join(collisions))
