# Roadmap

Features that have been decided on but not built. Each entry records what the feature is, what
already exists to build it from, and what the hard part is — so that picking one up does not
start with rediscovering the same ground.

Delete an entry when it ships; describe the shipped behaviour in `CHANGELOG.md` instead.

---

## Bulk remove galleries whose source is gone

Galleries whose files have been deleted from disk — usually because an external deduplication
tool replaced them with a better copy — stay in the library and have to be dismissed one at a
time.

**What exists already.** `Gallery.dead_link` is set at load time in
`gallerydb.default_exec`/`gallery_map` from a plain `os.path.exists(gallery.path)`, and the
delegate already paints *"Cannot find gallery source!"* over those covers
(`version/gallery.py`). `GalleryDB.del_gallery(list_of_gallery, local=False)` already takes a
list and already defaults to leaving the filesystem alone.

**What is missing.** A way to select all of them at once, and one confirmation in front of it.

**The hard part.** Nothing technical — the risk is entirely that this deletes rows from the one
copy of the library index, so the confirmation has to state the count and be dismissible, and
the action must never fall through to a filesystem delete. Note also that `dead_link` is
computed once at load: a drive that was not mounted at startup makes *every* gallery on it look
dead. The confirmation should be refused, or the flag recomputed, when the share of dead
galleries is implausibly large.

---

## Scan for better versions of a gallery already held

Two variants of one feature, and they want to be built together as a single
*Scan for improved gallery versions* pass rather than as two:

- **Decensored releases.** A `[Decensored]` edition of a gallery already held in its censored
  form.
- **Translations.** An English release of a gallery held only in Japanese, Chinese or Korean.

Both surfaced the same way: during manual selection, the chooser was already showing the better
version as one of its candidates, with no way to say "not this one, but keep it in mind".

**What exists already.** More than it looks. The candidate list a search produces is the same
list this feature needs, `title_languages()` in `version/fetch.py` already reads the language
tags off a candidate title, and `[Decensored]` is a bracketed tag that the same helper shape
reads. The matching machinery — `canonical_title()`, the numbering guard, `match_forms()` —
already establishes "these two titles are the same work", which is the whole question here.

**The hard part is not matching, it is the request budget and the surface.** A scan across the
library is one search per gallery against a source that bans by IP, which is the same cost as a
full metadata run and cannot be a background task that fires on its own. It also needs somewhere
to put the results: this is a review list the user works through later, not a yes/no applied
inline, so it wants its own tab or window listing *held version → better version available*, and
each row's decision is "download this myself later", not anything the app applies to the
database. Decide that surface before writing any of the matching.

**Sequencing note.** This is worth building only after the ordinary metadata pass stops
producing a large tail of unmatched galleries, because it reuses the same searches and would
inherit every one of their failure modes.
