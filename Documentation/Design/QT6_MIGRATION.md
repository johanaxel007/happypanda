# Qt5 → Qt6 Migration Design

**Version:** 1.6  
**Date:** 2026-09-12  
**Status:** In progress — Q0–Q3 are complete and the app runs on PyQt6, but a startup performance regression blocks Q4/Q5. See [`./QT6_STARTUP_REGRESSION.md`](./QT6_STARTUP_REGRESSION.md).  
**Target:** PyQt6 6.11 / Qt 6.11 on Python 3.14 (current: PyQt5 5.15.11 / Qt 5.15.2)

> Happypanda's Qt surface is ~610 individual edits across 16 modules, and the single most
> important finding is that **~98% of them are forward-compatible: PyQt5 5.15.11 already accepts
> the Qt6 scoped-enum spelling for all 584 enum call sites, with identical values.** The
> migration therefore does not have to be a big-bang binding switch — the mechanical bulk can
> land incrementally against the running Qt5 app, leaving roughly 11 edits plus the PyInstaller
> spec for switch day. **The recommended binding is PyQt6, not PySide6.**
>
> Before implementation starts, re-verify §8: nothing here has been confirmed by actually
> *running* Happypanda under Qt6 — no window has ever been painted, no build produced. The
> analysis is static review plus API-level probing, which settles what breaks at the API
> boundary and settles nothing about rendering, layout, or the frozen build.

> **v1.1, after implementing Q0–Q2.** The measured figures below were re-derived from the AST
> rather than by regex, and three of them moved. The class-keyed surface was **503 sites across
> 150 symbols**, not 517/154 — the original count included commented-out lines. The
> instance-level surface was **81 sites, not "~15 as a lower bound"**, and those are the ones no
> class-name codemod can catch. `QPalette.Background` is a **tenth removed-API family** that §5
> missed. All of it has now landed; §7 carries the phase statuses.

**Amended:** 2026-09-12 — `qtawesome` pulls in `qtpy`, which patches the Qt5 spelling back onto
PyQt6 at import. The app running is therefore not evidence that the conversion is complete, and
§4 gained the subsection that says what still is.

**Audited:** 2026-09-09, at commit `69b1ae0` (branch `feat/better-versions-scan`).
**Re-audited:** 2026-09-10 during Q0–Q2, on branch `feat/qt6-migration-prep`.
Findings come from static review of all 19 modules in `version/` plus `misc/gui_smoke.py`, and
from executing probes against three real interpreter environments built for this analysis:
PyQt6 6.11.0, PySide6 6.11.2, and the project's own PyQt5 5.15.11 venv, all on Python 3.14.7.
Every claim below is tagged ✅ **Verified** or ⚠️ **Unverified** — see the legend in §2.

**Relationship to other documents:**

- [`../../ROADMAP.md`](../../ROADMAP.md) — carries the one-line pointer to this doc.
- [`../../CLAUDE.md`](../../CLAUDE.md) — the four Core Constraints this migration is checked against in §6.
- [`../../.agents/rules/settings-plumbing.md`](../../.agents/rules/settings-plumbing.md) — governs the `FORCE_HIGH_DPI_SUPPORT` removal in Q4.

---

## 1. Goals & non-goals

### Goals

1. **Leave Qt5 before it becomes a liability** — Qt 5.15 is end-of-life for open-source users, and
   PyQt5 wheels for future Python releases are not guaranteed.
2. **Never risk the library to do it** — no phase may put gallery data, paths, or the database at
   risk (CLAUDE.md Core Constraints 1 and 2). See §6.
3. **Keep the tree runnable at every step** — each phase ships an app that launches and passes its
   gates, so a regression is attributable to the commit that caused it.
4. **Make the mechanical work verifiable early** — separate the ~561 edits that can be proven
   against the running Qt5 app from the ~11 that can only be proven after the switch.

### Non-goals (v1)

- **Migrating to PySide6.** Rejected on evidence, see §3 and §9.
- **Adopting Qt6-only capabilities** (native dark-mode palette integration, newer
  `QRegularExpression` features). Deferred to a **v2 extension**, see the §7 extension roadmap —
  this migration is a like-for-like port, not a feature pass.
- **Reformatting or modernising the modules being touched.** CLAUDE.md is explicit that wholesale
  modernisation is not a goal; a rescoping diff that also reflows untouched lines hides the real
  change.
- **Building GUI test coverage.** Genuinely desirable and genuinely large; called out as the
  dominant residual risk in §8 rather than folded into this work.

---

## 2. Current state (what exists today)

**Claim legend, used throughout this document:**

