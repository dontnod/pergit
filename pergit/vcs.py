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
''' Git and Perforce call utilities '''
import logging
import re
import shlex
import subprocess

P4_FIELD_RE = re.compile(r'^... (?P<key>\w+) (?P<value>.*)$')

class _VCS(object):
    def __init__(self, command_prefix):
        self._command_prefix = command_prefix

    def _run(self, command, *args, **kwargs):
        command = self._get_command(command, *args, **kwargs)
        logging.getLogger('pergit').debug('Running %s', ' '.join(command))
        result = subprocess.run(command, check=True, text=True, capture_output=True)
        return result.stdout

    def check(self, command, *args, **kwargs):
        ''' Returns true if the given command succeeds '''
        command = self._get_command(command, *args, **kwargs)
        logging.getLogger('pergit').debug('Running %s', ' '.join(command))
        result = subprocess.run(command, check=True)
        return result.returncode == 0

    def _get_command(self, command, *args, **kwargs):
        command = command.format(*args, **kwargs)
        return self._command_prefix + shlex.split(command)


class P4(_VCS):
    ''' Wrapper for P4 calls '''
    def __init__(self, client=None, password=None, port=None, user=None):
        command_prefix = ['p4', '-z', 'tag']
        if client is not None:
            command_prefix += ['-c', client]
        if password is not None:
            command_prefix += ['-P', password]
        if port is not None:
            command_prefix += ['-p', port]
        if user is not None:
            command_prefix += ['-u', user]
        super().__init__(command_prefix)

    def __call__(self, command, *args, **kwargs):
        output = self._run(command, *args, **kwargs)
        result = []
        current_object = {}
        for line in output.split('\n'):
            # Empty line means we have multiple objects returned, change
            # the returned dict in a list
            if not line:
                if current_object:
                    result.append(current_object)
                    current_object = {}
                continue

            match = P4_FIELD_RE.match(line)
            assert match

            key = match.group('key')
            value = match.group('value')
            assert key not in current_object
            current_object[key] = value

        if result and current_object:
            result.append(current_object)

        if len(result) > 1:
            return result

        return result[0]

class Git(_VCS):
    ''' Wrapper representing a given git repository cloned in a given
        directory '''
    def __init__(self, config=None, git_dir=None, work_tree=None):
        command_prefix = ['git']

        if git_dir:
            command_prefix += ['--git-dir', work_tree]

        if work_tree:
            command_prefix += ['--work-tree', work_tree]

        for option, value in config.items():
            command_prefix += ['-c', '%s=%s' % (option, value)]

        super().__init__(command_prefix)

    def __call__(self, command, *args, **kwargs):
        return self._run(command, *args, **kwargs)
