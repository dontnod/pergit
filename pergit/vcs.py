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
"""Git and Perforce call utilities"""

import contextlib
import logging
import os
import re
import subprocess
import tempfile
from collections.abc import Iterator
from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any
from typing import Generic
from typing import TypeVar
from typing import overload

from P4 import P4 as P4Python

import pergit

P4_FIELD_RE = re.compile(r"^\.\.\. (?P<key>\w+) (?P<value>.*)$")

_T = TypeVar("_T")


class VCSCommand(Sequence[_T]):
    """Object representing a git or perforce commmand"""

    def __init__(self, command: list[str], env: Mapping[str, str]) -> None:
        self.logger = logging.getLogger(f"{pergit.LOGGER_NAME}.{self.__class__.__name__}")
        self.logger.debug("Running %s", subprocess.list2cmdline(command))

        self._result = subprocess.run(command, check=False, capture_output=True, env=env)

        def _decode(bytes_: bytes | None) -> str:
            if bytes_ is None:
                return ""

            encodings = [
                ("utf-8", "strict"),
                ("utf-8-sig", "strict"),  # utf-8 with or without BOM
                ("cp850", "strict"),  # our actual p4 setting, may change to utf-8 in the future
            ]
            for encoding, errors in encodings:
                try:
                    return bytes_.decode(encoding=encoding, errors=errors)
                except UnicodeDecodeError:
                    pass

            return bytes_.decode(encoding="cp850", errors="replace")  # last chance

        self._stdout = _decode(self._result.stdout)
        self._stderr = _decode(self._result.stderr)

        self._debug_output(self._stdout, "--")
        self._debug_output(self._stderr, "!!")

    def check(self) -> None:
        """Raises CalledProcessError if the command failed"""
        self._result.check_returncode()

    def err(self) -> str:
        """Returns stdeer for this command"""
        return self._stderr

    def out(self) -> str:
        """Returns stdout for command, raise CalledProcessError if the command
        failed"""
        self.check()
        return self._stdout.strip()

    def __bool__(self) -> bool:
        return self._result.returncode == 0

    def _debug_output(self, output: str, prefix: str) -> None:
        for line in output.splitlines(keepends=False):
            self.logger.debug(" %s %s", prefix, line)


VCSCommandType = TypeVar("VCSCommandType", bound=VCSCommand[Any])


class _VCS(Generic[VCSCommandType]):
    def __init__(self, command_class: type[VCSCommandType], command_prefix: list[str]) -> None:
        self._command_class = command_class
        self._command_prefix = command_prefix
        self._env_stack: list[dict[str, str]] = []

        self.logger = logging.getLogger(f"{pergit.LOGGER_NAME}.{command_class.__name__}")

    @contextlib.contextmanager
    def with_env(self, **kwargs: str) -> Iterator[None]:
        """Calls to the VCS in the scope of this context managed method
        will have given variables added to environment"""
        self._env_stack.append(dict(**kwargs))
        count = len(self._env_stack)
        yield
        assert len(self._env_stack) == count
        self._env_stack.pop()

    def __call__(self, command: list[str]) -> VCSCommandType:
        env = os.environ.copy()
        for env_it in self._env_stack:
            env.update(env_it)

        command = self._command_prefix + command
        return self._command_class(command, env)


class P4Command(VCSCommand[dict[str, str]]):
    """Object representing a p4 command, containing records returned by p4"""

    _records: list[dict[str, str]] | None = None

    def single_record(self) -> dict[str, str]:
        """Checks there is a single record returned by Perforce and returns
        it"""
        self._eval_output()
        assert self._records is not None and len(self._records) == 1
        return self._records[0]

    @overload
    def __getitem__(self, key: int) -> dict[str, str]: ...

    @overload
    def __getitem__(self, key: slice[Any, Any, Any]) -> Sequence[dict[str, str]]: ...

    def __getitem__(self, key: int | slice[Any, Any, Any]) -> dict[str, str] | Sequence[dict[str, str]]:
        self._eval_output()
        assert self._records is not None
        return self._records[key]

    def __bool__(self) -> bool:
        return super().__bool__() and len(self) != 0

    def __len__(self) -> int:
        self._eval_output()
        assert self._records is not None
        return len(self._records)

    def _eval_output(self) -> None:
        if self._records is not None:
            return

        self.check()
        self._records = []

        if not self.out():
            return

        current_record = {}
        current_key = None
        current_value: str = ""
        for line in self.out().split("\n"):
            # Empty line means we have multiple objects returned, change
            # the returned dict in a list
            match = P4_FIELD_RE.match(line)

            if not match:
                # We maybe are parsing a multiline value
                current_value += line
            else:
                next_key = match.group("key")
                next_value = match.group("value")

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


class P4(_VCS[P4Command]):
    """Wrapper for P4 calls"""

    def __init__(
        self,
        port: str | None = None,
        user: str | None = None,
        client: str | None = None,
        password: str | None = None,
    ) -> None:
        self._p4python = P4Python()  # type: ignore[no-untyped-call]
        command_prefix = ["p4", "-z", "tag"]
        if client is not None:
            command_prefix += ["-c", client]
            self._p4python.client = client
        if password is not None:
            command_prefix += ["-P", password]
        if port is not None:
            command_prefix += ["-p", port]
            self._p4python.port = port
        if user is not None:
            command_prefix += ["-u", user]
            self._p4python.user = user

        super().__init__(P4Command, command_prefix)

        self.logger.debug("Using P4Python: %s", repr(self._p4python))
        self._p4python.connect()  # type: ignore[no-untyped-call]

    def submit(self, desc: str) -> None:
        change = self._p4python.fetch_change()
        change._description = desc
        self.logger.debug("%s", change)
        self._p4python.run_submit(change)  # type: ignore[no-untyped-call]

    @contextlib.contextmanager
    def ignore(self, *patterns: str) -> Iterator[None]:
        """Ignore specified patterns for every calls in a with scope
        for this P4 instance
        """
        tmp_path = None
        with tempfile.NamedTemporaryFile(mode="w") as tmp_file:
            tmp_path = tmp_file.name
            for it in patterns:
                tmp_file.write(f"{it}\n")

            ignore_env = tmp_path + os.environ.get("P4IGNORE", "")
            with self.with_env(P4IGNORE=ignore_env):
                yield


class GitCommand(VCSCommand[str]):
    """Object representing a git command, containing lines returned by it"""

    _lines: list[str] | None = None

    @overload
    def __getitem__(self, key: int) -> str: ...

    @overload
    def __getitem__(self, key: slice[Any, Any, Any]) -> Sequence[str]: ...

    def __getitem__(self, key: int | slice[Any, Any, Any]) -> str | Sequence[str]:
        self._eval_output()
        assert self._lines is not None
        return self._lines[key]

    def __len__(self) -> int:
        self._eval_output()
        assert self._lines is not None
        return len(self._lines)

    def _eval_output(self) -> None:
        if self._lines is not None:
            return
        self.check()
        self._lines = [stripped_it for it in self.out().split("\n") if (stripped_it := it.strip())]


class Git(_VCS[GitCommand]):
    """Wrapper representing a given git repository cloned in a given
    directory"""

    def __init__(
        self,
        config: Mapping[str, str] | None = None,
        git_dir: str | None = None,
        work_tree: None = None,
    ) -> None:
        command_prefix = ["git"]

        if git_dir is not None:
            command_prefix += ["--git-dir", git_dir]

        if config:
            for option, value in config.items():
                command_prefix += ["-c", f"{option}={value}"]

        super().__init__(GitCommand, command_prefix)
