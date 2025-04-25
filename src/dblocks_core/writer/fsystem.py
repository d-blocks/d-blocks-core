import json
import os
from pathlib import Path
from typing import Iterable

import cattrs

from dblocks_core.config import config
from dblocks_core.config.config import logger
from dblocks_core.model import config_model, meta_model, plugin_model
from dblocks_core.writer.contract import AbstractWriter

TABLE_SUFFIX = ".tab"
VIEW_SUFFIX = ".viw"
PROC_SUFFIX = ".pro"
JIDX_SUFFIX = ".jix"
IDX_SUFFIX = ".idx"
MACRO_SUFFIX = ".mcr"
DATABASE_SUFFIX = ".dtb"
USER_SUFFIX = ".usr"
ROLE_SUFFIX = ".rol"
PROFILE_SUFFIX = ".prf"
TRIGGER_SUFFIX = ".trg"
FUNCTION_SUFFIX = ".fnc"
FUNCTION_MAPPING_SUFFIX = ".mfnc"
TYPE_SUFFIX = ".type"
AUTH_SUFFIX = ".auth"
GENERIC_SQL_SUFFIX = ".sql"
GENERIC_BTEQ_SUFFIX = ".bteq"

TYPE_TO_EXT = {
    meta_model.TABLE: TABLE_SUFFIX,
    meta_model.VIEW: VIEW_SUFFIX,
    meta_model.PROCEDURE: PROC_SUFFIX,
    meta_model.JOIN_INDEX: JIDX_SUFFIX,
    meta_model.INDEX: IDX_SUFFIX,
    meta_model.MACRO: MACRO_SUFFIX,
    meta_model.DATABASE: DATABASE_SUFFIX,
    meta_model.TRIGGER: TRIGGER_SUFFIX,
    meta_model.FUNCTION: FUNCTION_SUFFIX,
    meta_model.FUNCTION_MAPPING: FUNCTION_MAPPING_SUFFIX,
    meta_model.TYPE: TYPE_SUFFIX,
    meta_model.AUTHORIZATION: AUTH_SUFFIX,
    meta_model.GENERIC_SQL: GENERIC_SQL_SUFFIX,
    meta_model.GENERIC_BTEQ: GENERIC_BTEQ_SUFFIX,
    meta_model.USER: USER_SUFFIX,
    meta_model.ROLE: ROLE_SUFFIX,
    meta_model.PROFILE: PROFILE_SUFFIX,
}

EXT_TO_TYPE = {v.lower(): k for k, v in TYPE_TO_EXT.items()}

STP_PROFILES = "003-profiles"
STP_ROLES = "004-roles"
STP_DATABASES = "005-databases"
STP_TYPES = "006-types"
STP_AUTH = "007-auth"
STP_TABLES = "010-tables"
STP_VIW_INDICES = "020-views-indices"
STP_EXECUTABLES = "030-executables"
STP_GENERIC_SQL = "050-sql"

EXT_TO_STEP = {
    PROFILE_SUFFIX: STP_PROFILES,
    ROLE_SUFFIX: STP_ROLES,
    TABLE_SUFFIX: STP_TABLES,
    VIEW_SUFFIX: STP_VIW_INDICES,
    PROC_SUFFIX: STP_EXECUTABLES,
    JIDX_SUFFIX: STP_VIW_INDICES,
    IDX_SUFFIX: STP_VIW_INDICES,
    MACRO_SUFFIX: STP_EXECUTABLES,
    DATABASE_SUFFIX: STP_DATABASES,
    TRIGGER_SUFFIX: STP_EXECUTABLES,
    FUNCTION_SUFFIX: STP_EXECUTABLES,
    FUNCTION_MAPPING_SUFFIX: STP_EXECUTABLES,
    TYPE_SUFFIX: STP_TYPES,
    AUTH_SUFFIX: STP_AUTH,
    GENERIC_SQL_SUFFIX: STP_GENERIC_SQL,
    GENERIC_BTEQ_SUFFIX: STP_GENERIC_SQL,
}

UTF8 = "utf-8"


