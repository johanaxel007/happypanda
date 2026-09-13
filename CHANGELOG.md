## Unreleased

- New Features
    - Image support for JXL, AVIF and TIF / TIFF files.
    - Metadata fetching now verifies every candidate against the local folder name with a similarity score instead of taking the first hit, and picks a result automatically when it is an exact match.
        - New option: `Web / Metadata / Confidence threshold`. How similar a search result title has to be to the folder name before it counts as a match. Lower values risk wrong matches, higher ones miss slightly differently worded titles. Default 95%: measured across a whole library, 85% of correct matches score an exact 100 and the rest tail off thinly, so a high bar gives up around five percent of them and in exchange stops a near miss being applied over your metadata without being shown to you. An existing `settings.ini` keeps whatever it already stores, so change it in the dialog if you want the new default. Note the second cost: a gallery that no longer clears the bar spends its whole search budget and the fallback source instead of stopping at the query that used to match it, and it is retried on every later run because it never counts as processed.
        - New option: `Web / Metadata / Search by image hash first`. An image hash only matches when your files are byte identical to the ones the source indexed, so this is **off by default**; turn it on only if you keep galleries exactly as downloaded. Leaving it off also skips a pointless delay on every gallery.
    - The gallery chooser, shown when several search results are equally plausible, is usable on a long unattended run: it says which of how many galleries you are answering for, every choice carries its source URL as a tooltip, and right clicking or double clicking one opens it in your browser to settle it against the actual page. Double clicking or right clicking the local gallery at the top left opens its folder, with the file selected when it is an archive.
        - Hovering a choice shows a card carrying its cover, its URL and what clicking will do, placed on whichever side of the cursor fits on screen. The cover usually settles which edition of a work it is without leaving the dialog, and a choice the source served no cover for still gets the card. Covers are fetched once each, on hover, and reused afterwards.
        - New option: `Web / Metadata / Look up cover art and native titles for the gallery picker`. A search listing carries one title, usually romaji, and no cover at all, which is little help in choosing when your own folder name is in Japanese. Every ambiguous gallery in a run is looked up together in batches, so this costs a handful of requests for a whole run rather than one per gallery, and no dialog waits on the request pacing to open. Default on.
    - `info.txt` files written by the E-Hentai Downloader userscript are read. Their first three lines are the romaji title, the native title and the gallery URL, each bare with no key in front, which the existing HDoujin reader could not see - it claimed the file, extracted nothing from it, and reported success.
    - A gallery that has no URL of its own now takes the one from the metadata file beside it, so galleries imported before that file could be read no longer have to be found by searching. Only the URL is taken; the rest of such a file is a snapshot from download time, and the fetch that follows replaces it with current data.
    - When dropping results by language leaves exactly one, you are asked rather than having it applied for you - a source can write a language beside its own name for itself, such as `[Thai ภาษาไทย]`, and anything unrecognised survives a filter that removed every alternative it would have been weighed against.
    - Search results in a language the gallery is not in are dropped rather than offered, but only when that language is actually known: a gallery whose folder name never stated one is stored as the default language, which says nothing about what it really is, and filtering on that would have thrown away correct results.
        - New option: `Web / Metadata / Ignore results in a different language`. Only applies to a gallery whose own language is a translation, since an untranslated one falls back to the default language rather than a known one, and results that state no language are always kept. Default on.
    - **A review list of better versions of galleries you already hold**, under `Gallery / Better versions found`: a decensored release of a gallery held censored, or a translated release of one held untranslated. Every row pairs the gallery you have with the release that improves on it; double clicking one opens it on the source, right clicking offers the held gallery's folder and the URL. Nothing is downloaded, nothing is applied to your library and nothing is written to the gallery database - the rows live in a database of their own, so the list survives a restart and can be worked through over days, and deleting it loses nothing a scan cannot find again.
        - The gallery chooser gains a `Better version` button. It was already showing the better release among its candidates with no way to say "not this one, but keep it in mind"; the button notes the highlighted result and leaves the dialog open, so the match you were choosing is still yours to make. It costs no requests at all - the search that turned the candidate up has already been paid for.
        - `Gallery / Scan for better versions...` searches for the rest. It acts on the galleries in view, so typing a search first aims the run at those rather than the whole library, and it says how many galleries and roughly how long before it starts. To scan just a few, select them and use `Web / Scan selected for better versions` from the right click menu, the same way fetching metadata for a selection works; starting it from the menu bar with galleries selected covers the whole tab instead, and now says so rather than letting you agree to it by accident. Exactly one request per gallery - a single page of results, so the figure you agree to is a ceiling rather than a floor - searched on the source's own title for the gallery rather than the folder name. Galleries that cannot benefit are never searched for: one the source has never tagged, or one already holding a translation, an uncensored release and no complaint about the translation's quality. Whether a candidate is really an improvement is read from the tags the source reports for it, in batches of 25, because a release marks itself `[Decensored]` only sometimes. A row has to be an improvement rather than a trade: an uncensored release in a language you do not hold the gallery in is not offered, since taking it would cost you the language, and neither is a translation that puts back censorship you had already escaped. A release of a *different* work that happens to share a short title is turned down too, on the series the source tags it with rather than on the title: strip the decorations off `Seishoku (Phantasy Star Online 2)` and off `Seishoku (Fate/Grand Order)` and both are the same eight characters. Expect few rows - the other releases of a given work turn out to be mostly translations into languages you are not looking for - and `happypanda.log` names every candidate it turned down together with the language, censorship, translation quality and series it actually carried, so a quiet run can be checked rather than guessed at. A run that only turns up rows already on your list says so, rather than reporting that it found nothing.
        - **A third kind of better version: the same translation, done better.** The source marks a translation it considers poor with `rewrite`, `rough grammar` or `rough translation`, so a gallery can already be in the language you want and still be worth replacing. The scan now offers a release in that same language carrying none of those tags, listed as `Better translation`. Galleries marked this way were previously skipped outright - already translated and already uncensored read as nothing left to find - so they cost no requests at all until now, and picking them up needs no rescan: a gallery the filter skipped was never recorded as scanned, so the next ordinary run simply searches for it. On a library of 19,400 galleries that is 314 extra searches, against 7,780 a full scan already spent.
        - Like a decensored row, this one is earned by a tag being *absent*, so it is worth checking rather than certain: a release nobody marked is not the same as one known to be good. A candidate carrying a complaint of its own is turned down as a trade rather than offered, and the log names which tag each side held. `text cleaned` and `textless narrative` do not count - they say the original text was removed or was never there, which is not a verdict on a translation.
        - The scan can be stopped from the same menu and picks up where it left off, so a long run does not have to be finished in one sitting. `Forget scan progress` in the window makes the next scan cover everything again.
        - A candidate by a *different artist* is turned down. The series tag alone could not do this: two doujins of one franchise share it as readily as they share a short title, so a held `Pink Archive` by unacchi was offered Alpha91's gallery of the same name, `MIZUGI Archive` by guchico was offered Subachi's, and a gallery named after a character was offered nine AI sets of that character by nine different people. Who made a release is read from the artist and group tags the source writes, never from the `[Circle (Artist)]` group in the title, which is whatever the uploader typed: across a real library those titles wrote `jackdempa` and `[Jaku Denpa]` for one artist, and `[Google Translated]` where an artist belongs. A release the source credits to nobody is still offered, as before.
        - `Recheck the list` in the window re-judges the rows already found, without searching for anything again. A rule added after a scan cannot otherwise reach them: the scan records every gallery it searched, so benefiting would mean `Forget scan progress` and another full pass of one request per gallery. This is one request per 25 rows instead. A row that turns out to be a different work is dismissed rather than deleted, so nothing is lost if a rule was wrong, and a row you noted by hand from the gallery chooser is left alone - you picked it while looking at the alternatives, which is better evidence than the tags are. Whether a row still improves on your gallery is deliberately not rechecked, because that reads your own gallery's tags and a metadata fetch may have rewritten them since.
        - The recheck can be stopped from the same button while it runs, and the rows it reached keep their verdicts. A row it turns down is dismissed rather than deleted, and `Show dismissed` in the window lists those together with the ones you turned down yourself - right click one and `Put back on the list` undoes it, classification intact. Worth knowing why that matters: the recheck judges a row against your gallery's tags **as they stand**, and a metadata fetch may have rewritten them since the row was found, so a dismissal is something you can audit in `happypanda.log` (both sides' tags are named) and reverse.
        - New option: `Web / Metadata / Better version language`. Which translation counts as an improvement. Every language the source tags is offered, less the ones a candidate can never carry - it tags a language only once a gallery has been translated into it, so Japanese is not among them. Anything added under `General / gallery custom languages` is offered too. Default English.
    - `Gallery / Remove galleries with a missing source` clears out the galleries whose files have been deleted from disk, which until now had to be dismissed one at a time. It acts on the tab you are looking at, only ever removes the library entry, never the files, and asks once with the count in front of it. Whether a source is missing is rechecked when you run it rather than trusted from startup, and a whole drive that cannot be reached is refused by name instead of being offered up for deletion.
    - Gallery hover tooltips show the folder name rather than the stored title.
    - A `HappyPanda.spec` file for building with PyInstaller.

