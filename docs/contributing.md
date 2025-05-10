# Contribution guide

Development of this package uses the following tools:

- [poetry](https://pypi.org/project/poetry/)
- [poetry-dynamic-versioning](https://pypi.org/project/poetry-dynamic-versioning/)


The simplest way how to start is to prepare your environment in the following fashion:

- [install pipx](https://github.com/pypa/pipx?tab=readme-ov-file#on-windows)
- install poetry using pipx: `pipx install poetry`
- inject the poetry-dynamic-versioning plugin to the poetry environment: `poetry self add "poetry-dynamic-versioning[plugin]"`

Releases poetry self add "poetry-dynamic-versioning[plugin]"Each release is tagged using notation : `vA.B.C.D` - in the future, we plan to use semver standard to it's full extent, however, at this stage, `d-blocks` is too young, therefore we are reluctant to say that we follow it fully.