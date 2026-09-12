# PyQt6 Startup Performance Regression

**Version:** 1.3  
**Date:** 2026-09-12  
**Status:** Proposed design — not implemented.  
**Target:** PyQt6 6.11.0 / Qt 6.11.2 on Python 3.14.7 (baseline: PyQt5 5.15.11 / Qt 5.15.2)

> Switching the binding to PyQt6 makes database startup **roughly four times slower** — 12.1s
> against 39–52s for the gallery load alone, and about 26s against about 126s across all three
> startup phases on a 19,974-gallery library. **The cost lands entirely in Qt-free Python running
> on worker threads, not in any Qt call**: the one Qt call in the loop, `insertRows`, is 0.01s
> under both bindings.
>
> **Bisecting the binding now names where it enters: Qt 6.7.** PyQt6 6.6.1 / Qt 6.6.3 loads the
> same library in about 16s — within about 1.3× of the PyQt5 floor and not worth blocking a
> migration over — while the very next release, 6.7.0, takes about 38s, and it worsens to about
> 47s by 6.11 (§5). So this is not a PyQt5-versus-PyQt6 architectural difference.
>
> Twenty-five candidate causes were ruled out by measurement (§4, §5, §11), and every attempt to
> reproduce the cost outside the application fails — including a faithful model/view replica
> whose Python callback counts come out **identical** between the two bindings. What changed
> inside Qt 6.7 is **no longer** open at the granularity this project can reach: profiling the
> GUI thread's own event delivery shows the cost is **queued meta-call delivery**. The application
> issues the *same* number of them under both versions — 112 to the sort/filter proxy, 154 to
> PyQt's lambda-proxy receivers — and each one costs **about twice as much** under 6.7 (§11).
>
> That makes pinning Qt 6.6 the fallback rather than the answer: **112 proxy invalidations per
> library load is the application's own doing**, and cutting them helps under every Qt version.
> Phase S6.

**Audited:** 2026-09-10, at commit `7ba4813` (branch `feat/qt6-migration`).
**Amended:** 2026-09-10 — phases S0–S3 executed; §5 and §7 rewritten around the result.
**Amended:** 2026-09-12 — phase S5 executed: nine further subtractions from the running
application, all null, and a GUI-thread event profile that names queued meta-call delivery as the
mechanism. §11 carries it, with the candidates left untested.
**Amended:** 2026-09-12 — phase S4 executed. The model/view harness rung was built and
committed (`misc/qt_modelview_bench.py`) and does not reproduce; the binding was bisected across
PyQt6 6.2–6.11 against the running application, three runs per release with the startup scan and
the watchdog monitor disabled. §5 gained the harness result and the bisection curve, §10 the
adjacent tab-switch finding.
Findings come from instrumenting `version/gallerydb.py` (`fetch_galleries`, split into four
timers) and `version/gallery.py` (`GridDelegate.paint`, call counter), applying the identical
patch to both `feat/qt6-migration` and `feat/qt6-migration-prep`, and running the real application
against the same database under each binding. Supporting probes: a stack sampler over
`sys._current_frames()`, two standalone harnesses replicating the startup architecture with and
without a Qt event loop, and direct `sqlite3`, `NtQueryTimerResolution` and `devicePixelRatio`
measurements. All instrumentation was reverted. The one artefact that ships is
`misc/qt_modelview_bench.py`, the model/view harness S4 built.

**Relationship to other documents:**

- [`../../ROADMAP.md`](../../ROADMAP.md) — carries the pointer to this doc.
- [`./QT6_MIGRATION.md`](./QT6_MIGRATION.md) — the migration this blocks; its §7 phase Q3 is what
  introduced the regression, and its §8 item 1 asked whether the app runs under Qt6 at all.
- [`../../CLAUDE.md`](../../CLAUDE.md) — the Core Constraints checked in §6.

---

## 1. Goals & non-goals

### Goals

1. **Preserve the measurement** — the attribution cost a dozen application runs across two
   branches and two bindings, and is expensive to redo.
2. **Record what is already excluded** so a later session does not re-test a dead hypothesis.
3. **Name the next experiment** precisely enough that it can be run without re-deriving the setup.

### Non-goals (v1)

- **Fixing the regression.** No cause is identified yet; a fix cannot be designed against an
  unknown mechanism.
- **Deciding whether to ship Qt6 regardless.** That is a judgement for after the cause is known —
  the size of the regression may or may not survive the explanation.
- **Optimising startup generally.** `gen_galleries` issues one SQL query per gallery through
  `ListDB.query_gallery`, which is why the Qt-free baseline is 3.7s rather than 0.5s. Worth its
  own entry; unrelated to this regression, which is a *ratio* between bindings.

---

## 2. Current state (what is measured)

**Claim legend, used throughout this document:**

| Tag | Meaning |
|-----|---------|
| ✅ **Verified** | Reproduced by executing code. The method is named inline. |
| ⚠️ **Unverified** | Static reading, grep, or reasoning. Plausible, not executed. Treat as a lead. |

### The library under test