| Tag | Meaning |
|-----|---------|
| ✅ **Verified** | Reproduced this session by executing code against a real installed binding. The method is named inline. |
| ⚠️ **Unverified** | Derived from static reading, `grep`, or reasoning. Plausible, not executed. Treat as a lead. |

### Qt dependency surface

| Area | State |
|------|-------|
| Binding | PyQt5 5.15.11 / Qt 5.15.2, pinned in `requirements.txt`. ✅ **Verified** by importing `PyQt5.QtCore` in the project venv. |
| Modules importing Qt | 16 of 20 in `version/`, plus `misc/gui_smoke.py` and `misc/app_smoke.py`. Only `settings.py`, `asm_manager.py`, `app_constants.py` and `tagreaders.py` are Qt-free. ✅ **Verified** by AST scan of every `from PyQt5.* import`. |
| Qt modules used | `QtCore`, `QtGui`, `QtWidgets` only. No `QtWebEngine`, `QtMultimedia`, `QtSql`, `QtNetwork`, `QtSvg`, `QtPrintSupport`. ✅ **Verified** by grep across `version/` and `misc/`. |
| `.ui` files / `uic` | None. All UI is hand-built in Python. ✅ **Verified** by grep for `loadUi`, `uic`, `.ui`. |
| Styling | One plain CSS file, `res/style.css`. No `.qss`. ✅ **Verified** by directory listing. |
| Custom widget layer | 62 `QWidget` subclasses, 71 event-handler overrides, 7 custom `paint`/`paintEvent` methods. ⚠️ **Unverified** — grep-derived counts, accurate to within a few. |
| Third-party Qt consumer | `qtawesome` 1.4.2, used for every toolbar icon in `app_constants.load_icons()`. |
| Threading | `moveToThread` onto `app_constants.GENERAL_THREAD` plus ad-hoc `QThread`s; ~106 `pyqtSignal` declarations. No `pyqtSlot` decorators anywhere. ✅ **Verified** by grep. |
| Licence | GPL (`LICENSE`, © 2016 Pewpews). Neither PyQt6 (GPL) nor PySide6 (LGPL) is constrained by it. ✅ **Verified** by reading `LICENSE`. |

### Enum call sites, by file

**503 class-keyed enum references across 150 distinct symbols, plus 81 instance-level ones.**
✅ **Verified** — `misc/check_qt_enums.py` walks the AST of every module and resolves each
symbol against the installed binding; all 150 resolved to exactly one scope, none ambiguous.

The v1.0 figure of 517/154 came from a regex over the source, which also counted names inside
comments — `misc.py:517–518` and `misc.py:2780` are commented-out `QDesktopWidget` lines, and
`gallery.py:312` a commented-out `msg.exec()`.

| File | Class-keyed | Instance-level |
|------|------:|------:|
| `version/misc.py` | 184 | 26 |
| `version/gallery.py` | 110 | 20 |
| `version/app.py` | 53 | 3 |
| `version/settingsdialog.py` | 46 | 1 |
| `version/gallerydialog.py` | 26 | — |
| `version/io_misc.py` | 24 | 22 |
| `version/main.py` | 16 | 1 |
| `version/misc_db.py` | 14 | 7 |
| `misc/gui_smoke.py` | 15 | — |
| `version/executors.py` | 9 | 1 |
| `version/utils.py` | 5 | — |
| **Total** | **503** | **81** |

The tree was already partway there: 74 sites used the scoped Qt6 spelling before this work
began, most of them `QSizePolicy.Policy` in `gallerydialog.py`.

### Existing gates

| Gate | Covers | Verdict for this migration |
|------|--------|----------------------------|
| `pytest tests/ -q` | 344 pass, 4 pre-existing failures in `test_db.py::test_init_db`. ✅ **Verified** 2026-09-12; the 283 recorded at Q0 is stale, the suite has grown since. | **Was weak; no longer, and it is the only gate that can see this.** No test referenced Qt at all before Q0. `tests/test_qt_scoping.py` now resolves every scoped site against the installed binding and asserts no unscoped one is left. That source scan is the whole of the coverage: qtpy restores the Qt5 spelling at runtime, so a missed site does not raise when the widget paints either (§4). |
| `misc/gui_smoke.py` | Settings dialog, gallery chooser, better-version review list, gallery edit dialog, crash regressions. | **Widgets in isolation.** Ported in Q1 and named PyQt6 in Q3, so it exercises the shipping binding. |
| `misc/app_smoke.py` | The real `AppWindow` and its own methods: confirmation dialogs, the worker thread, the metadata lock. | **App-level assembly.** The only gate that builds the window, so a mis-scoped `StandardButton` in a confirmation surfaces here rather than in front of a user. Named PyQt6 with the rest in Q3. |
| Launching the app | Everything else. | The real gate for rendering, layout and the build. **Not** a gate for the enum conversion, for the reason in §4. Manual, and per CLAUDE.md expects a multi-minute library scan. |