- Fixes
    - **Startup no longer freezes the window, and a large library starts in seconds.** Sorting by a date re-read every gallery's date as text on every comparison, and the toolkit Happypanda now runs on does that about twelve times slower than the old one, so sorting the whole library by date added - the default - kept Windows reporting the window as not responding for close to two minutes of a startup that took over two. On a 20,000-gallery library the startup now takes about 13 seconds and is never reported as not responding. Sorting by any date from the menu or a column is as quick as sorting by title.
    - Clicking a column header in the table view sorts by that column. It used to go on sorting by whatever the sort menu last chose and only change the direction, so with the default date sort clicking `Title` reordered the table by date; and under the title sort, clicking `Date Added` or `Published` froze the window the same way the startup did. Clicking the same header again reverses it.
    - The sort menu, the table header's sort arrow and the direction icon always agree about how the galleries are sorted, whichever of them changed it. The sort is remembered for the next start together with its direction, however it was chosen - so a column clicked twice to sort Z to A opens Z to A - except `Tags`, `Chapters` and `Page Count`, which read information that is only loaded after the startup has sorted. Clearing a search or adding galleries while sorted by `Tags` no longer stalls the window either. `Asc/Desc` reverses the current sort instead of quietly resetting a header's column.
    - Galleries with no publication date, or never read, sort after the ones that have a date in both directions. Sorting by `Date Published` or `Last Read` newest first used to open on every gallery with no date - most of an inbox - ahead of any that had one.
    - A language in a folder name is recognised whether or not the language dropdowns list it. They offer four names plus whatever you have added, while the source tags 83, so a folder ending `[Korean]`, `[Dutch]` or `[Vietnamese]` used to be stored under your default language - and then searched for with an `l:english$` filter that could only ever exclude the gallery being looked for. The same list decides whether a leading bracket is an artist or a language, so `[Korean] Some Title` no longer goes out as `a:korean$` either.
    - Editing a gallery no longer replaces a language the dropdown does not list. The dropdown fell back to the default when it could not show the stored value, and while a single gallery is being edited that field is always written on Done - so opening a Korean gallery and pressing Done filed it as English, with no undo and nothing said. The gallery's own language is now added to the list when it is missing from it, the same way the better version language setting already kept an unlisted value.
    - Metadata fetching no longer files `translated`, `rewrite`, `text cleaned` or `textless narrative` as a gallery's language. The source keeps those in the same `language:` namespace as a real language, to say what was done to a release rather than what language it is in, and whichever came back first was taken. A real language now wins wherever it sits in the list; where the source names none of them, what it did write is still kept rather than thrown away.
    - `Better version` in the gallery chooser no longer files part of the row's own text as the release's native title. It recovered that title by splitting the row at its first line break, so the line naming the artist - new in this release - ended up stored in the native title field instead. The native title is now read from the field the source answered with, which cannot pick up whatever the row learns to show next.
    - A scan or recheck that fails now hands the metadata lock back before it reports being finished, rather than a moment after. The report is what re-enables starting another one, so a run begun in that moment could have had its own lock cleared by the one that just died, and two of them would then search at once against a source that bans on request volume.
    - Stopping a recheck says `Stopping...` until the run actually ends, instead of immediately offering to start another one that would be refused.
    - `Not interested` on the better versions list removes the row you picked even if a scan has added a row and re-sorted the list while the menu was open.
    - **Fetching metadata works again at all.** `Web / Fetch metadata` and every other entry point to it raised an error immediately and did nothing: the change that gave each background job a thread that ends with its work removed the local variable this path still referred to, and nothing in the test suite reaches an application menu, so it went unnoticed. A headless harness that builds the real window now covers that path. Worth knowing before your first run: with `Web / Metadata / Replace metadata` on, fetching overwrites stored titles, artists, tags and dates and there is no undo, and for as long as this was broken nothing was being overwritten. Aim the first run at a selection rather than a whole tab.
    - The gallery info popup fades in the first time it is shown, the way it already did on every later one. Its show handler tested an animation constant rather than the animation's state, so the first appearance started its fade from fully opaque and simply snapped into view.
    - The scrollbar in the gallery info popup is visible. Its handle was painted the same colour as the popup behind it, so a tag list long enough to scroll looked like it had no bar at all - as did the chapter list, and the lists inside the gallery chooser and the other popups, which sit on the same dark background.
    - **panda.chaika.moe metadata fetching works again.** It had been broken three ways at once: the fallback source list silently emptied itself and could never be restored, chaika's results were discarded by the new confidence check because chaika reports no title with them, and chaika was only ever queried by image hash. It now searches by title as well, addresses each hit individually, and talks to the site over HTTPS.
    - Fetching metadata no longer crashes on a gallery whose source reports no publication date. A negative or missing timestamp is now read as "unknown" rather than aborting the whole run partway through.
    - `Use currently applied gallery URL` now does what it says for every source. A gallery holding a chaika URL used to be searched for on e-hentai first, and was only fetched from its own URL after every one of those searches had failed.
    - Gallery URLs on `e-hentai.org` are recognised again; only the older `g.e-hentai.org` form was, which also meant a link Happypanda had itself rewritten stopped being accepted afterwards.
    - Temporary IP bans are detected properly and waited out, with the remaining time shown in the notification bar.
    - A gallery with no artist prefix no longer adopts its language suffix as the artist. `Guardian of Faith II [English]` used to be filed under the artist "English", which then went out as an `artist:english$` filter on every search for it.
    - A language tag is recognised even when it is the only bracketed group in the name, so `Some Title [English]` is no longer filed under the default language and searched for with the wrong language filter.
    - Titles are no longer searched for with the full width characters a filesystem forces onto them. Most importantly `｜`, the separator between a romaji and a translated title, which no source indexes.
    - A gallery whose folder name drops the source's trailing `-Subtitle-` is matched again. The extra text alone was enough to push an otherwise exact match below the confidence threshold.
    - A sequel numbered with a roman numeral is told apart from its siblings. `Kino no Tabi no Erohon V` and `Kino no Tabi no Erohon II` contain no digits, so the numbering check had nothing to compare and a 97% title similarity was enough to apply the wrong gallery's metadata over yours. Roman numerals now count as the numbers they denote, in both the ASCII and the full width form - which also recovers matches that were being lost the other way round, such as a folder named `DepthSinker2` against a source title of `DepthSinker II`. Japanese numerals are deliberately still not read: `ni`, `san` and `go` are the particle, the honorific and an ordinary syllable far more often than they are numbers, and reading them broke 142 working matches while fixing none.
    - Search results are matched against gallery titles written in Japanese. A Japanese folder name and a romaji site title share no characters, so the right result used to score zero and be thrown away.
    - `Also search expunged galleries` works again. e-hentai used to fold expunged galleries into ordinary search results; it now lists them separately and exclusively, so the option had quietly turned into "search **only** expunged galleries" - enabling it would have made every normal search fail. Expunged galleries are now reached with a second search, run only when the first found nothing, and the option is worth turning on for an older library whose galleries may since have been deleted from the source.
    - Galleries in Japanese are no longer searched for with a `language:japanese$` filter, which matches nothing at all. E-Hentai tags a language only when it is not its own default, so the absence of a tag is what says Japanese, and almost every search for an untranslated gallery was narrowed to nothing before it ran.
    - The plain title, with no artist filter, no language filter and no `[Circle (Artist)]` prefix, is now always one of the four search attempts rather than the fifth. It is the form a source is likeliest to hold, and a gallery whose stored artist or language is the thing the source disagrees with never reached it. Neither change costs an extra request.
    - Covers in the gallery chooser load instead of coming up blank. The thumbnail host refuses any request that does not name the source's own site as its referer, and answers with an error page that arrives as a perfectly ordinary file.
    - A cover that cannot be decoded no longer leaves its gallery on "Loading..." or "Thumbnail regeneration needed!" for good. The failure used to stay inside the worker thread, where nothing ever looked at it; the gallery now falls back to the placeholder cover and the reason is written to the log. Galleries already in this state pick up a real cover from `Settings / Advanced / Regenerate Thumbnails`.
    - Very large pages get a thumbnail again. Pillow refuses an image past a decompression bomb ceiling, and a stitched cosplay set or a large scan runs past the stock one honestly, so the ceiling is now 400 megapixels.
    - A gallery that keeps no pages of its own, only subfolders of them, gets its cover from the first subfolder that holds one. Nothing at the top level used to mean no cover at all.
    - The cover is the gallery's first page rather than whichever filename sorted first as text. Pages and subfolders are now ordered the way the file manager orders them, so `2` comes before `10` and `007` sorts as seven.
    - A folder whose name ends in `.zip`, `.cbz` or `.7z` is read as a folder. That is what an archive extracted in place leaves behind, and handing it to the archive reader got the default cover instead of the gallery's own first page.
    - Double clicking a gallery in a popup no longer crashes. The cover widget went on using itself after telling everyone it had been clicked, by which point a listener may have closed the window it lived in and destroyed it.
    - The panda.chaika.moe fallback searched for the artist's name instead of the title whenever the title had been long enough to be trimmed, and could build a lookup URL out of a title where a file hash belongs.
    - An unexpected error during a metadata run no longer leaves the fetcher permanently "already running" until the application is restarted, and a gallery whose folder name yields no searchable title is reported rather than aborting the run.
    - Background work no longer leaves its thread running for the rest of the session. Fetching metadata, populating from a directory, scanning for new galleries and checking for updates each started a thread that was never asked to stop, so they accumulated for as long as the application stayed open. A gallery dialog closed while its metadata fetch was still running is fixed by the same change: it waited for that thread to finish before closing, which is something that could not previously happen, so the window hid itself and stayed open forever.
    - Following a second page of search results now waits as long as any other request rather than as little as a second.
    - Potential crash when RoboBrowser met an unsupported encoding.
    - The notification bar renders above the full screen blur effect.
    - `settings.ini` is written and read as UTF-8 whatever the machine's locale is. A frozen build never turns on Python's UTF-8 mode however the environment is set, while running from source does, so the two disagreed about how to store a non-ASCII library path and neither could read the other's. An ini left behind in the old encoding is migrated on the next launch rather than aborting startup before there is a window to report it in, and a byte order mark left by a text editor no longer hides the first section.
    - Gallery titles appear in `happypanda.log` as text rather than as a bytes repr with every non-ASCII character escaped, so a Japanese or accented title can be read straight out of a run. The log handlers have been UTF-8 all along; it was the log calls themselves that encoded the title before formatting it.