| Area | State |
|------|-------|
| Galleries | 19,974 rows in `series`. ✅ **Verified** by `SELECT COUNT(*)`. |
| Chapters | 19,999 rows. ✅ **Verified** the same way. |
| Tag mappings | 123,077 rows in `series_tags_map`. ✅ **Verified**. |
| Gallery lists | **0** rows in both `list` and `series_list_map`, so `ListDB.query_gallery`'s loop body never executes — but it still issues its per-gallery `SELECT`. ✅ **Verified**. |
| Database file | 20.0 MB. ✅ **Verified** by `os.path.getsize`. |

### Startup timings, whole phases

From `utils.Stopwatch` lines already in `gallerydb.DatabaseStartup.startup`. ✅ **Verified** — read
out of `happypanda.log` and its two rotated predecessors.

| Phase | PyQt5 | PyQt6 |
|-------|-------|-------|
| Loading galleries | 11.3, 11.5, 11.5, 11.8, 12.9s | 45.2, 48.4s |
| Loading chapters | 1.8, 2.1, 2.8, 3.0, 3.4s | 11.5, 14.5s |
| Loading tags | 8.7, 11.6, 12.0, 14.0, 15.3s | 62.8s |

### Startup timings, split within `fetch_galleries`

The same instrumentation patch on both branches, same database, same machine. ✅ **Verified**.

| Run | Binding | `select` | `fetchall` | `gen_galleries` | `insertRows` | total |
|-----|---------|---------:|-----------:|----------------:|-------------:|------:|
| 20:55 | PyQt5 | 0.27s | 2.99s | 8.78s | 0.02s | 12.10s |
| 20:57 | PyQt5 | 0.24s | 2.34s | 7.41s | 0.01s | 10.04s |
| 20:47 | PyQt6 | 0.31s | 13.55s | 25.16s | 0.01s | 39.07s |
| 20:58 | PyQt6 | 0.33s | 17.07s | 25.23s | 0.01s | 42.69s |
| 20:50 | PyQt6 | 0.31s | 18.66s | 33.80s | 0.01s | 52.83s |

The 20:50 row ran under the stack sampler, which adds its own overhead; it is listed for
completeness and should not be read as the PyQt6 baseline.

**The shape of the result is the finding.** `select` is a queued call onto the database thread and
is unchanged. `insertRows` — the only Qt API call in the loop — is 0.01s under both. The entire
difference sits in `c.fetchall()` and `gen_galleries`, which are plain Python and `sqlite3`.

### Gates

| Gate | Verdict for this investigation |
|------|-------------------------------|
| `pytest tests/ -q` | 344 pass, 4 pre-existing `test_init_db` failures. ✅ **Verified** 2026-09-12; the 289 recorded in v1.1 is stale, the suite has grown since. Says nothing about startup cost — no test loads the library. |
| `misc/gui_smoke.py` | `GUI SMOKE OK` under PyQt6. ✅ **Verified**. Builds no gallery model and loads no galleries, so it cannot see this at all. |
| Launching the app | The only gate that observes it, and the timings above come from `happypanda.log`. |

---

## 3. Decision: is the regression caused by the binding?

Pivotal because it decides whether this blocks the migration or is an artefact of the machine, and
because the first four measurements were taken across a window in which other things changed.

### Option A — an environmental difference, not the binding (rejected)

- ✅ **Genuinely plausible at first.** The initial PyQt6 numbers were taken minutes after
  installing 78 MB of Qt6 DLLs, on a machine that had been running test suites all session, and
  the first PyQt6 run performed a full library scan concurrently while an earlier PyQt5 run had
  not. Any of those could inflate a startup measurement.
- ❌ **Refuted by controlled re-measurement.** The identical instrumentation patch was applied to
  both branches and run back to back against the same database on the same machine within four
  minutes: 12.10s and 10.04s under PyQt5, 39.07s and 42.69s under PyQt6. ✅ **Verified**.
- ❌ **The scan confound was checked directly** — the 45.2s run logged **zero** "already exists or
  ignored" lines, so nothing was competing with it. ✅ **Verified**.

### Option B — the binding ✅ **CHOSEN**

The ratio survives every control available: same commit-for-commit code path, same database, same
machine, same instrumentation, interleaved in time. The only variable left is which binding is
imported.

What that does **not** establish is a mechanism. §4 is the list of mechanisms already excluded,
and §5 is the reproduction that ought to have exhibited it and does not.

---

## 4. Hypotheses excluded, with the measurement that excluded each

Every row is ✅ **Verified** — each was executed, not reasoned about. This is the section that
saves a later session the most time.