---

## 3. Decision: which binding

The pivotal choice, because it determines whether the 517 enum sites are work or not.

### Option A — PySide6 (rejected)

- ✅ **Genuinely erases the bulk of the diff.** PySide6 keeps "forgiving" unscoped enum access:
  `Qt.AlignCenter`, `Qt.UserRole`, `QMessageBox.Yes`, `QSizePolicy.Expanding`,
  `QPainter.Antialiasing` and `QImage.Format_ARGB32` all still resolve. ✅ **Verified** against
  PySide6 6.11.2. It also keeps `exec_()`, `QDropEvent.pos()`, and tolerates
  `AA_EnableHighDpiScaling` as a live constant.
- ✅ LGPL rather than GPL, and backed by The Qt Company.
- ✅ `qtawesome` works unmodified. ✅ **Verified** by rendering `fa6s.bars` under PySide6.
- ❌ **Trades 517 mechanical edits for 106 signal edits that are not forward-compatible.**
  `pyqtSignal` does not exist; it is `Signal`. Those 106 declarations across 11 files cannot be
  pre-landed on PyQt5, so the diff moves from "provable early" to "big-bang". ✅ **Verified** —
  `PySide6.QtCore` has no `pyqtSignal`.
- ❌ `QVariant` and `qRound` do not exist at all, both of which the codebase imports.
  ✅ **Verified**.
- ❌ **The forgiveness is deprecation debt, not a saving.** You would arrive on Qt6 still spelling
  enums the Qt5 way, and do the rescoping later anyway — having meanwhile touched every signal
  declaration in the codebase.

### Option B — PyQt6 ✅ **preferred direction**

Wins because the work it asks for is the work that is *provably mechanical and forward-compatible*
(§4), while the work it avoids is not. Concretely: `pyqtSignal`, `QVariant` and `qRound` all
survive, so 106 signal declarations and the model layer are untouched; and the 517 enum edits can
be verified against the running Qt5 app weeks before the switch.

It is also the direction the codebase already leans — 77 sites are Qt6-scoped today — and the same
vendor and API shape the project has always used, which matters for a fork maintained by one
person.

✅ **Verified** that PyQt6 6.11.0 and `qtawesome` 1.4.2 install and import cleanly on Python
3.14.7, and that `qtawesome` renders an icon under it.

### Option C — stay on PyQt5 (rejected)

- ✅ Zero work today, and Qt 5.15.2 is stable and well understood.
- ❌ **Qt 5.15 is end-of-life for open-source users**; security and platform fixes land only in the
  commercial branch. ⚠️ **Unverified** — stated from general knowledge, not checked against
  Riverbank's current support statement.
- ❌ The cost does not shrink with time. Every new dialog adds enum sites, so deferring means
  migrating a strictly larger surface later.

---

## 4. Decision: pre-migrate on Qt5 before switching binding

The finding that shapes the whole plan.

**PyQt5 5.15.11 already accepts the Qt6 scoped spelling for every one of the 517 enum sites, and
the resolved values are identical to the unscoped ones.** ✅ **Verified** — the resolver emitted
all 154 mappings, and a back-test asserted, per symbol, both that the scoped path exists under
PyQt5 and that `Scope.NAME == Class.NAME`. Result: 517 sites work, 0 fail.

That makes almost the entire mechanical diff landable *today*, on the shipping binding.

### What can land now, on Qt5

All ✅ **Verified** by executing the same probe under both PyQt5 5.15.11 and PyQt6 6.11.0.

| Change | Sites | PyQt5 | PyQt6 |
|--------|------:|:-----:|:-----:|
| Scoped enums (`Qt.AlignmentFlag.AlignCenter`) | 517 | ✅ | ✅ |
| Instance-level enums (`self.ResizeMode.Adjust`) | ~15 | ✅ | ✅ |
| `exec_()` → `exec()` | 11 | ✅ | ✅ |
| `QDesktopWidget` → `primaryScreen()` / `screenAt()` | 6 | ✅ | ✅ |
| `qApp` → `QApplication.instance()` | 3 | ✅ | ✅ |
| `fontMetrics().width()` → `horizontalAdvance()` | 2 | ✅ | ✅ |
| `pyqtWrapperType` → `type(QObject)` | 1 | ✅ | ✅ |
| `QFileDialog.DirectoryOnly` → `FileMode.Directory` + `Option.ShowDirsOnly` | 1 | ✅ | ✅ |
| `return QVariant()` → `return None` | 3 | ✅ | ✅ |
| `QMouseEvent` built with `QPointF` | 1 | ✅ | ✅ |

**≈561 of ≈572 edits — about 98% — are forward-compatible.**