class FSWriter(AbstractWriter):
    def __init__(self, cfg: config_model.WriterParameters):
        self.target_dir: Path = cfg.target_dir
        logger.debug(f"{self.target_dir=}")
        self.encoding: str = cfg.encoding
        logger.debug(f"{self.encoding=}")
        self.errors: str = cfg.errors
        logger.debug(f"{self.errors=}")

    def drop_nonex_objects(
        self,
        existing_objects: Iterable[meta_model.IdentifiedObject],
        tagged_databases: Iterable[meta_model.DescribedDatabase],
        *,
        databases_in_scope: Iterable[meta_model.DescribedDatabase],
    ):
        """Deletes objects that no longer exists.

        Args:
            existing_objects (Iterable[meta_model.IdentifiedObject]): list of
                all objects that exist
        """
        tags = {d.database_name.lower(): d for d in tagged_databases}
        tags_in_scope = {d.database_tag.lower() for d in databases_in_scope}

        tagged_objects = set()
        for obj in existing_objects:
            try:
                database_tag = tags[obj.database_name.lower()].database_tag
            except KeyError:
                database_tag = obj.database_name

            try:
                ext = TYPE_TO_EXT[obj.object_type]
            except KeyError:
                raise NotImplementedError(
                    f"can not get expected extension for: {obj.object_type}"
                ) from None
            expected_path = f"{database_tag.lower()}/{obj.object_name.lower()}{ext}"  # type: ignore
            tagged_objects.add(expected_path)
            logger.trace(expected_path)

        for file in self.target_dir.rglob("*.*"):
            # rglob returns also dirs, skip them
            if not file.is_file():
                continue
            # skip files that are not managed by this tool
            if file.suffix.lower() not in EXT_TO_TYPE:
                continue

            # skip the object if the db was skipped
            db_tag = file.parent.name.lower()
            is_object = db_tag + "/" + file.name.lower()

            if db_tag not in tags_in_scope:
                logger.trace(is_object)
                continue

            # skip the file if the object in question exists
            if is_object in tagged_objects:
                logger.trace(is_object)
                continue

            # drop the file
            logger.debug(f"drop file: {file.as_posix()}")
            file.unlink(missing_ok=True)

    def write_databases(
        self,
        databases: list[meta_model.DescribedDatabase],
        *,
        env_name: str,
    ):
        """Writes the list of described databases to a JSON file.

        Args:
            databases (list[meta_model.DescribedDatabase]): List of described databases.
            env_name (str): Environment name to be used in the filename.
        """
        data = cattrs.unstructure(databases)
        text = json.dumps(data, indent=4)
        tf = self.target_dir / f"{env_name}-databases.json"
        tf.write_text(text, encoding=UTF8)

    def path_to_object(
        self,
        obj: meta_model.DescribedObject,
        database_tag: str,
        parent_tags_in_scope: list[str] | None = None,
    ) -> Path | str:
        # překlad typu objektu na extenzi
        try:
            ext = TYPE_TO_EXT[obj.identified_object.object_type]
        except KeyError:
            raise NotImplementedError(
                f"can not write {obj.identified_object.object_type}"
            ) from None

        # cílové umístění
        filename = f"{obj.identified_object.object_name.lower()}{ext}"
        target_dir = self.standardize_subpath(database_tag, parent_tags_in_scope)
        target_file = target_dir / filename
        return target_file

    def write_object(
        self,
        obj: meta_model.DescribedObject,
        *,
        database_tag: str,
        parent_tags_in_scope: list[str] | None = None,
        plugin_instances: list[plugin_model._PluginInstance] | None = None,
    ):
        """Writes a described object to a file.

        Args:
            obj (meta_model.DescribedObject): The described object to be written.
            database_tag (str): The database tag associated with the object.
            parent_tags_in_scope (list[str] | None): Optional list of parent tags in scope.
        """
        target_file = self.path_to_object(obj, database_tag, parent_tags_in_scope)
        target_dir = target_file.parent

        logger.debug(f"write to: {target_file.as_posix()}")
        target_dir.mkdir(parents=True, exist_ok=True)

        # get the DDL script
        ddl_script = "\n".join(self._get_statements(obj))

        # call plugins before
        # FIXME: subptimal, cycle through everything, always ... really?
        for plugin in plugin_instances:
            plugin_instance = plugin.instance
            if not isinstance(plugin_instance, plugin_model.PluginFSWriter):
                continue
            logger.debug(
                f"call plugin before write: {plugin.module_name}.{plugin.class_name}"
            )
            new_ddl_script = plugin_instance.before(
                target_file,
                obj,
                ddl_script,
            )
            if new_ddl_script is not None:
                ddl_script = new_ddl_script

        # ddl skript
        target_file.write_text(
            ddl_script,
            encoding=self.encoding,
            errors=self.errors,
        )

        # call plugins after
        for plugin in plugin_instances:
            plugin_instance = plugin.instance
            if not isinstance(plugin_instance, plugin_model.PluginFSWriter):
                continue
            logger.debug(
                f"call plugin after write: {plugin.module_name}.{plugin.class_name}"
            )
            plugin_instance.after(target_file, obj)

    def _get_statements(
        self,
        object: meta_model.DescribedObject,
    ) -> list[str]:
        """Generates a list of DDL statements for the described object.

        Args:
            object (meta_model.DescribedObject): The described object.

        Returns:
            list[str]: List of DDL statements.
        """
        statements = []
        if object.basic_definition:
            statements.append(object.basic_definition)

        if object.object_comment_ddl:
            statements.append(f"\n{object.object_comment_ddl}")

        separate_stats = True
        for i, detail in enumerate(object.additional_details):
            # na prvním řádku chceme mít dvouřádkový odskok
            if i == 0:
                statements.append("\n")

            if isinstance(detail, meta_model.TableStatistic):
                # na první statistice chceme mít prázdný řádek nahoře
                if separate_stats:
                    statements.append("\n")
                    separate_stats = False
                statements.append(detail.ddl_statement)
            elif isinstance(detail, meta_model.ColumnDescription):
                statements.append(detail.ddl_statement)
            else:
                msg = f"can not write detail: {detail=}\n{object=}"
                raise NotImplementedError(msg)

        return statements

    def standardize_subpath(
        self,
        subpath: Path | str,
        parent_tags_in_scope: list[str] | None = None,
    ) -> Path:
        """
        Converts a relative path to lowercase and joins it with the target directory.

        Args:
            subpath (Path | str): The relative path to be standardized.
            parent_tags_in_scope (list[str] | None): Optional list of parent tags in scope.

        Returns:
            Path: The standardized path joined with the target directory.
        """
        if isinstance(subpath, str):
            subpath = Path(subpath.lower())
        else:
            subpath = subpath.as_posix().lower()

        # databázová hierarchie
        if parent_tags_in_scope:
            for p in parent_tags_in_scope:
                subpath = Path(p.lower()) / subpath

        return self.target_dir / subpath