| # | Hypothesis | Measurement | Result |
|---|------------|-------------|--------|
| 1 | A concurrent library scan competed for the database thread | Counted scan lines in the 45.2s run's log window | **0 lines** — nothing competing |
| 2 | Filesystem: `gen_galleries` stats every gallery path | Timed `os.path.exists` over all 19,974 paths | **0.38s** |
| 3 | `sqlite3` itself, or the database being large | Ran the identical 20 batched `SELECT`+`fetchall` with plain `sqlite3` | **0.30s** (0.10s unbatched) |
| 4 | Debug logging — `DBBase.execute` calls `log_d('DB Query: {}'.format(args))` per query | Grepped all three log files for `DB Query` | **0 lines**; level is INFO, and the `-d` flag was not used |
| 5 | Qt6's always-on high-DPI scaling enlarges what is painted | Queried `devicePixelRatio` and `logicalDotsPerInch` per screen | **1.0 and 96 DPI** on both monitors |
| 6 | The grid delegate paints far more under Qt6 | Counted `GridDelegate.paint` calls during the phase, both bindings | PyQt5 **240**, PyQt6 **80** and **0** — fewer paints, still 4× slower |
| 7 | The Qt model insert is the cost | Timed `gallery_model.insertRows` separately | **0.01s** under both |
| 8 | GIL preemption granularity | `sys.setswitchinterval(0.1)` for a whole run | **40.94s** — unchanged |
| 9 | Windows timer resolution differs (affects thread waits, not painting) | `NtQueryTimerResolution` before and after creating a `QApplication`, both bindings | **0.997 ms** in all four cases |
| 10 | Merely having a `QApplication` slows threaded Python | Ran the Qt-free workload with one created | **3.65s** (PyQt6), **3.69s** (PyQt5), **3.68s** (no Qt) |

Hypothesis 6 is worth singling out: PyQt6 painted *fewer* delegate items than PyQt5 in every run,
and one PyQt6 run painted none at all while still taking 40.94s. Any explanation resting on
rendering cost is contradicted by that.

---

## 5. The reproduction that fails to reproduce

Two standalone harnesses replicate the startup architecture with no application code. Both are
scratch scripts and were not committed; §8 records how to rebuild them. A third, the model/view
rung S4 added, is committed as `misc/qt_modelview_bench.py`.

The architecture under test, which is what `DatabaseStartup` does per 1000-gallery batch:

```
  loader thread                 method queue              database thread
  ─────────────                 ────────────              ───────────────
  call(SELECT …)      ─────────────▶ put ──────────────▶  conn.execute()
  c.fetchall()   ◀── cursor returned across the thread boundary
  call(gen_galleries) ─────────────▶ put ──────────────▶  per row: one SELECT
                                                          + os.path.exists()
```

| Harness | What it adds | PyQt5 | PyQt6 |
|---------|--------------|------:|------:|
| Queue + worker thread, no Qt imported | the architecture alone | — | — (3.68s with no binding) |
| …plus a `QApplication` | the binding loaded and initialised | 3.69s | 3.65s |
| …plus a running event loop, workload moved onto a worker thread | the last structural difference from the app | **3.67s** | **3.69s** |

The third row is the closest reproduction available and the two bindings are indistinguishable in
it. ✅ **Verified**. So the trigger requires something the real application does that a
`QApplication`, a running event loop and a worker thread doing this exact workload do not.

### What the stack sampler showed

Sampling `sys._current_frames()` every 20 ms during a PyQt6 startup. ✅ **Verified**:

- the loader thread's hottest frame is `gallerydb.py` at the `c.fetchall()` line
- the database thread is simultaneously hot in `database/db.py` inside `DBBase.execute`
- the GUI thread sits in `main.py` inside `start_main_window`, i.e. below Python in Qt C++
- the remaining threads — watchdog monitor, download-manager workers — are in `threading.wait`
  or `read_directory_changes`

Two Python threads being hot at once on a connection they share is consistent with contention, but
the harnesses above contend identically and do not slow down. ⚠️ **Unverified** as an explanation.

### The harness was later extended to the app's actual threading shape

`DatabaseStartup` does not run on a plain thread: `app.py:71-75` creates a `QThread`, moves the
object onto it and invokes `startup` through a queued signal. The harness was extended to match — a
`QObject` moved to a `QThread`, started via `thread.started`. ✅ **Verified**: PyQt5 4.37s, PyQt6
4.27s. The QThread shape is not the trigger either.

### What the bisection found

Subtracting subsystems from the running application (§7) localised it in three runs.

| Configuration | `fetchall` | `gen_galleries` | Verdict |
|---------------|-----------:|----------------:|---------|
| PyQt6 baseline | 13.30s | 25.64s | — |
| PyQt6, watchdog monitor disabled | 16.96s | 30.96s | monitor excluded |
| PyQt6, download manager given 0 workers | 12.46s | 30.51s | download manager excluded |
| **PyQt6, view loop skipped** | **0.14s** | **5.25s** | **the cost is here** |
| PyQt5, view loop skipped | 0.12s | 5.74s | identical floor |

✅ **Verified**, all five. Removing `view.gallery_model.insertRows(...)` from the batch loop takes
PyQt6 from about 39s to about 5.6s, and PyQt5's floor for the same configuration is about 6.1s —
**the two bindings are indistinguishable once the view is out of the loop.** So the model/view
insert path costs roughly 6s under PyQt5 and roughly 34s under PyQt6.

The trap in reading this: `insertRows` itself measures 0.01s in every run. The expense is not the
call, it is what the call schedules — the proxy-model and view work that follows on the GUI
thread, which then starves the loader and database threads.

