# UI gates — settings and Qt

Load when the diff touches `version/settingsdialog.py`, `version/app_constants.py`,
`version/settings.py`, or any dialog, widget, or signal code.

Nothing in this shard is covered by the test suite. `pytest` imports none of it, so a change here
can be entirely broken with a green suite — which is why both gates below insist on naming the
screen that would prove it.

`@.agents/rules/settings-plumbing.md` is the source of truth for gate 9.

---

## Gate 9 — Setting not wired, or a value that cannot round-trip

**What fails.** A persisted setting is wired through **four** places, and missing one produces no
error — the setting silently reverts or latches.

| # | Where | What |
|---|---|---|
| 1 | `app_constants.py` | `NAME = get(<default>, '<Section>', '<key>', <type>)` |
| 2 | `settingsdialog._make_*` | the widget, added to a layout |
| 3 | `settingsdialog.restore_options` | read `app_constants.NAME` **into** the widget |
| 4 | `settingsdialog.accept` | widget → `app_constants.NAME`, **and** `set(...)` |

The specific failures:

- **A widget with no `restore_options` read.** `accept()` writes every setting it knows about,
  whether or not the user opened that tab — so the widget's constructor default is written out on
  the first Ok press, overwriting the stored value.
- **A one-way read.** `setChecked(True) if <cond> else None` can only ever turn a box on. Once the
  stored value is empty it can never recover, because the unchecked box is written straight back.
  It must be `setChecked(<cond>)`.
- **Mismatched section or key strings** between the `get` and the `set`. These are strings; no
  static check compares them.
- **An intentionally empty collection stored as blank.** `settings.get` treats blank as "never
  configured" and returns the default, so an emptied list comes back full. It must be stored as
  `none` (see `HEN_LIST`).
- **A non-conservative default** for anything that writes to the library or costs requests.

**How to check.** For each setting the diff adds or renames, grep all four sites and compare the
section/key strings literally:

```bash
grep -n "'<key>'" version/app_constants.py version/settingsdialog.py
```

Then round-trip it in the running app: set a non-default value, Ok, reopen the dialog, confirm it
shows what you set. That is the only thing that proves 3 and 4 agree.

**Absolute** — a setting is wired or it is not.

**Severity.** High. Silent reversion is the worst kind of bug to diagnose later, and the user only
finds it weeks on.

---

## Gate 10 — GUI change with no proof path

**What fails.** Qt code whose correctness nothing here can check, shipped without naming what
would.

- **No screen named.** A widget, layout, dialog or menu change must come with the exact screen to
  open and what proves it appeared and works. "It should render" is not that.
- **A signal or slot bound by a renamed name.** Connections are resolved at runtime; a symbol
  grep does not see a name used in a `connect` string or a dynamically-resolved slot. Renaming one
  leaves everything green and the button dead.
- **Worker-thread code touching widgets.** The fetch pipeline runs off the GUI thread and must
  reach the UI only through signals. A direct widget call from a worker is a crash or a silent
  no-op depending on timing.
- **A reference kept to a `WA_DeleteOnClose` dialog.** `SettingsDialog` deletes itself on close;
  a stored reference dangles.
- **A blocking call on the GUI thread** — a network request, an archive scan, a database walk —
  added to a path that runs in the event loop.

**How to check.** Read the changed region in full; hunks are especially misleading for layout code.
For a rename, grep the string form as well as the symbol:

```bash
grep -rn "<old_name>" version/     # catches connect() strings and Qt Designer references
```

**Delta-based** for the patterns; **absolute** for the missing proof path.

**Severity.** Medium, ceiling High for a worker-thread widget call or a blocking call added to the
event loop — both present as intermittent freezes or crashes that are painful to trace back.

On an **intermediate** run the screen load itself is the owed half and goes under
`Still owed before merge`. The unwired widget, the renamed connection, and the threading violation
are findings now — all three are visible from source.
