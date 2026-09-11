#!/usr/bin/env python3
"""Summarise a better-version scan run from happypanda.log.

A scan turns up very little by design, so the useful question is never "did it find anything"
but "which stage dropped what". The log records the query, how many hits came back, how many of
those were judged the same work, how many were classified, every candidate that was turned down
with the tags it held, and every row stored. That is a funnel:

    hits -> same work -> classified -> improves on something -> stored

Read it before concluding the scan is broken. A run whose hits are plentiful and whose rejections
all name another language or another series is working exactly as intended.

Usage:
    python misc/analyze_scan_log.py [happypanda.log] [--run N] [--rejections] [--gallery TEXT]

    --run N        analyse a scan run by index: 0 is the first in the file, -1 the last
                   (the default). A long run split across a rotated log is one run only when
                   the parts are concatenated in order first.
    --rejections   group every turned-down candidate by the reason its tags gave
    --gallery TEXT show the full detail for galleries whose title contains TEXT
"""

import argparse
import collections
import io
import os
import re
import sys

RUN_START_RE = re.compile(r'Scanning (\d+) of (\d+) galleries for better versions')
GALLERY_RE = re.compile(r'--- Scanning gallery (\d+)/(\d+): (.*) ---')
QUERY_RE = re.compile(r'Scanning with query: (.*)$')
HITS_RE = re.compile(r'(\d+) hit\(s\), (\d+) of them the same work')
CLASSIFIED_RE = re.compile(r'Classified (\d+)/(\d+) candidate\(s\) in (\d+) request\(s\)')
REJECTED_RE = re.compile(r'(\d+) same-title candidate\(s\) rejected for (.*) \(held: (.*)\):')
CANDIDATE_RE = re.compile(r"^\s*- (.*?): '(.*)'$")
ROW_RE = re.compile(r'((?:Decensored|Translated)(?:, Translated)?) version of (.*?): (\S+)$')
SEEN_RE = re.compile(r'version of (.*?) (?:is already on the list|was dismissed earlier)')
NO_HITS_RE = re.compile(r'No hits found with')
FULL_PAGE_RE = re.compile(r'Found (\d+) potential gallery entries')


def read_runs(path):
    """Splits the log into scan runs, each a list of lines."""
    with io.open(path, encoding='utf-8', errors='replace') as handle:
        lines = handle.read().splitlines()
    starts = [i for i, line in enumerate(lines) if RUN_START_RE.search(line)]
    if not starts:
        return []
    bounds = starts + [len(lines)]
    return [lines[bounds[i]:bounds[i + 1]] for i in range(len(starts))]


def parse_galleries(run):
    """Splits one run into per-gallery blocks."""
    galleries = []
    current = None
    for line in run:
        match = GALLERY_RE.search(line)
        if match:
            current = {'index': int(match.group(1)), 'total': int(match.group(2)),
                       'title': match.group(3), 'lines': []}
            galleries.append(current)
        elif current is not None:
            current['lines'].append(line)
    return galleries


def funnel(galleries):
    """The counts at each stage, plus the rejections and rows, for one run's galleries."""
    stats = collections.Counter()
    rejections = []
    rows = []
    for gallery in galleries:
        body = '\n'.join(gallery['lines'])
        stats['galleries'] += 1
        hits = HITS_RE.search(body)
        if hits:
            stats['hits'] += int(hits.group(1))
            stats['same_work'] += int(hits.group(2))
            if int(hits.group(2)):
                stats['with_candidates'] += 1
        if NO_HITS_RE.search(body):
            stats['searches_empty'] += 1
        for page in FULL_PAGE_RE.finditer(body):
            if int(page.group(1)) >= 25:
                stats['full_pages'] += 1
                break
        for classified in CLASSIFIED_RE.finditer(body):
            stats['classified'] += int(classified.group(1))
            stats['lookups'] += int(classified.group(3))
        # The gallery a rejection belongs to comes from the rejection header, not from the
        # block it was logged in: candidates are classified a batch at a time, so a gallery's
        # rejections are written out while the log is already inside a later gallery.
        held_title, held = '', ''
        for line in gallery['lines']:
            rejected = REJECTED_RE.search(line)
            if rejected:
                stats['rejected'] += int(rejected.group(1))
                held_title, held = rejected.group(2), rejected.group(3)
                continue
            candidate = CANDIDATE_RE.match(line.split('betterversions ')[-1])
            if candidate and held:
                rejections.append((held_title, held, candidate.group(1), candidate.group(2)))
                stats['named'] += 1
                continue
            row = ROW_RE.search(line)
            if row and not SEEN_RE.search(line):
                rows.append((row.group(1), row.group(2), row.group(3)))
                stats['rows'] += 1
            elif SEEN_RE.search(line):
                stats['already_known'] += 1
    return stats, rejections, rows