### Excluded *inside* the view path

| Hypothesis | Measurement | Result |
|------------|-------------|--------|
| PyQt6 runs the Python filter callback more often | Counted `SortFilterModel.filterAcceptsRow` calls | PyQt5 **55,684**, PyQt6 **16,791** — fewer, still slower |
| PyQt6 paints delegate items more often | Counted `GridDelegate.paint` calls | PyQt5 **240**, PyQt6 **80**, and **0** on one run |
| `setDynamicSortFilter(True)` re-filters on every insert | Froze it for the load, re-enabled and `invalidate()`d after | **43.9s** — no improvement |

⚠️ **Unverified** as an explanation, but the shape is consistent across all five: PyQt6 makes
*fewer* transitions into Python than PyQt5 and is still several times slower, so the additional
time is being spent inside Qt6's own model-view machinery rather than in this project's callbacks.

### The rung the ladder was missing

The harness ladder above went queue, then `QApplication`, then a running event loop, then a
`QThread` — and never added a model or a view, which is the one subsystem the bisection then
blamed. `misc/qt_modelview_bench.py` is that rung, committed rather than thrown away this time: a
table model with the same columns and roles, a sorted proxy with a Python `filterAcceptsRow`, an
icon-mode `QListView` and a `QTableView` both attached to that one proxy, and a loader object on
its own `QThread` issuing `insertRows` across the thread boundary while the GUI thread runs the
event loop. 19,974 rows in batches of 1000, no database and no application code.

**It does not reproduce either, and the callback counts come out all but identical.**
✅ **Verified**, one counted run per configuration — counting is off by default because it runs
in the two hottest callbacks and would tax the thing being measured:

| Proxy sort role | Binding | loader work | `insertRows` | settle | `filterAcceptsRow` | `data()` |
|-----------------|---------|------------:|-------------:|-------:|-------------------:|---------:|
| title (a `str`) | PyQt5 | 4.55s | 0.01s | 0.01s | 249,922 | 1,627,920 |
| title (a `str`) | PyQt6 | 5.38s | 0.01s | 0.35s | 249,922 | 1,627,920 |
| date added (a `QDateTime`) | PyQt5 | 4.16s | 0.01s | 0.01s | 249,922 | 2,015,166 |
| date added (a `QDateTime`) | PyQt6 | 4.36s | 0.01s | 0.00s | 249,922 | 2,015,250 |

`filterAcceptsRow` matches exactly in all four, and `data()` matches exactly on the title role and
to within 84 calls in two million on the date role. Uncounted repeats spread 4.1–5.6s under PyQt5
and 4.2–5.5s under PyQt6 — **the run-to-run noise is larger than the difference between the
bindings**, which is the finding.

The second pair matters most. The application does **not** sort on `DisplayRole`: `current sort`
ships as `date_added`, so the proxy's comparator reads `GalleryModel.DATE_ADDED_ROLE`, whose
branch re-formats the stored date and re-parses it with `QDateTime.fromString` on **every**
comparison (`gallery.py:580-583`). That is the most expensive value the binding has to marshal in
the whole path, and 1,765,320 of them per run cost the two bindings the same. ✅ **Verified**
— counted in the application as well: one PyQt6 startup made 977,269 `data()` calls, 557,856 of
them on that role and **0** on `DisplayRole`.

### Excluded by the harness

| Hypothesis | Measurement | Result |
|------------|-------------|--------|
| The model/view insert path is inherently slower under PyQt6 | A faithful replica of it, 19,974 rows, both bindings | **within the run-to-run noise** — indistinguishable |
| Per-call sip conversion overhead in `data()` | The same replica sorting on a role that builds a `QDateTime` per comparison | **4.16s vs 4.36s** over 1,765,320 round-trips |
| PyQt6 reads the model more often | `data()` and `filterAcceptsRow` counted in the replica | **Identical**, 1,627,920 and 249,922 either way |

### Where the regression enters: Qt 6.7

Black-box measurement inside the path being exhausted, the remaining cheap question was *which
release*. Each row is the running application against the same 19,974-gallery database, three
launches, with the startup scan and the watchdog monitor disabled so nothing competes.
✅ **Verified**.

| Binding / Qt runtime | `Loading galleries`, three runs | mean |
|----------------------|---------------------------------|-----:|
| PyQt5 5.15.11 / Qt 5.15.2 | 11.3, 11.5, 11.5, 11.8, 12.9s (§2) | ~11.8s |
| PyQt6 6.5.3 / Qt 6.5.3 | 26.68, 24.85, 24.70s | 25.4s |
| **PyQt6 6.6.1 / Qt 6.6.3** | **17.17, 16.10, 14.56s** | **15.9s** |
| PyQt6 6.7.0 / Qt 6.7.0 | 36.95, 41.70, 36.25s | 38.3s |
| PyQt6 6.7.1 / Qt 6.7.3 | 36.19, 30.43, 30.83s | 32.5s |
| PyQt6 6.9.1 / Qt 6.9.2 | 45.00, 49.81, 48.51s | 47.8s |
| PyQt6 6.11.0 / Qt 6.11.2 | 49.07, 43.52, 47.55s | 46.7s |

