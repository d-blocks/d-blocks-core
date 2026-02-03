"""
Workflow for destroying environment definitions (databases, users, roles, profiles)
from Teradata database based on TOML configuration files.
"""

import sys
if sys.version_info < (3, 11):
    import tomli as tomllib
else:
    import tomllib

from pathlib import Path
from typing import Any

from rich.console import Console
from rich.prompt import Prompt

from dblocks_core import exc, tagger
from dblocks_core.config.config import logger
from dblocks_core.context import Context
from dblocks_core.dbi import AbstractDBI
from dblocks_core.model import config_model

console = Console()


def _should_destroy_for_env(obj_data: dict[str, Any], env_name: str) -> bool:
    """
    Check if object should be destroyed for given environment based on only_in/not_only_in.
    
    Args:
        obj_data: Object data dictionary
        env_name: Target environment name
        
    Returns:
        True if object should be destroyed, False otherwise
    """
    only_in = obj_data.get("only_in", None)
    not_only_in = obj_data.get("not_only_in", None)
    
    if only_in is not None and env_name not in only_in:
        return False
        
    if not_only_in is not None and env_name in not_only_in:
        return False
        
    return True


def _load_toml_file(filepath: Path) -> dict[str, Any]:
    """
    Load TOML file and return data.
    
    Args:
        filepath: Path to TOML file
        
    Returns:
        Dictionary with data
    """
    with open(filepath, "rb") as f:
        return tomllib.load(f)


def _expand_variables(data: dict[str, Any], tgr: tagger.Tagger) -> dict[str, Any]:
    """
    Recursively expand variables in dictionary values using tagger.
    
    Args:
        data: Dictionary with potential {{variable}} placeholders
        tgr: Tagger instance for variable expansion
        
    Returns:
        Dictionary with expanded values
    """
    expanded = {}
    for key, value in data.items():
        if isinstance(value, str):
            expanded[key] = tgr.expand_statement(value)
        elif isinstance(value, list):
            expanded[key] = [
                tgr.expand_statement(item) if isinstance(item, str) else item
                for item in value
            ]
        elif isinstance(value, dict):
            expanded[key] = _expand_variables(value, tgr)
        else:
            expanded[key] = value
    return expanded


def _check_database_exists(name: str, ext: AbstractDBI) -> bool:
    """
    Check if a database or user exists.
    
    Args:
        name: Database or user name
        ext: Database interface
        
    Returns:
        True if exists, False otherwise
    """
    try:
        # Use get_identified_object_for_db which queries DBC.DatabasesV
        obj = ext.get_identified_object_for_db(name)
        exists = obj is not None
        logger.debug(f"Checking if database exists: {name} --> {exists}")
        return exists
    except Exception as e:
        logger.debug(f"Database {name} does not exist: {e}")
        return False


def _check_role_exists(name: str, ext: AbstractDBI) -> bool:
    """
    Check if a role exists.
    
    Args:
        name: Role name
        ext: Database interface
        
    Returns:
        True if exists, False otherwise
    """
    try:
        # Use get_identified_object_for_role which queries DBC.RoleInfoV
        obj = ext.get_identified_object_for_role(name)
        exists = obj is not None
        logger.debug(f"Checking if role exists: {name} --> {exists}")
        return exists
    except Exception as e:
        logger.debug(f"Role {name} does not exist: {e}")
        return False


def _check_profile_exists(name: str, ext: AbstractDBI) -> bool:
    """
    Check if a profile exists.
    
    Args:
        name: Profile name
        ext: Database interface
        
    Returns:
        True if exists, False otherwise
    """
    try:
        # Use get_identified_object_for_profile which queries DBC.ProfileInfoV
        obj = ext.get_identified_object_for_profile(name)
        exists = obj is not None
        logger.debug(f"Checking if profile exists: {name} --> {exists}")
        return exists
    except Exception as e:
        logger.debug(f"Profile {name} does not exist: {e}")
        return False


