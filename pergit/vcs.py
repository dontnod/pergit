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
import os
import pathlib
import re
import shlex
import subprocess

P4_FIELD_RE = re.compile(r'^... (?P<key>\w+) (?P<value>.*)$')

class VCSCommand(object):
    ''' Object representing a git or perforce commmand '''
    def __init__(self, command):
        self._result = subprocess.run(command,
                                      check=False,
                                      text=True,
                                      capture_output=True)

    def check(self):
        ''' Raises CalledProcessError if the command failed '''
        self._result.check_returncode()

    def err(self):
        ''' Returns stdeer for this command '''
        return self._result.stderr

    def out(self):
        ''' Returns stdout for command, raise CalledProcessError if the command
            failed '''
        self.check()
        return self._result.stdout.strip()

    def __bool__(self):
        return self._result.returncode == 0

class _VCS(object):
    def __init__(self, command_class, command_prefix):
        self._command_class = command_class
        self._command_prefix = command_prefix

    def __call__(self, command, *args, **kwargs):
        command = command.format(*args, **kwargs)
        command = self._command_prefix + shlex.split(command)
        return self._command_class(command)

class P4Command(VCSCommand):
    ''' Object representing a p4 command, containing records returned by p4 '''
    def __init__(self, command):
        super().__init__(command)
        self._records = None

    def __getitem__(self, index):
        self._eval_output()
        assert self._records is not None
        return self._records[index]

    def __bool__(self):
        return super().__bool__() and len(self) != 0

    def __len__(self):
        self._eval_output()
        assert self._records is not None
        return len(self._records)

    def _eval_output(self):
        if self._records is not None:
            return

        self.check()
        self._records = []
        current_record = {}
        current_key = None
        current_value = None
        for line in self.out().split('\n'):
            # Empty line means we have multiple objects returned, change
            # the returned dict in a list
            match = P4_FIELD_RE.match(line)

            if not match:
                # We maybe are parsing a multiline value
                current_value += line
            else:
                key = match.group('key')
                value = match.group('value')

                if current_key:
                    assert current_key is not None
                    assert current_value is not None
                    # If key is already in the current record, we started to parse
                    # another record
                    if key not in current_record:
                        # Append currently parsed value to current record
                        assert current_value is not None
                        current_record[current_key] = current_value.strip()
                    else:
                        self._records.append(current_record)
                        current_record = {}
                current_key = key
                current_value = value

        if current_key:
            assert current_key is not None
            assert current_value is not None
            current_record[current_key] = current_value.strip()
            self._records.append(current_record)

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
        super().__init__(P4Command, command_prefix)

class Git(_VCS):
    ''' Wrapper representing a given git repository cloned in a given
        directory '''
    def __init__(self, config=None, git_dir=None, work_tree=None):
        command_prefix = ['git']

        if git_dir is not None:
            command_prefix += ['--git-dir', git_dir]

        if work_tree:
            command_prefix += ['--work-tree', work_tree]

        for option, value in config.items():
            command_prefix += ['-c', '%s=%s' % (option, value)]

        super().__init__(VCSCommand, command_prefix)
