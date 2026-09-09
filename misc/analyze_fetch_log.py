#!/usr/bin/env python3
"""Summarise an auto metadata fetch run from happypanda.log.

The log records every query a gallery was searched with, the score of every candidate that
came back, and why candidates were discarded. That is enough to tell the three failure modes
apart without guessing:

  * the source returned nothing            -> the query is wrong, or the gallery is not there
  * candidates came back but scored low    -> the local and site titles disagree
  * candidates were discarded by a guard   -> numbering mismatch

Usage:
    python misc/analyze_fetch_log.py [happypanda.log] [--run N] [--failures] [--gallery TEXT]

    --run N        analyse the Nth fetch run in the file (default: the last one, -1)
    --failures     list every gallery that matched nothing, with its queries and near misses
    --gallery TEXT show the full detail for galleries whose title contains TEXT
"""

import argparse
import collections
import io
import os
import re
import sys

RUN_START_RE = re.compile(r'Initiating auto metadata fetcher')
FALLBACK_RE = re.compile(r'Using fallback source')
GALLERY_RE = re.compile(r'--- Processing gallery (\d+)/(\d+): (.*) ---')
QUERY_RE = re.compile(r'Searching with query: (.*)$')
SCORE_RE = re.compile(r"- Score: (\d+|unverified) for '(.*)'")
DISCARD_RE = re.compile(r'Discarded (\d+) result')
SOURCE_RE = re.compile(r'using (\w+)')

OUTCOMES = [
    ('FAILED', 'All search attempts failed'),
    ('perfect', 'Single perfect'),
    ('confident', 'Single confident'),
    ('picker', 'confident title matches found'),
    ('deferred', 'belongs to a fallback source'),
]


def read_runs(path):
    """Splits the log into fetch runs, each a list of lines."""
    with io.open(path, encoding='utf-8', errors='replace') as handle:
        lines = handle.read().splitlines()
    starts = [i for i, line in enumerate(lines) if RUN_START_RE.search(line)]
    if not starts:
        return []
    bounds = starts + [len(lines)]
    return [lines[bounds[i]:bounds[i + 1]] for i in range(len(starts))]


def parse_galleries(run):
    """Splits one run into per-gallery blocks, tagged with the source that was searched."""
    source = 'primary'
    galleries = []
    current = None
    for line in run:
        if FALLBACK_RE.search(line):
            source = 'fallback'
        match = GALLERY_RE.search(line)
        if match:
            current = {
                'index': int(match.group(1)),
                'total': int(match.group(2)),
                'title': match.group(3),
                'source': source,
                'lines': [],
            }
            galleries.append(current)
        elif current is not None:
            current['lines'].append(line)
    return galleries


def outcome_of(gallery):
    body = '\n'.join(gallery['lines'])
    for name, needle in OUTCOMES:
        if needle in body:
            return name
    return 'used link/other'


def queries_of(gallery):
    return [QUERY_RE.search(line).group(1)
            for line in gallery['lines'] if QUERY_RE.search(line)]


def scores_of(gallery):
    """Every candidate score reported for this gallery, best first."""
    seen = {}
    for line in gallery['lines']:
        match = SCORE_RE.search(line)
        if match:
            raw, title = match.groups()
            seen[title] = -1 if raw == 'unverified' else int(raw)
    return sorted(seen.items(), key=lambda item: -item[1])


def summarise(galleries, label):
    if not galleries:
        return
    counts = collections.Counter()
    attempt_won = collections.Counter()
    total_queries = 0
    for gallery in galleries:
        counts[outcome_of(gallery)] += 1
        queries = queries_of(gallery)
        total_queries += len(queries)
        if queries and outcome_of(gallery) != 'FAILED':
            attempt_won[len(queries)] += 1
        if DISCARD_RE.search('\n'.join(gallery['lines'])):
            counts['~numbering guard fired'] += 1

    print('--- {} ({} galleries) ---'.format(label, len(galleries)))
    for name, count in counts.most_common():
        print('   {:<24} {}'.format(name, count))
    print('   {:<24} {} ({:.1f} per gallery)'.format(
        'queries issued', total_queries, total_queries / len(galleries)))
    if attempt_won:
        order = ', '.join('#{}: {}'.format(k, attempt_won[k]) for k in sorted(attempt_won))
        print('   {:<24} {}'.format('matched on attempt', order))
    print()


def show_failures(galleries):
    failed = [g for g in galleries if outcome_of(g) == 'FAILED']
    if not failed:
        print('No galleries failed outright.\n')
        return
    print('=== {} galleries matched nothing ==='.format(len(failed)))
    empty = 0
    for gallery in failed:
        scores = scores_of(gallery)
        queries = queries_of(gallery)
        body = '\n'.join(gallery['lines'])
        nothing = body.count('No hits found')
        if not scores:
            empty += 1
        print('\n### {}'.format(gallery['title'][:100]))
        print('    {} queries, {} returned nothing{}'.format(
            len(queries), nothing,
            ', best candidate {}'.format(scores[0][1]) if scores else ''))
        for query in queries:
            print('    Q: {}'.format(query[:118]))
        for title, score in scores[:3]:
            shown = 'unverified' if score < 0 else score
            print('    {:>10}: {}'.format(shown, title[:104]))
    print('\n{} of {} returned no candidates at all '
          '(query problem, not a scoring one).\n'.format(empty, len(failed)))


def show_gallery(galleries, needle):
    matches = [g for g in galleries if needle.lower() in g['title'].lower()]
    if not matches:
        print('No gallery title contains {!r}.'.format(needle))
        return
    for gallery in matches:
        print('=== [{}] {}'.format(gallery['source'], gallery['title']))
        for line in gallery['lines']:
            stripped = re.sub(r'^\d\d-\d\d \d\d:\d\d \w+ +\w+ +', '    ', line)
            print(stripped)
        print()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('log', nargs='?', default='happypanda.log',
                        help='path to happypanda.log (default: ./happypanda.log)')
    parser.add_argument('--run', type=int, default=-1,
                        help='which fetch run to analyse (default: the last)')
    parser.add_argument('--failures', action='store_true',
                        help='list every gallery that matched nothing')
    parser.add_argument('--gallery', metavar='TEXT',
                        help='show the full log detail for galleries matching TEXT')
    args = parser.parse_args(argv)

    if not os.path.isfile(args.log):
        parser.error('no such file: {}'.format(args.log))

    runs = read_runs(args.log)
    if not runs:
        print('No metadata fetch runs found in {}.'.format(args.log))
        return 1

    run = runs[args.run]
    galleries = parse_galleries(run)
    source = SOURCE_RE.search('\n'.join(run[:5]))

    number = (len(runs) + args.run if args.run < 0 else args.run) + 1
    print('Run {} of {} - {} galleries, primary source: {}\n'.format(
        number, len(runs), len(galleries), source.group(1) if source else 'unknown'))

    summarise([g for g in galleries if g['source'] == 'primary'], 'primary source')
    summarise([g for g in galleries if g['source'] == 'fallback'], 'fallback source')

    if args.gallery:
        show_gallery(galleries, args.gallery)
    elif args.failures:
        show_failures(galleries)
    else:
        print('Pass --failures to list what did not match, '
              'or --gallery TEXT to inspect one.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
