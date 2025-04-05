from pathlib import Path

import pytest
from loguru import logger

from dblocks_core import exc
from dblocks_core.deployer import tokenizer

fixtures_dir = Path(__file__).parent / "fixtures" / "tokenizer"

TRG = """
REPLACE TRIGGER
(
    INSERT INTO {{env}}_stg_t.xxx (
        
    )
    VALUES (
        OLD_ROW.ACCOUNT_ID,
        'UPDATE',
    );
)
;
"""


def test_tokenizer_stats():
    sql = """
COLLECT STATISTICS 
                   -- default SYSTEM SAMPLE PERCENT 
                   -- default SYSTEM THRESHOLD PERCENT 
            COLUMN ( PARTITION ) , 
            COLUMN ( load_dttm ) 
                ON a_tab
;

COLLECT STATISTICS 
             USING SAMPLE 10.00 PERCENT 
                   -- default SYSTEM THRESHOLD PERCENT 
            COLUMN ( a_col ) 
                ON a_tab 
;
"""
    statements = [s.statement for s in tokenizer.tokenize_statements(sql)]
    assert len(statements) == 2

    test_file = fixtures_dir / "stats.tab"
    test_content = test_file.read_text(encoding="utf-8")
    statements = [s.statement for s in tokenizer.tokenize_statements(test_content)]
    assert len(statements) == 3
    print(statements[1])


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
            statements = [s.statement for s in tokenizer.tokenize_statements(inp)]
            assert statements == []

    # works with valid inputs
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
        [
            "select ( ; )",
            ["select ( ; )"],
        ],
        [
            "select ( ; ) ';' ; a;",
            ["select ( ; ) ';' ;", "a;"],
        ],
        [TRG, [TRG.strip()]],
    ]
    for i, (inp, expected) in enumerate(inputs):
        logger.debug(inp)
        statements = [s.statement for s in tokenizer.tokenize_statements(inp)]
        assert len(statements) == len(expected)
        assert statements == expected, f"at test {i}"
        # for i, stmt in enumerate(statements):
        #     print(stmt)
        #     print(expected[i])
