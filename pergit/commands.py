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
import abc
import logging

import pergit.vcs

class CommandError(Exception):
    ''' Error raised when a command fails '''
    def __init__(self, message):
        super().__init__()
        self._message = message

class _Command(abc.ABC):
    ''' Pergit command base class '''
    def __init__(self, depot_path):
        self._depot_path = depot_path
        self._git = None
        self._logger = logging.getLogger('pergit')
        self._p4 = None
        self._previous_head = None
        self._work_tree = None

    def _info(self, fmt, *args, **kwargs):
        ''' Logs an info '''
        self._logger.info(fmt, *args, **kwargs)

    def _error(self, fmt, *args, **kwargs):
        ''' Logs an error '''
        raise CommandError(fmt.format(*args, **kwargs))

    def __enter__(self):
        self._p4 = pergit.vcs.P4()

        where = self._p4('where "{}"', self._depot_path)

        if isinstance(where, list):
            self._error('Got multiple results when retrieving path to working'
                        'tree from Perforce. Check that your work tree is not'
                        'unmapped (-//Worktree/path) in your Perforce client'
                        'configuration, as it is not supported')

        assert isinstance(where, dict)
        self._work_tree = where['path']

        p4_root = self._work_tree + '/...'

        # Reverting and cleaning files in order to not commit trash to git
        self._p4.check('revert {}', p4_root)
        self._p4.check('clean {}', p4_root)

        git_config = {'core.fileMode': 'false'}
        self._git = pergit.vcs.Git(config=git_config, work_tree=self._work_tree)

        if self._git.check('git rev-parse --is-inside-work-tree'):
            self._previous_head = self._git('rev-parse HEAD')
        return self

    def __exit__(self, ex_type, ex_value, ex_traceback):
        if self._previous_head is not None:
            self._git('reset --mixed {}', self._previous_head)

class Import(_Command):
    ''' Imports a Perforce depot into a git branch '''

    def run(self, branch, changelist):
        ''' Runs the import command '''
        git = self._git
        p4 = self._p4

        if changelist is None:
            changelist = 0

        if not git.check('git rev-parse --is-inside-work-tree'):
            git('init')

        if git.check('rev-parse --verify {branch}', branch):
            self._error('branch {} already exists, can\'t import on top of it',
                        branch)

        git('checkout --orphan {}', branch)

        changelists = p4('changes {}/...@{},#head', self._work_tree, changelist)

        for change in changelists:
            p4('sync {}/...@{}', self._work_tree, change['change'])
            description = change['desc'].replace('"', '\\"')
            git('commit . -m "{}"', description)

    def _cleanup(self):
        pass
        