def _build_dependency_tree(
    database_files: list[Path],
    user_files: list[Path],
    tgr: tagger.Tagger,
    env_name: str,
) -> tuple[list[tuple[str, str, Path]], dict[str, list[str]]]:
    """
    Build dependency tree for databases and users based on ownership.
    
    Args:
        database_files: List of database TOML files
        user_files: List of user TOML files
        tgr: Tagger for variable expansion
        env_name: Target environment name
        
    Returns:
        Tuple of (objects_list, dependency_graph)
        - objects_list: List of (name, type, filepath) tuples
        - dependency_graph: Dict mapping object name to list of its children
    """
    objects = []  # List of (name, type, filepath)
    dependency_graph = {}  # parent_name -> [child_names]
    
    # Process databases
    for filepath in database_files:
        data = _load_toml_file(filepath)
        data = _expand_variables(data, tgr)
        
        if not _should_destroy_for_env(data, env_name):
            continue
            
        name = data["name"]
        owner = data.get("owner")
        
        objects.append((name, "database", filepath))
        
        # Track ownership (child -> parent relationship, but we store parent -> children)
        if owner:
            if owner not in dependency_graph:
                dependency_graph[owner] = []
            dependency_graph[owner].append(name)
    
    # Process users
    for filepath in user_files:
        data = _load_toml_file(filepath)
        data = _expand_variables(data, tgr)
        
        if not _should_destroy_for_env(data, env_name):
            continue
            
        name = data["name"]
        owner = data.get("owner")
        
        objects.append((name, "user", filepath))
        
        # Track ownership
        if owner:
            if owner not in dependency_graph:
                dependency_graph[owner] = []
            dependency_graph[owner].append(name)
    
    return objects, dependency_graph


def _topological_sort_for_deletion(
    objects: list[tuple[str, str, Path]],
    dependency_graph: dict[str, list[str]],
) -> list[tuple[str, str, Path]]:
    """
    Sort objects for deletion - children first, then parents.
    
    Args:
        objects: List of (name, type, filepath) tuples
        dependency_graph: Dict mapping parent to list of children
        
    Returns:
        Sorted list of objects (children before parents)
    """
    # Build reverse mapping: child -> parent
    child_to_parent = {}
    for parent, children in dependency_graph.items():
        for child in children:
            child_to_parent[child] = parent
    
    # Calculate depth for each object (leaf nodes have depth 0)
    def get_depth(name: str, visited: set[str] = None) -> int:
        if visited is None:
            visited = set()
        if name in visited:
            # Circular dependency, treat as depth 0
            return 0
        visited.add(name)
        
        children = dependency_graph.get(name, [])
        if not children:
            return 0
        return 1 + max(get_depth(child, visited.copy()) for child in children)
    
    # Sort by depth ascending (shallowest/children first, deepest/parents last)
    object_depths = [(obj, get_depth(obj[0])) for obj in objects]
    sorted_objects = sorted(object_depths, key=lambda x: x[1], reverse=False)
    
    return [obj for obj, _ in sorted_objects]


def _destroy_single_database_or_user(
    name: str,
    obj_type: str,
    ext: AbstractDBI,
    dry_run: bool,
) -> tuple[bool, str | None]:
    """
    Destroy a single database or user.
    
    For Teradata:
    1. DELETE DATABASE/USER removes all objects within it
    2. DROP DATABASE/USER removes the database/user itself
    
    Args:
        name: Database or user name
        obj_type: "database" or "user"
        ext: Database interface
        dry_run: Dry run mode
        
    Returns:
        (success, error_message)
    """
    try:
        # Check if object exists
        if not _check_database_exists(name, ext):
            logger.info(f"{obj_type.capitalize()} {name} does not exist, skipping")
            return (True, None)
        
        statements = []
        
        # Step 1: DELETE to remove all objects within the database/user
        if obj_type == "user":
            statements.append(f'DELETE USER "{name}";')
        else:
            statements.append(f'DELETE DATABASE "{name}";')
        
        # Step 2: DROP to remove the database/user itself
        if obj_type == "user":
            statements.append(f'DROP USER "{name}";')
        else:
            statements.append(f'DROP DATABASE "{name}";')
        
        if dry_run:
            logger.info(f"[DRY-RUN] Would execute:\n" + "\n".join(statements))
        else:
            logger.info(f"Destroying {obj_type}: {name}")
            ext.deploy_statements(statements)
        
        return (True, None)
    except Exception as e:
        logger.error(f"Failed to destroy {obj_type} {name}: {e}")
        return (False, str(e))