The `QVariant` row was checked with a real `QAbstractTableModel` rather than trusted as an idiom:
PyQt5 normalises both `None` and `QVariant()` to `None` on read-back through the index, so the
swap is behaviour-identical, not merely tolerated. ✅ **Verified**.

The instance-level count was **badly underestimated at ~15**: an AST sweep that filters out the
project's own enums, stdlib receivers and already-scoped chains found **81**. These are enum
accesses keyed off a variable (`painter.Antialiasing`, `header.Stretch`,
`application.font().PreferAntialias`) rather than a class name, so no class-name codemod catches
them and no static check proves the list complete. All 81 were rewritten in Q2.

**They were rewritten in the instance form, not by naming a class** — `v_header.Fixed` became
`v_header.ResizeMode.Fixed`, not `QHeaderView.ResizeMode.Fixed`. That matters because `Fixed` is
2 under `QHeaderView.ResizeMode` and 0 under both `QListView.ResizeMode` and
`QSizePolicy.Policy`: writing the class out means deciding the receiver's type by hand, and a
wrong-but-valid choice compiles, resolves, passes every test and silently means something else.
The instance form lets the receiver pick its own scope, which is the only spelling that cannot
be wrong. ✅ **Verified** to work on both bindings.

### What cannot move early

Only four things, ~11 edits. ✅ **Verified** as mutually exclusive between the bindings.

| Change | Sites | Why it must wait |
|--------|------:|------------------|
| `QAction`, `QActionGroup`, `QShortcut` imports | 4 statements | `QtWidgets` on Qt5, `QtGui` on Qt6, no overlap. |
| `QDropEvent.pos()` → `position().toPoint()` | 2 (`misc_db.py:407,418`) | `position()` does not exist on Qt5. |
| `AA_EnableHighDpiScaling` / `AA_UseHighDpiPixmaps` | 2 (`main.py:136,148`) | Required on Qt5, absent on Qt6 (always on). Drags the `FORCE_HIGH_DPI_SUPPORT` setting removal with it — see §6. |
| `sip` → `PyQt6.sip` | 3 (`gui_smoke.py`) | Different module name per binding. |

Each could be a three-line `hasattr` shim landed early. **Recommended against**: eleven edits do
not justify a compat module that then has to be remembered and deleted.

### Traps worth recording

Three things that look broken and are not, plus one that looks safe and is not. All ✅ **Verified**.

- **`QContextMenuEvent.globalPos()` survives Qt6.** The 11 `menu.exec_(event.globalPos())` sites
  need only the `exec_` rename — not the `globalPosition().toPoint()` treatment that `QMouseEvent`
  and `QDropEvent` require. `QMouseEvent.pos()` also survives (deprecated);
  `QMouseEvent.globalPos()` does not — though the subsection below is why one such site ran for
  the whole migration without anyone noticing.
- **`Qt.ItemDataRole.UserRole + N` still yields a plain int.** All 69 custom-role arithmetic sites
  are safe once rescoped — they sit in `misc.py` (34), `gallery.py` (28), `io_misc.py` (4),
  `app.py` and `misc_db.py`.
- **`Qt.Key` is int-compatible** (`isinstance(Qt.Key.Key_Delete, int)` is `True`), so
  `event.key() == Qt.Key.Key_Delete` keeps working — `event.key()` returns a bare `int` in PyQt6.
- **`Qt.KeyboardModifier` is a flag and is *not* an int.** `modifiers() == ShiftModifier` compares
  fine flag-to-flag, but any code doing integer arithmetic or bitwise mixing on modifiers will
  break. No such site was found in this codebase, ⚠️ **Unverified** as exhaustive.

### The runtime is not a gate: qtpy puts the Qt5 spelling back

`app_constants` imports `qtawesome`, which imports `qtpy`, which **patches PyQt6 on import**. Two
mechanisms, both ✅ **Verified** by calling the affected names before and after importing
`app_constants` in one process:

| What qtpy does | Effect on this codebase |
|---|---|
| `enums_compat.promote_enums` walks `QtCore`, `QtGui`, `QtWidgets` and `QtTest` and copies every scoped enum member onto its class as an **unscoped** attribute | `Qt.AlignLeft` and `QListView.IconMode` resolve again, so a site Q1/Q2 missed executes instead of raising |
| removed Qt5 accessors are restored on `QSinglePointEvent`: `globalPos`, `globalX`, `globalY`, `localPos`, `posF` | `QMouseEvent.globalPos()` works, despite being absent from PyQt6 6.11 |

