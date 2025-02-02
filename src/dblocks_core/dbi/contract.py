from abc import ABC, abstractmethod

from dblocks_core.model import meta_model


class AbstractDBI(ABC):

    @abstractmethod
    def get_described_object(
        self,
        object: meta_model.IdentifiedObject,
    ) -> meta_model.DescribedObject | None:
        """Returns full definition of the object in database. None if the object does not exist."""

    @abstractmethod
    def get_object_list(
        self,
        database_name: str,
        *,
        limit_to_type: str | None = None,
    ) -> list[meta_model.IdentifiedObject]:
        """Returns list of objects in a database."""
        ...

    @abstractmethod
    def delete_database(self, database_name: str):
        """Drops all objects from a database. The operation is not recursive."""
        ...

    @abstractmethod
    def drop_identified_object(
        self,
        obj: meta_model.IdentifiedObject,
        *,
        ignore_errors: bool = True,
    ):
        """Drops the object."""
        ...

    @abstractmethod
    def rename_identified_object(
        self,
        obj: meta_model.IdentifiedObject,
        new_name: str,
        *,
        ignore_errors: bool = False,
    ):
        """Renames the object."""
        ...

    @abstractmethod
    def get_identified_object(
        self,
        database_name: str,
        object_name: str,
    ) -> meta_model.IdentifiedObject | None:
        """Returns basic metadata about object in a database."""
        ...

    @abstractmethod
    def get_object_ddl(
        self,
        database_name: str,
        object_name: str,
        object_type: str,
    ) -> str:
        """
        Returns definition of the object (DDL script)

        Args:
            database_name (str): name of the database
            object_name (str): name of the object
            object_type (str): type of the object,
                must be one of meta_model.OBJECT_TYPES

        Returns:
            str: the definition as string
        """
        ...

    @abstractmethod
    def get_object_comment(
        self,
        database_name: str,
        object_identification: str,
        *,
        object_type: str,
    ) -> str | None:
        """
        Returns comment of the object.

        Args:
            database_name (str): name of the database
            object_identification (str): identification of the object
                - for tables: name of the table
                - for columns: name of the table, dot,
                    name of the column ("table.column")
            object_type (str | None, optional): type of the object (table, column, etc)
                - must be one of the meta_model.OBJECT_TYPE

        Returns:
            str: _description_
        """
        ...

    @abstractmethod
    def get_object_details(
        self,
        database_name: str,
        object_identification: str,
        *,
        object_type: str,
    ) -> meta_model.ObjectDetails:
        """
        Returns details about the objects, such as:
        - definition of statistics
        - column comments
        - ...

        Args:
            database_name (str): name of the database
            object_identification (str): identification of the object
                - for tables: name of the table
                - for columns: name of th etable, dot,
                    name of the column ("table.column")
            object_type (str | None, optional): type of the object (table, column, etc)
                - must be one of the meta_model.OBJECT_TYPE

        Returns:
            str: _description_
        """
        ...

    @abstractmethod
    def get_databases(self) -> list[meta_model.DescribedDatabase]:
        """
        Returns information about databases existing in the platform,
        regardless of the environment.
        Does NOT provide values for env_database_name

        Returns:
            list[meta_model.DescribedDatabase]: list of databases
        """
        ...

    @abstractmethod
    def deploy_statements(self, statements: list[str]):
        """
        Executes the statement given

        Args:
            statement (str): _description_
        """

    @abstractmethod
    def test_connection(self): ...

    @abstractmethod
    def dispose(self):
        """
        Dispose of the engine (self.engine.dispose())
        """
        ...

    @abstractmethod
    def change_database(self, database_name: str):
        """
        Change default database
        """
        ...
