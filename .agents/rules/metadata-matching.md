---
name: metadata-matching
description: Rules for the online metadata pipeline — query building, candidate scoring, source fallback and request budget. A wrong match overwrites the user's stored metadata with no undo, and the sources ban by IP on request volume, so changes here are measured against real logs rather than reasoned about. Enforced when editing fetch.py, pewnet.py or title_formatter.py.
trigger: glob
glob: "{version/fetch.py,version/pewnet.py,version/formatters/title_formatter.py}"
paths:
  - "version/fetch.py"
  - "version/pewnet.py"
  - "version/formatters/title_formatter.py"
---

# Metadata matching

Two things make this code unforgiving:

- **A wrong match is data loss.** With `Replace metadata` on, the matched gallery's title,
  artist, tags and date overwrite the local ones, with no undo. Not matching is a *better*
  outcome than matching the wrong gallery — a sibling volume, a different translation, a
  same-series sequel. Undoing one after the fact is `@.agents/rules/gallery-database.md`, which
  owns the repair protocol and the reasons a raw delete makes things worse.
- **The sources ban by IP on volume.** Every extra query variation multiplies across the whole
  library. `MAX_SEARCH_ATTEMPTS` bounds it; `CommonHen.begin_lock` / `end_lock` pace it. Neither
  is decoration. The queries themselves are built by `search_queries()`, which is where a
  reordering belongs — it returns at most that many, so a variation added there costs nothing
  until it displaces one that was already earning its slot.

## Measure before you change matching

Query order, the confidence threshold and the guards are tuned against real runs, not intuition.
Before reordering, loosening, or adding a variation:

```sh
python misc/analyze_fetch_log.py path/to/happypanda.log            # what matched, on which attempt
python misc/analyze_fetch_log.py path/to/happypanda.log --failures # and why the rest did not
```

The analyzer separates the three failure modes, and they need opposite fixes:

| Symptom in the log | Meaning | Where the fix belongs |
|---|---|---|
| `No hits found` on every query | the query never reached the gallery | query building |
| candidates returned, `Found 0 confident result(s)` | the titles disagree | scoring / canonicalisation |
| `Discarded N result(s) with different numbering` | a guard rejected them | usually correct; check the numbers |

Two things have to stay inside the budget whatever else moves. **A filter only narrows a
language the source tags at all** — e-hentai tags one only when it is not its own default, so
`language:japanese$` matches nothing on the entire site and `language_filter()` returns nothing
for it. And **the plain title**, no prefix and no filters, is the form a source is likeliest to
hold; a gallery whose stored artist or language is the thing the source disagrees with is only
reachable through it.

An attempt that never wins across a whole run is dead weight — give its slot to something that
does, rather than raising `MAX_SEARCH_ATTEMPTS`. The cap is deliberately 4 and all four slots
have since been measured producing matches, so treat a proposal to lower it as needing the same
evidence as a proposal to raise it.

**The confidence threshold is bimodal, which is why its default is high.** Scored across a whole
library, the folder name against the source title actually applied to it: **85% of correct pairs
score an exact 100**, and the rest tail off thinly — 96.6% clear 70, 91.5% clear 95. So the
default of **95** gives up about five percent of correct matches to the chooser and in exchange
abandons the whole 70–94 band, which is where a near-miss sibling gets applied silently. It is a
user setting, so this is a default rather than a guarantee; do not reason about the pipeline as
though 95 were fixed. And note what a threshold cannot do: `TORANOANA … TYPE-X` against `TYPE-A`
scores 98 and `Erohon V` against `Erohon II` scores 97, so both clear any usable bar. The guards
are what separate those, not the score.

**A short title is the unsolved case.** `fuzz.ratio` against a title of a few characters clears
70 for anything containing it: a real run searching `"Hong"` returned 75 hits and scored 35 of
them confident, which is a chooser nobody can work through. The threshold cannot fix this on its
own, because the same threshold is right for a long title. Treat a proposal here as needing a
measurement first - the shape of a fix is probably a length-aware threshold or refusing to search
below some title length at all, and neither has been tried.

## Scoring invariants

