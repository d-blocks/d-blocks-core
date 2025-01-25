import pytest
from loguru import logger

from dblocks_core import exc
from dblocks_core.deployer import tokenizer


def test_tokenizer():
    # we should throw on invalid input
    inputs = (
        " ; ",
        " /* ",
        " */ ",
        " ' ",
    )
    for inp in inputs:
        with pytest.raises(exc.DParsingError):
            # tokenizer is a generator hence we need to do "next" on it
            statements = [s for s in tokenizer.tokenize_statemets(inp)]
            assert statements == []

    # works withh valid inputs
    inputs = [
        [
            "1 ; 2; 3",
            ["1 ;", "2;", "3"],
        ],
        [
            "1;2 /* cmt */\n/*cmt*/;3",
            ["1;", "2 /* cmt */\n/*cmt*/;", "3"],
        ],
        [
            "select ';'",
            [
                "select ';'",
            ],
        ],
        [
            "select '/*;' /* ;' */\n;select another thing; ",
            [
                "select '/*;' /* ;' */\n;",
                "select another thing;",
            ],
        ],
    ]
    for i, (inp, expected) in enumerate(inputs):
        logger.debug(inp)
        statements = [s for s in tokenizer.tokenize_statemets(inp)]
        assert statements == expected, f"at test {i}"
