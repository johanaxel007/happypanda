---
name: metadata-matching
description: Rules for the online metadata pipeline — query building, candidate scoring, source fallback and request budget. A wrong match overwrites the user's stored metadata with no undo, and the sources ban by IP on request volume, so changes here are measured against real logs rather than reasoned about. Enforced when editing fetch.py, pewnet.py, title_formatter.py or betterversions.py.
trigger: glob
glob: "{version/fetch.py,version/pewnet.py,version/formatters/title_formatter.py,version/betterversions.py}"
paths:
  - "version/fetch.py"
  - "version/pewnet.py"
  - "version/formatters/title_formatter.py"
  - "version/betterversions.py"
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
`l:japanese$` matches nothing on the entire site and `language_filter()` returns nothing for
it. And **the plain title**, no prefix and no filters, is the form a source is likeliest to
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
- **Two language vocabularies, and only one of them is a recognition set.**
  `tagreaders.LANGUAGE_TAGS` is what the source can tag: the documented 83, plus five names it
  appears to use that the wiki never listed. Those five are kept because the failures are not
  symmetric - a real tag missing from the set reads as "states no language" and lets a foreign
  release through the filter, while a name the source never tags only ever matches nothing.
  `app_constants.G_LANGUAGES` is the four-name list the pickers offer, and is **not** a
  recognition set: reading a folder name or a stored artist against it filed `[Korean]` under
  the default language and sent `a:korean$` as an artist filter. Use `utils.known_languages()`
  for anything deciding whether a string names a language.
  - **The leading group is tested against the same wide set, deliberately.** A circle named
    exactly after a language - `Lao`, `Latin`, `Shona`, `Creole` - therefore loses its artist,
    which was weighed and accepted: the cost is a dropped `a:` filter rather than a wrong match,
    and no folder in a 19,400-gallery library has a leading group that is a language at all.
    Do not narrow it back without measuring both sides again.
  - **A configured language is written back in its configured spelling**, via
    `language_spelling`. Capitalising instead turns a multi-word custom entry like
    `Traditional Chinese` into a value the pickers no longer hold.
- **The `language:` namespace holds tags that are not languages.** `translated`, `rewrite`,
  `rough grammar`, `rough translation`, `text cleaned` and `textless narrative` say what was
  done to a release and sit beside the real language rather than instead of it, and the
  namespace carries names beyond those - `speechless` is on 31 galleries of one library and on
  neither wiki list. So **prefer a tag that is in `LANGUAGE_TAGS`**, never exclude the ones
  known to be meta: taking the first tag that was not `translated` filed galleries under a
  language of `Text cleaned`. A release the source names no language for keeps whatever it did
  write, since discarding it would lose the only thing recorded.
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
- **The filters use the source's short namespaces, `a:` and `l:`.** They are spent out of
  `MAX_QUERY_LENGTH`, so the twelve characters they give back go to the title: measured over a
  whole library, the queries that lose their quoted phrase fall from 220 to 101. The short
  forms were checked against live queries — four pairs, quoted multi-word artist and both
  filters together, identical hits — because the wiki documents them for *tagging* and leaves
  them out of its search qualifier table, which is the `f_sh` trap exactly. Do not confuse
  these with the app's **own** search grammar in `app_constants`, where `artist:` / `language:`
  / `lang:` are local syntax over the library and must keep their long names.
- **`MAX_QUERY_LENGTH = 200` is ours, not the source's.** No site limit was ever established
  for it. Raising it is a plausible alternative to shortening the filters, and needs its own
  live check before anyone trusts it.
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
  Japanese folder name against a list of romaji candidates cannot be told apart by eye. Four
  things address this and none should be removed: every choice carries its source url and opens
  in a browser on right or double click; the local gallery opens its own folder the same way;
  and `PICKER_PREVIEWS` supplies each candidate's native title, cover, and the creator the
  source credits it to.