- **Canonicalise both sides.** `canonical_title()` before `fuzz.ratio`, never a raw title
  against a raw title. Sources keep `[Circle (Artist)]`, `(Magazine)`, `[English]`, `[Digital]`
  and translator credits that the folder name has already lost, and `fuzz.ratio` is length
  sensitive enough that those alone sink an exact match.
- **Never `token_set_ratio` or `partial_ratio`.** Both return 100 when one title is a subset of
  the other, so `Schoolgirl Guide` scores a perfect match against `Schoolgirl Guide 2` and gets
  auto-applied. A score of 100 must mean "identical after canonicalisation", because
  `_select_match` auto-selects a lone perfect hit.
- **Numbering is decisive, whatever the score.** `title_numbers()` compares the *set* of numbers
  on both sides; a mismatch rejects the candidate. Volume, chapter and sequel numbers are a tiny
  edit distance apart and a large semantic one. **Roman numerals count as the number they
  denote**, in ASCII and in the Unicode block, so `Erohon V` and `Erohon II` are told apart
  while `DepthSinker2` and `DepthSinker II` are one work — the source and a folder name
  disagree about the notation constantly, and folding it one way only turns a working match
  into a rejection. Upper case and word-bounded, two characters at least: `Ii` is Japanese for
  "good", `DRII` is a name, a lone `I` is the pronoun, `V` abbreviates versus and `X` is the
  crossover multiplier. **Japanese numerals are deliberately not read** — `ni`, `san` and `go`
  are the particle, the honorific and an ordinary syllable so much more often than they are
  numbers that a vocabulary for them broke 142 working matches and fixed none. Measured over a
  whole library, the roman fold cost 8 already-matched galleries and recovered 5 while separating
  114 confusable pairs; the 8 are tokenisation and parody-name artefacts (`DRII` for `DR:II`, a
  `(Final Fantasy VII)` parody beside a `VI` title) that the numbering guard cannot fix.
- **Compare halves too, on the candidate side only.** `match_forms()` offers each half of a
  `romaji | translated` pair, because a folder often kept one half while the source has both.
  Do **not** split the local title as well: `Kaizoku Kyonyuu` would then match
  `Kaizoku Kyonyuu Yawara`, a family the numbering guard cannot separate. The same one-sided rule covers the
  trailing `-Subtitle-` form: reducing both sides would score `Title -Sub A-` and
  `Title -Sub B-` a perfect 100 against each other.
- **Language is evidence, but only in one direction.** `title_languages()` reads the bracketed
  tags off a candidate. A candidate tagged with a language the local gallery is not in is a
  different release and gets dropped; a candidate that states no language is the ordinary shape
  of an untranslated listing and is kept - but see the next point, because "kept by default"
  becomes dangerous the moment the filter has removed everything it would have competed with.
- **Never auto-apply the lone survivor of the language filter.** A source writes a language beside
  its own name for itself - `[Thai \u0e20\u0e32\u0e29\u0e32\u0e44\u0e17\u0e22]` - and any tag shape the parser does not recognise
  reads as "states no language" and survives. When the filter has discarded this candidate's
  alternatives, nothing weighed it against them, so it goes to the picker however well it scored.
  This is not hypothetical: a Thai release was applied to an English gallery exactly this way.
- **Read a language tag by its first word, and skip the leading group.** `[Chinese] [\u5bae\u697d\u500b\u4eba\u7ffb\u8b6f]`
  puts the translator in a group of its own, while `[Thai \u0e20\u0e32\u0e29\u0e32\u0e44\u0e17\u0e22]` puts the language's own name
  inside the tag. Matching the first word covers both. The leading `[Circle (Artist)]` group is
  skipped because a circle name can begin with a language word - `[English Muffin (Yamada)]`.
- **A stored language is not automatically a fact.** Every gallery whose folder name never
  stated one is stored as `G_DEF_LANGUAGE`, which **ships as `English`** - so on a stock install
  the commonest stored language is also the one that means "nobody knew", and filtering on it
  discards correct candidates. `language_is_known()` is the gate: the folder name states the
  language outright, or it differs from the default nothing else could have set it to. Do not
  reintroduce a hardcoded set of "safe" languages; it silently keys the guard to one machine's
  configuration. The filter additionally skips an untranslated language, since a listing in one
  states nothing for the comparison to disagree with.
