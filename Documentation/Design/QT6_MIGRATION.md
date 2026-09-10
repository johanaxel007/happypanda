# Qt5 → Qt6 Migration Design

**Version:** 1.1  
**Date:** 2026-09-10  
**Status:** In progress — Q0, Q1 and Q2 are complete: the tree is written in the Qt6 dialect and still runs on PyQt5. The binding switch (Q3+) needs the §8 re-verification first.  
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
| Modules importing Qt | 16 of 19 in `version/`, plus `misc/gui_smoke.py`. Only `settings.py`, `asm_manager.py` and `database/db.py` are Qt-free. ✅ **Verified** by AST scan of every `from PyQt5.* import`. |
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
| `pytest tests/ -q` | 283 pass, 4 pre-existing failures in `test_db.py::test_init_db`. ✅ **Verified** by running it at the start of Q0. | **Was weak; no longer.** No test referenced Qt at all before Q0. `tests/test_qt_scoping.py` now resolves every scoped site against the installed binding and asserts no unscoped one is left, which is what turns a lazy paint-time AttributeError into a red suite. |
| `misc/gui_smoke.py` | Settings dialog, gallery chooser, better-version review list, two crash regressions. | **The only GUI gate.** Ported in Q1, so it now exercises the Qt6 dialect; it still imports PyQt5 by name, which is a Q3 edit. |
| Launching the app | Everything else. | The real gate. Manual, and per CLAUDE.md expects a multi-minute library scan. |

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
  `QMouseEvent.globalPos()` does not.
- **`Qt.ItemDataRole.UserRole + N` still yields a plain int.** All 69 custom-role arithmetic sites
  are safe once rescoped — they sit in `misc.py` (34), `gallery.py` (28), `io_misc.py` (4),
  `app.py` and `misc_db.py`.
- **`Qt.Key` is int-compatible** (`isinstance(Qt.Key.Key_Delete, int)` is `True`), so
  `event.key() == Qt.Key.Key_Delete` keeps working — `event.key()` returns a bare `int` in PyQt6.
- **`Qt.KeyboardModifier` is a flag and is *not* an int.** `modifiers() == ShiftModifier` compares
  fine flag-to-flag, but any code doing integer arithmetic or bitwise mixing on modifiers will
  break. No such site was found in this codebase, ⚠️ **Unverified** as exhaustive.

### The failure mode this plan is designed around

Rescoping errors fail **lazily** — `AttributeError` at the moment a widget paints or a menu opens,
not at import. A run can start cleanly and die three dialogs deep. Landing the enum work on Qt5,
where the app can actually be driven, is what converts that from a debugging problem into a
testing problem.

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
| `AA_EnableHighDpiScaling` / `AA_UseHighDpiPixmaps` | 2 | Gone — Qt6 always scales |
| `exec_()` | 11 | `exec()`. None of them is a `QMessageBox` — every message box already called `.exec()`, so the rename could not disturb what `gui_smoke.py` monkeypatches |
| `QAction` / `QActionGroup` / `QShortcut` | 4 names, 2 import statements | Moved `QtWidgets` → `QtGui` |

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
| **Q3 — Switch the binding** | The ~11 edits from §4, `requirements.txt`, and `HappyPanda.spec`. First point at which the app has never run before. | 🟡 | Q2 | — |
| **Q4 — Retire `FORCE_HIGH_DPI_SUPPORT`** | Four-place settings removal per Core Constraint 4, plus CHANGELOG. Separate commit — it is a user-visible behaviour change, not part of the port. | 🟢 | Q3 | — |
| **Q5 — Shakedown** | Drive all 62 widget subclasses by hand against a **copy** of the database. This phase dominates the schedule. | 🔴 | Q3 | — |

Status values: `—` not started · `In progress` · `✅ YYYY-MM-DD` complete · `⏸️ YYYY-MM-DD`
deliberately not implemented · `⛔ Superseded YYYY-MM-DD — <by what>`. Date every closed phase — an
undated completed phase reads as present tense.

**Q0–Q2 deliver standalone value even if the migration is never finished**: the tree ends up in the
Qt6 dialect, still on Qt5, with a gate preventing regression. That is a strictly better resting
position than today, and it is abandonable at any point. As of 2026-09-10 that is where the tree
sits — Q0–Q2 are done and Q3 has not started.

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
   `misc.py:136,209,389,961,1810`. Qt6 changed high-DPI pixmap handling and made scaling always-on;
   ⚠️ **Unverified** whether the gallery grid, star ratings and type badges still lay out correctly.
3. **Does `res/style.css` still apply?** ⚠️ **Unverified**.
4. **Does the PyInstaller build produce a working exe?** ⚠️ **Unverified**. Note CLAUDE.md's warning
   that a frozen build never enables Python's UTF-8 mode, so encoding checks run from a shell are a
   false green.
5. **Do the destructive confirmations still read the right answer?** Per Core Constraint 1, check
   delete, move and bulk-removal prompts explicitly — a mis-scoped `StandardButton` comparison is
   silent data loss, not a cosmetic miss.
6. **Are the instance-level enum sites exhausted?** ~15 is a lower bound (§4). Expect stragglers.
7. **Is Qt 5.15 actually EOL for this project's purposes?** The §3 Option C rationale is
   ⚠️ **Unverified** against Riverbank's current support statement. Worth confirming, since it is
   the motivation for the whole exercise.
8. **Re-run the §4 back-test against whatever PyQt5 and PyQt6 versions are current then.** The
   517/0 result is pinned to PyQt5 5.15.11 and PyQt6 6.11.0.

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

* **v1.0** - Initial draft
* **v1.1** - Q0-Q2 implemented. Counts re-derived from the AST: 503 class-keyed sites (not 517)
  and 81 instance-level ones (not ~15). `QPalette.Background` added to §5 as a tenth removed-API
  family. §8's reproduction recipe corrected - it only ever worked on PyQt6.

---

**Last Updated:** 2026-09-10  
**Next Review:** when Q3 starts, or on any PyQt5/PyQt6 version bump that invalidates the §4 back-test
