# Pergit : Perforce / Git synchronization script
## Installation
Pergit is a git / Perforce synchronization script. Unlike git-p4 it's intended
to be used in a merge-based workflow, rather than a rebase one. Pergit will
maintain a branch synchronized with Perforce, using tags to mark synchronized
Perforce changelist. You'll can merge from or to this branch prior to run
Pergit in order to synchronize Perforce. Pergit works by issuing git commands
setting the work tree of git to a Perforce repository.

## Prerequisites
Pergit will need a Perforce workspace configured for both pulling and pushing
changes from / to Perforce. You can add any mapping you want and synchronize
only a subdirectory of your Perforce workspace.

## Usage
### Simple synchronization
Just run pergit your_target_branch --path /path/to/perforce. If the target
branch doesn't exists, it will be created.

### Handling conflicts
A conflict is meant to be changes on both Perforce and git, Pergit doesn't
support file-level changes.