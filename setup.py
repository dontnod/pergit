#!/usr/bin/env python
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
''' pergit setup configuration '''
import re
import subprocess

import setuptools

# Tag master branch with revision and:
#  python3 setup.py bdist
#  python3 setup.py sdist upload
def _get_version():
    tag = subprocess.check_output(['git', 'tag', '--points-at', 'HEAD'])
    tag = tag.decode('utf-8').strip()
    if not tag:
        commit = subprocess.check_output(['git', 'rev-parse', '--short=10', 'HEAD'])
        return commit.decode('utf-8').strip()

    version_re = re.compile(r'v(\d+\.\d+\.\d+)')
    match = version_re.match(tag)
    if match is None:
        raise Exception('Bad version format : %s' % tag)

    return match.groups(1)

VERSION = _get_version()

setuptools.setup(**dict(
    name='pergit',
    version=VERSION,
    description='Git and Perforce synchronization utility',
    long_description=(
        'pergit is a git / Perforce synchronization utilities, using merge'
        'git workflow'),
    license='MIT',

    url='https://github.com/dontnod/pergit',
    download_url='https://github.com/dontnod/pergit/archive/' + VERSION + '.tar.gz',

    author='Dontnod Entertainment',
    author_email='root@dont-nod.com',

    packages=[
        'pergit',
    ],

    install_requires=[],

    entry_points={
        'console_scripts' : ['pergit = pergit.pergit:main'],
    },

    # See list at https://pypi.python.org/pypi?:action=list_classifiers
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Operating System :: MacOS',
        'Operating System :: Microsoft :: Windows',
        'Operating System :: POSIX',
        'Operating System :: Unix',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Topic :: Software Development :: Version Control :: Git',
    ],

    keywords='perforce git p4 synchronization',
))
