# Feature: Create incremental package based on git history

## Overview

Prepares an incremental package, based on git history. This is (very) opinionated command, that follows certain assumptions.

**Assumptions**

- the git repo in question is clean, with (no uncommitted changes)
- the incremental package will contain **current state** copy of added/changed files; this means we always use the "up-to-date" state of the repo as baseline for the comparison and creation of the package
- we prepare list of changed files either against specified **commit** or specified **branch** (different branch then the one we are on)
- we then copy current state of these files to the incremental package

## Arguments

```bash
 Usage: debbie pkg-from-diff DIFF_AGAINST DIFF_IDENT PACKAGE_NAME 
```

Where:

- `diff_against` - is either `branch` or `commit` (see use cases below)
- `diff_ident` - is either name of the **branch** you want to compare to (typically: develop branch), or SHA of the **commit** you want to compare to
- `package_name` - is name of the directory that will be created under the `<repo_root>/pkg` directory (based on your configuration)

See below for more information about typical use cases.


## Use case - prepare package against a different branch (feature to develop)

Typical use case is as follows:

- you are a developer, responsible to prepare a new feature
- your starting point is thge `develop` branch of your repo
- you create a new feature branch using git command

```bash
git flow feature start a-new-feature
```

- you then change a few DDL scripts in the `./meta` directory in your repo
- you create a few commits over time
- you now want to prepare an incremental package, that contains **all changes** you have made to the code, starting with the **first** divergence from `develop` branch

Therefore, you use d-blocks as such:

```bash
dbe pkg-from-diff branch develop my-package
```

A new incremental package containing all changed files in your repo, since you diverged from the branch `develop`, will be created.

## Use case - prepare package against a different branch (feature to develop) - with filter

Let's now assume, that you only want to take into consideration certain subdirectories of your repo. For example, the repo is structured like this:

- `<repo_root>/meta` - Teradata DDL scripts, changes were made
- `<repo_root>/doc` - documentation artefacts, changes were also made, however you do not wish to include them in the package

Therefore, you use b-blocks as such:

```bash
dbe pkg-from-diff branch develop my-package --include-only meta
```

This will keep (copy) only files that are under the `meta` subdirectory of your repo.


## Use case - prepare package against commit on the same branch

Let's assume, that your feature branch now has been alive for two full weeks. You have made a few changes to the code, and you now weant to sync 
these changes to your database. You want to create a diff package based on the last commit you have already deployed to the database (a few days ago).

Therefore, you use d-blocks as such:

```bash
dbe pkg-from-diff commit _sha-of-the-commit-that-was-last-deployed_
```

Of course, you can alse filter out unwanted subdirectories (keep only wanted directories).


```bash
dbe pkg-from-diff commit _sha-of-the-commit-that-was-last-deployed_ --include-only subdir1 --include-only subdir2
```

## Use case - a "real" example

For example, you can use d-blocks as such:

```bash
┌─[coder@blacktux]─(~/d-blocks/d-blocks-o2)(.venv)
└─[13:11]-(^_^)-[$] dbe pkg-from-diff commit a94c3e50783f0ab04219ee9cb1c070727fdedac1 test-package  --include-only meta/prod/technology_users
13:11:39 | INFO     | is_commit_on_branch - ['master']
13:11:39 | INFO     | changes_against_commit - latest commit is c57f3f4c82d5a6a091ffb5008bbed4dbfd9ad93d
13:11:39 | INFO     | changes_against_commit - full changespec: 11 items
13:11:39 | INFO     | copy - Changeset length is: 7
13:11:39 | INFO     | copy - Target dir is: /home/jan/d-blocks/d-blocks-o2/pkg/test-package
Are you sure you want to continue? (yes/no) (no): y
```

This could result in a directory structure, that looks like this:

```bash
┌─[coder@blacktux]─(~/d-blocks/d-blocks-o2)(.venv)
└─[13:11]-(^_^)-[$] tree pkg/test-package/
pkg/test-package/
└── db
    └── Teradata
        └── 030-executables
            ├── database_1
            │   ├── proc1.pro
            │   ├── proc2.pro
            │   └── proc3.pro
            └── database_2
                ├── proc4.pro
                ├── proc5.pro
                ├── proc6.pro
                └── proc7.pro
```
