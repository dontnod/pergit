# Pergit : Perforce / Git synchronization script
## Overview
Pergit is a git / Perforce synchronization script. Unlike git-p4 it's intended
to be used in a merge-based workflow, rather than a rebase one. Pergit will
maintain a branch synchronized with Perforce, using tags to mark synchronized
Perforce changelist. You'll can merge from or to this branch prior to run
Pergit in order to synchronize Perforce.

## Installation
Just run pip install git+https://github.com/dontnod/pergit

## Preparing the workspace
Pergit will need a Perforce workspace configured for both pulling and pushing
changes from / to Perforce. Your git repository should lie in the same repo-
sitory. As pergit will overwrite Perforce files, you should set the 'Allwrite'
to true so that P4 doesn't complain about writable files being overwritten
during synchronization.

## Usage
Just run
    pergit your_target_branch
In your git repository. If the target branch doesn't exists, it will be created.
If you have change in both Perforce and Git, Pergit will refuse to synchronize.
That's why you should have a branch dedicated to perforce synchronization, so
you can import Perforce changes before merging the git changes then sending them
to Perforce.
After you synchronized the repository, don't forget to issue a git push --tags so
the synchronization tags are sent to the git repository (see below).

### Commits tagging
Pergit uses lightweight tags to keep track of which C.L correspond to which
commit. To set the prefix of those tags (for example if you synchronize)
different branches witch different workspace in the same repository, use the
--tag-prefix option (defaults to 'p4')