**The concrete case.** `misc.py` called `ev.globalPos()` on a `QMouseEvent` from Q3 until it was
rewritten, and right-clicking a tag never once raised — the table above is why. A review flagged
it as a certain crash and a bare-PyQt6 probe agreed; both were wrong, because neither had the
application's own imports loaded. ✅ **Verified** by driving the real handler with a synthesised
right-click.

**What this does not undermine.** `misc/check_qt_enums.py` imports PyQt6 and nothing else, so run
on its own it sees the true Qt6 surface. ✅ **Verified** that `qtpy` and `qtawesome` are absent
from `sys.modules` after importing it. Its output against the current tree is byte-identical with
and without the shim loaded — ✅ **Verified**, though against a tree that has no unscoped site
left that demonstrates the tree is clean rather than that the checker is shim-proof. A full
`pytest tests/ -q` **does** have qtpy loaded, because an earlier test module imports
`app_constants` and pytest shares one process. ✅ **Verified**. Whether a leftover Qt5 site would
still be reported under those conditions is ⚠️ **Unverified**; the cheap way to settle it is to
reintroduce one deliberately and run the suite.

**The rule this leaves.** Probe with the application's own imports when asking what the *app*
does, and with a bare binding when asking what *Qt6* provides. The two disagree in both
directions, and picking the wrong one produces a confident answer that is exactly backwards.

### The failure mode this plan is designed around

Rescoping errors fail **lazily** — `AttributeError` at the moment a widget paints or a menu opens,
not at import. A run can start cleanly and die three dialogs deep. Landing the enum work on Qt5,
where the app can actually be driven, is what converts that from a debugging problem into a
testing problem. With qtpy in the process they may not fail even then, which makes the source scan
the gate rather than the run.

---

## 5. Breakage inventory (the Qt6 switch itself)

Removed outright in Qt6, independent of binding choice. All ✅ **Verified** by attribute probe
against PyQt6 6.11.0.

| Symbol | Sites | Replacement |
|--------|------:|-------------|
| `QDesktopWidget` | 4 live | `QApplication.primaryScreen().availableGeometry()` / `screenAt()`. Three of the six v1.0 counted are commented out. `misc.available_geometry()` now wraps both, because `screenAt()` answers `None` for a point on no screen |
| `pyqtWrapperType` (`hplugins.py:7`) | 1 | `type(QObject)`. **Not the first thing that fails** — `hplugins` is imported by no module in the tree, so the breakage was dormant |
| `qApp` (`io_misc.py:17,198,555`) | 3 | `QApplication.instance()` |
| `QFontMetrics.width()` | 2 | `horizontalAdvance()` |
| `QDropEvent.pos()` | 2 | `position().toPoint()` |
| `QFileDialog.DirectoryOnly` | 1 | `FileMode.Directory` + `Option.ShowDirsOnly` |
| `QPalette.Background` (`misc.py:2189`) | 1 | `ColorRole.Window`, same value (10). **Missed by v1.0** — it survives the rescoping as `ColorRole.Background`, which resolves on PyQt5 and does not exist on Qt6 |
| `Qt.Orientations` (`misc.py:2392`) | 1 | `Qt.Orientation(0)`. **Missed by v1.0.** Qt6 folded the `QFlags` companion types into the enums, so the enum is its own flag type. Every `Q…s` plural spelling is suspect; an AST sweep for `QClass.attr` chains that do not resolve under PyQt6 found this as the only remaining one |
| `QByteArray().append(str)` (`misc.py:132`) | 1 | `prop.encode()`. **Missed by v1.0.** Qt6's `append` takes bytes; `create_animation` built a property name from a `str`. `QPropertyAnimation` accepts `bytes` directly, so the `QByteArray` goes away entirely |
| `AA_EnableHighDpiScaling` / `AA_UseHighDpiPixmaps` | 2 | Gone — Qt6 always scales |
| `exec_()` | 11 | `exec()`. None of them is a `QMessageBox` — every message box already called `.exec()`, so the rename could not disturb what `gui_smoke.py` monkeypatches |
| `QAction` / `QActionGroup` / `QShortcut` | 4 names, 2 import statements | Moved `QtWidgets` → `QtGui` |

### An unhandled Python exception is now fatal

**PyQt5 printed the traceback and carried on; PyQt6 calls `qFatal` and the process aborts.** ✅
**Verified** — `Qt.Orientations` above presented as a silent death during `SettingsDialog`
construction: exit code 127, nothing on stderr, no Python traceback, and `faulthandler` caught
nothing because it is not a signal it handles.

This matters more than the one-line fix it caused, because it changes how every later failure will
present. Anything latent that Qt5 survived is now a hard stop, which is exactly the risk profile
Q5 is walking into.

To see the traceback, install a message handler before building any widget:

```python
from PyQt6.QtCore import qInstallMessageHandler
qInstallMessageHandler(lambda mode, ctx, msg: print(f'QT[{mode}] {msg}', flush=True))
```