- **The test suite reads `G_DEF_LANGUAGE` from an untracked `settings.ini`.** A checkout of this
  repo can therefore test a different configuration than the one it ships. Any case that depends
  on the default must monkeypatch `app_constants.G_DEF_LANGUAGE` rather than trust the ambient
  value - the language filter bug survived a full suite because the local ini said `Japanese`.
- **Order the candidates, not just the list.** Sources list newest first, so a work's later
  translations arrive ahead of the release actually held locally, and equal scores are common
  enough that the tie decides what the user sees first. The sort therefore breaks ties on
  whether the candidate's language matches the gallery's. This is presentation, so it applies
  whatever the filter setting says.
- **An unverifiable pair is `None`, not 0.** A title-less result (chaika resolving by hash) and
  a cross-script pair (Japanese folder name, romaji site title) cannot be compared. Scoring them
  0 discards correct hits; `None` marks them unverified, so a lone one is used and several go to
  the picker.

## Query building

- `TranslationStyle.SEARCH` normalises full width to ASCII for queries. `DEFAULT` does the
  opposite, for filenames. Using the wrong one sends `｜`, `＂` and `＜＞` to a source that
  indexes none of them.
- Strip `"` from a title before wrapping the query in quotes, or the phrase closes early.
- A quoted phrase that had to be truncated matches nothing — drop the quotes when trimming.
- `split_on_separator()` takes the **raw** folder name. A deleted separator survives only as the
  whitespace run around it, and formatting collapses that.
- **`Gallery.path_title` is only a title when the path is a live directory.** It returns
  `path.parent.name` for anything else, so an archive-backed gallery, or any gallery whose drive
  is not mounted, reports the name of the folder *above* it. A fetch run started with the library
  offline would search for that same string for every gallery. The scoring guards reject most of
  the results, but the run is wasted; check the first query in the log looks like a real title.

## The picker

Ambiguity is resolved by a human, at the *end* of the pass, so what the chooser shows is part of
matching rather than a separate UI concern.

- **The listing gives one title, it may be the wrong alphabet, and it has no cover.** A
  Japanese folder name against a list of romaji candidates cannot be told apart by eye. Three
  things address this and none should be removed: every choice carries its source url and opens
  in a browser on right or double click; the local gallery opens its own folder the same way;
  and `PICKER_PREVIEWS` supplies each candidate's native title and cover.
- **Batch the preview lookup across the whole run, never per dialog.** `_candidate_previews`
  collects every candidate url from every ambiguous gallery, dedupes, and asks `gdata` in chunks
  of `EHen.MAX_GDATA_URLS`. One call per dialog would be a request each and would put
  `begin_lock`'s pacing delay in front of every prompt the user is waiting at; batching turns a
  few hundred candidates into a handful of requests made once, before the first dialog opens.
- **Read the raw `gmetadata`, not `parse_metadata`'s output.** Preview data is only ever looked
  at. Routing it through the parser puts it one call away from `apply_metadata`, which writes to
  the gallery.
- **Do not swap the api lookup for scraping the search page.** The listing html very likely
  carries a thumbnail already, which looks like a free replacement for the `gdata` call. It has
  never been verified against a live page, the markup differs between the list and thumbnail
  views the account can be set to, and getting it wrong fails silently as a missing cover. The
  api field is documented and already relied on elsewhere in `pewnet`.
- **Covers load lazily, but not anonymously.** Thumbnails come off the image host, so hovering
  costs nothing against the rate limited api - but exhentai's host answers 403 to a request with
  no session cookies, and that error page arrives as an ordinary file, so the only symptom is a
  null pixmap. Queue every cover with `EHen.image_session()`. Fetch on hover through
  `Downloader`, cache per dialog, and connect a *bound method* to `file_rdy`: a lambda has no
  thread affinity and would run the slot on the download thread, touching widgets from there.

## Metadata files beside a gallery