- Changes
    - `Advanced / Misc / Force High DPI support` is gone. The toolkit Happypanda is now built on scales for high DPI displays on its own and cannot be told not to, so the option had nothing left to switch and the restart it asked for changed nothing. Any value left in your `settings.ini` is ignored.
    - The gallery chooser says who made each candidate. A search listing gives one title and the similarity score never sees the artist at all - it is stripped off both titles before they are compared - so two unrelated doujins that happen to share a short title, or a gallery named after a character, look identical in the list. Each choice now carries a third line naming the artist and circle the source credits it to. It costs no extra requests: the lookup that fetches each candidate's native title and cover already returns this. Shown rather than filtered on, deliberately - your folder name's `[Circle (Artist)]` disagrees with the source's own tag for about 8% of the galleries that state one and is missing from 41% of them, so dropping results on it would throw away correct matches.
    - Artist and language filters are sent to the source in its own short form, `a:` and `l:` rather than `artist:` and `language:`. A search query has a length budget and the filters are spent out of it, so the twelve characters this gives back go to the title instead: across a whole library it cuts the searches that have to drop their quoted phrase, which matches nothing once it has been cut mid-title, from 220 to 101. The short forms were checked against live searches rather than taken from the wiki, which documents them for tagging and omits them from its list of search qualifiers. Happypanda's own search box is unaffected and still takes `artist:` and `language:`.
    - Metadata title searches now try several forms of a title in a fixed order: as it stands, without the artist filter, cut at the `｜` separator, and without the language filter. The order is capped so a gallery that matches nothing costs a bounded number of requests.
    - Search results paginate. Only a page that comes back full is followed, so a specific title still costs a single request while a broad one no longer stops at the first 25 hits.
    - A candidate whose volume, chapter or sequel number differs from the local title is rejected outright, whatever it scores. `Kaizoku Kyonyuu` and `Kaizoku Kyonyuu 2` are otherwise a hair apart.
    - Thumbnail generation and loading may use more threads.
    - **The library is read from the database in a single batch at startup, which is much faster on a large one.** `Advanced / Database / Startup gallery fetch limit` now defaults to 0, meaning no limit, where it used to read 1000 galleries at a time. On a 20,000-gallery library that takes the gallery-loading step from about 38 seconds to about 5, and the whole startup from about 135 seconds to about 104. The reason is not the reading: the grid keeps its rows sorted, and every batch after the first makes it re-sort everything already loaded, so the cost is paid again and again. Four batches turn out to be no better than twenty - only one batch avoids it. An existing `settings.ini` only keeps the old batching if it actually stores this option; it is not written until you confirm the settings dialog once, so most upgrades pick the new default up on their own. The cost is that progress is reported once instead of continuously and the window is unresponsive for one longer stretch rather than several shorter ones; on this library it went from a 55-second freeze to a 92-second one, and the window is reported as not responding either way. That freeze had a cause of its own, and is gone: see the sorting fix under Fixes.
    - Updated QtAwesome to 1.4.0 and the icon set to Font Awesome 6.
    - When several results tie, the one in the gallery's own language is offered first. Sources list newest first, which used to bury the release actually held locally underneath every later translation of it.
    - The log now records the candidates a search settled on, with their scores, at the normal logging level. An ordering complaint about the chooser could not be looked into otherwise. It also records why a search found nothing: the closest rejected candidates with their scores, and anything dropped by the numbering check. `misc/analyze_fetch_log.py` summarises a run from it.
    - Happypanda now runs on Python 3.14, which the About page reads off the running interpreter rather than repeating from a literal that has to be remembered on every upgrade. Every dependency is pinned to the version it was tested against, so a fresh install resolves the same way twice; Werkzeug is held below 3.2, which removes a type RoboBrowser still uses.

