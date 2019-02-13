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
''' gitp4 entry '''

import sys
import argparse
import logging

import pergit

def main(argv=None):
    ''' gitp4 entry point '''

    if argv is None:
        argv = sys.argv

    parser = _get_parser()
    args = parser.parse_args()

    logging.basicConfig()

    try:
        with pergit.Pergit(path=args.path) as impl:
            impl.sychronize(
                branch=args.branch,
                changelist=args.changelist
            )
    except pergit.PergitError as error:
        logging.getLogger('pergit').error(error)

def _get_parser():
    parser = argparse.ArgumentParser()

    parser.add_argument('path',
                        help='Root path of the mapped Perforce repository to sync',
                        metavar='<path>')

    parser.add_argument('branch',
                        help='Branch name where to import changes (will be created)',
                        metavar='<git-branch>')

    parser.add_argument('--changelist',
                        help='Import changes starting at this revision',
                        default='0')

    return parser

if __name__ == "__main__":
    sys.exit(main())