- **A gallery folder may already name its own source.** `GMetafile` reads `info.json` /
  `info.txt`; the E-Hentai Downloader userscript's variant states the romaji title, the native
  title and the gallery url on the first three lines with no key in front of any of them. Taking
  that url turns a search that has already failed into a direct fetch, which is worth far more
  than anything the search could have done.
- **Take the url and nothing else at fetch time.** The rest of the file is a snapshot from
  download time. Applying it would overwrite the stored metadata with a stale copy moments
  before the fetch replaces it with a current one.
- **The url line records where it was copied from.** A gallery url in one of these files may
  carry a `#` or a `?p=2`; both name the page the link was taken from, not the gallery, and all
  three forms have to reduce to one url. Whatever recognises the format has to accept them, or
  the file falls through to a parser that reads nothing out of it and reports success anyway.
- **Read fields from the header only.** Everything below `Tags:` or `Uploader Comment:` is text
  the uploader wrote and routinely contains lines shaped exactly like fields - `Circle: foo`,
  even `Category: Western`. Scanning the whole file lets a comment overwrite the real values.
- **Keep the source's own casing for a category.** `Non-H` is one of `G_TYPES`; recapitalising
  it produces `Non-h`, which is not. Both other parsers store the raw category too.
- **Verify a parser against the whole library, not a sample.** Two files looked like the format
  was fully handled; running it over all of them found 77 galleries silently getting nothing,
  in two variants neither sample had. A handful are also written against a localised site (a
  Chinese `Category:` / `发布于:` header, with `今天` where a date should be) - not worth
  translating, and the url and title still parse, which is what the fetch needs.
- **Every parser in `detect()` is handed the same open file.** One that reads the handle and
  then declines has to `seek(0)`, or the next parser sees an empty file. `_hdoujindler` also
  reports success for any `info.txt` with lines in it, whether or not it recognised a key, so
  anything more specific has to be tried before it.
- **Say where in the queue the user is.** A long run ends in a stack of these blocking on
  `GALLERY_PICKER_QUEUE.get()` with no other sign of how many are left.
- **Log the candidate list at info.** An ordering complaint cannot be diagnosed from a count,
  and the builds these runs come from do not have debug logging on. Bounded by
  `MAX_LOGGED_CANDIDATES`, because a short title clears the threshold dozens of times over.

## Sources

- `CommonHen.QUEUE` is a **class attribute shared by every source.** Drain it between passes or
  one source's urls get fetched against another's api.
- **chaika is a small archive, not a mirror.** Its whole corpus is on the order of twenty thousand
  archives, so as a fallback it recovers a handful per run rather than a large share. A quiet
  chaika pass is the normal outcome, not a bug to chase.
- Follow the site's own pagination link rather than constructing one; it is only rendered when a
  further page exists, which is the gate for fetching it.
- **The search parameters drift, and a stale one fails silently.** `f_sh` once folded expunged
  galleries into the results and now selects them exclusively — the two listings are disjoint, so
  a flag that read as "also include" had become "only". Nothing errors when this happens; the
  result set just changes shape. Before trusting any search flag, check it against a live query
  whose total you can compare (`N results` appears in the page text), not against what the
  parameter name implies. Already ruled out as explanations for that behaviour, so do not re-probe
  them: `advsearch=1`, `f_cats=0`, and the `f_sft` / `f_sfl` / `f_sfu` scope flags all change
  nothing.
- `begin_lock` calls `random.randint(3, TIME_RAND)`, so a `global ehen time offset` below 3
  raises - which is also why chaika does not reuse it. It paces itself with
  `ChaikaHen.MIN_REQUEST_INTERVAL` instead, because three seconds is more than that source needs
  and a fallback pass makes over a thousand requests. Whatever the mechanism, a source that
  issues requests in a loop needs *some* floor: unpaced, chaika reached 35 requests a minute.

## After changing anything here

- [ ] `pytest tests/test_metadata_matching.py -q` passes — its cases are real past failures
- [ ] a new behaviour has a regression case added there, using the real title that motivated it
- [ ] the request count per gallery has not grown for the common (matching) path
