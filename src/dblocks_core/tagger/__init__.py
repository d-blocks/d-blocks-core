import re

from attrs import frozen

from dblocks_core import exc
from dblocks_core.config.config import logger
from dblocks_core.model import meta_model

BACKSLASH = "\\"
RE_DOT = r"\."
RE_QUOTE = '"'


@frozen
class _Pattern:
    pattern: re.Pattern
    replacement: str


class Tagger:
    def __init__(
        self,
        variables: dict[str, str],
        rules: list[str],
        *,
        tagging_strip_db_with_no_rules: bool = True,
    ):
        self.variables = variables
        self.original_rules = rules
        self.tagging_strip_db_with_no_rules = tagging_strip_db_with_no_rules
        self.matching_rules = [_matching_rule(r, variables) for r in rules]
        self.replacement_rules = [_replacement_rule(r) for r in rules]
        self.database_replacements: dict[str, str] = {}
        self.replacement_regexps: list[_Pattern] = []
        logger.debug(f"{self.matching_rules=}")
        logger.debug(f"{self.replacement_rules=}")
        self._check()

    def _check(self):
        errors = []
        for i, r in enumerate(self.matching_rules):
            if "{" in r or "}" in r:
                try:
                    orig_rule = self.original_rules[i]
                except IndexError:
                    orig_rule = r
                errors.append(f"rule #{i}: {orig_rule}")
        if errors:
            message = (
                "Failed to replace some variables in one or more rules:\n"
                + "\n".join(errors)
            )
            raise exc.DConfigError(message)

    def expand_statement(self, statement: str | None) -> str:
        if not statement:
            return ""
        new_statement = statement  # type: ignore
        for name, value in self.variables.items():
            search_for = "{{" + name + "}}"
            new_statement = new_statement.replace(search_for, value)
        return new_statement

    def tag_object(
        self,
        object: meta_model.DescribedObject,
    ):
        object.basic_definition = self.tag_statement(
            object.basic_definition,
            database_name=object.identified_object.database_name,
            object_name=object.identified_object.object_name,
        )
        object.object_comment_ddl = self.tag_statement(
            object.object_comment_ddl,
            database_name=object.identified_object.database_name,
            object_name=object.identified_object.object_name,
        )
        for stmt in object.additional_details:
            # pyright complains on the following line, due to the fact that
            # tag_statement returns None on input of None. However, the
            # ddl_statemen can not be None
            # therefore we switch off the check
            stmt.ddl_statement = self.tag_statement(
                stmt.ddl_statement,
                database_name=object.identified_object.database_name,
                object_name=object.identified_object.object_name,
            )  # type: ignore

    def tag_statement(
        self,
        statement: str | None,
        *,
        database_name: str | None = None,
        object_name: str | None = None,
    ) -> str | None:
        """Tags one and only one statement.

        Args:
            statement (str): the statement in question
            database (str|None): name of the database
            object (str|None): name of the object

        Returns:
            str: tagged statement
        """
        if statement is None:
            return statement

        # case 1: the tagger is set to have replacement rules
        if len(self.replacement_rules) > 0:
            for rule in self.replacement_regexps:
                pattern, replacement = rule.pattern, rule.replacement
                statement = pattern.sub(replacement, statement)
            return statement

        # case 2: the tagger is NOT set to have replacement rule
        #         but is set to have both database and object name
        if self.tagging_strip_db_with_no_rules and database_name and object_name:
            tr = re.compile(f'"?{database_name}"?\\s*[.]\\s*("?{object_name}"?)', re.I)
            statement = tr.sub(r"\1", statement)
            return statement

        # giving up
        return statement

    def build(self, databases: list[str], *, flags=re.I):
        """Create list of tagged databases.

        Args:
            databases (list[str]): list of databases
            flags (_type_, optional): re.flags. Defaults to re.I.
        """
        self.database_replacements = {db: "" for db in databases}

        for db in databases:
            for i, mrule in enumerate(self.matching_rules):
                if re.fullmatch(mrule, db, flags=flags):
                    self.database_replacements[db] = re.sub(
                        mrule,
                        self.replacement_rules[i],
                        db,
                        flags=flags,
                    )
                    break

        # keep only those databases that can effectively be replaced
        self.database_replacements = {
            db: tagged_db
            for db, tagged_db in self.database_replacements.items()
            if tagged_db
        }

        # prepare regex in form of db. => tagged_db
        for db, tagged_db in self.database_replacements.items():
            # DB. => env. - simple replacement, no quoting of names
            pattern = re.compile(f"(^|\\s+){db}{RE_DOT}", re.I)
            replacement = f"\\1{tagged_db}."
            self.replacement_regexps.append(_Pattern(pattern, replacement))

            # "DB". => "env".
            pattern = re.compile(f"(^|\\s+){RE_QUOTE}{db}{RE_QUOTE}{RE_DOT}", re.I)
            replacement = f"\\1{RE_QUOTE}{tagged_db}{RE_QUOTE}."
            self.replacement_regexps.append(_Pattern(pattern, replacement))

    def tag_database(self, database: str) -> str:
        try:
            replacement = self.database_replacements[database]
            return replacement if replacement is not None else database
        except KeyError:
            return database


def _matching_rule(rule: str, variables: dict[str, str]):
    rule = rule.replace("%", "(.*)")
    for k, v in variables.items():
        tag = "{{" + k + "}}"
        rule = rule.replace(tag, re.escape(v))
    rule = "^" + rule + "$"
    return rule


def _replacement_rule(rule: str):
    prev_pattern, pattern = "", rule
    i = 0
    while pattern != prev_pattern:
        i = i + 1
        prev_pattern = pattern
        pattern = pattern.replace("%", f"{BACKSLASH}{i}", 1)
    return pattern