Note also that **exit code 127 does not distinguish a Qt abort from the user closing the window** —
both surface identically with no traceback. ✅ **Verified** (observed both). Read
`happypanda.log` and the message handler's output, not the exit code.

### Build and tooling

- `HappyPanda.spec` excludes 14 PyQt5 submodules **by name** and sets
  `hiddenimports=['PyQt5.sip']`. Both need rewriting. ✅ **Verified** by reading the spec.
- Whether the PyInstaller build succeeds and the frozen exe runs under PyQt6 is
  ⚠️ **Unverified** — never attempted.
- Whether `res/style.css` renders identically under Qt6's stylesheet engine is ⚠️ **Unverified**.
- Whether the non-Qt dependencies (`watchdog`, `Send2Trash`, `py7zr`, `robobrowser`, Pillow and its
  JXL/AVIF plugins) are affected is ⚠️ **Unverified**, though none of them import Qt.

---

## 6. Constraint compliance checklist

Checked against the four Core Constraints in `CLAUDE.md`.

| Core constraint | How this design complies |
|-----------------|--------------------------|
| **1. Writes to the user's real library** | No phase changes gallery paths, moves, renames, or recycle-bin calls. The one behavioural risk is a rescoping error inside a *confirmation* dialog — a mis-scoped `QMessageBox.StandardButton.Yes` comparison could make a destructive prompt read the wrong answer. §8 names the delete/move confirmations as mandatory manual checks. |
| **2. Gallery database is the only copy** | Nothing in this migration touches `gallerydb` schema or queries; `gallerydb.py` carries 0 enum sites. Q3+ shakedown must nonetheless run against a **copy** of the database, never the live one. |
| **3. e-hentai request budget** | Untouched. `fetch.py` and `pewnet.py` use Qt only for `QObject`/`pyqtSignal`, both of which survive under PyQt6 unchanged — 0 enum sites in either. No query, pacing, or `begin_lock` behaviour is in scope. |
| **4. Settings are plumbed through four places** | Q4 **removes** a setting rather than adding one, and the same rule applies in reverse: `FORCE_HIGH_DPI_SUPPORT` must come out of `app_constants.py:78`, `settingsdialog._make_*` (`:1509–1512`), `restore_options` (`:321`) and `accept` (`:644–645`), plus a `CHANGELOG.md` entry. Missing one leaves a dead checkbox that silently writes an ignored ini key. |

---

## 7. Phased implementation plan

| Phase | Scope | Effort | Depends on | Status |
|-------|-------|:------:|------------|--------|
| **Q0 — Tooling** | `misc/check_qt_enums.py` and `tests/test_qt_scoping.py`. The gate landed in two halves: the resolve-and-invariant tests were green from the first commit, and the zero-unscoped assertion was added once Q2 finished, so the suite is never red. | 🟢 | — | ✅ 2026-09-10 |
| **Q1 — Port the gate** | `misc/gui_smoke.py`: 15 enum sites, `QMouseEvent`→`QPointF`, and `from PyQt5 import sip` — a bare `import sip` only ever worked because PyQt5 aliases it into `sys.modules`. | 🟢 | Q0 | ✅ 2026-09-10 |
| **Q2 — Forward-compatible codemod** | 610 edits, still on PyQt5: 503 class-keyed and 81 instance-level enum sites plus the 26 removed-API swaps. Landed as one commit per module, renames separated from behavioural swaps. | 🟡 | Q1 | ✅ 2026-09-10 |
| **Q3 — Switch the binding** | The edits from §4 plus `requirements.txt` and `HappyPanda.spec`, and the three §5 families v1.0 missed. `pytest`, both smoke harnesses and the scoping gate all pass on PyQt6 6.11.0 / Qt 6.11.2, and the app launches. | 🟡 | Q2 | ✅ 2026-09-10 |
| **Q4 — Retire `FORCE_HIGH_DPI_SUPPORT`** | Four-place settings removal per Core Constraint 4, plus CHANGELOG. Separate commit — it is a user-visible behaviour change, not part of the port. Q3 already deleted the two `setAttribute` calls, so the setting is **inert but still wired**: the checkbox saves a value nothing reads. | 🟢 | Q3 | — |
| **Q5 — Shakedown** | Drive all 62 widget subclasses by hand against a **copy** of the database. This phase dominates the schedule, and every failure now aborts the process rather than printing (§5). | 🔴 | Q3 | — |

Status values: `—` not started · `In progress` · `✅ YYYY-MM-DD` complete · `⏸️ YYYY-MM-DD`
deliberately not implemented · `⛔ Superseded YYYY-MM-DD — <by what>`. Date every closed phase — an
undated completed phase reads as present tense.