- **The creator belongs in the row, and only in the row.** `canonical_title` strips the
  `[Circle (Artist)]` group out of both titles before either is scored, so who made a release is
  exactly the thing the score cannot see - and two doujins of one franchise share the parody tag
  as readily as they share a short title. `picker_labels` puts it on a third line, read off the
  `artist:`/`group:` namespaces of an entry `_candidate_previews` has already fetched, so it
  costs no request.
  - **Do not turn it into a guard here.** The candidate's side is the api's, but the local side
    is a folder name, and measured over a whole library the folder's `[Circle (Artist)]` group
    **disagrees with the source's own tag for 8.4%** of the galleries that state one and is
    **absent from 41%** of them - `[774]` against `774 house`/`nanashi`, `[Abarenbou Tengu]`
    against `abarenbow tengu`, and a large `[Anthology]` class whose real credits are several
    contributors the folder never names. Filtering or reordering on that discards correct
    matches; the stored `artist` column agrees with the source 18,668 to 102, but only because a
    previous fetch overwrote it, and `gallery.exed` means a run skips exactly those galleries.
  - **This is why the fetch still has no creator guard where the scan does.** Only ambiguous
    galleries reach the picker, so a lone perfect-scoring hit by a different artist is still
    auto-applied. Closing that needs the candidate's tags *before* `_select_match`, which means
    a `gdata` lookup per gallery batch and splitting the per-gallery loop into two passes.
- **Batch the preview lookup across the whole run, never per dialog.** `_candidate_previews`
  collects every candidate url from every ambiguous gallery, dedupes, and asks `gdata` in chunks
  of `EHen.MAX_GDATA_URLS`. One call per dialog would be a request each and would put
  `begin_lock`'s pacing delay in front of every prompt the user is waiting at; batching turns a
  few hundred candidates into a handful of requests made once, before the first dialog opens.
- **Read the raw `gmetadata`, not `parse_metadata`'s output.** Preview data is only ever looked
  at. Routing it through the parser puts it one call away from `apply_metadata`, which writes to
  the gallery.
- **Pass the preview data to the chooser, never re-derive it from the row's label.** The label is
  a display string that grows a line whenever the chooser learns to show something new, so
  anything parsing it back out silently acquires that line. `note_better_version` split the label
  once to recover the native title, and the day a creator line was added it began storing
  `by <artist>` into the native-title field of `better_versions.db`. The whole `previews` dict
  therefore rides along in the picker's `extras`, beside `thumbnails`, and every field is read
  from it by name.
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

## The better version scan

`betterversions.py` reuses the helpers above for a different question — "is this hit another
release of the same work" rather than "is this the gallery" — and the invariants change shape
because **both sides are the source's own title**, not a folder name against a site title.

- **It may require near-identity, and it must.** `SAME_WORK_SCORE` is far above
  `FUZZ_CONFIDENCE_THRESHOLD` because near-identical is actually reachable here. Measured over
  the whole library: at 99 the distinct works it conflates are almost all one work titled two
  ways, at 95 there are a hundred. Do not align it with the fetch's threshold.
- **Compare case-folded.** The two titles were written by different uploaders and capitalisation
  is the commonest thing they disagree on. Folding conflates no distinct works at all, which is
  why it is the right fix for that variance rather than a lower score.
- **The numbering guard still cannot see a Japanese volume marker.** `Sono Ni` / `Sono San`,
  `Chuu` / `Jou` and `zenpen` / `kouhen` reach the scorer on title similarity alone — see the
  numbering bullet above for why reading them is not worth it. Roman numerals *are* read now.
  This is why the scan's bar cannot be lowered much further: those pairs have nothing else
  separating them.
- **Only the scan splits the held title, and only its romaji head.** A raw release carries just
  that half, so a gallery stored with the full `romaji | translated` pair would never match its
  own decensored edition — a quarter of the censored galleries in a real library. The translated
  **tail** is never offered: distinct works share one (`Doubutsu no Oyome-san` and
  `Kemono no Oyome-san` are both `Animal Bride`), while a shared romaji head is nearly always
  one work someone translated twice. `fetch`'s one-sided rule still stands for `fetch`.
