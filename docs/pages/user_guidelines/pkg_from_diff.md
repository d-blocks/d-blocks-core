# Feature: Create incremental package based on git history

## Overview

Prepares an incremental package, based on git history. This is (very) opinionated command, that follows certain assumptions.

**Assumptions**

- the git repo in question is clean, with (no uncommitted changes)
- the incremental package will contain **current state** copy of added/changed files; this means we always use the "up-to-date" state of the repo as baseline for the comparison and creation of the package
- we prepare list of changed files either against specified **commit** or specified **branch** (different branch then the one we are on)
- for **table** scripts (`.tab` extension), instead of a simple copy, the tool generates intelligent **change scripts** that preserve data
- for **deleted objects**, the tool generates appropriate DROP or RENAME scripts
- each package includes **release notes** summarising all changes

## Arguments

```bash
 Usage: debbie pkg-from-diff DIFF_AGAINST DIFF_IDENT PACKAGE_NAME 
```

Where:

- `diff_against` - is either `branch` or `commit` (see use cases below)
- `diff_ident` - is either name of the **branch** you want to compare to (typically: develop branch), or SHA of the **commit** you want to compare to
- `package_name` - is name of the directory that will be created under the `<repo_root>/pkg` directory (based on your configuration)

See below for more information about typical use cases.


## Package Structure

The generated package uses **ordered step folders** (double-digit prefixed) that determine the deployment sequence:

```
pkg/<package_name>/
├── RELEASE_NOTES.md
└── db/
    └── teradata/
        ├── 010-tables/                    ← tables deployed first
        │   └── <database_name>/
        │       ├── my_table_change.sql    ← change script (RENAME-CREATE-INSERT)
        │       └── new_table.tab          ← new table DDL (copied as-is)
        ├── 020-views-indices/             ← views and indices
        │   └── <database_name>/
        │       └── my_view.viw
        ├── 030-executables/               ← procedures, macros, functions, triggers
        │   └── <database_name>/
        │       └── my_proc.pro
        ├── 050-sql/                       ← generic SQL scripts
        │   └── <database_name>/
        │       └── script.sql
        ├── 080-drops/                     ← DROP / RENAME-obsolete scripts
        │   └── <database_name>/
        │       ├── old_view_drop.sql      ← DROP VIEW statement
        │       └── old_table_obsolete.sql ← RENAME TABLE … _obsolete<ts>
        └── 090-drop-backups/              ← cleanup of backup tables
            └── <database_name>/
                └── my_table_drop_bkp.sql  ← DROP TABLE … _bkp<ts>
```

**Deployment order rationale:**
1. **010-tables** — tables are deployed first since other objects (views, procedures) may depend on them.
2. **020-views-indices** — views and indices come next.
3. **030-executables** — procedures, macros, functions, triggers.
4. **050-sql** — generic SQL scripts.
5. **080-drops** — DROP scripts for deleted objects; deletion happens after new objects are deployed to avoid breaking remaining dependencies temporarily.
6. **090-drop-backups** — cleanup of backup tables created by the RENAME-CREATE-INSERT strategy. This runs last, ensuring data is safe until deployment is confirmed successful.


## Table Change Handling

When a table script (`.tab`) is **modified**, the tool parses both the old version (retrieved from the baseline commit via git) and the new version to understand what changed.

### Structural changes (RENAME-CREATE-INSERT)

When columns, primary index, or partitioning changed, the generated change script follows the **RENAME-CREATE-INSERT** strategy:

```sql
-- Step 1: Backup existing table via RENAME
RENAME TABLE db.my_table TO db.my_table_bkp20260220143015;

-- Step 2: Create new version of the table
CREATE MULTISET TABLE db.my_table (
    id INTEGER NOT NULL,
    name VARCHAR(100) NOT NULL,
    new_col DATE
)
PRIMARY INDEX (id);

-- Step 3: Migrate data from backup to new table
INSERT INTO db.my_table
(
    "id",
    "name",
    "new_col"
)
SELECT
    "id",
    "name",
    CAST(NULL AS DATE)  /* new column */
FROM db.my_table_bkp20260220143015;
```

### Column mapping during INSERT

The generated INSERT … SELECT handles several scenarios:

| Scenario | Behaviour | Warning |
|----------|-----------|---------|
| Column exists in both, same type | Direct copy | — |
| Column exists in both, **data type changed** | `CAST(old_col AS new_type)` | Yes |
| Column exists in both, was NULLABLE → now NOT NULL | `COALESCE(old_col, default_value)` | Yes — validate |
| Column exists in both, type changed **and** became NOT NULL | `COALESCE(CAST(old_col AS new_type), default_value)` | Yes — validate |
| Column exists **only in new table**, NOT NULL | `CAST(default_value AS new_type)` | Yes — validate |
| Column exists **only in new table**, NULLABLE | `CAST(NULL AS new_type)` | — |
| Column dropped in old, new column added | — | Yes — possible rename |