The curve is not monotonic: **6.6 is the floor of the Qt6 range and 6.5 is worse than it**, so
something improved in 6.6 and something else regressed hard in 6.7. The step at 6.6 → 6.7 is
2.4× and lands on the *first* 6.7 release, not a later patch.

**6.6.1 is within about 1.3× of PyQt5.** That is an ordinary version-to-version difference, not
the fourfold blocker, which turns the open question from "can this migration ship at all" into
"which Qt does it pin".

Three practical limits found while doing it, all ✅ **Verified**:

- **PyQt6 6.0 and 6.1 cannot be installed here at all.** Neither has a `win_amd64` wheel on PyPI,
  only an sdist needing a local Qt build — so the range is 6.2 upward, not the 6.0–6.11 v1.1
  assumed. Confirmed with `pip download --no-deps`.
- **The application will not run below 6.5.** 6.2.3 and 6.3.1 die at
  `AttributeError: 'QAction' object has no attribute 'setMenu'` (`app.py:636`), and 6.4.2 exits
  139 with nothing logged at all.
- **Binding and Qt runtime cannot be varied independently**, so the step cannot be attributed to
  Riverbank's layer or to Qt's separately. Every 6.2–6.8 wheel declares `PyQt6-Qt6` with no upper
  bound, so a bare pin silently pulls the newest Qt against an old binding; and forcing a crossing
  with `--no-deps` fails to load in both directions — binding 6.6.1 on Qt 6.7.3 raises
  `ImportError: DLL load failed while importing QtGui`, and binding 6.7.1 on Qt 6.6.3 fails on
  `QtCore`. **Pin both halves explicitly on every rung.**

---

## 6. Constraint compliance checklist

| Core constraint (`CLAUDE.md`) | How this investigation complies |
|-------------------------------|--------------------------------|
| **1. Writes to the user's real library** | Not touched. Every measurement is a read: startup loads galleries and never renames, moves or trashes a file. The instrumentation added timers and a counter, no behaviour. |
| **2. Gallery database is the only copy** | Read-only throughout. No schema change, no write outside `gallerydb`, and the standalone harnesses open the database with `sqlite3` for `SELECT` only. The measured 20 MB file is the repository's development database, not a user library. |
| **3. e-hentai request budget** | Not touched. No phase of this work issues a network request; the `temp banned` line in the logs is pre-existing account state observed at startup, not caused here. |
| **4. Settings plumbed through four places** | No setting added, removed or renamed. `DATABASE_STARTUP_FETCH_LIMIT` (default 1000) was read to understand batching and left alone. |

---

## 7. Phased plan — bisect downward from the application

Building the reproduction upward stopped short of the failure (§5), so the remaining approach is
subtraction: start the real application with subsystems disabled until the ratio collapses.

| Phase | Scope | Effort | Depends on | Status |
|-------|-------|:------:|------------|--------|
| **S0 — Re-establish the harness** | Four-timer instrumentation on `fetch_galleries`, applied identically to both branches. | 🟢 | — | ✅ 2026-09-10 |
| **S1 — Disable the monitor** | `enable monitor = False` in `settings.ini`; no code change needed. Excluded it. | 🟢 | S0 | ✅ 2026-09-10 |
| **S2 — Disable the download manager** | `start_manager(0)` in place of 4 workers. Excluded it. | 🟢 | S0 | ✅ 2026-09-10 |
| **S3 — Strip to the loader** | Skip the `manga_views` loop. **Found it** — see §5. | 🟡 | S1, S2 | ✅ 2026-09-10 |
| **S4 — Narrow within the model/view** | Built the missing model/view harness rung — binding-neutral, so three more hypotheses fall — then bisected the binding. **Found the release**: it enters at Qt 6.7, and 6.6.1 is within ~1.3× of PyQt5. See §5. | 🔴 | S3 | ✅ 2026-09-12 |
| **S5 — Name what changed in Qt 6.7** | Nine subtractions from the running application, all null, then a GUI-thread event profile applied identically to 6.6.3 and 6.7.0. **Found the mechanism**: queued meta-call delivery, same count, ~2× the cost per call. See §11. | 🔴 | S4 | ✅ 2026-09-12 |
| **S6 — Cut the meta-calls** | The application invalidates the proxy 112 times during one load. Suppressing that for the duration of the load and invalidating once at the end would remove most of the GUI-thread work at any Qt version. Design work, not measurement — it changes what the user sees while the library loads. | 🟡 | S5 | — |

Effort: 🟢 low (hours, localized) · 🟡 medium (days, several files) · 🔴 high (cross-cutting, or
dominated by manual verification).

Status: `—` not started · `In progress` · `✅ YYYY-MM-DD` complete · `⏸️ YYYY-MM-DD` deliberately
not implemented · `⛔ Superseded YYYY-MM-DD — <by what>`.

