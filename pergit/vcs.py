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

import contextlib
import logging
import os
import re
import subprocess
import tempfile
from typing import Type
from P4 import P4 as P4Python

import pergit

P4_FIELD_RE = re.compile(r'^\.\.\. (?P<key>\w+) (?P<value>.*)$')

class VCSCommand(object):
    ''' Object representing a git or perforce commmand '''
    def __init__(self, command: list[str], env):
        logger = logging.getLogger(pergit.LOGGER_NAME)
        logger.debug('Running %s', subprocess.list2cmdline(command))
        self._result = subprocess.run(command,
                                      check=False,
                                      capture_output=True,
                                      env=env)
        def _decode(bytes_: bytes) -> str:
            if bytes_ is None:
                return ''

            encodings = [
                ('utf-8', 'strict'), ('utf-8-sig', 'strict'), # utf-8 with or without BOM
                ('cp850', 'strict'), # our actual p4 setting, may change to utf-8 in the future
            ]
            for (encoding, errors) in encodings:
                try:
                    return bytes_.decode(encoding=encoding, errors=errors)
                except UnicodeDecodeError:
                    pass

            return bytes_.decode(encoding='cp850', errors='replace')  # last chance


        self._stdout = _decode(self._result.stdout)
        self._stderr = _decode(self._result.stderr)

        VCSCommand._debug_output(self._stdout, '--')
        VCSCommand._debug_output(self._stderr, '!!')

    def check(self):
        ''' Raises CalledProcessError if the command failed '''
        self._result.check_returncode()

    def err(self):
        ''' Returns stdeer for this command '''
        return self._stderr

    def out(self):
        ''' Returns stdout for command, raise CalledProcessError if the command
            failed '''
        self.check()
        return self._stdout.strip()

    def __bool__(self):
        return self._result.returncode == 0

    @staticmethod
    def _debug_output(output, prefix):
        logger = logging.getLogger(pergit.LOGGER_NAME)
        if output:
            for line in output.strip().split('\n'):
                logger.debug(' %s %s', prefix, line)

class _VCS(object):
    def __init__(self, command_class: Type[VCSCommand], command_prefix: list[str]):
        self._command_class = command_class
        self._command_prefix = command_prefix
        self._env_stack = []

    @contextlib.contextmanager
    def with_env(self, **kwargs):
        ''' Calls to the VCS in the scope of this context managed method
            will have given variables added to environment '''
        self._env_stack.append(dict(**kwargs))
        count = len(self._env_stack)
        yield
        assert len(self._env_stack) == count
        self._env_stack.pop()

    def __call__(self, command: list[str]):
        env = os.environ.copy()
        for env_it in self._env_stack:
            env.update(env_it)

        command = self._command_prefix + command
        return self._command_class(command, env)

class P4Command(VCSCommand):
    ''' Object representing a p4 command, containing records returned by p4 '''
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._records = None

    def single_record(self):
        ''' Checks there is a single record returned by Perforce and returns
            it '''
        self._eval_output()
        assert len(self._records) == 1
        return self._records[0]

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

        if not self.out():
            return

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
                next_key = match.group('key')
                next_value = match.group('value')

                if current_key:
                    assert current_key is not None
                    assert current_value is not None
                    assert current_key not in current_record
                    current_record[current_key] = current_value.strip()

                    # If next key is already in the current record, we started
                    # to parse another record
                    if next_key in current_record:
                        self._records.append(current_record)
                        current_record = {}
                current_key = next_key
                current_value = next_value

        if current_key:
            assert current_key is not None
            assert current_value is not None
            current_record[current_key] = current_value.strip()
            self._records.append(current_record)

class P4(_VCS):
    ''' Wrapper for P4 calls '''
    def __init__(self, port=None, user=None, client=None, password=None):
        self._p4python = P4Python()
        command_prefix = ['p4', '-z', 'tag']
        if client is not None:
            command_prefix += ['-c', client]
            self._p4python.client = client
        if password is not None:
            command_prefix += ['-P', password]
        if port is not None:
            command_prefix += ['-p', port]
            self._p4python.port = port
        if user is not None:
            command_prefix += ['-u', user]
            self._p4python.user = user

        logging.debug('Using P4Python: %s', repr(self._p4python))
        self._p4python.connect()
        super().__init__(P4Command, command_prefix)


    def submit(self, desc):
        change = self._p4python.fetch_change()
        change._description = desc
        logging.debug("%s", change)
        self._p4python.run_submit( change )

    @contextlib.contextmanager
    def ignore(self, *patterns):
        ''' Ignore specified patterns for every calls in a with scope
            for this P4 instance '''
        tmp_path = None
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp_file:
            tmp_path = tmp_file.name
            for it in patterns:
                tmp_file.write('%s\n' % it)
        ignore_env = tmp_path
        if 'P4IGNORE' in os.environ:
            ignore_env += os.environ['P4IGNORE']
        with self.with_env(P4IGNORE=ignore_env):
            yield
        os.remove(tmp_path)

class GitCommand(VCSCommand):
    ''' Object representing a git command, containing lines returned by it '''
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lines = None

    def __getitem__(self, index):
        self._eval_output()
        assert self._lines is not None
        return self._lines[index]

    def __len__(self):
        self._eval_output()
        assert self._lines is not None
        return len(self._lines)

    def _eval_output(self):
        if self._lines is not None:
            return
        self.check()
        self._lines = [it for it in self.out().split('\n') if it]

class Git(_VCS):
    ''' Wrapper representing a given git repository cloned in a given
        directory '''
    def __init__(self, config=None, git_dir=None, work_tree=None):
        command_prefix = ['git']

        if git_dir is not None:
            command_prefix += ['--git-dir', git_dir]

        if config:
            for option, value in config.items():
                command_prefix += ['-c', '%s=%s' % (option, value)]

        super().__init__(GitCommand, command_prefix)
