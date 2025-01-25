import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from loguru import logger

from dblocks_core import exc
from dblocks_core.git import git


def get_environ(key: str) -> str | None:
    try:
        return os.environ[key]
    except KeyError:
        return None


def test_git():
    if get_environ("TEST_GIT") is None:
        logger.warning("skip the test, set TEST_GIT=1")
        return

    with TemporaryDirectory(suffix="gittst") as tmpdir:

        # init the repo
        logger.info(f"tmpdir: {tmpdir}")
        repo = git.Repo(tmpdir)
        rslt = repo.init()
        assert (repo.repo_dir / ".git" / "config").is_file()
        assert rslt.code == 0

        # checkout develop branch
        with pytest.raises(exc.DGitCommandError):
            rslt = repo.checkout("develop")

        rslt = repo.checkout("develop", missing_ok=True)
        assert rslt.code == 0
        assert repo.is_clean() is True

        # create a file
        datfile = repo.repo_dir / "data.txt"
        datfile.write_text("test data")
        assert datfile.is_file()
        assert repo.is_clean() is False

        # add the file
        rslt = repo.add([datfile])
        assert rslt[0].code == 0
        assert rslt[0].out == ""

        # commit the file
        assert repo.is_clean() is False
        rslt = repo.commit("test commit")
        assert rslt.code == 0
        assert rslt.out == "A  data.txt\n"
        assert rslt.err == ""