**Every phase's gate is the same:** the `TIMING galleries` line in `happypanda.log`, compared
against the S0 baseline. S1–S3 needed PyQt6 runs only, since the question was whether the number
collapses toward the known PyQt5 figure rather than what PyQt5 does. `pytest` and `misc/gui_smoke.py` cannot observe any of
this — neither loads a library — so they serve only to confirm the instrumentation broke nothing.

Each phase is disposable: the instrumentation is reverted at the end and nothing ships. The
deliverable is a named subsystem, which then justifies its own design work.

### Extension roadmap (post-S3, in intended order)

| Version | Extension |
|---------|-----------|
| **v2** | The decision S5 hands over: **cut the meta-call count** (phase S6) so the Qt version stops mattering, or **pin PyQt6 6.6.1 / Qt 6.6.3** and unblock Q4/Q5 on the older Qt. S6 is the better outcome because it also speeds up 6.6, and because the cost it removes is the application's own. |
| **v3+** | The unrelated startup cost `gen_galleries` carries — one SQL query per gallery through `ListDB.query_gallery`, which is most of the 3.7s Qt-free floor. Gets its own entry. |

---

## 8. Open questions

1. **Which Qt change made a queued meta-call twice as expensive?** S5 localised the cost to
   meta-call delivery (§11) but not to a commit. Qt stopped shipping `dist/changes-*` files after
   6.0, and the obvious item in the item-view history — passing the widget to
   `QStyle::pixelMetric()` — was backported to 6.6, 6.5 and 6.2, so it cannot be the step.
   Settling it needs either a Windows native profiler or a local build of qtbase bisected between
   v6.6.3 and v6.7.0. Also unexplained: why 6.6 is *faster* than 6.5, and whether the further
   slide from 6.7 to 6.11 shares this cause.
2. **Does the ratio scale with library size?** Every measurement here is against one 19,974-gallery
   database. A smaller library might show it proportionally or not at all, which would itself be a
   clue. ⚠️ **Unverified** — untested in either direction.
3. **Is it specific to PyQt6 6.11.0 / Qt 6.11.2?** Answered by S4: no. It enters at 6.7.0 and
   worsens through 6.11, and 6.6.1 does not have it (§5).

### Rebuilding the harnesses

Both were scratch scripts. To recreate:

- **Instrumentation** — in `gallerydb.DatabaseStartup`, wrap the four steps of `fetch_galleries`
  in `time.perf_counter()` accumulators on a class-level dict and log it once after the loop.
  Apply the *same* patch to both branches; the file differs between them only by its Qt import.
- **Model/view harness** — `misc/qt_modelview_bench.py`, committed. Takes the binding as its
  first argument and carries a switch per element of the insert fan-out (`--no-view`, `--no-table`,
  `--no-sort`, `--no-refilter`, `--sort-role`, `--count-data`), so the subtraction S3 performed on
  the application can be repeated in seconds.
- **Architecture harness** — a `queue.Queue` pair, one worker thread owning a
  `sqlite3.connect(..., check_same_thread=False)`, and a caller that blocks on the return queue.
  Per batch: `SELECT * FROM series LIMIT n, 1000` on the worker, `fetchall()` on the caller, then a
  per-row `SELECT list_id FROM series_list_map WHERE series_id=?` plus `os.path.exists` back on the
  worker. Take the binding as `sys.argv[1]` and create the `QApplication` before connecting; for
  the event-loop variant, run the workload on a thread and call `qapp.exec()` on the main thread.
- **Stack sampler** — a daemon thread walking `sys._current_frames()` every 20 ms, counting
  `(thread, top frame)` pairs, dumping to a file every 2s. Dump periodically, not via `atexit`;
  the application is killed rather than exited and `atexit` never runs.

---

## 9. Rejected alternatives