Default values per data type:

| Type family | Default value |
|------------|---------------|
| INTEGER, SMALLINT, BIGINT, BYTEINT | `0` |
| FLOAT, REAL, DOUBLE PRECISION | `0.0` |
| DECIMAL, NUMERIC, NUMBER | `0` |
| DATE | `DATE '1900-01-01'` |
| TIMESTAMP | `TIMESTAMP '1900-01-01 00:00:00'` |
| CHAR, VARCHAR, CLOB | `''` |
| Others | `NULL` |


### Non-structural changes (stats / comments only)

When only COLLECT STATISTICS or COMMENT ON statements changed, the table DDL is **not** re-deployed. Instead, only the affected statements are emitted:

```sql
-- New/changed statistics:
COLLECT STATISTICS COLUMN (col_x) ON db.my_table;

-- Changed comments:
COMMENT ON COLUMN db.my_table.col_x IS 'new description';
```


## Deleted Objects

### Deleted tables

Instead of dropping a table (which would destroy data), the tool generates a **RENAME** that adds an `_obsolete<timestamp>` suffix:

```sql
-- Mark table as obsolete (dropped from Git): db.old_table
RENAME TABLE db.old_table TO db.old_table_obsolete20260220143015;
```

### Deleted non-table objects

For views, procedures, macros, etc., a plain **DROP** is generated:

```sql
-- Drop VIEW: db.old_view
DROP VIEW db.old_view;
```


## Release Notes

Every package includes a `RELEASE_NOTES.md` file that summarises:

- All **added**, **modified**, and **deleted** objects.
- **Warnings** raised during change script generation (e.g. possible renames, NOT NULL default values).
- A summary with counts per action.


## Use case - prepare package against a different branch (feature to develop)

Typical use case is as follows:

- you are a developer, responsible to prepare a new feature
- your starting point is the `develop` branch of your repo
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

Therefore, you use d-blocks as such:

```bash
dbe pkg-from-diff branch develop my-package --include-only meta
```

This will keep (copy) only files that are under the `meta` subdirectory of your repo.


## Use case - prepare package against commit on the same branch

Let's assume, that your feature branch now has been alive for two full weeks. You have made a few changes to the code, and you now want to sync 
these changes to your database. You want to create a diff package based on the last commit you have already deployed to the database (a few days ago).

Therefore, you use d-blocks as such:

```bash
dbe pkg-from-diff commit _sha-of-the-commit-that-was-last-deployed_ my-package
```

Of course, you can also filter out unwanted subdirectories (keep only wanted directories).

```bash
dbe pkg-from-diff commit _sha-of-the-commit-that-was-last-deployed_ my-package --include-only subdir1 --include-only subdir2
```

## Use case - a "real" example

For example, you can use d-blocks as such:

```bash
┌─[coder@blacktux]─(~/d-blocks/d-blocks-o2)(.venv)
└─[13:11]-(^_^)-[$] dbe pkg-from-diff commit a94c3e50 test-package --include-only meta/prod/technology_users
13:11:39 | INFO     | is_commit_on_branch - ['master']
13:11:39 | INFO     | changes_against_commit - latest commit is c57f3f...
13:11:39 | INFO     | changes_against_commit - full changespec: 11 items
13:11:39 | INFO     | copy - Changeset length is: 11
13:11:39 | INFO     | copy - Target dir is: /home/jan/d-blocks/d-blocks-o2/pkg/test-package
Are you sure you want to continue? (yes/no) (no): y
13:11:40 | INFO     | structural change for table: meta/prod/technology_users/my_table.tab
13:11:40 | INFO     | new table: meta/prod/technology_users/new_table.tab
13:11:40 | INFO     | Release notes written to: ...

⚠️  2 warning(s) during package creation:
  - Column 'status': new NOT NULL column. Default value '''' will be used. Please validate.
  - Column 'old_col' was dropped and 'new_col' was added — possibly a rename. Please validate.
```

This could result in a directory structure that looks like this:

```bash
pkg/test-package/
├── RELEASE_NOTES.md
└── db
    └── teradata
        ├── 010-tables
        │   └── technology_users
        │       ├── my_table_change.sql
        │       └── new_table.tab
        ├── 030-executables
        │   └── technology_users
        │       ├── proc1.pro
        │       └── proc2.pro
        ├── 080-drops
        │   └── technology_users
        │       └── old_view_drop.sql
        └── 090-drop-backups
            └── technology_users
                └── my_table_drop_bkp.sql
```