def _destroy_single_role(
    name: str,
    ext: AbstractDBI,
    dry_run: bool,
) -> tuple[bool, str | None]:
    """
    Destroy a single role.
    
    Args:
        name: Role name
        ext: Database interface
        dry_run: Dry run mode
        
    Returns:
        (success, error_message)
    """
    try:
        # Check if role exists
        if not _check_role_exists(name, ext):
            logger.info(f"Role {name} does not exist, skipping")
            return (True, None)
        
        statement = f'DROP ROLE "{name}";'
        
        if dry_run:
            logger.info(f"[DRY-RUN] Would execute: {statement}")
        else:
            logger.info(f"Destroying role: {name}")
            ext.deploy_statements([statement])
        
        return (True, None)
    except Exception as e:
        logger.error(f"Failed to destroy role {name}: {e}")
        return (False, str(e))


def _destroy_single_profile(
    name: str,
    ext: AbstractDBI,
    dry_run: bool,
) -> tuple[bool, str | None]:
    """
    Destroy a single profile.
    
    Args:
        name: Profile name
        ext: Database interface
        dry_run: Dry run mode
        
    Returns:
        (success, error_message)
    """
    try:
        # Check if profile exists
        if not _check_profile_exists(name, ext):
            logger.info(f"Profile {name} does not exist, skipping")
            return (True, None)
        
        statement = f'DROP PROFILE "{name}";'
        
        if dry_run:
            logger.info(f"[DRY-RUN] Would execute: {statement}")
        else:
            logger.info(f"Destroying profile: {name}")
            ext.deploy_statements([statement])
        
        return (True, None)
    except Exception as e:
        logger.error(f"Failed to destroy profile {name}: {e}")
        return (False, str(e))


def _confirm_destruction(
    environment: str,
    deploy_dir: Path,
    total_objects: int,
    assume_yes: bool,
):
    """
    Confirm destruction with user.
    
    Args:
        environment: Target environment name
        deploy_dir: Deployment directory
        total_objects: Total number of objects to destroy
        assume_yes: Skip confirmation
    """
    if assume_yes:
        return
    
    console.print("\n[bold red]DESTRUCTION CONFIRMATION[/bold red]")
    console.print(f"Environment: [bold]{environment}[/bold]")
    console.print(f"Source directory: {deploy_dir}")
    console.print(f"Total objects to destroy: [bold red]{total_objects}[/bold red]")
    console.print("\n[bold yellow]WARNING: This will permanently delete all specified objects![/bold yellow]")
    
    answer = Prompt.ask(
        "\n[bold]Are you ABSOLUTELY sure you want to proceed?[/bold]",
        choices=["yes", "no"],
        default="no"
    )
    
    if answer.lower() != "yes":
        raise exc.DOperationsError("Destruction cancelled by user")


