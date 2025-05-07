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
"""pergit commands"""

from __future__ import annotations

import gettext
import logging
import os
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import NoReturn
from typing import Self

import pergit
import pergit.vcs

if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Iterator
    from collections.abc import Sequence
    from types import TracebackType

_ = gettext.gettext
_TAG_RE = re.compile(r"^.*@(?P<changelist>\d+)")

_MSG_ARGUMENT_NOT_SET = _(
    "Argument {} was not provided and no previous value for the specified branch "
    "was found in the settings. Please run Pergit for this branch at least once "
    "with this value set as command argument."
)


class PergitError(Exception):
    """Error raised when a command fails"""

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def __repr__(self) -> str:
        return self._message

    def __str__(self) -> str:
        return self._message


class Pergit:
    """Imports a Perforce depot into a git branch"""

    def __init__(
        self,
        branch: str | None = None,
        squash_commits: bool = False,
        strip_comments: bool = False,
        p4_port: str | None = None,
        p4_user: str | None = None,
        p4_client: str | None = None,
        p4_password: str | None = None,
        force_full_reconcile: bool = False,
        simulate: bool = False,
    ) -> None:
        self.logger = logging.getLogger(pergit.LOGGER_NAME)
        self.force_full_reconcile = force_full_reconcile
        self.simulate = simulate
        self._git = pergit.vcs.Git(config={"core.fileMode": "false"})

        if self.simulate:
            self.logger.info("*** SIMULATING PERGIT ***")

        if branch is None:
            branch = self._git(["rev-parse", "--abbrev-ref", "HEAD"]).out()
        remote = self._git(["remote", "show"]).out()

        self._branch = branch
        self._remote = remote
        self._squash_commits = squash_commits
        self._strip_comments = strip_comments
        self._work_tree = pergit.vcs.Git()(["rev-parse", "--show-toplevel"]).out()
        # dirty hack to prevent bad behavior whith msys2 / windows
        if os.name == "nt":
            self._work_tree = re.sub("^/(.)/", r"\1:/", self._work_tree)

        p4_port = self._load_argument("p4-port", p4_port, None, True)
        p4_client = self._load_argument("p4-client", p4_client, None, True)
        p4_user = self._load_argument("p4-user", p4_user, None, True)
        p4_password = self._load_argument("p4-password", p4_password, None, True)

        self._p4 = pergit.vcs.P4(port=p4_port, user=p4_user, client=p4_client, password=p4_password)
        # BB hack
        self._p4_submit = pergit.vcs.P4(port=p4_port, user=p4_user, client=p4_client, password=p4_password)

        self._previous_head: str | None = None

    def _error(self, fmt: str, *args: Any, **kwargs: Any) -> NoReturn:
        """Logs an error"""
        raise PergitError(fmt.format(*args, **kwargs))

    def _load_argument(
        self,
        key: str,
        value: str | None,
        default_value: str | None,
        allow_none: bool = False,
    ) -> str | None:
        git = self._git
        branch_key = self._branch.replace("/", ".")
        config_key = f"pergit.{branch_key}.{key}"
        if value is None:
            if config_cmd := git(["config", config_key]):
                assert config_cmd.out()
                return config_cmd.out()
            if default_value is None and not allow_none:
                self._error(_MSG_ARGUMENT_NOT_SET, key)
            value = default_value

        if value is not None:
            git(["config", "--local", config_key, value]).check()
        return value

    def __enter__(self) -> Self:
        p4_root = self._work_tree + "/..."

        # Reverting and cleaning files in order to not commit trash to git
        p4 = self._p4
        self.logger.info("Preparing Git and Perforce workspaces")
        p4(["revert", p4_root]).check()

        git = self._git
        if not git(["rev-parse", "--is-inside-work-tree"]):
            self._error(
                _(
                    "Not in a git repository, please run pergit from the"
                    " folder of the git repository in which you want to "
                    "import Perforce depot"
                )
            )

        current_head = git(["rev-parse", "--abbrev-ref", "HEAD"])

        if current_head:
            self._previous_head = current_head.out()

        return self

    def sychronize(
        self,
        changelist: str | None,
        tag_prefix: str | None = None,
        auto_submit: bool = False,
    ) -> None:
        """Runs the import command"""
        git = self._git

        tag_prefix = self._load_argument("tag-prefix", tag_prefix, self._branch)

        git(["symbolic-ref", "HEAD", f"refs/heads/{self._branch}"])

        sync_commit, sync_changelist = self._get_latest_sync_state(tag_prefix)
        git_changes, perforce_changes = self._get_changes(changelist, sync_commit, sync_changelist)
        if perforce_changes and git_changes:
            self._error(
                _("You have changes both from P4 and git side, refusing to sync.\nperforce: {perforce}\ngit: {git}\n"),
                perforce=perforce_changes,
                git=git_changes,
            )
        elif perforce_changes:
            assert not git_changes
            self._import_changes(tag_prefix, perforce_changes)
        elif git_changes:
            assert not perforce_changes
            self._export_changes(tag_prefix, git_changes, sync_commit, auto_submit)
        else:
            self.logger.warning("Nothing to sync")

    def _get_latest_sync_state(self, tag_prefix: str | None) -> tuple[str | None, str | None]:
        git = self._git
        latest_tag_cmd = git(["describe", "--tags", "--match", f"{tag_prefix}@*"])
        if not latest_tag_cmd:
            return None, None
        latest_tag = latest_tag_cmd.out()
        match = _TAG_RE.match(latest_tag)

        if not match:
            self._error("Commit {} seems to have a changelist tag, but it'sformat is incorrect.")

        changelist = match.group("changelist")
        commit = git(["show", "--pretty=format:%H", "--no-patch", "-n1", f"{tag_prefix}@{changelist}"])
        return commit.out(), changelist

    def _get_changes(
        self,
        changelist: str | None,
        sync_commit: str | None,
        sync_changelist: str | None,
    ) -> tuple[list[str], list[dict[str, str]]]:
        if sync_changelist is None:
            sync_changelist = "0"
        if changelist is None:
            changelist = sync_changelist

        if changelist is not None and sync_changelist > changelist:
            self._error(
                _(
                    "Trying sync at a C.L anterior to the latest synced "
                    "C.L. This would duplicate commits on top of the "
                    " current branch. Reset your branch to the changelist"
                    " you want to sync from, then run pergit again"
                )
            )

        changelists = list(reversed(self._p4(["changes", "-l", f"{self._work_tree}/...@{changelist},#head"])))

        # last_synced_cl is already sync, but when giving --changelist as
        # argument, one would expect that the change range is inclusive
        if changelist == sync_changelist and changelists:
            assert changelists[0]["change"] == sync_changelist or sync_changelist == "0"
            changelists = changelists[1:]

        if sync_commit:
            commits = self._git(["log", "--pretty=format:%H", "--ancestry-path", f"{sync_commit}..HEAD"])
        else:
            commits = self._git(["log", "--pretty=format:%H"])

        if commits:
            return list(reversed(commits)), changelists

        # Happens when branch isn't already created
        return [], changelists

    def _get_perforce_changes(self, changelist: str) -> Iterator[dict[str, str]]:
        changelists = self._p4(["changes", "-l", f"{self._work_tree}/...@{changelist},#head"])

        return reversed(changelists)

    def _import_changes(self, tag_prefix: str | None, changes: Iterable[dict[str, Any]]) -> None:
        info = self._p4(["info"]).single_record()
        server_date = info["serverDate"]

        date_re = re.compile(r"\d{4}\/\d{2}\/\d{2} \d{2}:\d{2}:\d{2} ([+|-]\d{4}).*$")
        utc_offset = date_match.group(1) if (date_match := date_re.match(server_date)) else None
        assert isinstance(utc_offset, str)

        user_cache: dict[str, str] = {}
        for change in changes:
            self._import_changelist(change, utc_offset, user_cache)
            self._tag_commit(tag_prefix, change)

    def _import_changelist(self, change: dict[str, Any], utc_offset: str, user_cache: dict[str, str]) -> None:
        p4 = self._p4
        git = self._git
        self.logger.info(_("Syncing then committing changelist %s : %s"), change["change"], change["desc"])
        p4(["sync", "{}/...@{}".format(self._work_tree, change["change"])]).check()
        description = change["desc"]
        git(["add", "."]).check()

        # Commit event if there are no changes, to keep P4 C.L description
        # and corresponding tag in git history
        author = self._get_author(change, user_cache)
        date = f"{change['time']} {utc_offset}"
        with git.with_env(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date):
            git(["commit", "--allow-empty", "--author", author, "-m", description]).check()

    def _get_author(self, change: dict[str, Any], user_cache: dict[str, str]) -> str:
        user = change["user"]
        if user in user_cache:
            return user_cache[user]

        # FIXME(tdesveaux): populate user cache?

        user = self._p4(["users", user])

        if not user:
            author = "Pergit <a@b>"
        else:
            assert len(user) == 1
            user = user[0]
            author = f"{user['FullName']} <{user['Email']}>"

        return author

    def _tag_commit(self, tag_prefix: str | None, change: dict[str, Any], description: str | None = None) -> None:
        git = pergit.vcs.Git()
        tag = "{}@{}".format(tag_prefix, change["change"])
        tag_command = ["tag", "-f", tag]
        if description is not None:
            # create an annoted tag to write version changelog in description
            tag_command.extend(["-m", description])

        if self.simulate:
            self.logger.info("SIMULATE :: %s", tag_command)
        if not self.simulate:
            if git(["tag", "-l", tag]).out():
                self.logger.warning(_("Tag %s already existed, it will be replaced."), tag)
            git(tag_command).out()
            self.logger.info("Pushing tags...")
            for remote in git(["remote"]).out().splitlines(keepends=False):
                git(["push", "--verbose", remote, tag]).out()

    def _export_change(
        self,
        tag_prefix: str | None,
        commit: str,
        description: str,
        fileset: Iterable[str],
        auto_submit: bool,
    ) -> None:
        git = pergit.vcs.Git()
        p4 = self._p4
        root = self._work_tree

        self.logger.info(_("Preparing commit %s : %s"), commit[:10], description)
        if not auto_submit:  # buildbot takes care of cleaning workspace
            git(["checkout", "-f", "--recurse-submodules", commit]).check()
            git(["clean", "-fd"]).check()

        # reconcile everything
        modified_paths = f"{root}/..."
        # limit the scope of reconcile to files modified by Git to speed things up
        # only if command line length allows for it
        if fileset and not self.force_full_reconcile:
            paths = " ".join([f"{root}/{file}" for file in fileset])
            # cmd limit is arround 8000 char
            modified_paths = paths if len(paths) < 7500 else modified_paths

        # ALF DEBUG, don't fail process if this fails for any reason
        try:
            # List Game/ALF/Plugins to make sure file are there at pergit time
            for dp, dn, filenames in os.walk(root):
                for f in filenames:
                    file_path = Path(dp, f).as_posix()
                    if "Game/ALF/Plugins" in file_path:
                        self.logger.info("ALF DEBUG Plugins: " + file_path)
            # debug client output to make sure client specs are what they should be
            p4(["client", "-o"]).out()
            reconcile_alf_debug_path = f"{root}/Game/ALF/Plugins/..."
            p4(["reconcile", "-n", reconcile_alf_debug_path]).out()
        except Exception:
            self.logger.warning("ALF debug failed")

        with p4.ignore("**/.git"):
            if self.simulate:
                p4(["reconcile", "-n", modified_paths]).out()
                self.logger.info(f'SIMULATE :: submit -d "{description}" "{root}/..."')
            else:
                reconcile_output = p4(["reconcile", modified_paths]).out()
                _reconcile_warning_flag = " !! "
                _reconcile_legit_warning = "can't reconcile filename with wildcards [@#%*]. Use -f to force reconcile."
                reconcile_errors = [
                    line.strip()
                    for line in reconcile_output.split("\n")
                    if line.startswith(_reconcile_warning_flag) and not line.endswith(_reconcile_legit_warning)
                ]
                if reconcile_errors:
                    self._error("Failing sync because of the following errors:\n{}", "\n".join(reconcile_errors))

        if not self.simulate:
            if not auto_submit:  # legacy behavior - not for buildbot
                self.logger.info("Submit is ready in default changelist.")
                while True:
                    char = sys.stdin.read(1)
                    if char == "s" or char == "S":
                        break

            self.logger.info("Submitting")
            p4_submit = self._p4_submit
            p4_submit.submit(description)

        change = p4(["changes", "-m", "1", "-s", "submitted"]).single_record()
        self._tag_commit(tag_prefix, change, description)

    def _strip_description_comments(self, description: str) -> str:
        if self._strip_comments:
            stripped = [ln for ln in description.splitlines() if not (len(ln)) == 0]
            if len(stripped) > 1:  # Protect against empty descriptions if we have only # message
                stripped = [ln for ln in stripped if not ln.strip().startswith("#")]
            return "\n".join(stripped)
        else:
            return description

    def _get_git_fileset(
        self,
        commits: Sequence[str],
        sync_commit: str | None,
        git_dir: str | None = None,
    ) -> list[str]:
        assert len(commits) > 0

        workdir = Path(git_dir) if git_dir is not None else Path()

        git_workdir = ["-C", str(workdir)]

        # get diff files from regular repo, does not include possible submodules
        # we're syncing whole repo history from initial commit when no sync occured yet, do not try to fetch previous commit
        one_commit_before = "~1" if sync_commit else ""

        current_commit = commits[-1]
        prev_commit = commits[0]

        fileset = list(
            self._git(
                [
                    *git_workdir,
                    "diff",
                    "--name-only",
                    f"{prev_commit}{one_commit_before}..{current_commit}",
                    "--",
                ]
            )
        )

        # get file list from diff
        self.logger.info(":: start debug fileset ::")
        self.logger.info("\n".join(fileset))
        self.logger.info(":: end debug fileset ::")

        # SUBMODULES

        git_modules_path = workdir / ".gitmodules"

        if git_modules_path.exists():
            # list submodules
            config_submodule_args = ["config", "--file", ".gitmodules"]

            # list all path entries in .gitmodules
            submodule_entries = list(
                self._git(
                    [
                        *git_workdir,
                        *config_submodule_args,
                        "--name-only",
                        "--get-regexp",
                        "submodule.*.path",
                    ]
                )
            )

            submodules_path = [
                self._git(git_workdir + config_submodule_args + ["--get", value]).out() for value in submodule_entries
            ]

            # remove submodule paths from changed fileset
            fileset = [e for e in fileset if e not in submodules_path]

            self.logger.info(":: found submodules at paths ::")
            self.logger.info("\n".join(submodules_path))

            ls_tree_output_regex = re.compile(r"^\d+ commit (?P<rev>[a-z0-9]+)\t.*$")
            for submodule_path in submodules_path:
                submodule_entry_at_current = self._git(
                    [*git_workdir, "ls-tree", current_commit, "--", submodule_path]
                ).out()
                if not submodule_entry_at_current:
                    # submodule was probably removed
                    fileset.append(submodule_path)
                    continue

                submodule_entry_at_prev = self._git([*git_workdir, "ls-tree", prev_commit, "--", submodule_path]).out()
                if not submodule_entry_at_prev:
                    # submodule was added at this commit
                    submodule_entry_at_prev = submodule_entry_at_current

                submodule_prev_commit = ls_tree_output_regex.match(submodule_entry_at_prev)["rev"]  # type: ignore[index]

                submodule_current_commit = ls_tree_output_regex.match(submodule_entry_at_current)["rev"]  # type: ignore[index]

                submodule_git_dir = submodule_path
                if git_dir is not None:
                    submodule_git_dir = f"{git_dir}/{submodule_path}"

                submodule_fileset = self._get_git_fileset(
                    [submodule_prev_commit, submodule_current_commit],
                    sync_commit,
                    submodule_git_dir,
                )

                fileset.extend(f"{submodule_path}/{file}" for file in submodule_fileset)

        return fileset

    def _export_changes(
        self,
        tag_prefix: str | None,
        commits: Sequence[str],
        sync_commit: str | None,
        auto_submit: bool,
    ) -> None:
        p4 = self._p4
        git = self._git
        root = self._work_tree
        self.logger.info(_("Syncing perforce"))
        p4(["sync", f"{root}/..."]).check()

        assert any(commits)
        if self._squash_commits:
            desc_command = ["show", "-s", "--pretty=format:%s <%an@%h>%n%b"]
            description = self._strip_description_comments(
                "\n".join(
                    reversed(
                        [git([*desc_command, it]).out() for it in commits],
                    )
                )
            )
            if (
                len(description) > 3900
            ):  # limit desc size because it breaks cmd on windows when exceding a certain amount of chars
                description = description[:3900]
            self._export_change(
                tag_prefix, commits[-1], description, self._get_git_fileset(commits, sync_commit), auto_submit
            )
        else:
            for commit in commits:
                description = git(["show", "-s", "--pretty=format:%s <%an@%h>%n%b"]).out()
                description = self._strip_description_comments(description)
                self._export_change(
                    tag_prefix, commit, description, self._get_git_fileset([commit], sync_commit), auto_submit
                )

    def __exit__(
        self, ex_type: type[BaseException] | None, ex_value: BaseException | None, ex_traceback: TracebackType | None
    ) -> None:
        git = self._git
        if self._previous_head is not None:
            git(["symbolic-ref", "HEAD", f"refs/heads/{self._previous_head}"])
