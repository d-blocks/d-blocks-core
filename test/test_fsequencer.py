from pathlib import Path

from dblocks_core.deployer import fsequencer

fixtures_dir = Path(__file__).parent / "fixtures" / "fsequencer" / "db"


def test_sequencer1():
    batch = fsequencer.create_batch(root_dir=fixtures_dir)
    expected_batch = fsequencer.DeploymentBatch(
        root_dir=Path("/home/jan/d-blocks/d-blocks-core/test/fixtures/fsequencer/db"),
        steps=[
            fsequencer.DeploymentStep(
                name="10-step1",
                location=Path(
                    "/home/jan/d-blocks/d-blocks-core/test/fixtures/fsequencer/db/10-step1"
                ),
                files=[
                    fsequencer.DeploymentFile(
                        default_db=None,
                        file=Path(
                            "/home/jan/d-blocks/d-blocks-core/test/fixtures/fsequencer/db/10-step1/1.tab"
                        ),
                    ),
                    fsequencer.DeploymentFile(
                        default_db=None,
                        file=Path(
                            "/home/jan/d-blocks/d-blocks-core/test/fixtures/fsequencer/db/10-step1/2.sql"
                        ),
                    ),
                ],
            ),
            fsequencer.DeploymentStep(
                name="20-step2",
                location=Path(
                    "/home/jan/d-blocks/d-blocks-core/test/fixtures/fsequencer/db/20-step2"
                ),
                files=[
                    fsequencer.DeploymentFile(
                        default_db="db1",
                        file=Path(
                            "/home/jan/d-blocks/d-blocks-core/test/fixtures/fsequencer/db/20-step2/db1/1.tab"
                        ),
                    ),
                    fsequencer.DeploymentFile(
                        default_db="db2",
                        file=Path(
                            "/home/jan/d-blocks/d-blocks-core/test/fixtures/fsequencer/db/20-step2/db2/1.tab"
                        ),
                    ),
                ],
            ),
        ],
    )

    assert len(batch.steps) == len(expected_batch.steps)
    assert batch.root_dir == expected_batch.root_dir

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
