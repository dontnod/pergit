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
import logging
import gettext

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
        self._logger = logging.getLogger('pergit')
        self._p4 = pergit.vcs.P4()
        self._git = pergit.vcs.Git(config={'core.fileMode': 'false'},
                                   work_tree=self._work_tree)
        self._previous_head = None

    def sychronize(self, branch, changelist):
        ''' Runs the import command '''
        git = self._git
        p4 = self._p4

        if changelist is None:
            changelist = 0

        if not git('rev-parse --is-inside-work-tree'):
            self._error(_('Not in a git repository, please run pergit from the'
                          ' folder of the git repository in which you want to '
                          'import Perforce depot'))

        if not git('rev-parse --verify {}', branch):
            git('checkout --orphan {}', branch).check()

        changelists = p4('changes "{}/...@{},#head"', self._work_tree, changelist)

        for change in reversed(changelists):
            p4('sync "{}/...@{}"', self._work_tree, change['change']).check()
            description = change['desc'].replace('"', '\\"')
            git('commit . -m "{}"', description).check()

    def _info(self, fmt, *args, **kwargs):
        ''' Logs an info '''
        self._logger.info(fmt, *args, **kwargs)

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
        if git('git rev-parse --is-inside-work-tree'):
            self._previous_head = git('rev-parse HEAD').out()

        return self

    def __exit__(self, ex_type, ex_value, ex_traceback):
        if self._previous_head is not None:
            self._git('reset --mixed {}', self._previous_head).check()
        