def destroy_env_def(
    deploy_dir: Path,
    *,
    cfg: config_model.Config,
    env: config_model.EnvironParameters,
    env_name: str,
    ctx: Context,
    ext: AbstractDBI,
    assume_yes: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Destroy environment definitions from Teradata based on TOML configuration files.
    
    This function removes databases, users, roles, and profiles in the correct order:
    1. Child databases/users (based on ownership hierarchy)
    2. Parent databases/users
    3. Roles
    4. Profiles
    
    For databases and users, it performs:
    1. DELETE DATABASE/USER (removes all objects within)
    2. DROP DATABASE/USER (removes the database/user itself)
    
    Args:
        deploy_dir: Directory containing TOML definition files
        cfg: Configuration
        env: Environment parameters
        env_name: Target environment name
        ctx: Context
        ext: Database interface
        assume_yes: Skip confirmations
        dry_run: Don't actually execute, just show what would be done
        
    Returns:
        Dictionary with destruction results
    """
    logger.info(f"Starting environment definition destruction for: {env_name}")
    logger.info(f"Source directory: {deploy_dir}")
    
    # Initialize tagger for variable expansion (needed for detagging)
    tgr = tagger.Tagger(
        variables=env.tagging_variables,
        rules=env.tagging_rules,
        tagging_strip_db_with_no_rules=env.tagging_strip_db_with_no_rules,
    )
    
    # Collect all TOML files
    profiles_dir = deploy_dir / "profiles"
    roles_dir = deploy_dir / "roles"
    databases_dir = deploy_dir / "databases"
    users_dir = deploy_dir / "users"
    
    profile_files = list(profiles_dir.glob("*.toml")) if profiles_dir.exists() else []
    role_files = list(roles_dir.glob("*.toml")) if roles_dir.exists() else []
    database_files = list(databases_dir.glob("*.toml")) if databases_dir.exists() else []
    user_files = list(users_dir.glob("*.toml")) if users_dir.exists() else []
    
    total_objects = len(profile_files) + len(role_files) + len(database_files) + len(user_files)
    
    # Confirm destruction
    _confirm_destruction(
        environment=env_name,
        deploy_dir=deploy_dir,
        total_objects=total_objects,
        assume_yes=assume_yes,
    )
    
    results = {
        "destroyed": [],
        "skipped": [],
        "failed": [],
    }
    
    # Destruction order (reverse of deployment):
    # 1. Child databases/users first (based on ownership hierarchy)
    # 2. Parent databases/users
    # 3. Roles
    # 4. Profiles
    
    # Build dependency tree and sort for deletion (children first)
    db_user_objects, dependency_graph = _build_dependency_tree(
        database_files, user_files, tgr, env_name
    )
    sorted_db_user_objects = _topological_sort_for_deletion(db_user_objects, dependency_graph)
    
    # 1-2. Destroy databases and users in correct order (children first)
    logger.info(f"Destroying {len(sorted_db_user_objects)} databases/users...")
    for name, obj_type, filepath in sorted_db_user_objects:
        success, error = _destroy_single_database_or_user(name, obj_type, ext, dry_run)
        
        if success:
            results["destroyed"].append({"type": obj_type, "name": name})
        else:
            results["failed"].append({"type": obj_type, "name": name, "error": error})
    
    # 3. Destroy roles
    logger.info(f"Destroying {len(role_files)} roles...")
    for filepath in role_files:
        try:
            data = _load_toml_file(filepath)
            data = _expand_variables(data, tgr)
            
            if not _should_destroy_for_env(data, env_name):
                logger.info(f"Skipping role {data['name']} (overlay filter)")
                results["skipped"].append({"type": "role", "name": data["name"]})
                continue
            
            role_name = data["name"]
            success, error = _destroy_single_role(role_name, ext, dry_run)
            
            if success:
                results["destroyed"].append({"type": "role", "name": role_name})
            else:
                results["failed"].append({"type": "role", "name": role_name, "error": error})
        except Exception as e:
            logger.error(f"Failed to process role from {filepath}: {e}")
            results["failed"].append({"type": "role", "file": str(filepath), "error": str(e)})
    
    # 4. Destroy profiles
    logger.info(f"Destroying {len(profile_files)} profiles...")
    for filepath in profile_files:
        try:
            data = _load_toml_file(filepath)
            data = _expand_variables(data, tgr)
            
            if not _should_destroy_for_env(data, env_name):
                logger.info(f"Skipping profile {data['name']} (overlay filter)")
                results["skipped"].append({"type": "profile", "name": data["name"]})
                continue
            
            profile_name = data["name"]
            success, error = _destroy_single_profile(profile_name, ext, dry_run)
            
            if success:
                results["destroyed"].append({"type": "profile", "name": profile_name})
            else:
                results["failed"].append({"type": "profile", "name": profile_name, "error": error})
        except Exception as e:
            logger.error(f"Failed to process profile from {filepath}: {e}")
            results["failed"].append({"type": "profile", "file": str(filepath), "error": str(e)})
    
    # Summary
    logger.info("\n[bold red]Destruction Summary[/bold red]")
    logger.info(f"Destroyed: {len(results['destroyed'])}")
    logger.info(f"Skipped: {len(results['skipped'])}")
    logger.info(f"Failed: {len(results['failed'])}")
    
    if results["failed"]:
        logger.warning("Some objects failed to be destroyed. Check logs for details.")
    
    return results