**Q0–Q2 deliver standalone value even if the migration is never finished**: the tree ends up in the
Qt6 dialect, still on Qt5, with a gate preventing regression. That is a strictly better resting
position than today, and it is abandonable at any point. `feat/qt6-migration-prep` holds exactly
that state and is unaffected by anything after it.

**Q3 shipped on `feat/qt6-migration`, and then a blocker appeared.** Startup is roughly four times
slower under PyQt6 — bisected to the model/view insert path, cause still open. Q4 and Q5 are not
worth starting until that is settled, because Q5 in particular is weeks of manual work against a
build that may not be shippable. See [`./QT6_STARTUP_REGRESSION.md`](./QT6_STARTUP_REGRESSION.md).

**Effort is ⚠️ Unverified judgement, not measurement.** Rough shape: Q0–Q2 a few days spread over
several commits; Q3–Q4 small; Q5 realistically 1–2 weeks of real use. The mechanical phases are
predictable because they are verified; Q5 is not, because 62 widget classes have no automated
coverage and each fails only when a user opens that particular dialog.

### Extension roadmap (post-Q5, in intended order)

| Version | Extension |
|---------|-----------|
| **v2** | Adopt Qt6-only capabilities deliberately — native dark-mode palette integration, newer `QRegularExpression` features. |
| **v3+** | GUI test coverage beyond `gui_smoke.py`. Gets its own design doc; it is a larger problem than this migration. |

---

## 8. Verification checklist (MUST re-verify before implementation)

Nothing here has been confirmed by running Happypanda under Qt6. Before Q3:

1. **Does the app launch under PyQt6 at all?** Everything in §4 and §5 is API-level probing. No
   window has been painted. This is the single largest unknown.
2. **Do the 7 custom painters render correctly?** `gallery.py:382,729` and
   `misc.py:147,220,400,973,1826`. Qt6 changed high-DPI pixmap handling and made scaling always-on;
   ⚠️ **Unverified** whether the gallery grid, star ratings and type badges still lay out correctly.
3. **Does `res/style.css` still apply?** ⚠️ **Unverified**.
4. **Does the PyInstaller build produce a working exe?** ⚠️ **Unverified**. Note CLAUDE.md's warning
   that a frozen build never enables Python's UTF-8 mode, so encoding checks run from a shell are a
   false green.
5. **Do the destructive confirmations still read the right answer?** Per Core Constraint 1, check
   delete, move and bulk-removal prompts explicitly — a mis-scoped `StandardButton` comparison is
   silent data loss, not a cosmetic miss.
6. **Are the instance-level enum sites exhausted?** All 81 were rewritten in Q2 and
   `tests/test_qt_scoping.py` now checks that each names a real scope and member — but only a
   `self` receiver is checked against its own class, so a scope that is real yet wrong for the
   object it is read off still surfaces only when that widget is built.
7. **Is Qt 5.15 actually EOL for this project's purposes?** The §3 Option C rationale is
   ⚠️ **Unverified** against Riverbank's current support statement. Worth confirming, since it is
   the motivation for the whole exercise.
8. **Do the int-typed parameters still accept an enum member?** PyQt5's enums are ints, so
   `setFrameStyle(QFrame.Shape.StyledPanel)` is fine today; PyQt6's are Python enums, and an
   `int` parameter is where that bites. The call sites are `misc.py:191,209,1501`,
   `io_misc.py:766`, and the `QListWidgetItem.ItemType.Type` / `QTableWidgetItem.ItemType.Type`
   default arguments at `misc.py:2623,2629`. Deliberately left alone: ⚠️ **Unverified** either
   way without PyQt6 installed, and both candidate fixes carry their own risk —
   `setFrameShape()` is **not** equivalent (✅ **Verified**: `setFrameStyle(StyledPanel)`
   leaves `frameShadow()` 0, `setFrameShape(StyledPanel)` leaves it 16), and an `int()` wrapper
   is noise if the enums turn out to be `IntEnum`. Failure here is a loud `TypeError` at the
   call, not a silent one.
9. **Re-run the §4 back-test against whatever PyQt5 and PyQt6 versions are current then.** The
   517/0 result is pinned to PyQt5 5.15.11 and PyQt6 6.11.0.
10. **Would a leftover Qt5 site still be reported with qtpy loaded?** A full `pytest tests/ -q`
    runs with the shim in the process (§4), and the checker builds its Qt5-spelling universe from
    `dir(cls)`, which promotion changes. ⚠️ **Unverified**: reintroduce one unscoped site
    deliberately and confirm the suite goes red. Until that is done, the scan is trustworthy only
    when run on its own.

### Reproducing the analysis

`misc/check_qt_enums.py` is this resolver, committed. It runs against whichever binding is
installed and needs no probe environment:

