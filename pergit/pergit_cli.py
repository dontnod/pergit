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
"""gitp4 entry"""

import argparse
import logging
import subprocess
import sys

from . import LOGGER_NAME
from ._implementation import Pergit
from ._implementation import PergitError


def main(argv: list[str] | None = None) -> int:
    """gitp4 entry point"""

    if argv is None:
        argv = sys.argv

    parser = _get_parser()
    args = parser.parse_args()

    logging.basicConfig()

    logging_format = "%(message)s"
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    if args.verbose:
        logging.basicConfig(format=logging_format, level=logging.DEBUG)
    else:
        logging.basicConfig(format=logging_format, level=logging.INFO)

    try:
        with Pergit(
            branch=args.branch,
            squash_commits=args.squash_commits,
            strip_comments=args.strip_comments,
            p4_port=args.p4_port,
            p4_user=args.p4_user,
            p4_client=args.p4_client,
            p4_password=args.p4_password,
            force_full_reconcile=args.force_full_reconcile,
            simulate=args.simulate,
        ) as impl:
            impl.sychronize(changelist=args.changelist, tag_prefix=args.tag_prefix, auto_submit=args.auto_submit)

            return 0
    except PergitError as error:
        logger = logging.getLogger(LOGGER_NAME)
        logger.exception("", exc_info=error)
    except subprocess.CalledProcessError as error:
        logger = logging.getLogger(LOGGER_NAME)
        logger.exception('Error while runnig command "%s" :\n%s', " ".join(error.cmd), error.stderr, exc_info=error)

    return -1


def _get_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "branch",
        help="Branch name where to import changes. Defaultsto current branch, will be created if it Doesn't exists",
        metavar="<git-branch>",
        nargs="?",
        default=None,
    )

    parser.add_argument("--verbose", help="Enable verbose mode", action="store_true")

    parser.add_argument("--p4-port", help="Perforce server")

    parser.add_argument("--p4-user", help="Perforce user")

    parser.add_argument("--p4-client", help="Perforce workspace")

    parser.add_argument("--p4-password", help="Perforce password")

    parser.add_argument(
        "--squash-commits",
        help="Submits all git commits in one changelist, rather than one commit per changelist",
        action="store_true",
    )

    parser.add_argument("--changelist", help="Import changes starting at this revision", default=None)

    parser.add_argument("--tag-prefix", help="Prefix for Perforce C.L tags (defaults to branch", default=None)

    parser.add_argument(
        "--auto-submit", help="Submit to perforce server without asking for user validation", action="store_true"
    )

    parser.add_argument("--strip-comments", help='Remove every live leaded by "#" from the log', action="store_true")

    parser.add_argument(
        "--force-full-reconcile",
        help="Force perforce reconcile over full workspace",
        action="store_true",
        default=False,
    )

    parser.add_argument(
        "--simulate", help="Perform a dry run with no submit nor push", action="store_true", default=False
    )

    return parser


if __name__ == "__main__":
    sys.exit(main())