## Happypanda v1.7.0

- New Features
    - Namespace Aliases in Search: The settings menu under "Application" has a new "Search" tab where you can define namespace aliases to make searching a bit more comfortable. The default set of aliases is taken from the [EHWiki](https://ehwiki.org/wiki/Namespace): 

- Ignored Tags
    - The settings menu under "Application" / "Ignore" has a new section where you can set up a list of tags that can be ignored when Happypanda fetches tags from certain automated sources, in case you were ever annoyed that tags like "forbidden content" just took up unused space in your database.

- Changes
    - If a gallery's author is "Anthology" or "アンソロジー", then Happypanda should no longer replace it with the first artist found in the tags, be it from an online tag fetch or an embedded metadata file.



## Happypanda v1.6.2

- Fixes
    - Removing tags from galleries with the edit dialog is possible again.

- Changes
    - Galleries can only have one edit dialog open at a time. That includes multi-gallery edit dialogs. Hitting F2 on a gallery with an already open edit dialog will not create a new one but re-raise the existing one to the top and re-center it on the main window.
    - Pretty large speedup for loading all the data from the database when the app starts. With my test database of 18700 galleries the startup loading time went from 38s down to about 7.
    - New option: `Advanced / Database / Startup gallery fetch limit`
        - If you have galleries in the 4-digit range or more, you may have noticed that the number of loaded galleries upon startup changes in steps of 500. This setting can increase that number and speed up the process. You can even set it to 0 to have the app fetch all galleries in one batch, but be aware that this will probably make the GUI appear stuck until it's done.
        - If you don't touch this setting, the default value is 1000.
    - The toolbar at the top as well as the default tabs "Favorites", "Library" and "Inbox" no longer have context menus. The only contents in them were a "Show" action that hid the entire toolbar or a "Close" action that closed a tab with no way to get them back outside of an app restart.


## Happypanda v1.6.1

- Fixes
    - Fix for https://github.com/mycropen/happypanda/issues/2 (Crash after failed metadata fetch).
    - Directory monitoring can be enabled again. The watchdog observer API had changed.

- Changes
    - You can no longer open multiple gallery edit dialogs for the same existing gallery. That includes single-gallery dialogs (F2) and multi-gallery dialogs (Shift+F2). You can still open as many dialogs to make new galleries (Ctrl+N) as you want.
    - When editing tags in the gallery edit dialog, the auto completer will now disappear if its only possible suggestion is the same string that prompted it.
    - The gallery meta window (that appears when you click on a gallery) can now appear above galleries even at the bottom left or right edge of the view when until now the fallback option was to put it below those galleries and likely completely out of view.
    - Removed dependency on scandir as all of that is in the standard library nowadays.


## Happypanda v1.6

- upgraded the Python version to 3.13
- upgraded the PyQt version to 5.15

- Changes & New Features
    - New setting for the gallery edit window default width: `Visual / General / Gallery Edit Dialog` or `galleryedit.w` value in the `[Visual]` section of the settings.ini. This is to account for high DPI screens and window scaling.
    - Gallery edit dialog is no longer scrollable and instead just adjusts itself to its contents.
    - Archives with less than 4 pages and a non-image file can now be added as galleries.
    - A new option that lets you send every archive you drag & drop into Happypanda to the inbox, even if it's only one: `Application / General / Send every new gallery to the inbox` or `always send to inbox` in the `[Application]` section of the settings ini.
    - The gallery meta window that appears when you click on a gallery is now confined horizontally to the main window borders.
    - Support for .7z and .cb7 archives.

- Fixes
    - Pressing Ctrl or Enter in a multi-gallery edit dialog shouldn't give you an error message anymore.
    - The table view no longer tries to hide the nonexistent popup window.
    - If the notification bar didn't show correctly for you, it should be visible again now.


## Happypanda v1.5.1

- Changes
    - Allow .webp images in archives. If you got "Invalid gallery source" before, try again now.

- Fixes
    - Separating titles that have parentheses before the "|" should no longer cause the app to freeze.


## Happypanda v1.5

- Changes
    - Holding Ctrl in a gallery edit dialog now lets you get the metadata for all open gallery edit dialogs at once
        - Technically in batches of 25, but that's much better than 1 at a time


## Happypanda v1.4

- Changes
    - Option to disable desktop notifications (Application/General)
    - Gallery info window hides itself when changing tabs
    - New sort option: Page Count
        - Because of how the database is set up, this sort option will not be saved after closing the app.
    - New Options (Web/Metadata) to selectively copy some metadata anyway if "Replace all old metadata" is not set
        - No more copypasting url, title and author for new galleries. Now only the url is needed.
        - Options are "Always", "Inbox & new galleries only" or "Never".
    
- Fixes
    - #1: the crash that happened when closing a gallery dialog with the X after fetching metadata.


## Happypanda v1.3

- Changes
    - The gallery info window now disappears when moving the selection with the keyboard
    - New option: Dual Search in Application/General/Search ('dual gallery search' in settings.ini)
        - default False
        - If True: Any search will affect both Library (+ Favorites) and Inbox. Clearing it in one will clear both.
        - If False: Searches are kept separate (like before), but switching between Inbox and Library will restore the search term in the search bar. So if the search bar was cleared in the Inbox, the Library view will still be filtered but not with an empty search bar anymore.
    - New option: Searchable Inbox in Application/General/Search ('searchable inbox' in settings.ini)
        - default True
        - Disabling search in the Inbox may fix an issue where one of multiple new galleries items isn't shown until it's "refreshed" with an empty search.

- Fixes
    - Gallery thumbnails should now load more consistently when scrolling with arrow keys
    - The issue where sometimes dropping multiple new galleries into Happypanda leaves one of them hidden in the Inbox until you perform a blank search is possibly fixed while keeping the Inbox searchable. If not, then try disabling search in the Inbox.


## Happypanda v1.2.5

- Changes
    - Keys and shortcuts
        - F2 with multiple gallery items selected: Open individual edit dialogs
        - Shift+F2 with multiple gallery items selected: Open combined edit dialog
        - In edit dialog: Pressing Tab once when editing url brings the name edit into focus. Before it needed 3 Tab presses.
        - In edit dialog: Tab now changes focus when editing the description and tags.
    - New option "Use global metadata fetch lock" in Web/Metadata or "global ehen metadata fetch lock" in settings.ini.
        - Default is True to keep previous behavior (only one edit dialog can fetch metadata at a time). Set it to False to allow multiple gallery edit dialogs to queue metadata fetches from their urls. This caused issues in the past, so change it back if it does for you.

- Fixes
    - Trying to drag a gallery caused a 'critical error'. Drag & drop for galleries has been disabled since that feature was never finished anyway.


## Happypanda v1.2.4

- Changes
    - New keyboard shortcuts:
        - F2 with one gallery item selected: Open edit dialog
        - In edit dialog: Return while editing url: fetch metadata
        - In edit dialog: Return anywhere else: Same as 'Done' button
        - In edit dialog: Escape: Same as 'Cancel' button


## Happypanda v1.2.3

- Fixes
    - Sidebar doesn't open and close itself anymore when unminimizing the window.


## Happypanda v1.2.2

- Changes
   - Added option for removing starting parentheses in new gallery titles
   - Added option for removing curly braces in new gallery titles
   - Added option for keeping only part of a new gallery title that's split with a '|'


## Happypanda v1.2.1

- Changes
   - Publication locations like (C86), (COMIC1☆10), etc. will be stripped from the beginning of new gallery titles.
   - Anything in curly braces like {5 a.m.}, {Hennojin}, etc. will be stripped from new gallery titles
   - Starts maximized by default.


## Happypanda v1.2

- Changes
  - HP will now check for updates in this fork (Kramoule's)
- Fixes
   - Fixed some crashes that happened when the current sort was set on *Author*
   - Fixed pages numbering being 0 when image files have extension name in uppercase
   - Titles that contain a slash should now be correctly parsed
   - Export/Import of metadata fixed


## Happypanda v1.1.1

- Fixes
   - Fixed Metadata fetcher with the new design of E-h/Exh
   - Small bug fixes


## Happypanda v1.1

- Fixes
   - Fixed HP settings unusable without internet connection
   

## Happypanda v1.0

* New stuff
    - New GUI look
    - New helpful color widgets added to `Settings -> Visual` [rachmadaniHaryono]
    - Gallery Contextmenu:
        - Added `Set rating` to quickly set gallery rating
        - Added `Lookup Artist` to open a new tab on preferred site with the artist's galleries
        - Added `Reset read count` under `Advanced`
    - Gallery Lists are now included when exporting gallery data
    - New sorting option: Gallery Rating
    - It is now possible to also append tags to galleries instead of replacing when editing
    - New gallery download source: `asmhentai.com` [rachmadaniHaryono]
    - New [special namespaced tag](https://github.com/Pewpews/happypanda/wiki/Gallery-Searching#special-namespaced-tags): `URL`
        - Use like this: `url:none` or `url:g.e-hentai`
    - Many quality of life changes

* Changed stuff
    - `g.e-hentai` to `e-hentai`
        - Old URLs will automatically be converted to new on metadata fetch
    - Displaying rating on galleries is now optional
    - Improved search history
    - Improved gallery downloader (now very reliable) [rachmadaniHaryono]
    - Galleries will automatically be rated 5 stars on favorite
    - Gallery List edit popup will now appear in the middle of the application
    - Added a way to relogin into website

* Fixes
    - E-Hentai login & gallery downloading
    - `date added` metadata wasn't included when exporting gallery data
    - `last read` Metadata wasn't included when importing gallery data
    - backup database name would get unusually long [rachmadaniHaryono]
    - Fixed HDoujin `info.txt` parsing
    - Newly downloaded galleries would sometimes cause a crash
    - Attempting to download exhentai links without being logged in would cause a crash
    - Using the random gallery opener would in rare cases cause a crash
    - Moving a gallery would cause a crash from a raised PermissionError exception
    - Fetching metadata for galleries would return multiple unrelated galleries to choose among
    - Fetching metadata for galleries with a colored cover whose gallery source is an archive would sometimes cause a crash
    - Galleries with an empty tag field wouldn't show up on a `tag:none` filter search
    - Gallery Deleted popup would appear when deleting gallery files from the application
    - Attempting to download removed galleries would cause a crash
    - Some gallery importing issues



## Happypanda v0.30

- Someone finally convinced me into adding star ratings
    - *Note:* Ratings won't be fetched from EH since I find them useless... Though I might make it an option later on. 
    - External viewer icon on galleries has been removed in favor of this
- Visual make-over
- Improved how thumbnails are loaded in gridview
- Moving files into a monitored folder will now automatically add the galleries into your inbox 
- Added the following special namespaced tags:
    - `path:none` to filter galleries that has a broken source
    - `rating:integer` to filter galleries that has been rated `integer`
    - read more about them [here](https://github.com/Pewpews/happypanda/wiki/Gallery-Searching)
- Updated DB to version 0.26
    - Added `Rating` metadata
- Fixed bugs:
    - Attempting to add galleries on a fresh install was causing an exception
    - Moving files into a monitored folder, and then accepting the pop-up would cause an exception


## Happypanda v0.29

- Increased and improved stability and perfomance
- Shortened startup time
- Galleries are now added dynamically
- New feature: Tabs
    - New inbox tab for new gallery additions
    - Checking for duplicates will also make a new tab
- Gallery deletion will now process smoothly
- It is now possible to edit multiple galleries
- Type and Langauge in metadata popup window are now clickable to issue a search
- Updated DB to version 0.25
    - Added views in series table
- Visual changes in gridview
    - Added a recently added indicator
    - Gallery filetypes will now be displayed with text
- Added new options in settings
    - Removed option: autoadd scanned galleries
- Fixed bugs:
    + Fixed some metadata fetchings bugs
    + Fixed database import and export issues
    + Closing gallery metadata popup window caused an exception
    + Fetching metadata with no internet connection caused an exception
    + Invalid folders/archives were being picked up by the monitor
    + Fixed default language issues
    + Metadata would sometimes fail when doing a filesearch
    + Thumbnail cache dir was not being cleared
    + Adding from directory was not possible with single gallery add method


## Happypanda v0.28.1

- Fixed bugs:
    + Fixed typo in external viewer args
    + Fixed regex not working when in namespace
    + Fixed thumbnail generation causing an unhandled exception
    + Moved directories kept their old path
    + Fixed auto metadata fetcher failing when mixing galleries with colored covers and galleries with greyscale covers
    + Gallery Metadata window wouldn't stay open
    + Fixed a DB bug causing all kinds of errors, including:
        + Editing a gallery while fetching its metadata would cause an exception
    + Closing the gallery dialog while fetching metadata would cause an exception


## Happypanda v0.28

- Improved perfomance of grid view significantly
- Galleries are now draggable
    + It is now possible to add galleries to a list by dragging them to the list
- Improved metadata fetching accuracy from EH
- Improved gallery lists with new options
    + It is now possible to enable several search options on per gallerylist basis
    + A new *Enforce* option to enforce the gallerylist filter
- Improved gallery search
    + New special namespaced tags: `read_count`, `date_added` and `last_read`
        + Read more about them in the gallery searching guide
    + New `<` less than and `>` greater than operator to be used with some special namespaced tags
        + Read about it in the special namespaced tags section in the gallery searching guide
- Brought back the old way of gaining access to EX
    - Only to be used if you can't gain access to EX by logging in normally
- Added ability to specify arguments sent to viewer in settings (in the `Advanced` section)
    + If when opening a gallery only the first image was viewable by your viewer, try change the arguments sent to the viewer
- Updated the database to version 0.24 with the addition of new gallerylist fields
- Moved regex search option to searchbar
- Added grid spacing option in settings (`Visual->Grid View`)
- Added folder and file extensions ignoring in settings (`Application->Ignore`)
    + Folder and file extensions ignoring will work for the directory monitor and *Add gallery..* and *Populate from folder* gallery adding methods
- Added new default language: Chinese
- Improved and fixed URL parser in gallery-downloader
- Custom languages will now be parsed from filenames along with the default languages
- Tags are now sorted alphabetically everywhere
- Gallerylists in contextmenu are also now sorted
- Reason for why metadata fecthing failed is now shown in the failed-to-get-metadata-gallery popup
- The current search term will now be upkeeped (upkept?) when switching between views
- Disabled some tray messages on linux to prevent crash
- The current gallerylist context will now be shown on the statusbar
- The keys `del` and `shift + del` are now bound to gallery deletion
- Added *exclude/include in auto metadata fetcher* in contextmenu for selection
- Bug fixes:
    + No thumbnails were created for images with incorrect extensions (namely png images with .jpg extension)
    + Only accounts with access to EX were able to login
    + Some filesystem events were not being detected
    + Name parser was not parsing languages
    + Some gallery attributes to not be added to the db on initial gallery creation
    + Attempting to fetch metadata while an instance of auto metadata fetcher was already running caused an exception
    + Gallery wasn't removed in view when removing from the duplicate-galleries popup
    + Other minor bugs


## Happypanda v0.27

- Many visual changes
    + Including new ribbon indicating gallery type in gridview
- New sidebar widget:
    + New feature: Gallery lists
    + New feature: Artists list
    + Moved *NS & Tags* treelist from settings to sidebar widget
- Metadata fetcher:
    + Galleries with multiple hits found will now come last in the fetching process
    + Added fallback system to fetch metadata from other sources than EH
        + Currently supports panda.chaika.moe
- Gallery downloader should now be more tolerant to mistakes in URLs
- Added a "gallery source is missing" indicator in grid view
- Removed EH member_id and pass_hash in favor for EH login method
- Added new sort option: *last read*
- Added option to exclude/include gallery from auto metadata fetcher in the contextmenu
- Added general key shortcuts (read about the not so obvious shortcuts [here](https://github.com/Pewpews/happypanda/wiki/Keyboard-Shortcuts))
- Added support for new metafile: *HDoujin downloader*'s default into.txt file
- Added support for panda.chaika.moe URLs when fetching metadata
- Updated database to version 0.23:
    - Gallery lists addition
    - New unique indexes in some tables
    - Thumbnail paths are now relative (removing the need to rebuild thumbs when moving Happypanda folder)
- Settings:
    + Added option to force support for high DPI displays
    + Added option to control the gallery size in grid view
    + Enabled most *Gallery* options in the *Visual* section for OSX
    + Added options to customize gallery type ribbon colors
    + Added options to set default gallery values
    + Added a way to add custom languages in settings
    + Added option to send deleted files  to recycle bin
    + Added option to hide the sidebar widget on startup
- Bug fixes:
    + Fixed a bug causing some external viewers to only be able to view the first image
    + Fixed metadata disappearance bug (hopefully, for real this time!)
    + Fixed decoding issues preventing some galleries from getting imported
    + Fixed lots of critical database issues requiring a rebuild for updating users
    + Fixed gallery downloading from g.e-hentai
    + Fixed bug causing "Show in library" to not work properly
    + Fixed a bug causing a hang while fetching metadata
    + Fixed a bug causing autometadata fetcher to sometimes fail fetching for some galleries
    + Fixed hand when checking for duplicates
    + Fixed database rebuild issues
    + Potentially fixed a bug preventing archives from being imported, courtesy of KuroiKitsu
    + Many other minor bugs


## Happypanda v0.26

- Startup is now slighty faster
- New redesigned gallery metadata window!
    + New chapter view in the metadata window
    + Artist field is now clickable to issue a search for galleries with same artist
- Some GUI changes
- New advanced gallery search **(make sure to read the search guide found in `Settings -> About -> Search Guide`)**
    + Case sensitive searching
    + Whole terms match searching
    + Terms excluding
    + New special namespaced tags (Read about them in `Settings -> About -> Search Guide`)
- New import/export database feature found in `Settings -> About -> Database`
- Added new column in `Skipped paths` window to show what reason caused a file to be skipped
- Gallery downloader
    + Added new batch urls window to gallery downloader
    + Gallery downloading from `panda.chaika.moe` is now using its new api
    + Added context menu's to download items
    + Added download progress on download items
    + Doubleclicking on finished download items will open its containing folder
- Added autocomplete on the artist field in gallery edit dialog
- Activated the `last read` attribute on galleries
- Improved hash generation
- Introducing metafiles:
    + Files containing gallery metadata in same folder/archive is now detected on import
    + Only supports [eze](https://github.com/dnsev-h/eze)'s `info.json` files for now
- Settings
    + Moved alot of options around. **Note: Some options will be reset**
    + Reworded some options and fixed typos
    + Enabled the `Database` tab in *About* section with import/export database feature
- Updated the database to version 0.22
    + Database will now be backed up before upgrading
- Clicking on the tray icon ballon will now activate Happypanda
- Thumbnail regenerating
    + Added confirmation popup when about to regenerate thumbnails
    + Application restart is no longer required after regenerating thumbnails
    + Added confirmation popup asking about if the thumbnail cache should be cleaned before regenerating
- Renamed `Random Gallery Opener` to `Open random gallery` and also moved it to the Gallery menu on the toolbar
- `Open random gallery` will now only pick a random gallery in current view.
    + *E.g. switching to the favorite view will make it pick a random gallery among the favorites*
- Fixed bugs:
    + Fixed a bug causing archives downloaded from g.e/ex to fail when trying to add to library
    + Fixed a bug where fetching galleries from the database would sometimes throw an exception
    + Fixed a bug causing people running from source to never see the new update notification
    + Fixed some popup blur bug
    + Fixed an annoyance where the text cursor would always move to the end when searching
    + Fixed a bug where `Show in Folder` and `Open folder/archive` in gallery context menu was doing the same thing
    + Fixed a bug where tags fetched from chaika included underscores
    + Fixed bug where the notification widget would sometimes not show messages
    + Fixed bug where chapters added to gallery with directory source would not open correctly


## Happypanda v0.25

- Added *Show in folder* entry in gallery contextmenu
- Gallery popups
    + A contextmenu will now be shown when you rightclick a gallery
    + Added *Skip* button in the metadata gallery chooser popup (the one asking you which gallery you want to extract metadata from)
    + The text in metadata gallery chooser popups will now wrap
    + Added tooltips displaying title and artist when hovering galleries in some popups
- Settings
    + A new button allowing you to recreate your thumbnail cache is now in *Settings* -> *Advanced* -> *Gallery*
    + Added new tab *Downloader* in *Web* section
    + Renamed *General* tab in *Web* section to *Metadata*
    + Some options in settings will now show a tooltip explaining the option on hover
- You can now go back to previous or to next search terms with the two new buttons beside the search bar (hidden until you actually search something)
    + Back and Forward keys has been bound to these two buttons (very OS dependent but something like `ALT + LEFT ARROW` etc.) Back and Forward buttons on your mouse should also probably work (*shrugs*)
    + Added *Use current gallery link* checkbox option in *Web* section
- Toolbar
    + Renamed *Misc* to *Tools*
    + New *Scan for new galleries* entry in *Gallery*
    + New *Gallery Downloader* entry in *Tools*
- Gallery downloading
    + Supports archive and torrent downloading
    + archives will be automatically imported while torrents will be sent to your torrent client
    + Currently supports ex/g.e gallery urls and panda.chaika.moe gallery/archive urls
        - Note: downloading archives from ex/g.e will be handled the same way as if you did it in your browser, i.e. it will cost you GP/credits.
- Tray icon
    + You can now manually check for a new update by right clicking on the tray icon
    + Triggering the tray icon, i.e. clicking on it, will now activate (showing it) the Happypanda window
- Fixed bugs:
    + Fixed a bug where skipped galleries/paths would get moved
    + Fixed a bug where gallery archives/folders containing images with `.jpeg` and/or capitalized (`.JPG`, etc.) extensions were treated as invalid gallery sources, or causing the program to behave very weird if they managed to get imported somehow
    + Fixed a bug where you couldn't search with the Regex option turned on
    + Fixed a bug where changing gallery covers would fail if the previous cover was not deleted or found.
    + Fixed a bug where non-existent monitored folders were not detected
    + Fixed a bug in the user settings (*settings.ini*) parsing, hence the reset
    + Fixed other minor misc. bugs


## Happypanda v0.24.1

- Fixed bugs:
    + Removing a gallery and its files should now work
    + Popups was staying on top of all windows


## Happypanda v0.24

- Mostly gui fixes/improvements
    + Changed toolbar style and icons
    + Added new native spinners
    + Added spinner for the metadata fetching process
    + Added spinner for initial load
    + Added spinner for DB activity
    + Removed sort contextmenu and added it to the toolbar
    + Removed some space around galleries in grid view
    + Added kinetic scrolling when scrolling with middlemouse button
- New DB Overview window and tab in settings dialog
    + you can now see all namespaces and tags in the `Namespace and Tags` tab
- Pressing the return-key will now open selected galleries
- New options in settings dialog
    + Make extracting archives before opening optional in `Application -> General`
    + Open chapters sequentially or all at once in `Application -> General`
- Added a confirmation when closing while there is still DB activity to avoid data loss
- Added log file rotation
    + When happypanda.log reaches `10 mb` a new file will be made (rotating between 3 files)
- Fixed bugs:
    + Temporarily fixed a critical bug where galleries wouldn't load
    + Fixed a bug where the tray icon would stay even after closing the application
    + Fixed a bug where clicking on a tag with no namespace in the Gallery Metadata Popup would search the tag with a blank namespace
    + Fixed a minor bug where when opening the settings dialog a small window would appear first in a split second


## Happypanda v0.23

- Stability and perfomance increase for very large libraries
    + Instant startup: Galleries are now lazily loaded
    + Application now supports very large galleries (tested with 10k galleries)
    + Gallery searching will now scale with amount of galleries (means, no freezes when searching)
    + Same with adding new galleries.
- The gallery window appearing when you click on a gallery is now interactable
    + Clicking on a link will open it in your default browser
    + Clicking on a tag will search for the tag
- Added some animation and a spinner
- Fixed bugs:
    + Fixed critical bug where slected galleries were not mapped properly. (Which sometimes resulted in wrong galleries being removed)
    + Fixed a bug where pressing CTRL + A to select all galleries would tell that i has selected the total amount of galleries multipled by 3
    + Fixed a bug where the notificationbar would sometiems not hide itself
    + & other minor bugs


## Happypanda v0.22

- Added support for .rar files.
    + To enable rar support, specify the path to unrar in Settings -> Application -> General. Follow the instructions for your OS.
- Fixed most (if not all) gallery importing issues
- Added a way to populate form archive.
    + Note: Subfolders will always be treated as galleries when populating from an archive.
- Fixed a bug where users who tries Happypanda for the first time would see the 'rebuilding galleries' dialog.
- & other misc. changes


## Happypanda v0.21

- The application will now ask if you want to view skipped paths after searching for galleries
- Added 'delete successful' in the notificationbar
- Bugfixes:
    + Fixed critical bug: Could not open chapters
        + If your gallery still won't open then please try re-adding the gallery.
    + Fixed bug: Covers for archives with no folder in-between were not being found
    + & other minor bugs


## Happypanda v0.20

- Added support for recursively importing of galleries (applies to archives)
    + Directories in archives will now be noticed when importing
    + Directories with archives as chapters will now be properly imported
- Added drag and drop feature for directories and archives
- Galleries that was unsuccesful during gallery fetching will now be displayed in a popup
- Added support for directory or archive ignoring
- Added support for changing gallery covers
- Added: move imported galleries to a specified folder feature
- Increased speed of Populate from folder and Add galleries...
- Improved title parser to now remove unneecessary whitespaces
- Improved gallery hashing to avoid unnecessary hashing
- Added 'Add archive' button in chapter dialog
- Popups will now center on parent window correctly
    + It is now possible to move popups by leftclicking and dragging
    + Added background blur effect when popups are shown
- The rebuild galleries popup will now show real progress
- Settings:
    + Added new option: Treat subfolders as galleries
    + Added new option: Move imported galleries
    + Added new option: Scroll to new galleries (disabled)
    + Added new option: Open random gallery chapters
    + Added new option: Rename gallery source (disabled)
    + Added new tab in Advanced section: Gallery
    + Added new options: Gallery renamer (disabled)
    + Added new tab in Application section: Ignore
    + Enabled General tab in Application section
    + Reenabled Display on gallery options
- Contextmenu:
    + When selecting more galleries only options that apply to selected galleries will be shown
    + It is now possible to favourite/Unfavourite selected galleries
    + Reenabled removing of selected galleries
    + Added: Advanced and Change cover
- Updated database to version 0.2
- Bugfixes:
    + Fixed critical bug: not being able to add chapters
    + Fixed bug: removing a chapter would always remove the first chapter
    + Fixed bug: fetched metadata title and artist would not be formatted correctly
    + & other minor bugs


## Happypanda v0.19

- Improved stability
- Updated and fixed auto metadata fetcher:
    + Now twice as fast
    + No more need to restart application because it froze
    + Updated to support namespace fetching directly from the official API
- Improved tag autocompletion in gallery dialog
- Added a system tray to notify you about events such as auto metadata fetcher being done
- Sorting:
    + Added a new sort option: Publication Date
    + Added an indicator to the current sort option.
    + Your current sort option will now be saved
    + Increased pecision of date added
- Settings:
    + Added new options:
        * Continue auto metadata fetcher from where it left off
        * Use japanese title
    + Enabled option:
        * Auto add new galleries on startup
    + Removed options:
        * HTML Parsing or API
- Bugfixes:
    + Fixed critical bug: Fetching metadata from exhentai not working
    + Fixed critical bug: Duplicates were being created in database
    + Fixed a bug causing the update checker to always fail.


## Happypanda v0.18

- Greatly improved stability
- Added numbers to show how many galleries are left when fetching for metadata
- Possibly fixed a bug causing the *"big changes are about to occur"* popup to never disappear
- Fixed auto metadata fetcher (did not work before)


## Happypanda v0.17

- Improved UI
- Improved stability
- Improved the toolbar
-   + Added a way to find duplicate galleries
    + Added a random gallery opener
    + Added a way to fetch metadata for all your galleries
- Added a way to automagically fetch metadata from g.e-/exhentai
    + Fetching metadata is now safer, and should not get you banned
- Added a new sort option: Date added
- Added a place for gallery hashes in the database
- Added folder monitoring support
    + You will now be informed when you rename, remove or add a gallery source in one of your monitored folders
    + The application will scan for new galleries in all of your monitored folders on startup
- Added a new section in settings dialog: Application
    + Added new options in settings dialog
    + Enabled the 'General' tab in the Web section
- Bugfixes:
    + Fixed a bug where you could only open the first chapter of a gallery
    + Fixed a bug causing the application to crash when populating new galleries
    + Fixed some issues occuring when adding archive files
    + Fixed some issues occuring when editing galleries
    + other small bugfixes
- Disabled gallery source type and external program viewer icons because of memory leak (will be reenabled in a later version)
- Cleaned up some code


## Happypanda v0.16

- A more proper way to search for namespace and tags is now available
- Added support for external image viewers
- Added support for CBZ
- The settings button will now open up a real settings dialog
    + Tons of new options are now available in the settings dialog
- Restyled the grid view
- Restyled the tooltip to now show other metadata in grid view
- Added troubleshoot, regex and search guides
- Fixed bugs:
    + Application crashing when adding a gallery
    + Application crashing when refreshing
    + Namespace & tags not being shown correctly
    + & other small bugs


## Happypanda v0.15

- More options are now available in contextmenu when rightclicking a gallery
- It's now possible to add and remove chapters from a gallery
- Added a way to select more galleries
    + More options are now available in contextmenu for selected galleries
- Added more columns to tableview
    + Language
    + Link
    + Chapters
- Tweaked the grid view to reduce the lag when scrolling
- Added 1 more way to add galleries
- Already exisiting galleries will now be ignored
- Database will now try to auto update to newest version
- Updated Database to version 0.16 (breaking previous versions)
- Bugfixes


## Happypanda v0.14

- New tableview. Switch easily between grid view and table view with the new button beside the searchbar
- Now able to add and read ZIP archives (You don't need to extract anymore).
    + Added temp folder for when opening a chapter
- Changed icons to white icons
- Added tag autocomplete in series dialog
- Searchbar is now enabled for searching
    + Autocomplete will complete series' titles
    + Search for title or author
    + Tag searching is only partially supported.
- Added sort options in contextmenu
- Title of series is now included in the 'Opening chapter' string
- Happypanda will now check for new version on startup
- Happypanda will now log errors.
    + Added a --debug or -d option to create a detailed log
- Updated Database version to 0.15 (supports 0.14 & 0.13)
    + Now with unique tag mappings
    + A new metadata: times_read


## Happypanda v0.13

- First public release