| Alternative | Why rejected | Date |
|-------------|--------------|------|
| **Attributing the slowdown to the environment** | Refuted by interleaved back-to-back runs of the same instrumentation on both branches: 12.10s / 10.04s against 39.07s / 42.69s. | 2026-09-10 |
| **Blaming Qt6's always-on high-DPI scaling** | Both monitors report `devicePixelRatio` 1.0 at 96 DPI, so no additional scaling is in force. | 2026-09-10 |
| **Blaming delegate painting** | PyQt6 painted 240 → 80 fewer items than PyQt5, and one 40.94s run painted **zero**. | 2026-09-10 |
| **Raising `sys.setswitchinterval`** | Tried as both diagnosis and candidate workaround at 0.1s; run took 40.94s, unchanged. | 2026-09-10 |
| **Windows timer resolution as the mechanism** | `NtQueryTimerResolution` returns 0.997 ms with and without a `QApplication`, under both bindings. | 2026-09-10 |
| **Building the reproduction upward** | Reached a running event loop with the workload on a worker thread and still measured 3.67s vs 3.69s. Subtraction from the application (§7) replaces it. | 2026-09-10 |
| **The watchdog monitor as the cause** | Disabled via `enable monitor = False`; 16.96s / 30.96s, no better than baseline. | 2026-09-10 |
| **The download manager's four worker threads** | Started with 0 workers; 12.46s / 30.51s, no better. | 2026-09-10 |
| **The QThread shape of the loader** | Harness extended to a `QObject` moved onto a `QThread` and invoked by signal, matching `app.py:71-75`: PyQt5 4.37s, PyQt6 4.27s. | 2026-09-10 |
| **`setDynamicSortFilter` re-filtering on every insert** | Frozen for the whole load and invalidated once afterwards: 43.9s, unchanged. | 2026-09-10 |
| **The view as the place the time goes** | Detaching both views from the proxy entirely recovers only about 15% (34.9s against a 42s baseline at Qt 6.7.0), while removing `insertRows` altogether took PyQt6 from 39s to 5.6s. | 2026-09-12 |
| **The application-wide stylesheet, the blur effect, the spinner, the tooltip role, the view's layout mode and batch size, and the status-bar row callback** | Nine subtractions from the running application at Qt 6.7.0, every one inside the 38-50s run-to-run band; see §11. | 2026-09-12 |
| **`py-spy --native` as the profiler** | py-spy 0.4.2 cannot read Python 3.14: `Failed to find python version from target process`. Profiling `QApplication::notify` replaced it. | 2026-09-12 |
| **The model/view insert path as inherently slower under PyQt6** | A faithful replica — sorted proxy, Python filter, icon list view and table view, cross-thread batched inserts, 19,974 rows — measures 4.2s under both bindings with bit-identical callback counts. | 2026-09-12 |
| **Per-call sip conversion overhead in `data()`** | The same replica sorting on the role that builds a `QDateTime` per comparison: 4.46s against 4.53s over more than a million round-trips. | 2026-09-12 |
| **Attributing the step to Riverbank's layer or to Qt separately** | Both crossings fail to load: binding 6.6.1 on Qt 6.7.3 raises `ImportError` on `QtGui`, binding 6.7.1 on Qt 6.6.3 on `QtCore`. The two halves cannot be varied independently. | 2026-09-12 |
| **Bisecting from PyQt6 6.0** | 6.0 and 6.1 have no `win_amd64` wheel on PyPI, and the application itself will not run below 6.5 (`QAction.setMenu` absent in 6.2/6.3, hard exit in 6.4). | 2026-09-12 |
| **Keeping both bindings installed for A/B convenience** | `misc/check_qt_enums.py` and `tests/test_qt_scoping.py` resolve PyQt5 first, so a venv holding both silently gates the Qt6 branch against Qt5. Install the second binding only for the duration of a comparison. | 2026-09-10 |

---

## 10. Adjacent finding: switching tabs re-filters the whole library

Not this regression — it is present under PyQt5 too — but it was found while reading the insert
path and it shares that path's two real costs. Recorded here rather than acted on.

Library and Favorites are **one** `MangaViews`. `ToolbarTabManager.addTab` (`misc_db.py:86`) builds
a new view only when `library_btn` is already set, and it is `None` while both of the first two tabs
are created, so both buttons point at `default_manga_view`. Clicking either runs `fav_view()` or
`catalog_view()` (`app.py:747-749`), which is `GallerySearch._filter` over every loaded gallery on
`GENERAL_THREAD`, then `invalidateFilter` and a full proxy re-map on the GUI thread. Inbox is a
separate `MangaViews`, so that switch instead hides one view and shows the other
(`misc_db.py:72-73`) and swaps the layout (`app.py:677`) — and showing a list view holding 19,974
rows lays out all of them. ✅ **Verified** by reading those paths.

**A virtualised canvas would not help.** `QListView` is already virtual where it counts: it paints
only the items intersecting the viewport, which is why §4's delegate-paint counts are 240 and 80
rather than 20,000. What is *not* virtual is the proxy's row mapping, which materialises one entry
per accepted row, and `doItemsLayout`, which positions every item — `setUniformItemSizes(True)` and
`LayoutMode.Batched` (`gallery.py:1133,1138`) are the mitigations already applied. A hand-written
canvas would replace the part that is already virtual and keep both parts that are not.

The lever that would help is not re-filtering and re-laying-out the whole model on every tab click:
cache the filter result per view, or give Favorites its own proxy over the same source rather than
re-running the search. ⚠️ **Unverified** as a design — not prototyped, and deliberately kept out of
S4, whose value is a clean ratio between two bindings.

---

## 11. What S5 found: the cost is queued meta-call delivery

