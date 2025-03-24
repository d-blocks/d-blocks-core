import sys
from contextlib import contextmanager

from dblocks_core.config.config import logger


class DBlocksError(Exception):
    "Base class for all future errors."

    no_stack_trace = False

    def __init__(self, message: str | None = None):
        if message is not None:
            self.message = message


class DConfigError(DBlocksError):
    "Configuration error."

    pass


class DOperationsError(DBlocksError):
    "File creation/removal error, and simillar types of problems."

    pass


class DGitError(DOperationsError):
    "Git related error."

    pass


class DGitCommandError(DGitError):
    "Git command failed."

    pass


class DGitNotFound(DGitError):
    "Git related error."

    pass


class DBError(DBlocksError):
    "Base class for errors on database operations."

    pass


class DBAccessRightsError(DBError):
    pass


class DBStatementError(DBError):
    "generic error caused by an invalid statement"

    def __init__(self, message: str | None = None, statement: str | None = None):
        self.statement = statement
        super().__init__(message)


class DBCannotConnect(DBError):
    "Can not connect to the database."

    pass


class DBObjectDoesNotExist(DBError):
    "Object in database does not exist."

    pass


class DBNoStatsDefined(DBError):
    "No statistics defined for the object."

    pass


class DParsingError(DBlocksError):
    "Can not parse or tokenize the input."

    pass


class DDeployerInvalidBatch(DOperationsError):
    pass


@contextmanager
def catch_our_errors():
    try:
        yield
    except DBlocksError as err:
        logger.error(err.message)
        sys.exit(1)
    except KeyboardInterrupt:
        logger.error("Program was interrupted (Ctrl+C)")
        sys.exit(1)


def _print_exception_tree():
    def _print_exception_tree(exception_class, indent="", symbol=""):
        doc = (
            exception_class.__doc__.strip()
            if exception_class.__doc__
            else "No documentation available"
        )
        print(f"{indent}{symbol} {exception_class.__name__}: {doc}")

        for subclass in exception_class.__subclasses__():
            new_symbol = symbol + "--" if symbol else "+--"
            _print_exception_tree(subclass, indent + "  ", new_symbol)

    _print_exception_tree(DBlocksError, symbol="")


if __name__ == "__main__":
    _print_exception_tree()
