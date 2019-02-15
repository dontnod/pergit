# -*- coding: utf-8 -*-
# Copyright © 2019 Dontnod Entertainment

# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:

# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
''' pergit commands '''
import gettext
import logging
import re

import pergit
import pergit.vcs

_ = gettext.gettext
_TAG_RE = re.compile(r'^.*@(?P<changelist>\d+)')

ON_CONFLICT_FAIL = 0
ON_CONFLICT_RESET = 1
ON_CONFLICT_ERASE = 2

class PergitError(Exception):
    ''' Error raised when a command fails '''
    def __init__(self, message):
        super().__init__()
        self._message = message

    def __repr__(self):
        return self._message

    def __str__(self):
        return self._message

class Pergit(object):
    ''' Imports a Perforce depot into a git branch '''
    def __init__(self, path):
        self._work_tree = path
        self._p4 = pergit.vcs.P4()
        self._git = pergit.vcs.Git(config={'core.fileMode': 'false'},
                                   work_tree=self._work_tree)
        self._previous_head = None

    def _info(self, fmt, *args, **kwargs):
        ''' Logs an info '''
        logging.getLogger(pergit.LOGGER_NAME).info(fmt, *args, **kwargs)

    def _warn(self, fmt, *args, **kwargs):
        ''' Logs an info '''
        logging.getLogger(pergit.LOGGER_NAME).warning(fmt, *args, **kwargs)

    def _error(self, fmt, *args, **kwargs):
        ''' Logs an error '''
        raise PergitError(fmt.format(*args, **kwargs))

    def __enter__(self):
        p4_root = self._work_tree + '/...'

        # Reverting and cleaning files in order to not commit trash to git
        p4 = self._p4
        p4('revert "{}"', p4_root).check()
        p4('clean "{}"', p4_root).check()

        git = self._git
        if not git('rev-parse --is-inside-work-tree'):
            self._error(_('Not in a git repository, please run pergit from the'
                          ' folder of the git repository in which you want to '
                          'import Perforce depot'))

        current_head = git('rev-parse --abbrev-ref HEAD')

        if current_head:
            self._previous_head = current_head.out()

        return self

    def sychronize(self,
                   branch,
                   changelist,
                   tag_prefix=None,
                   conflict_handling=ON_CONFLICT_FAIL):
        ''' Runs the import command '''
        git = self._git

        if not tag_prefix:
            tag_prefix = branch

        git('symbolic-ref HEAD refs/heads/{}', branch)

        sync_commit, sync_changelist = self._get_latest_sync_state(tag_prefix)
        git_changes, perforce_changes = self._get_changes(changelist,
                                                          sync_commit,
                                                          sync_changelist)

        if perforce_changes and git_changes:
            if conflict_handling == ON_CONFLICT_FAIL:
                # todo : explain on conflict handling
                self._error(_('You have changes both from P4 and git side, '
                              'refusing to sync'))
            git_changes = []
            if conflict_handling == ON_CONFLICT_RESET:
                git('reset --mixed {}', sync_commit)
            elif conflict_handling == ON_CONFLICT_ERASE:
                pass # Nothing to to, will import on top of existing branch
            else:
                assert False, 'Not implemented'

        if perforce_changes:
            assert not git_changes
            for change in perforce_changes:
                self._import_changelist(change)
                self._tag_commit(tag_prefix, change)
        elif git_changes:
            assert not perforce_changes
            # todo : submit git changes
        else:
            self._info('Nothing to sync')

    def _get_latest_sync_state(self, tag_prefix):
        git = self._git
        #todo : parse commit one-by-one, to not retrieve all git history here
        commits = git('log --pretty=format:%H')
        # This can fail when current branch doesn't have any commit, as when
        # specified branch didn't exists. Could be nice to check for that
        # particular error though, as anyting else would lead to overwrite some
        # changes by importing in top of some exisitng work
        if commits:
            for commit in commits:
                tag = git('describe --tags --exact-match --match "{}@*" {}',
                          tag_prefix,
                          commit)
                if not tag:
                    continue

                match = _TAG_RE.match(tag.out())

                if not match:
                    self._warn('Commit {} seems to have a changelist tag, but'
                               't\'s format is incorrect. This commit will be '
                               'considered as a git-side change.')
                    continue

                changelist = match.group('changelist')
                return commit, changelist

        return None, None

    def _get_changes(self, changelist, sync_commit, sync_changelist):
        if sync_changelist is None:
            sync_changelist = '0'
        if changelist is None:
            changelist = sync_changelist

        if changelist is not None and sync_changelist > changelist:
            self._error(_('Trying sync at a C.L anterior to the latest synced '
                          'C.L. This would duplicate commits on top of the '
                          ' current branch. Reset your branch to the changelist'
                          ' you want to sync from, then run pergit again'))

        changelists = self._p4('changes -l "{}/...@{},#head"',
                               self._work_tree,
                               changelist)

        changelists = list(reversed(changelists))

        # last_synced_cl is already sync, but when giving --changelist as
        # argument, one would expect that the change range is inclusive
        if changelist == sync_changelist:
            assert changelists[0]['change'] == sync_changelist
            changelists = changelists[1:]

        if sync_commit:
            commits = self._git('log --pretty=format:%H --ancestry-path {}..HEAD', sync_commit)
        else:
            commits = self._git('log --pretty=format:%H')

        commits = list(commits)[1:]

        return commits, changelists

    def _get_perforce_changes(self, changelist):
        changelists = self._p4('changes -l "{}/...@{},#head"',
                               self._work_tree,
                               changelist)

        return reversed(changelists)

    def _import_changelist(self, change):
        p4 = self._p4
        git = self._git
        self._info(_('Syncing then committing changelist %s : %s'),
                   change['change'],
                   change['desc'])
        p4('sync "{}/...@{}"', self._work_tree, change['change']).check()
        description = change['desc'].replace('"', '\\"')
        git('add .').check()

        # Commit event if there are no changes, to keep P4 C.L description
        # and corresponding tag in git history
        git('commit --allow-empty -m "{}"', description).check()

    def _tag_commit(self, tag_prefix, change):
        git = self._git
        tag = '{}@{}'.format(tag_prefix, change['change'])

        if git('tag -l {}', tag).out():
            self._warn(_('Tag %s already existed, it will be replaced.'), tag)

        git('tag -f {}', tag).check()

    def __exit__(self, ex_type, ex_value, ex_traceback):
        git = self._git
        if self._previous_head is not None:
            git('symbolic-ref HEAD refs/heads/{}', self._previous_head)