py-spy 0.4.2 cannot read Python 3.14's interpreter (`Failed to find python version from target
process`), so the native profile the plan called for is unavailable without installing the Windows
ADK. ✅ **Verified** by running it.

The same question was answered at Qt's own granularity instead: subclass `QApplication`, time every
`notify()`, and accumulate by event type and receiver class. The patch is identical under both Qt
versions, so its own overhead cancels.

| Receiver, `QEvent::MetaCall` (type 43) | Qt 6.6.3 | Qt 6.7.0 | calls |
|----------------------------------------|---------:|---------:|-------|
| `SortFilterModel` | 52.47s | 112.78s | **112 under both** |
| plain `QObject` — PyQt's lambda-proxy receivers | 61.52s | 124.03s | 154 → 156 |
| next largest, `NoTooltipModel` | 0.88s | 0.93s | 48 under both |
| profiler total | 117.20s | 239.77s | 6,789 → 10,089 events |

`Loading galleries` in these two runs: **17.63s under 6.6.3, 34.08s under 6.7.0.** ✅ **Verified**.

**The application issues the same meta-calls and each one costs about twice as much**: 2.15× for
the proxy, 2.02× for the lambda receivers, against an observed startup ratio of about 2.2× in the
same pair of runs. Everything else on the GUI thread is under a second.

The timing is inclusive and re-entrant — the totals exceed wall-clock time because a meta-call that
runs a nested event loop counts its children — so the absolute seconds mean nothing. The *ratio
between two identically instrumented runs* is the result, and the call counts are exact.

**Where those 112 come from is the application's own doing.** `SortFilterModel.setup_search`
connects `GallerySearch.FINISHED` to `invalidateFilter` and to a `ROWCOUNT_CHANGE` lambda
(`gallery.py:209-210`), and `sourceModel().rowsInserted` to `refresh` (`gallery.py:216`). One
library load therefore invalidates the proxy scores of times. That is why S6 is worth more than
pinning: cutting the count helps under *every* Qt version, and the cost being cut is ours.

### Excluded by subtraction from the running application

Nine variants, each behind an environment switch on one patch so a single Qt install covered them
all, measured at Qt 6.7.0 against a baseline of about 42s. The run-to-run band across the whole
session was 38–50s; a mechanism worth 2.4× would have to drop the figure to about 17s, and none
came close. ✅ **Verified**.

| Subtraction | Result |
|-------------|--------|
| Application-wide stylesheet (`res/style.css`) not applied | 39.1s |
| `QGraphicsBlurEffect` never installed on `AppWindow.center` | 46.3s |
| Data-fetch spinner never shown | 48.7s |
| `ToolTipRole` returns `None` | 38.5s |
| `LayoutMode.SinglePass` instead of `Batched` | 45.4s |
| `setBatchSize(30000)` | 42.5s |
| Status-bar row callback not connected to `rowsInserted` | 36.1s |
| **Both views detached from the proxy entirely** | **34.9s** |
| Per-insert `refresh` not connected | 36.7s |

The eighth row is the one that refines S3. **Detaching both views from the proxy recovers only
about 15%**, while removing `insertRows` altogether took PyQt6 from 39s to 5.6s (§5). So "the model
and view" is too broad: the view is not where the time goes.

### Left untested

Recorded so a later session resumes rather than restarts. Nothing below has been measured.

1. **The second `MangaViews`.** The Inbox tab (`app.py:767`) builds its own model, proxy and two
   views, and `fetch_galleries` loops over every registered view. Never subtracted.
2. **`GridDelegate` replaced by a plain `QStyledItemDelegate`**, to price the Python `sizeHint`.
3. **`DecorationRole` thumbnails**, returning nothing instead of a pixmap.
4. **The proxy removed from the path entirely.** `HP_NO_SOURCE` was written and crashes:
   `setup_search` reads `self.sourceModel()._data` (`gallery.py:211`), so an unsourced proxy needs
   a larger patch than a one-line switch.
5. **An exclusive-time event profiler.** The one used here is inclusive, so it ranks stacks rather
   than self-time. Subtracting nested `notify()` durations would price the meta-call itself.
6. **A Windows native profile** via the ADK's Windows Performance Recorder, py-spy being unable to
   read Python 3.14.
7. **A local qtbase build bisected between `v6.6.3` and `v6.7.0`**, which is the only thing that
   names a commit. Expensive, and the definitive answer.
8. **Whether the further slide from 6.7 to 6.11** (about 38s to about 47s) shares this cause.

---

## Document History

* **v1.0** - Initial report
* **v1.1** - Phases S0-S3 executed. The regression is localised to the model/view insert path:
  removing it drops PyQt6 to the PyQt5 floor. Monitor, download manager, QThread shape, Python
  callback volume and dynamic sort/filter all excluded. Phase S4 opened.
* **v1.2** - Phase S4 executed. The missing model/view harness rung was built and committed, and is
  binding-neutral with bit-identical callback counts, which excludes the insert path itself and
  per-call sip conversion. Bisecting the binding names the release: the regression enters at Qt
  6.7.0 and 6.6.1 is within ~1.3x of PyQt5. Phase S5 opened for the native profile. §10 records the
  unrelated tab-switch cost.
* **v1.3** - Phase S5 executed. py-spy cannot profile Python 3.14, so the GUI thread was profiled
  at Qt granularity instead: the cost is queued meta-call delivery, the same 112 invalidations of
  the sort/filter proxy under both Qt versions at about twice the cost each. Nine more subtractions
  excluded, including the finding that detaching both views recovers only 15%. §11 carries the
  result and the untested candidates; phase S6 opened to cut the meta-call count.

---

**Last Updated:** 2026-09-12  
**Next Review:** when S6 is scoped, or if the migration is reconsidered on other grounds
