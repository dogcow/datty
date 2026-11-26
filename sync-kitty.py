#!/usr/bin/env python3
# License: GPLv3
"""Merge a newer kitty into datty.

datty is kitty with kitty renamed to datty and kitten renamed to daddy, in
file names and in file contents, plus the changes made in datty. Merging
kitty directly conflicts in every line the rename touched, and the lines
that do merge still say kitty.

So this script applies the rename to a pristine kitty commit, commits the
result as a snapshot whose parents are the previous snapshot and that kitty
commit, and merges the snapshot. The merge base is then the previous
snapshot, which is already renamed, so the only conflicts are real ones,
between a change made in datty and a change made in kitty.

Usage:

    git fetch upstream
    ./sync-kitty.py                  # merges upstream/master
    ./sync-kitty.py <kitty commit>   # merges that commit

Then resolve any conflicts, run ./dev.sh build and ./test.py, and commit.
"""

import os
import re
import subprocess
import sys
import tempfile

PAIRS = (
    ('kittens', 'daddies'),
    ('Kittens', 'Daddies'),
    ('KITTENS', 'DADDIES'),
    ('kitten', 'daddy'),
    ('Kitten', 'Daddy'),
    ('KITTEN', 'DADDY'),
    ('kitty', 'datty'),
    ('Kitty', 'Datty'),
    ('KITTY', 'DATTY'),
)
# These name things that belong to kitty and that datty uses as they are
KEEP = (
    'kovidgoyal/kitty-themes',
    'download.calibre-ebook.com/ci/kitty/',
    '/Users/Shared/kitty-build/',
)
TRAILER = 'Renamed-From'
replacements = dict(PAIRS)
pattern = re.compile('|'.join(re.escape(x) for x in KEEP + tuple(replacements)))


def rename(text: str) -> str:
    return pattern.sub(lambda m: replacements.get(m.group(), m.group()), text)


def git(*args: str, cwd: str | None = None) -> str:
    return subprocess.run(('git',) + args, cwd=cwd, check=True, stdout=subprocess.PIPE).stdout.decode().strip()


def rename_tree(root: str) -> None:
    "Rename all the files tracked by git in root, and their contents"
    for path in filter(None, git('ls-files', '-z', cwd=root).split('\0')):
        src, dest = os.path.join(root, path), os.path.join(root, rename(path))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.islink(src):
            target = os.readlink(src)
            os.unlink(src)
            os.symlink(rename(target), dest)
            continue
        with open(src, 'rb') as f:
            raw = f.read()
        new_raw = raw
        if b'\0' not in raw:  # binary files are renamed but their contents are left alone
            try:
                new_raw = rename(raw.decode()).encode()
            except UnicodeDecodeError:
                pass
        if dest != src:
            os.rename(src, dest)
        if new_raw != raw:
            with open(dest, 'wb') as f:
                f.write(new_raw)


def renamed_snapshot(commit: str, previous_snapshot: str) -> str:
    "A commit with the renamed tree of commit, descended from both previous_snapshot and commit"
    with tempfile.TemporaryDirectory(prefix='sync-kitty-') as tdir:
        worktree = os.path.join(tdir, 'kitty')
        git('worktree', 'add', '--quiet', '--detach', worktree, commit)
        try:
            rename_tree(worktree)
            # --force as a renamed file must not be dropped for matching an ignore pattern
            git('add', '--all', '--force', cwd=worktree)
            tree = git('write-tree', cwd=worktree)
        finally:
            git('worktree', 'remove', '--force', worktree)
    msg = (
        f'Mechanical rename of kitty at {commit[:9]}\n\n'
        f'The tree of kitty commit {commit} with\n'
        'kitty renamed to datty and kitten to daddy, in file names and contents,\n'
        'and nothing else. Made by sync-kitty.py.\n\n'
        f'{TRAILER}: {commit}\n'
    )
    return git('commit-tree', tree, '-p', previous_snapshot, '-p', commit, '-m', msg)


def main() -> None:
    args = sys.argv[1:]
    if len(args) > 1 or (args and args[0].startswith('-')):
        raise SystemExit(__doc__)
    os.chdir(git('rev-parse', '--show-toplevel'))
    commit = git('rev-parse', '--verify', (args[0] if args else 'upstream/master') + '^{commit}')
    if subprocess.run(('git', 'merge-base', '--is-ancestor', commit, 'HEAD')).returncode == 0:
        print(f'kitty at {commit[:9]} is already merged')
        return
    previous_snapshot = git('log', '-1', '--format=%H', f'--grep=^{TRAILER}: ', 'HEAD')
    if not previous_snapshot:
        raise SystemExit(f'No renamed snapshot of kitty found in the history of HEAD, looked for a {TRAILER}: trailer')
    snapshot = renamed_snapshot(commit, previous_snapshot)
    print(f'Merging the renamed snapshot {snapshot[:9]} of kitty at {commit[:9]}', flush=True)
    ret = subprocess.run(('git', '-c', 'merge.renameLimit=20000', 'merge', '--no-ff', '-m', f'Merge kitty at {commit[:9]}', snapshot)).returncode
    if ret != 0:
        print('\nResolve the conflicts, run ./dev.sh build and ./test.py, then git commit', file=sys.stderr)
    raise SystemExit(ret)


if __name__ == '__main__':
    main()
