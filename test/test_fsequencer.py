from pathlib import Path

from dblocks_core.deployer import fsequencer
from dblocks_core.model import meta_model

fixtures_dir = Path(__file__).parent / "fixtures" / "fsequencer" / "db"


def test_sequencer1():
    batch = fsequencer.create_batch(root_dir=fixtures_dir)
    expected_batch = fsequencer.DeploymentBatch(
        root_dir=fixtures_dir,
        steps=[
            fsequencer.DeploymentStep(
                name="10-step1",
                location=fixtures_dir / "10-step1",
                files=[
                    fsequencer.DeploymentFile(
                        default_db=None,
                        file=fixtures_dir / "10-step1/1.tab",
                        file_type=meta_model.TABLE,
                    ),
                    fsequencer.DeploymentFile(
                        default_db=None,
                        file=fixtures_dir / "10-step1/2.sql",
                        file_type=meta_model.GENERIC_SQL,
                    ),
                ],
            ),
            fsequencer.DeploymentStep(
                name="20-step2",
                location=fixtures_dir / "20-step2",
                files=[
                    fsequencer.DeploymentFile(
                        default_db=None,
                        file=fixtures_dir / "20-step2/x-at-the-end.viw",
                        file_type=meta_model.VIEW,
                    ),
                    fsequencer.DeploymentFile(
                        default_db="db1",
                        file=fixtures_dir / "20-step2/db1/1.tab",
                        file_type=meta_model.TABLE,
                    ),
                    fsequencer.DeploymentFile(
                        default_db="db2",
                        file=fixtures_dir / "20-step2/db2/1.tab",
                        file_type=meta_model.TABLE,
                    ),
                ],
            ),
        ],
    )

    assert len(batch.steps) == len(expected_batch.steps)
    assert batch.root_dir == expected_batch.root_dir
    assert batch == expected_batch

    for i, eb in enumerate(expected_batch.steps):
        assert (
            eb.name == batch.steps[i].name
        ), f"{i=}: {eb.name=}, {batch.steps[i].name=}"
        print(i)
        print(eb.files)
        print(batch.steps[i].files)
        print("------------------------")

    stmts = list(batch.steps[0].files[0].statements())
    assert stmts == []

    stmts = list(batch.steps[0].files[1].statements())
    es = [
        fsequencer.DeploymentStatement(sql="select 1;"),
        fsequencer.DeploymentStatement(sql="select 2;"),
        fsequencer.DeploymentStatement(sql="select 3"),
    ]
    assert stmts == es
