from loguru import logger

from dblocks_core import tagger
from dblocks_core.model import meta_model


def test_tagger_norules():
    tagging_variables = {}
    tagging_rules = []
    tgr = tagger.Tagger(
        variables=tagging_variables,
        rules=tagging_rules,
        tagging_strip_db_with_no_rules=True,
    )
    databases = ["adb"]
    tgr.build(databases=databases)
    cases = [
        ("adb", "table1", "create table adb.table1 ()", "create table table1 ()"),
        ("adb", "table1", 'create table "adb"."table1" ()', 'create table "table1" ()'),
        (
            "adb",
            "view1",
            "replace view adb.view1 as select * from otherdb.sometab;",
            "replace view view1 as select * from otherdb.sometab;",
        ),
        (
            "adb",
            "view1",
            'replace view "adb"."view1" as select * from otherdb.sometab;',
            'replace view "view1" as select * from otherdb.sometab;',
        ),
    ]
    for db, obj, to_tag, expected in cases:
        got = tgr.tag_statement(to_tag, database_name=db, object_name=obj)
        logger.warning(f"{to_tag=}, {got=}, {expected=}")
        assert got == expected

    _do = meta_model.DescribedObject(
        meta_model.IdentifiedObject(
            database_name="adb",
            object_name="table1",
            object_type=meta_model.TABLE,
            platform_object_type="T",
            create_datetime=None,
            last_alter_datetime=None,
            creator_name="me",
            last_alter_name="also_me",
        ),
        basic_definition="""create table "adb"."table1" ()""",
        object_comment_ddl=None,
        additional_details=[],
    )
    cases = [
        (_do, 'create table "table1" ()'),
    ]
    for obj, expected in cases:
        tgr.tag_object(obj)
        logger.warning(f"{to_tag=}, {got=}, {expected=}")
        assert obj.basic_definition == expected

    # disallow stripping name of the database
    tgr = tagger.Tagger(
        variables=tagging_variables,
        rules=tagging_rules,
        tagging_strip_db_with_no_rules=False,
    )
    databases = ["adb"]
    tgr.build(databases=databases)
    cases = [
        ("adb", "table1", "create table adb.table1 ()", "create table adb.table1 ()"),
        (
            "adb",
            "view1",
            "replace view adb.view1 as select * from otherdb.sometab;",
            "replace view adb.view1 as select * from otherdb.sometab;",
        ),
    ]

    for db, obj, to_tag, expected in cases:
        got = tgr.tag_statement(to_tag, database_name=db, object_name=obj)
        logger.warning(f"{to_tag=}, {got=}, {expected=}")
        assert got == expected


def test_tagger():
    tagging_variables = {
        "env_dbe": "Ep",
        "env_dba": "aP",
    }
    tagging_rules = [
        "{{env_dbe}}%",
        "{{env_dba}}%",
    ]
    databases = ["eP_OPr", "ap_stg", "ep_tda", "ed0_tda"]
    tgr = tagger.Tagger(variables=tagging_variables, rules=tagging_rules)
    tgr.build(databases)

    logger.error(f"{tgr.database_replacements=}")
    logger.error(f"{tgr.replacement_rules=}")
    for repl in tgr.replacement_regexps:
        logger.error(f"replacement_regexp = {repl}")

    # tagging of databases does not use regexes and is case sensitive
    assert tgr.tag_database("eP_OPr") == "{{env_dbe}}_OPr"

    # tagging of content, however, should not be case sensitive
    cases = [
        ("create table ep_opr.table ()", "create table {{env_dbe}}_OPr.table ()"),
        (
            "replace view ap_stg.whatever as select ... join ap_stg.whatever ...",
            "replace view {{env_dba}}_stg.whatever as select ... join {{env_dba}}_stg.whatever ...",  # noqa: E501
        ),
        (
            'replace view "ap_stg".whatever as select ... join ap_stg.whatever ...',
            'replace view "{{env_dba}}_stg".whatever as select ... join {{env_dba}}_stg.whatever ...',  # noqa: E501
        ),
    ]
    for to_tag, expected in cases:
        got = tgr.tag_statement(to_tag)
        logger.warning(f"{to_tag=}, {got=}, {expected=}")
        assert got == expected

    # check expansion
    got = "create table {{env_dbe}}_stg.whartever {{env_dba}}"
    wanted = "create table Ep_stg.whartever aP"
    assert tgr.expand_statement(got) == wanted
