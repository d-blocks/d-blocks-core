from collections import namedtuple
from pathlib import Path

import pytest
from loguru import logger

from dblocks_core.script.workflow import cmd_git_copy_changed
from dblocks_core.writer import fsystem


def test_path_in_package():
    repo_dir_absp = Path.cwd() / "repo"
    metadata_dir_absp = repo_dir_absp / "meta"
    steps_subdir = Path("DB/Teradata")

    Test = namedtuple("Test", "name,src,tgt,subdir_list")
    tests = [
        Test(
            name="in metadata dir",
            src=Path(metadata_dir_absp / "DATABASE/table.tab"),
            tgt=steps_subdir / fsystem.STP_TABLES / "DATABASE/table.tab",
            subdir_list=None,
        ),
        Test(
            name="outside metadata dir",
            src=Path(repo_dir_absp / "out" / "DATABASE/table.tab"),
            tgt=Path("out") / "DATABASE/table.tab",
            subdir_list=None,
        ),
        Test(
            name="outside metadata dir with filter",
            src=Path(repo_dir_absp / "out" / "DATABASE/table.tab"),
            tgt=Path("DATABASE/table.tab"),
            subdir_list=["out"],
        ),
        Test(
            name="outside metadata dir with filter 2",
            src=Path(repo_dir_absp / "out" / "DATABASE/table.tab"),
            tgt=Path("DATABASE/table.tab"),
            subdir_list=["in", "out"],
        ),
        Test(
            name="outside metadata dir with filter 3",
            src=Path(repo_dir_absp / "out" / "DATABASE/table.tab"),
            tgt=Path("out/DATABASE/table.tab"),
            subdir_list=["different_dir"],
        ),
    ]

    for tst in tests:
        got = cmd_git_copy_changed._rel_path_in_package(
            repo_dir_absp=repo_dir_absp,
            src_file_absp=tst.src,
            metadata_dir_absp=metadata_dir_absp,
            steps_subdir=steps_subdir,
            subdir_list=tst.subdir_list,
        )
        assert (
            got == tst.tgt
        ), f"\nname  : {tst.name}\ngot   : {got}\nwanted: {tst.tgt}\n"
