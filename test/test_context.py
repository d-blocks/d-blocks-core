from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import cattrs
import pytest
from attrs import define

from dblocks_core.context import FSContext
from dblocks_core.model import meta_model


def test_context():
    with TemporaryDirectory() as tmp:
        ctx = FSContext(
            name="test",
            directory=Path(tmp),
            log_self=False,
            atexit_handler=False,
        )

        ctx.set_checkpoint("test")
        ctx.atexit_handler()
        ctx["a_str"] = "string"

        assert ctx["a_str"] == "string"
        ctx.atexit_handler()
        del ctx

        ctx = FSContext(name="test", directory=Path(tmp), log_self=False)
        assert ctx.get_checkpoint("test")
        assert ctx["a_str"] == "string"
        assert len(ctx) == 1
        assert ctx.is_in_progress()

        for k, v in ctx.items():
            assert k == "a_str"
            assert v == "string"

        with pytest.raises(KeyError):
            ctx["neexistujici_klic"]

        db_in = meta_model.DescribedDatabase(
            database_name="db",
            database_tag="database_tag",
            parent_name="dbc",
            parent_tag="dbc",
            comment_string="comment",
            database_details=meta_model.DescribedTeradataDatabase(
                owner_name="dbc", perm_space=0, spool_space=0, temp_space=0, db_kind="D"
            ),
        )
        obj_in = meta_model.IdentifiedObject(
            database_name="db",
            object_name="table1",
            object_type="TABLE",
            platform_object_type="T",
            create_datetime=datetime.now(),
            last_alter_datetime=None,
            creator_name="me",
            last_alter_name="also me",
            in_scope=True,
        )
        env_in = meta_model.ListedEnv(
            all_databases=[db_in],
            dbs_in_scope=[db_in],
            all_objects=[obj_in],
        )

        ENV = "ENV"
        ctx[ENV] = cattrs.unstructure(env_in)
        ctx.save()
        del ctx[ENV]
        ctx.load()
        env_out = cattrs.structure(ctx[ENV], meta_model.ListedEnv)
        assert env_in == env_out
