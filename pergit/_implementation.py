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
import sys

import pergit
import pergit.vcs

_ = gettext.gettext
_TAG_RE = re.compile(r'^.*@(?P<changelist>\d+)')

_MSG_ARGUMENT_NOT_SET = _(
    'You didn\'t gave {} argument and no previous value was stored in settings '
    'for the specified  branch. Please run Pergit for this branch at least once'
    'with this value set as command argument.')

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
    def __init__(self,
                 branch=None,
                 squash_commits=False,
                 strip_comments=False,
                 p4_port=None,
                 p4_user=None,
                 p4_client=None,
                 p4_password=None):
        self._git = pergit.vcs.Git(config={'core.fileMode': 'false'})

        if branch is None:
            branch = self._git('rev-parse --abbrev-ref HEAD').out()

        self._branch = branch
        self._squash_commits = squash_commits
        self._strip_comments = strip_comments
        self._work_tree = pergit.vcs.Git()('rev-parse --show-toplevel').out()

        p4_port = self._load_argument('p4-port', p4_port, None, True)
        p4_client = self._load_argument('p4-client', p4_client, None, True)
        p4_user = self._load_argument('p4-user', p4_user, None, True)
        p4_password = self._load_argument('p4-password', p4_password, None, True)

        self._p4 = pergit.vcs.P4(port=p4_port,
                                 user=p4_user,
                                 client=p4_client,
                                 password=p4_password)

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

    def _load_argument(self, key, value, default_value, allow_none=False):
        git = self._git
        branch_key = self._branch.replace('/', '.')
        config_key = 'pergit.{}.{}'.format(branch_key, key)
        if value is None:
            value = git('config {}', config_key)
            if value:
                assert value.out()
                return value.out()
            if default_value is None and not allow_none:
                self._error('You didn\'t gave {} argument and no previous'
                            ' value was stored in settings for the specified '
                            ' branch. Please run Pergit for this branch at '
                            ' least once with this value set as command '
                            ' argument.',
                            key)
            value = default_value

        if value is not None:
            git('config --local {} "{}"', config_key, value).check()
        return value

    def __enter__(self):
        p4_root = self._work_tree + '/...'

        # Reverting and cleaning files in order to not commit trash to git
        p4 = self._p4
        self._info("Preparing Git and Perforce workspaces")
        p4('revert "{}"', p4_root).check()

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
                   changelist,
                   tag_prefix=None,
                   auto_submit=False):
        ''' Runs the import command '''
        git = self._git

        tag_prefix = self._load_argument('tag-prefix', tag_prefix, self._branch)

        git('symbolic-ref HEAD refs/heads/{}', self._branch)

        sync_commit, sync_changelist = self._get_latest_sync_state(tag_prefix)
        git_changes, perforce_changes = self._get_changes(changelist,
                                                          sync_commit,
                                                          sync_changelist)
        if perforce_changes and git_changes:
            self._error(_('You have changes both from P4 and git side, '
                          'refusing to sync'))
        elif perforce_changes:
            assert not git_changes
            self._import_changes(tag_prefix, perforce_changes)
        elif git_changes:
            assert not perforce_changes
            self._export_changes(tag_prefix, git_changes, auto_submit)
        else:
            self._info('Nothing to sync')

    def _get_latest_sync_state(self, tag_prefix):
        git = self._git
        latest_tag = git('describe --tags --match "{}@*"', tag_prefix)
        if not latest_tag:
            return None, None
        latest_tag = latest_tag.out()
        match = _TAG_RE.match(latest_tag)

        if not match:
            self._error('Commit {} seems to have a changelist tag, but it\'s'
                        'format is incorrect.')

        changelist = match.group('changelist')
        commit = git('show --pretty=format:%H --no-patch {}@{}', tag_prefix, changelist)
        return commit.out(), changelist


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
        if changelist == sync_changelist and changelists:
            assert (changelists[0]['change'] == sync_changelist or
                    sync_changelist == '0')
            changelists = changelists[1:]

        if sync_commit:
            commits = self._git('log --pretty=format:%H --ancestry-path {}..HEAD', sync_commit)
        else:
            commits = self._git('log --pretty=format:%H')

        if commits:
            commits = list(commits)
            commits.reverse()
            return commits, changelists

        # Happens when branch isn't already created
        return [], changelists

    def _get_perforce_changes(self, changelist):
        changelists = self._p4('changes -l "{}/...@{},#head"',
                               self._work_tree,
                               changelist)

        return reversed(changelists)

    def _import_changes(self, tag_prefix, changes):
        info = self._p4('info').single_record()
        date_re = r'\d{4}\/\d{2}\/\d{2} \d{2}:\d{2}:\d{2} ([+|-]\d{4}).*$'
        date_re = re.compile(date_re)
        utc_offset = date_re.match(info['serverDate']).group(1)
        user_cache = {}
        for change in changes:
            self._import_changelist(change, utc_offset, user_cache)
            self._tag_commit(tag_prefix, change)

    def _import_changelist(self, change, utc_offset, user_cache):
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
        author = self._get_author(change, user_cache)
        date = '%s %s' % (change['time'], utc_offset)
        with git.with_env(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date):
            git('commit --allow-empty --author "{}" -m "{}"',
                author,
                description).check()

    def _get_author(self, change, user_cache):
        user = change['user']
        if user in user_cache:
            return user_cache[user]

        user = self._p4('users {}', user)

        if not user:
            author = 'Pergit <a@b>'
        else:
            assert len(user) == 1
            user = user[0]
            author = '%s <%s>' % (user['FullName'], user['Email'])

        return author

    def _tag_commit(self, tag_prefix, change):
        git = self._git
        tag = '{}@{}'.format(tag_prefix, change['change'])

        if git('tag -l {}', tag).out():
            self._warn(_('Tag %s already existed, it will be replaced.'), tag)

        git('tag -f {}', tag).check()

    def _export_change(self, tag_prefix, commit, description, auto_submit):
        git = self._git
        p4 = self._p4
        root = self._work_tree

        git('checkout -f --recurse-submodules {}', commit).check()
        self._info(_('Preparing commit %s : %s'), commit[:10], description)
        git('clean -fd').check()

        with p4.ignore('**/.git'):
            p4('reconcile "{}/..."', root).check()

        if not auto_submit:
            self._info('Submit in ready in default changelist.')
            self._info('Press (s) to submit.')
            while True:
                char = sys.stdin.read(1)
                if char == 's' or char == 'S':
                    break

        self._info('Submitting')
        p4('submit -d "{}" "{}/..."', description, root).check()
        change = p4('changes -m 1 -s submitted').single_record()
        self._tag_commit(tag_prefix, change)

    def _strip_description_comments(self, description):
        if self._strip_comments:
            stripped = [ ln for ln in description.splitlines() if not (len(ln) == 0 or ln.strip().startswith('#')) ]
            return '\n'.join(stripped)
        else:
            return description

    def _export_changes(self, tag_prefix, commits, auto_submit):
        p4 = self._p4
        git = self._git
        root = self._work_tree
        self._info(_('Syncing perforce'))
        p4('sync "{}/..."', root).check()

        assert(any(commits))
        if self._squash_commits:
            desc_command = 'show -s --pretty=format:\'%%s <%%an@%%h>%%n%%b\' %s'
            description = [git(desc_command % it).out() for it in commits]
            description.reverse()
            description = '\n'.join(description)
            description = description.replace("'", "\\'")
            description = description.replace('"', '\\"')
            description = self._strip_description_comments(description)
            self._export_change(tag_prefix, commits[-1], description, auto_submit)
        else:
            for commit in commits:
                description = git('show -s --pretty=format:\'%s <%an@%h>%n%b\' ').out()
                description = self._strip_description_comments(description)
                self._export_change(tag_prefix, commit, description, auto_submit)

    def __exit__(self, ex_type, ex_value, ex_traceback):
        git = self._git
        if self._previous_head is not None:
            git('symbolic-ref HEAD refs/heads/{}', self._previous_head)
