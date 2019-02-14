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

import pergit
import pergit.vcs

_ = gettext.gettext

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

    def sychronize(self, branch, changelist):
        ''' Runs the import command '''
        git = self._git
        p4 = self._p4

        if changelist is None:
            changelist = 0

        git('symbolic-ref HEAD refs/heads/{}', branch)

        perforce_changes = list(self._get_perforce_changes(changelist))
        git_changes = list(self._get_git_changes())

        if perforce_changes and git_changes:
            self._error('You have changes both from P4 and git side, refusing'
                        'to sync')
        elif perforce_changes:
            for change in perforce_changes:
                self._import_changelist(change)

    def _get_perforce_changes(self, changelist):
        last_synced_cl = changelist # todo : check git tags

        changelists = self._p4('changes -l "{}/...@{},#head"',
                               self._work_tree,
                               last_synced_cl)

        return reversed(changelists)

    def _get_git_changes(self):
        commits = self._git('log --ancestry-path --pretty=format:%H')
        # This can fail when current branch doesn't have any commit, as when
        # specified branch didn't exists. Could be nice to check for that
        # particular error though, as anyting else would lead to overwrite some
        # changes by importing in top of some exisitng work
        if commits:
            for commit in commits:
                # todo : check git tags
                yield commit

    def _import_changelist(self, change):
        p4 = self._p4
        git = self._git
        p4('sync "{}/...@{}"', self._work_tree, change['change']).check()
        description = change['desc'].replace('"', '\\"')
        git('add .').check()
        git('commit -m "{}"', description).check()

    def __exit__(self, ex_type, ex_value, ex_traceback):
        git = self._git
        if self._previous_head is not None:
            git('symbolic-ref HEAD refs/heads/{}', self._previous_head)