- **Anchor that guard on the whole held title.** A romaji head carries none of the numbers its
  translated half holds, so comparing form by form lets `Foo | Bar 2` and `Foo | Bar 3` agree on
  an empty set and read as one work.
- **One result page per query.** `search(max_pages=1)`, so a run costs exactly one request per
  gallery and the total can be stated before the user agrees to it. Following the pagination
  would make the real cost up to `MAX_SEARCH_PAGES` times the figure they saw.
- **Classify from the api's tags, never the candidate's title.** A release marks itself
  `[Decensored]` inconsistently; `uncensored` is the tag the site's own filters run on. The
  lookup is batched at `MAX_GDATA_URLS`, and the raw `gmetadata` is read so none of it can
  reach `apply_metadata`.
- **A short title needs the parody tag to say which work it is, and the tag rather than the
  title.** `canonical_title` strips the group naming the series, so a Phantasy Star Online 2
  doujin called `Seishoku` and a Fate/Grand Order one of the same name reduce to the same eight
  characters and score 100. `same_parody` compares the **`Parody:` namespace** by intersection,
  which needs no threshold because the source normalises it: one `kantai collection` where
  titles write both `Kantai Collection` and `Kantai Collection -KanColle-`. Comparing the titles'
  own groups instead would reject that pair, which is one work. Measured on a real library: 80%
  of galleries carry the tag and 595 of 595 whose title named a series also had it. Either side
  naming none decides nothing — about a fifth are untagged, so absence is not a mismatch. It has
  to run in `_classify` rather than `same_work`, because the candidate's tags do not exist until
  the batched lookup has happened.
- **The series is not enough on its own — the creator is the other half.** Two doujins of one
  franchise share the parody as readily as they share a short title, so `same_parody` passes
  them both. `same_creator` compares the **`Artist:` and `Group:` namespaces pooled**, by
  intersection, on the same terms as the parody: undecidable when either side credits nobody.
  Measured over a whole library's list of 725 stored rows, with every candidate's tags read
  back from the api: **26 rows are a different work**, all of them verified by hand — `Pink
  Archive` by unacchi offered Alpha91's, `MIZUGI Archive` by guchico offered Subachi's, nine AI
  sets of `Fischl` against a held gallery of that name. 57 of them shared the held gallery's
  parody tag, which is why that guard did not catch them.
  - **Read the tag, never the `[Circle (Artist)]` group.** Scoring the title's own group instead
    turns 65 rows into mismatches where the api says 26: the titles write `jackdempa` and
    `[Jaku Denpa]` for one artist, `[chaccu, TinkerBell]` against a stored `chaccu`, and
    `[Google Translated]` or `[Pixiv+FANBOX]` where an artist belongs. The source normalises
    the namespace; the title is whatever the uploader typed.
  - **A release credited to a decensorer is not a counter-example, though it looks like one.**
    `[jnnkleeche] Umi no Soko [uncensored]`, `[Japanese Underground Skinmag] Love Generation
    (Uncensored)` and `(NotoriousCRS) Second Chance` all read as the same work republished
    under an editor's name. Their api tags say otherwise: the jnnkleeche one is a yaoi merman
    manga (`male:yaoi`, `male:merman`), the NotoriousCRS one a 3D `Misc` set, and both Skinmag
    releases keep the original artist in `artist:` and agree. Do not weaken the guard for this
    case — it was checked and it does not exist.
  - **Content-tag overlap is not a second chance for a rejected row.** Measured on the same
    data, agreeing rows median 0.67 Jaccard and rejected ones 0.05, but no cutoff rescues any
    of the 26 while 163 correct rows already sit below 0.5. The creator tag alone is the signal.
