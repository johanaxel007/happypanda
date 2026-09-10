# PyQt6 Startup Performance Regression

**Version:** 1.1  
**Date:** 2026-09-10  
**Status:** Proposed design — not implemented.  
**Target:** PyQt6 6.11.0 / Qt 6.11.2 on Python 3.14.7 (baseline: PyQt5 5.15.11 / Qt 5.15.2)

> Switching the binding to PyQt6 makes database startup **roughly four times slower** — 12.1s
> against 39–52s for the gallery load alone, and about 26s against about 126s across all three
> startup phases on a 19,974-gallery library. **The cost lands entirely in Qt-free Python running
> on worker threads, not in any Qt call**: the one Qt call in the loop, `insertRows`, is 0.01s
> under both bindings. This is an open blocker on `feat/qt6-migration`.
>
> Ten candidate causes were ruled out, each by measurement (§4), and a minimal reproduction built
> up from a bare `QApplication` through a QThread carrying the workload **fails to reproduce it**
> (§5). Bisecting the running application instead (§7) localised the whole cost to **the model and
> view**: taking `gallery_model.insertRows` out of the load loop drops PyQt6 from about 39s to
> about 5.6s, against a PyQt5 floor of about 6.1s for the same configuration. What is *inside*
> that path is still open — it is not the volume of Python callbacks, which PyQt6 makes **fewer**
> of.

**Audited:** 2026-09-10, at commit `7ba4813` (branch `feat/qt6-migration`).
**Amended:** 2026-09-10 — phases S0–S3 executed; §5 and §7 rewritten around the result.
Findings come from instrumenting `version/gallerydb.py` (`fetch_galleries`, split into four
timers) and `version/gallery.py` (`GridDelegate.paint`, call counter), applying the identical
patch to both `feat/qt6-migration` and `feat/qt6-migration-prep`, and running the real application
against the same database under each binding. Supporting probes: a stack sampler over
`sys._current_frames()`, two standalone harnesses replicating the startup architecture with and
without a Qt event loop, and direct `sqlite3`, `NtQueryTimerResolution` and `devicePixelRatio`
measurements. All instrumentation was reverted; nothing in it is committed.

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
| `pytest tests/ -q` | 289 pass, 4 pre-existing `test_init_db` failures, under both bindings. ✅ **Verified**. Says nothing about startup cost — no test loads the library. |
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
scratch scripts and were not committed; §8 records how to rebuild them.

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

⚠️ **Unverified** as an explanation, but the shape is consistent across all three: PyQt6 makes
*fewer* transitions into Python than PyQt5 and is still several times slower, so the additional
time is being spent inside Qt6's own model-view machinery rather than in this project's callbacks.
Narrowing further needs native profiling, not black-box measurement.

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
| **S4 — Narrow within the model/view** | Three sub-hypotheses already excluded (§5). What is left needs a native profiler on the Qt6 build, or bisecting PyQt6 across 6.0–6.11 to find the release where it appears. | 🔴 | S3 | — |

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
| **v2** | Once the mechanism is named: either a fix, or a decision to accept the cost. If it proves to be a PyQt6 defect, the bisection output is the minimal reproduction to send to Riverbank. |
| **v3+** | The unrelated startup cost `gen_galleries` carries — one SQL query per gallery through `ListDB.query_gallery`, which is most of the 3.7s Qt-free floor. Gets its own entry. |

---

## 8. Open questions

1. **What inside the model/view path is slow?** S3 named the subsystem; the mechanism within it
   is open. Not the Python callback volume, and not dynamic sort/filter (§5). Two directions are
   left: a native profile of the Qt6 build, and bisecting PyQt6 6.0–6.11 to find the release where
   it appears — the latter is cheap and would narrow the search enormously.
2. **Does the ratio scale with library size?** Every measurement here is against one 19,974-gallery
   database. A smaller library might show it proportionally or not at all, which would itself be a
   clue. ⚠️ **Unverified** — untested in either direction.
3. **Is it specific to PyQt6 6.11.0 / Qt 6.11.2?** No other Qt6 point release was tried. Riverbank
   ships 6.0 through 6.11; if S1–S3 find nothing, bisecting the binding version is the fallback.

### Rebuilding the harnesses

Both were scratch scripts. To recreate:

- **Instrumentation** — in `gallerydb.DatabaseStartup`, wrap the four steps of `fetch_galleries`
  in `time.perf_counter()` accumulators on a class-level dict and log it once after the loop.
  Apply the *same* patch to both branches; the file differs between them only by its Qt import.
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
| **Keeping both bindings installed for A/B convenience** | `misc/check_qt_enums.py` and `tests/test_qt_scoping.py` resolve PyQt5 first, so a venv holding both silently gates the Qt6 branch against Qt5. Install the second binding only for the duration of a comparison. | 2026-09-10 |

---

## Document History

* **v1.0** - Initial report
* **v1.1** - Phases S0-S3 executed. The regression is localised to the model/view insert path:
  removing it drops PyQt6 to the PyQt5 floor. Monitor, download manager, QThread shape, Python
  callback volume and dynamic sort/filter all excluded. Phase S4 opened.

---

**Last Updated:** 2026-09-10  
**Next Review:** when S4 starts, or if the migration is reconsidered on other grounds
