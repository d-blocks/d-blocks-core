from typing import Generator

from dblocks_core import exc

SEMICOLON = ";"
APOSTROPHE = "'"
SLASH = "/"
STAR = "*"
NEW_LINE = "\n"
LBRACKET = "("
RBRACKET = ")"
MINUS = "-"
QUOTE = '"'


def tokenize_statements(
    text: str,
    *,
    separator=SEMICOLON,
) -> Generator[str, None, None]:
    """
    Tokenizes SQL statements from a text input, handling comments and string
    literals.

    Args:
        text (str): The input text containing SQL statements.
        separator (str, optional): The character used to separate statements.
            Defaults to `SEMICOLON`.

    Raises:
        exc.DParsingError: Raised for errors such as unterminated comments or
            strings, or invalid empty statements.

    Yields:
        str: A parsed SQL statement.

    Behavior:
    - Processes the input text character by character, maintaining state for
    handling string literals and block comments.
    - Identifies the end of a statement using the provided separator, ensuring
    that statements are non-empty.
    - Detects and raises errors for unterminated comments or string literals,
    enhancing error messages with line numbers.
    - Yields each valid SQL statement, and processes any remaining text at the end
    as the final statement.
    """

    # initial state
    in_string, in_comment, skip_next_n = False, False, 0
    in_identifier, in_single_line_comment = False, False
    bracket_count = 0
    next_char = ""
    line_no = 1
    prev_stmt_idx, stmt_count = 0, 1

    for i, char in enumerate(text):
        # count new lines to enhance error messages
        if char == NEW_LINE:
            line_no = line_no + 1

        # skip unterminated parts of the statement
        if skip_next_n > 0:
            skip_next_n = skip_next_n - 1
            continue

        # peek the next character
        try:
            next_char = text[i + 1]
        except IndexError:
            next_char = ""

        # peek at the next 2 characters
        try:
            next_2chars = text[i + 1 : i + 3]  # noqa: E203
        except IndexError:
            next_2chars = ""

        # start and end of string
        if char == APOSTROPHE and not in_comment:
            # start of a string literal
            if not in_string:
                in_string = True
                continue
            if next_2chars == APOSTROPHE + APOSTROPHE:
                # inside a string, this char is APOSTROPHE and next as well
                # this means "escaped" apostrophe, skip it,
                # as well as the next apostrophe
                skip_next_n = 2
                continue
            else:
                # ending apostrophe
                in_string = False

        # start of comment
        if char == SLASH and next_char == STAR and not in_string:
            if in_comment:
                message = (
                    f"Error at line {line_no}: unterminated comment "
                    "('/*' encountered)"
                )
                raise exc.DParsingError(message)
            in_comment, skip_next_n = True, 1
            continue

        # end of comment
        if char == STAR and next_char == SLASH and not in_string:
            if not in_comment:
                message = (
                    f"Error at line {line_no}: termination of comment with no start "
                    "('*/' encountered)"
                )
                raise exc.DParsingError(message)
            in_comment, skip_next_n = False, 1

        # start of single line comment
        if char == MINUS and next_char == MINUS:
            in_single_line_comment, skip_next_n = True, 1
            continue

        # in single line comment
        if in_single_line_comment:
            if char == NEW_LINE:
                in_single_line_comment = False
            continue

        # in an identifier
        if char == QUOTE:
            in_identifier = not in_identifier
            continue
        if in_identifier:
            continue

        # in a bracket ... could be in an identifier, do not count them
        # example: COLLECT STATS COLUMN ( CAST((start_dt ) AS TIMESTAMP(6)))  AS "CAST((start_dt ) _41900072" , )
        # this is a valid SQL, however number of brackets is not "symmetrical"
        if char == LBRACKET:
            bracket_count += 1
            continue
        if char == RBRACKET:
            bracket_count -= 1
            continue

        # end of statement
        if (
            char == separator
            and not in_comment
            and not in_string
            and bracket_count == 0
        ):
            # get the statement, throw on empty statement
            # TODO this does not take into account comments,
            #      hence it is "semi" validating
            statement = text[prev_stmt_idx : i + 1].strip()  # noqa: E203
            if len(statement) == 0 or statement == separator:
                message = (
                    f"Error at line {line_no}: empty statement ({stmt_count=}, {i=})"
                )
                raise exc.DParsingError(message)

            # yield the statement and prep for next iteration
            yield statement
            stmt_count = stmt_count + 1
            prev_stmt_idx = i + 1

    # sanity check
    if in_comment:
        message = f"Error at line {line_no}: unterminated comment (expected to see: */)"
        raise exc.DParsingError(message)

    if in_string:
        message = f"Error at line {line_no}: unterminated string (expected to see: ')"
        raise exc.DParsingError(message)

    # if - at the end - we got unprocessed characters, yield last statement
    try:
        statement = text[prev_stmt_idx:].strip()
        if len(statement) > 0:
            yield statement
    except IndexError:
        pass