- **A guard added after a scan cannot reach the rows it already stored.** `mark_scanned` records
  every gallery searched, so a rescan would need `forget_scanned` and a second full pass — one
  request per gallery, hours of them. `BetterVersionRecheck` re-judges the stored rows instead,
  at one request per `MAX_GDATA_URLS`, and applies only the two same-work guards: whether a row
  still *improves* reads the held gallery's own tags, which a metadata fetch rewrites, so a row
  dismissed on that would be dismissed for a change in the library rather than for being wrong.
  A row noted from the picker is skipped — the user chose it against the alternatives — and a
  failing row is **dismissed, not deleted**, so a guard that turns out wrong is recoverable.
- **A row must be a strict improvement, never a trade — and the condition is on the *other*
  axes.** An uncensored release in a language the held gallery is not in gives the language away
  to gain the censorship; a translation that is censored gives the censorship back to gain the
  language. Both were reported to a user before `better_kinds` compared the axes together: a
  gallery held in English and censored was offered a Spanish uncensored release. Decensored
  therefore requires `held_langs ⊆ candidate_langs ⊆ held_langs ∪ {target}`, and translated
  requires the candidate not be known-censored when the held copy is already uncensored.
- **Three axes, and two of them read an absence as the improvement.** The third is translation
  quality: the source marks a poor translation `rewrite`, `rough grammar` or `rough translation`
  (`ROUGH_TAGS`), so a gallery can hold the language you want and still be worth replacing by a
  release in the same language carrying none of them. It reuses the decensored axis's language
  condition, which is also what stops an untranslated candidate reaching it and taking the
  translation away. `text cleaned` and `textless narrative` are deliberately out: they say the
  original text was removed or absent, which is not a caveat on a translation. Like decensored,
  this axis is satisfied by a *missing* tag, so a row is worth checking rather than certain.
- **Widening `worth_scanning` reaches its galleries by itself; no rescan is needed.** A gallery
  the filter rejects is never passed to `mark_scanned`, so one that becomes eligible under a new
  rule is simply unscanned and the next ordinary run searches for it. Measured when the quality
  axis was added: a store holding 7,780 scanned galleries contained **none** of the 314 newly
  eligible ones, so the top-up cost 314 requests rather than the 8,094 of a full rescan. Check
  the store before building a rules-version mechanism for this; the note below about a guard not
  reaching stored rows is about `better_kinds`, which is a different thing.
- **Log every candidate that improves on nothing, with the tags it turned out to hold.** This is
  where a scan discards nearly everything — over a whole library it threw away 9,603 of 10,343
  same-work candidates — and the rejections are correct only as long as someone can check them. `three
  states per axis` matters in that log: a release that states no language and one that states no
  censorship are not the same as either alternative. Bounded by `MAX_LOGGED_REJECTIONS`.
- **Most of what a scan finds is discarded, and that is the honest answer rather than a bug.**
  Measured over a whole library: **7,742 galleries searched → 36,522 hits → 10,343 judged the
  same work → 723 rows**, so roughly one gallery in eleven ends up with one. What goes is
  overwhelmingly translations into languages the scan is not looking for — chinese, korean,
  spanish, russian, portuguese and french dominate the rejections. A small run looks far worse
  than that (an early 59-gallery pass produced two rows) because the yield is thin and lumpy, so
  do not read a quiet run as a broken one. Check the funnel in the log first: hits, then how
  many were the same work, then how many were classified, then rows.
- **A failure mid-run must not throw away searches already paid for.** By the time a batch of
  candidates is waiting on its metadata lookup, the searches behind them are spent, and the
  source bans on request volume. `_scan` flushes that batch from a `finally`, so a connection
  error costs one lookup rather than re-spending up to `MAX_GDATA_URLS` galleries' searches on
  the next run. The flush is itself guarded: a failure there must not replace the error that
  caused it. The refused-search path does the same thing explicitly and then clears the batch,
  so the two cannot classify it twice.
- **A failed lookup is not a scanned gallery.** A batch whose request never completed leaves its
  galleries unrecorded so a later run retries them; a candidate the api answers for with an
  `error` entry is a removed gallery and must *not* hold its holder back, or that gallery is
  re-searched on every run forever.

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
