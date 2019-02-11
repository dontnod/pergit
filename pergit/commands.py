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

import pergit.vcs

class CommandError(Exception):
    ''' Error raised when a command fails '''
    def __init__(self, message):
        super().__init__()
        self._message = message

class Command(object):
    ''' Pergit command base class '''
    def __init__(self, depot_path):
        self._logger = logging.getLogger('pergit')
        self._p4 = pergit.vcs.P4()

        self._work_tree = self._p4('where {}', depot_path)['path']
        git_config = {
            'core.fileMode': 'false'
        }

        self._git = pergit.vcs.Git(config=git_config, work_tree=self._work_tree)

    def _info(self, fmt, *args, **kwargs):
        self._logger.info(fmt, *args, **kwargs)

    def _error(self, fmt, *args, **kwargs):
        raise CommandError(fmt.format(*args, **kwargs))

    def _p4_root(self):
        return self._work_tree + '/...'

    def _clean_workspace(self):
        self._p4.check('revert {}', self._p4_root())
        self._p4.check('clean {}', self._p4_root())

class Import(Command):
    ''' Import command '''
    def __init__(self, branch, **kwargs):
        super().__init__(**kwargs)
        git = self._git

        if git.check('rev-parse --verify {}', branch):
            self._error('branch {} already exists, can\'t import on top of it',
                        branch)

        git('checkout --orphan {}', branch)