```sh
venv/Scripts/python.exe misc/check_qt_enums.py            # per-file counts
venv/Scripts/python.exe misc/check_qt_enums.py --sites    # every site and its replacement
venv/Scripts/python.exe misc/check_qt_enums.py --instance # the receiver-keyed review list
```

**The v1.0 recipe above only worked on PyQt6, and silently found nothing on PyQt5.** Two reasons,
both ✅ **Verified**: PyQt5's nested scopes are `sip.enumtype` objects, not `enum.Enum`
subclasses, so the `issubclass(s, enum.Enum)` test never fires; and `dir()` on one of them lists
`int` methods rather than its members, so the member universe has to be built from each *class's*
own attributes instead. The committed resolver does both.

Read files with `encoding='utf-8-sig'` — 7 of the 25 files scanned carry a UTF-8 BOM and
`ast.parse` rejects it otherwise. A codemod must also split lines the way `ast` numbers them
(`splitlines`, not a split on one terminator): a file with mixed endings otherwise desyncs, and
every edit after the first odd line out lands on the wrong line.

---

## 9. Rejected alternatives

| Alternative | Why rejected | Date |
|-------------|--------------|------|
| **PySide6** | Erases the 517 enum edits (verified: forgiving enums work), but costs 106 `pyqtSignal`→`Signal` edits that are **not** forward-compatible, plus loss of `QVariant` and `qRound`. Converts a provable incremental migration into a big-bang one, and leaves the enum debt to pay later anyway. | 2026-09-09 |
| **Stay on PyQt5 indefinitely** | Cost does not shrink with time; every new dialog adds enum sites. Qt 5.15 open-source support is ended (⚠️ unverified). | 2026-09-09 |
| **Big-bang switch, then fix** | Measured as unnecessary: 98% of edits are forward-compatible (verified 517/0 on PyQt5). A big-bang leaves ~572 unverified edits and a non-booting app, with no way to tell a rescoping typo from a genuine Qt6 behaviour difference. | 2026-09-09 |
| **`hasattr` compat shims for the residual 11 edits** | Only ~11 edits and 4 import statements; a compat module for that is debt that must be remembered and deleted. Better to take them at switch time. | 2026-09-09 |
| **`qtpy` abstraction layer** | Would decouple the codebase from the binding, but adds an indirection layer to a single-target desktop app, and does not remove the enum work — QtPy targets the scoped spelling too. Note it is **already installed**, as a transitive dependency of `qtawesome`, so the cost is pinning rather than adding it. ⚠️ **Unverified** — considered on reasoning, not prototyped. | 2026-09-09 |

---

## Document History

* **v1.6** - qtpy, pulled in by qtawesome, patches the Qt5 spelling back onto PyQt6 at import:
  every scoped enum member is copied onto its class unscoped, and the removed point accessors are
  restored. So the app running is not evidence that the conversion is complete - one
  `QMouseEvent.globalPos()` site survived from Q3 to now without ever raising. §4 gained the
  subsection, §2's gate table now says which gate can actually see a missed site, and §8 gained
  the open question of whether the scan still reports one with the shim in the process. The
  header had also drifted to 1.3 while this list already ran to v1.5.
* **v1.5** - Rebased onto `feat/qt6-migration-prep`. The two smoke harnesses the base branch had
  grown since Q3 named PyQt5 in their imports and now name PyQt6.
* **v1.4** - Q3 shipped. §5 gained the three families v1.0 missed (`QPalette.Background`,
  `Qt.Orientations`, `QByteArray.append`) and the abort-on-unhandled-exception behaviour change.
  Q4/Q5 blocked on the startup regression.
* **v1.3** - Rebased onto `feat/better-versions-scan`. The 15 enum sites that branch had
  added since the audit were rescoped, `misc/app_smoke.py` joined the scanned modules, and the
  `exec_` alias it installed on `QMessageBox` went with the last caller. §8's line references
  re-derived.
* **v1.2** - Review follow-ups: a project class deriving from Qt hid an unscoped site from the
  checker (`misc_db.py:379`, an import-time failure under Qt6); the scoping gate extended to the
  receiver-keyed sites; §8 gained the int-typed-parameter question.
* **v1.1** - Q0-Q2 implemented. Counts re-derived from the AST: 503 class-keyed sites (not 517)
  and 81 instance-level ones (not ~15). `QPalette.Background` added to §5 as a tenth removed-API
  family. §8's reproduction recipe corrected - it only ever worked on PyQt6.
* **v1.0** - Initial draft

---

**Last Updated:** 2026-09-12  
**Next Review:** when the startup regression is settled, or on any PyQt5/PyQt6 version bump that invalidates the §4 back-test
