from abc import ABC, abstractmethod
from typing import Iterable

from dblocks_core.model import meta_model


class AbstractWriter(ABC):
    @abstractmethod
    def drop_nonex_objects(
        self,
        existing_objects: Iterable[meta_model.IdentifiedObject],
        tagged_databases: Iterable[meta_model.DescribedDatabase],
        *,
        databases_in_scope: Iterable[meta_model.DescribedDatabase],
    ):
        """Deletes objects that no longer exists.

        Args:
            existing_objects (Iterable[meta_model.IdentifiedObject]): list of
                all objects that exist
        """
        ...

    @abstractmethod
    def write_databases(
        self,
        databases: list[meta_model.DescribedDatabase],
        *,
        env_name: str,
    ):
        """Writes list of databases.

        Args:
            databases (list[meta_model.DescribedDatabase]): list of databases
        """
        ...

    @abstractmethod
    def write_object(
        self,
        obj: meta_model.DescribedObject,
        *,
        database_tag: str,
        parent_tags_in_scope: list[str] | None = None,
    ):
        """Stores object in the repository.

        Args:
            object (meta_model.DescribedObject): the object in question
        """
        ...
