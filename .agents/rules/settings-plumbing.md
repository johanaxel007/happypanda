---
name: settings-plumbing
description: Rules for adding or changing a persisted setting. A setting is wired through four separate places and a blank ini value has its own meaning; missing a step makes the setting silently revert or latch to a wrong value. Enforced when editing app_constants.py, settings.py or settingsdialog.py.
trigger: glob
glob: "{version/app_constants.py,version/settings.py,version/settingsdialog.py}"
paths:
  - "version/app_constants.py"
  - "version/settings.py"
  - "version/settingsdialog.py"
---

# Settings plumbing

A persisted setting is wired through **four** places. Miss one and nothing errors — the setting
just quietly stops working, usually by reverting on the next time the user presses Ok.

| # | File | What goes there |
|---|------|-----------------|
| 1 | `version/app_constants.py` | `NAME = get(<default>, '<Section>', '<key>', <type>)` — the runtime value and its default |
| 2 | `version/settingsdialog.py`, a `_make_*` method | the widget, added to its layout |
| 3 | `version/settingsdialog.py`, `restore_options()` | read `app_constants.NAME` **into** the widget |
| 4 | `version/settingsdialog.py`, `accept()` | read the widget back into `app_constants.NAME` **and** `set(...)` it |

`accept()` writes **every** setting it knows about, whether the user visited that tab or not. So
a widget that exists but is never populated in `restore_options` is written out at its
constructor default the first time the dialog is confirmed, overwriting whatever was stored.

## Round-trip the value, do not one-way it

`restore_options` must set the widget to the stored value in **both** directions:

```python
# Wrong - can only ever turn the box on. Once the stored value is empty it can never recover,
# because the unchecked box is written straight back out on the next save.
self.fallback_chaika.setChecked(True) if 'chaikahen' in app_constants.HEN_LIST else None

# Right
self.fallback_chaika.setChecked('chaikahen' in app_constants.HEN_LIST)
```

## A blank ini value means "never configured"

`settings.get` treats a blank value as absent and returns the default. That is what lets a
default change reach users who already have an ini file.

The consequence: a value the user has deliberately emptied cannot be stored as blank, or it
comes back as the default. Store it as the string `none`, which `get` maps to `None`:

```python
# app_constants.py — 'none' reads back as None, so coerce to the empty container
HEN_LIST = get(['chaikahen'], 'Web', 'hen list', list) or []

# settingsdialog.accept()
set(henlist if henlist else 'none', 'Web', 'hen list')
```

## Checklist

- [ ] `app_constants` entry with a sensible default
- [ ] widget created and added to a layout in a `_make_*` method
- [ ] `restore_options` sets the widget from `app_constants`, unconditionally in both directions
- [ ] `accept` reads the widget into `app_constants` **and** calls `set(...)`
- [ ] section and key strings identical in all three `settings` calls
- [ ] an intentionally empty collection is stored as `none`, not blank
- [ ] the new option is described in `CHANGELOG.md` under `## Unreleased`
