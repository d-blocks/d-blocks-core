from pathlib import Path

import cattrs
from loguru import logger

from dblocks_core.model.config_model import WriterParameters
from dblocks_core.model.meta_model import DescribedDatabase
from dblocks_core.script.workflow import dbi
from dblocks_core.writer import fsystem


def test_set_database_parents():
    A_PRODUCTION = "A_PRODUCTION"
    A_STG_PRODUCTION = "A_STG_PRODUCTION"
    A_STG = "A_STG"
    A_STO = "A_STO"
    DBC = "DBC"

    # simple DB hierarchy
    databases = [
        DescribedDatabase(
            database_name=A_PRODUCTION,
            database_tag=A_PRODUCTION,
            parent_name=DBC,
            parent_tag=DBC,
        ),
        DescribedDatabase(
            database_name=A_STG_PRODUCTION,
            database_tag=A_STG_PRODUCTION,
            parent_name=A_PRODUCTION,
            parent_tag=A_PRODUCTION,
        ),
        DescribedDatabase(
            database_name=A_STG,
            database_tag=A_STG,
            parent_name=A_STG_PRODUCTION,
            parent_tag=A_STG_PRODUCTION,
        ),
        DescribedDatabase(
            database_name=A_STO,
            database_tag=A_STO,
            parent_name=A_STG_PRODUCTION,
            parent_tag=A_STG_PRODUCTION,
        ),
    ]

    dbi.set_database_parents(databases)
    checked_databases = {d.database_tag: d for d in databases}

    # A_PRODUCTION is under DBC, however DBC is not in scope, therefore we do not
    # report any parent
    assert checked_databases[A_PRODUCTION].parent_tags_in_scope == []

    # A_STG_PRODUCTION is below A_PRODUCTION
    assert checked_databases[A_STG_PRODUCTION].parent_tags_in_scope == [A_PRODUCTION]

    # A_STG is below A_STG_PRODUCTION, whic is below A_PRODUCTION
    assert checked_databases[A_STG].parent_tags_in_scope == [
        A_STG_PRODUCTION,
        A_PRODUCTION,
    ]

    # A_STO is below A_STG_PRODUCTION, whic is below A_PRODUCTION
    assert checked_databases[A_STO].parent_tags_in_scope == [
        A_STG_PRODUCTION,
        A_PRODUCTION,
    ]

    # writer can (and will) create hierarchical structure
    # for databases in scope
    # TODO: this API is really, really "clumsy" and I do not like it one bit.
    #       what I mean by that is that we should probably give list of parents, and not the
    #       database name, and parents above it ...
    wrt = fsystem.FSWriter(WriterParameters(target_dir="."))
    subpath = wrt.standardize_subpath(
        A_STO,
        [
            A_STG_PRODUCTION,
            A_PRODUCTION,
        ],
    )
    expected_path = (
        Path(".") / A_PRODUCTION.lower() / A_STG_PRODUCTION.lower() / A_STO.lower()
    )
    assert subpath == expected_path