def summarise(stats, rows):
    print('  galleries searched            {}'.format(stats['galleries']))
    print('  searches that found nothing   {}'.format(stats['searches_empty']))
    print('  hits returned                 {}'.format(stats['hits']))
    print('  judged the same work          {}  (across {} galleries)'.format(
        stats['same_work'], stats['with_candidates']))
    print('  classified                    {}  in {} api request(s)'.format(
        stats['classified'], stats['lookups']))
    print('  turned down                   {}  ({} of them named in the log)'.format(
        stats['rejected'], stats['named']))
    print('  already on the list           {}'.format(stats['already_known']))
    print('  rows stored                   {}'.format(stats['rows']))
    if stats['full_pages']:
        print('  results truncated             {} gallery(s) filled their single page'.format(
            stats['full_pages']))
    for kind, title, url in rows:
        print('      [{}] {} -> {}'.format(kind, title[:52], url))


def axes(summary):
    """The language, censorship and parody a logged tag summary states.

    The creator segment is dropped rather than counted: it is absent whenever the source
    credits nobody, so a summary with no series would otherwise present it as one.
    """
    parts = [p.strip() for p in summary.split(' / ') if not p.strip().startswith('by ')]
    while len(parts) < 3:
        parts.append('')
    return parts[0], parts[1], parts[2]


def reason_of(held_summary, candidate_summary):
    """Why a candidate was turned down, read off both sides' tag summaries.

    Both are needed: a candidate in the target language is rejected for some other reason
    entirely, so labelling it by its own language alone would be wrong.
    """
    if 'a different series' in candidate_summary:
        return 'a different series'
    if 'a different creator' in candidate_summary:
        return 'a different creator'
    held_language, held_censorship, _ = axes(held_summary)
    language, censorship, _ = axes(candidate_summary)
    if language == 'no language' and held_language != 'no language':
        return 'untranslated, so the translation would be lost'
    if language == held_language:
        return 'already in that language, and no censorship to gain'
    if held_censorship == 'uncensored' and censorship == 'censored':
        return 'would put the censorship back'
    return 'in {}, which is neither yours nor the target'.format(language or 'no language')


def show_rejections(rejections):
    print('\n=== every candidate turned down, grouped by why ===')
    grouped = collections.defaultdict(list)
    for held_title, held, summary, candidate in rejections:
        grouped[reason_of(held, summary)].append((held_title, held, summary, candidate))
    for reason, entries in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        print('\n{} ({})'.format(reason, len(entries)))
        for held_title, held, summary, candidate in entries[:8]:
            print('    held      {}  ({})'.format(held_title[:56], held))
            print('    candidate {}  ({})'.format(candidate[:56], summary))
        if len(entries) > 8:
            print('    ... and {} more'.format(len(entries) - 8))


def show_gallery(galleries, needle):
    needle = needle.lower()
    found = [g for g in galleries if needle in g['title'].lower()]
    if not found:
        print('\nNo scanned gallery matches {!r}.'.format(needle))
        return
    for gallery in found:
        print('\n### {}/{} {}'.format(gallery['index'], gallery['total'], gallery['title']))
        for line in gallery['lines']:
            if 'betterversions' in line:
                print('    {}'.format(line.split('betterversions ')[-1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('log', nargs='?', default='happypanda.log')
    parser.add_argument('--run', type=int, default=-1)
    parser.add_argument('--rejections', action='store_true')
    parser.add_argument('--gallery')
    args = parser.parse_args()

    if not os.path.isfile(args.log):
        parser.error('no such file: {}'.format(args.log))

    runs = read_runs(args.log)
    if not runs:
        print('No better-version scan runs found in {}.'.format(args.log))
        return 1

    if not -len(runs) <= args.run < len(runs):
        parser.error('--run {} is out of range: the file holds {} scan run(s), so 0 to {} '
                     'or -1 to -{}'.format(args.run, len(runs), len(runs) - 1, len(runs)))

    run = runs[args.run]
    admitted = RUN_START_RE.search(run[0])
    galleries = parse_galleries(run)
    stats, rejections, rows = funnel(galleries)

    number = (len(runs) + args.run if args.run < 0 else args.run) + 1
    print('Scan {} of {} - {} of {} galleries admitted by the tag filter\n'.format(
        number, len(runs), admitted.group(1), admitted.group(2)))
    summarise(stats, rows)

    # Both, when both were asked for: they answer different questions, and silently dropping
    # one reads as the run simply not having had any.
    if args.gallery:
        show_gallery(galleries, args.gallery)
    if args.rejections:
        show_rejections(rejections)
    if not args.gallery and not args.rejections:
        print('\nPass --rejections to see why each candidate was turned down, '
              'or --gallery TEXT to inspect one.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
