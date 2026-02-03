"""
Workflow for deploying environment definitions (databases, users, roles, profiles, privileges)
from TOML configuration files to Teradata database.
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
from rich.table import Table

from dblocks_core import exc, tagger
from dblocks_core.config.config import logger
from dblocks_core.context import Context
from dblocks_core.dbi import AbstractDBI
from dblocks_core.model import config_model

# Deployment strategies
RAISE_STRATEGY = "raise"
DROP_STRATEGY = "drop"
SKIP_STRATEGY = "skip"
IGNORE_STRATEGY = "ignore"

_DEPLOYMENT_STRATEGIES = [DROP_STRATEGY, RAISE_STRATEGY, IGNORE_STRATEGY, SKIP_STRATEGY]

console = Console()


def _build_space_dependency_tree(
    database_files: list[Path],
    user_files: list[Path],
    env_name: str,
    tgr: tagger.Tagger,
) -> tuple[dict[str, list[str]], dict[str, dict[str, Any]]]:
    """
    Build dependency tree for space calculation.
    
    Returns parent->children mapping and object data mapping.
    
    Args:
        database_files: List of database TOML files
        user_files: List of user TOML files
        env_name: Environment name for filtering
        tgr: Tagger for variable expansion
        
    Returns:
        Tuple of (parent_to_children_map, object_data_map)
        - parent_to_children_map: Dict mapping parent name to list of children names
        - object_data_map: Dict mapping object name to its data (owner, perm_space, etc.)
    """
    parent_to_children: dict[str, list[str]] = {}
    object_data_map: dict[str, dict[str, Any]] = {}
    
    # Process all databases and users
    all_files = [(f, "database") for f in database_files] + [(f, "user") for f in user_files]
    
    for filepath, obj_type in all_files:
        try:
            data = _load_toml_file(filepath)
            data = _expand_variables(data, tgr)
            
            # Skip objects not for this environment
            if not _should_deploy_for_env(data, env_name):
                continue
            
            name = data.get("name")
            owner = data.get("owner")
            
            if not name:
                logger.warning(f"Skipping {filepath} - no name defined")
                continue
            
            # Store object data
            object_data_map[name] = {
                "name": name,
                "owner": owner,
                "perm_space": data.get("perm_space"),
                "spool_space": data.get("spool_space"),
                "temp_space": data.get("temp_space"),
                "kind": data.get("kind", obj_type),
            }
            
            # Build parent->children mapping
            if owner:
                if owner not in parent_to_children:
                    parent_to_children[owner] = []
                parent_to_children[owner].append(name)
                
        except Exception as e:
            logger.warning(f"Failed to process {filepath} for space calculation: {e}")
    
    return parent_to_children, object_data_map


def _calculate_cumulative_space(
    parent_to_children: dict[str, list[str]],
    object_data_map: dict[str, dict[str, Any]],
) -> dict[str, dict[str, str]]:
    """
    Calculate cumulative space requirements for each database/user.
    
    When a child database/user is created, it "steals" space from its parent.
    Therefore, parent's space allocation must include all descendant space.
    
    Args:
        parent_to_children: Mapping of parent name to list of children names
        object_data_map: Mapping of object name to its data
        
    Returns:
        Dict mapping object name to cumulative space dict (perm_space, spool_space, temp_space)
    """
    cumulative_space: dict[str, dict[str, str]] = {}
    
    def calculate_recursive(obj_name: str) -> dict[str, int]:
        """
        Recursively calculate cumulative space for an object and all its descendants.
        
        Returns dict with perm_space, spool_space, temp_space as integers (bytes).
        """
        if obj_name in cumulative_space:
            # Already calculated - convert back to int for summing
            cached = cumulative_space[obj_name]
            return {
                "perm_space": _parse_space_to_bytes(cached.get("perm_space", "0")),
                "spool_space": _parse_space_to_bytes(cached.get("spool_space", "0")),
                "temp_space": _parse_space_to_bytes(cached.get("temp_space", "0")),
            }
        
        # Get own space
        obj_data = object_data_map.get(obj_name, {})
        own_perm = _parse_space_to_bytes(obj_data.get("perm_space", "0"))
        own_spool = _parse_space_to_bytes(obj_data.get("spool_space", "0"))
        own_temp = _parse_space_to_bytes(obj_data.get("temp_space", "0"))
        
        # Sum up children's space
        children = parent_to_children.get(obj_name, [])
        for child_name in children:
            child_space = calculate_recursive(child_name)
            own_perm += child_space["perm_space"]
            own_spool += child_space["spool_space"]
            own_temp += child_space["temp_space"]
        
        # Cache result (convert bytes back to string format)
        cumulative_space[obj_name] = {
            "perm_space": _format_bytes_to_space(own_perm),
            "spool_space": _format_bytes_to_space(own_spool),
            "temp_space": _format_bytes_to_space(own_temp),
        }
        
        return {
            "perm_space": own_perm,
            "spool_space": own_spool,
            "temp_space": own_temp,
        }
    
    # Calculate for all objects
    for obj_name in object_data_map.keys():
        if obj_name not in cumulative_space:
            calculate_recursive(obj_name)
    
    return cumulative_space


def _parse_space_to_bytes(space_str: str | None) -> int:
    """
    Parse space string to bytes.
    
    Examples: "100", "10e6", "1e9", "50M", "2G"
    
    Args:
        space_str: Space string (may include scientific notation or suffixes)
        
    Returns:
        Space in bytes as integer
    """
    if not space_str:
        return 0
    
    space_str = str(space_str).strip().upper()
    
    # Handle scientific notation (e.g., "1e9" or "10e6")
    if 'E' in space_str:
        try:
            return int(float(space_str))
        except ValueError:
            pass
    
    # Handle suffixes (K, M, G, T)
    multipliers = {
        'K': 1024,
        'M': 1024 * 1024,
        'G': 1024 * 1024 * 1024,
        'T': 1024 * 1024 * 1024 * 1024,
    }
    
    for suffix, multiplier in multipliers.items():
        if space_str.endswith(suffix):
            try:
                value = float(space_str[:-1])
                return int(value * multiplier)
            except ValueError:
                pass
    
    # No suffix - just parse as number
    try:
        return int(float(space_str))
    except ValueError:
        logger.warning(f"Failed to parse space value: {space_str}, using 0")
        return 0


def _format_bytes_to_space(bytes_val: int) -> str:
    """
    Format bytes back to space string (keeping original format as much as possible).
    
    For simplicity, we return plain byte count as string.
    
    Args:
        bytes_val: Space in bytes
        
    Returns:
        Space string
    """
    return str(bytes_val) if bytes_val > 0 else "0"


def _should_deploy_for_env(obj_data: dict[str, Any], env_name: str) -> bool:
    """
    Check if object should be deployed for given environment based on only_in/not_only_in.
    
    Args:
        obj_data: Object data dictionary
        env_name: Target environment name
        
    Returns:
        True if object should be deployed, False otherwise
    """
    only_in = obj_data.get("only_in", None)
    not_only_in = obj_data.get("not_only_in", None)
    
    if only_in is not None and env_name not in only_in:
        return False
        
    if not_only_in is not None and env_name in not_only_in:
        return False
        
    return True


def _generate_database_ddl(
    db_data: dict[str, Any],
    cumulative_space_map: dict[str, dict[str, str]] | None = None,
) -> list[str]:
    """
    Generate CREATE DATABASE DDL from configuration.
    
    Args:
        db_data: Database configuration data
        cumulative_space_map: Optional mapping of object names to cumulative space
            (includes space needed for all descendants)
        
    Returns:
        List of DDL statements
    """
    name = db_data["name"]
    owner = db_data["owner"]
    kind = db_data.get("kind", "database")
    
    if kind == "user":
        ddl = f'CREATE USER "{name}"'
    else:
        ddl = f'CREATE DATABASE "{name}"'
    
    ddl += f' FROM "{owner}"'
    
    # Add AS keyword only if there are space parameters
    as_params = []
    
    # Use cumulative space if available, otherwise use configured space
    if cumulative_space_map and name in cumulative_space_map:
        cumulative = cumulative_space_map[name]
        logger.debug(f"Using cumulative space for {name}: {cumulative}")
        
        # For PERM space: use cumulative if > 0, otherwise fallback to original config
        if perm_space := cumulative.get("perm_space"):
            if perm_space != "0":
                as_params.append(f"PERM = {perm_space}")
            elif perm_space_orig := db_data.get("perm_space"):
                # Cumulative is 0 but original config has value - use original
                as_params.append(f"PERM = {perm_space_orig}")
        elif perm_space_orig := db_data.get("perm_space"):
            # No cumulative but original exists - use original
            as_params.append(f"PERM = {perm_space_orig}")
        
        # For SPOOL space: use cumulative if > 0, otherwise fallback to original
        if spool_space := cumulative.get("spool_space"):
            if spool_space != "0":
                as_params.append(f"SPOOL = {spool_space}")
            elif spool_space_orig := db_data.get("spool_space"):
                # Cumulative is 0 but original config has value - use original
                as_params.append(f"SPOOL = {spool_space_orig}")
        elif spool_space_orig := db_data.get("spool_space"):
            # No cumulative but original exists - use original
            as_params.append(f"SPOOL = {spool_space_orig}")
        
        # TEMP is only valid for CREATE USER, not CREATE DATABASE
        if kind == "user":
            if temp_space := cumulative.get("temp_space"):
                if temp_space != "0":
                    as_params.append(f"TEMP = {temp_space}")
                elif temp_space_orig := db_data.get("temp_space"):
                    as_params.append(f"TEMP = {temp_space_orig}")
            elif temp_space_orig := db_data.get("temp_space"):
                as_params.append(f"TEMP = {temp_space_orig}")
    else:
        # Fallback to original space values
        if perm_space := db_data.get("perm_space"):
            as_params.append(f"PERM = {perm_space}")
        
        if spool_space := db_data.get("spool_space"):
            as_params.append(f"SPOOL = {spool_space}")
        
        # TEMP is only valid for CREATE USER, not CREATE DATABASE
        if kind == "user" and (temp_space := db_data.get("temp_space")):
            as_params.append(f"TEMP = {temp_space}")
    
    if as_params:
        ddl += " AS " + ", ".join(as_params)
    
    ddl += ";"
    
    statements = [ddl]
    
    # Add comment if present (as separate statement)
    if comment := db_data.get("comment"):
        comment_ddl = f'COMMENT ON DATABASE "{name}" IS \'{comment.replace("\'", "\'\'")}\';'
        statements.append(comment_ddl)
    
    return statements


def _generate_user_ddl(
    user_data: dict[str, Any],
    cumulative_space_map: dict[str, dict[str, str]] | None = None,
) -> list[str]:
    """
    Generate CREATE USER DDL from configuration.
    
    Args:
        user_data: User configuration data
        cumulative_space_map: Optional mapping of object names to cumulative space
            (includes space needed for all descendants)
        
    Returns:
        List of DDL statements
    """
    name = user_data["name"]
    owner = user_data["owner"]
    
    ddl = f'CREATE USER "{name}" FROM "{owner}"'
    
    # AS clause: Only PERM and PASSWORD belong here
    as_params = []
    
    # Use cumulative space if available, otherwise use configured space
    if cumulative_space_map and name in cumulative_space_map:
        cumulative = cumulative_space_map[name]
        logger.debug(f"Using cumulative space for {name}: {cumulative}")
        
        # For PERM space: use cumulative if > 0, otherwise fallback to original config
        if perm_space := cumulative.get("perm_space"):
            if perm_space != "0":
                as_params.append(f"PERM = {perm_space}")
            elif perm_space_orig := user_data.get("perm_space"):
                # Cumulative is 0 but original config has value - use original
                as_params.append(f"PERM = {perm_space_orig}")
        elif perm_space_orig := user_data.get("perm_space"):
            # No cumulative but original exists - use original
            as_params.append(f"PERM = {perm_space_orig}")
    else:
        # Fallback to original space value
        if perm_space := user_data.get("perm_space"):
            as_params.append(f"PERM = {perm_space}")
    
    # Password is required for CREATE USER
    # If redacted, use username as temporary password
    password = user_data.get("password", "<REDACTED>")
    if password == "<REDACTED>":
        # Use username as temporary password - user must change it after first login
        as_params.append(f'PASSWORD = "{name}"')
        logger.warning(f"User {name} created with username as temporary password - MUST BE CHANGED!")
    else:
        as_params.append(f'PASSWORD = "{password}"')
    
    # Add AS clause if there are parameters
    if as_params:
        ddl += " AS " + ", ".join(as_params)
    
    # User attributes come after AS clause (or after FROM if no AS clause)
    # These are: SPOOL, TEMPORARY, DEFAULT DATABASE, PROFILE, ACCOUNT, etc.
    user_attrs = []
    
    # Use cumulative space if available for SPOOL and TEMP
    if cumulative_space_map and name in cumulative_space_map:
        cumulative = cumulative_space_map[name]
        
        # For SPOOL space: use cumulative if > 0, otherwise fallback to original
        if spool_space := cumulative.get("spool_space"):
            if spool_space != "0":
                user_attrs.append(f"SPOOL = {spool_space}")
            elif spool_space_orig := user_data.get("spool_space"):
                user_attrs.append(f"SPOOL = {spool_space_orig}")
        elif spool_space_orig := user_data.get("spool_space"):
            user_attrs.append(f"SPOOL = {spool_space_orig}")
        
        # For TEMP space: use cumulative if > 0, otherwise fallback to original
        if temp_space := cumulative.get("temp_space"):
            if temp_space != "0":
                user_attrs.append(f"TEMPORARY = {temp_space}")
            elif temp_space_orig := user_data.get("temp_space"):
                user_attrs.append(f"TEMPORARY = {temp_space_orig}")
        elif temp_space_orig := user_data.get("temp_space"):
            user_attrs.append(f"TEMPORARY = {temp_space_orig}")
    else:
        # Fallback to original space values
        if spool_space := user_data.get("spool_space"):
            user_attrs.append(f"SPOOL = {spool_space}")
        
        if temp_space := user_data.get("temp_space"):
            user_attrs.append(f"TEMPORARY = {temp_space}")
    
    if default_db := user_data.get("default_database"):
        user_attrs.append(f'DEFAULT DATABASE = "{default_db}"')
    
    if profile := user_data.get("profile"):
        user_attrs.append(f'PROFILE = "{profile}"')
    
    if account := user_data.get("account"):
        user_attrs.append(f"ACCOUNT = '{account}'")
    
    # Add user attributes separated by commas
    if user_attrs:
        # If we had AS params, continue with comma
        # If not, add space before first attribute
        separator = ", " if as_params else " "
        ddl += separator + ", ".join(user_attrs)
    
    ddl += ";"
    
    statements = [ddl]
    
    # Add comment if present (as separate statement)
    if comment := user_data.get("comment"):
        comment_ddl = f'COMMENT ON USER "{name}" IS \'{comment.replace("\'", "\'\'")}\';'
        statements.append(comment_ddl)
    
    return statements


def _generate_role_ddl(role_data: dict[str, Any]) -> list[str]:
    """
    Generate CREATE ROLE DDL from configuration.
    
    Args:
        role_data: Role configuration data
        
    Returns:
        List of DDL statements
    """
    name = role_data["name"]
    ddl = f'CREATE ROLE "{name}";'
    
    statements = [ddl]
    
    # Add comment if present (as separate statement)
    if comment := role_data.get("comment"):
        comment_ddl = f'COMMENT ON ROLE "{name}" IS \'{comment.replace("\'", "\'\'")}\';'
        statements.append(comment_ddl)
    
    return statements


def _generate_profile_ddl(profile_data: dict[str, Any]) -> list[str]:
    """
    Generate CREATE PROFILE DDL from configuration.
    
    Args:
        profile_data: Profile configuration data
        
    Returns:
        List of DDL statements
    """
    name = profile_data["name"]
    ddl = f'CREATE PROFILE "{name}"'
    
    parts = []
    
    if spool_space := profile_data.get("spool_space"):
        parts.append(f"SPOOL = {spool_space}")
    
    if temp_space := profile_data.get("temp_space"):
        parts.append(f"TEMP = {temp_space}")
    
    if account := profile_data.get("account"):
        parts.append(f"ACCOUNT = '{account}'")
    
    if default_db := profile_data.get("default_database"):
        parts.append(f'DEFAULT DATABASE = "{default_db}"')
    
    if parts:
        ddl += " " + ", ".join(parts)
    
    ddl += ";"
    
    statements = [ddl]
    
    # Add comment if present (as separate statement)
    if comment := profile_data.get("comment"):
        comment_ddl = f'COMMENT ON PROFILE "{name}" IS \'{comment.replace("\'", "\'\'")}\';'
        statements.append(comment_ddl)
    
    return statements


def _generate_privilege_ddl(priv_data: dict[str, Any], tgr: tagger.Tagger) -> list[str]:
    """
    Generate GRANT statements from privileges configuration.
    
    Handles both database privileges and role assignments:
    - Database privileges: GRANT privilege ON database TO grantee
    - Role assignments: GRANT role TO grantee [WITH ADMIN OPTION]
    
    Args:
        priv_data: Privilege configuration data with [[grant]] blocks
        tgr: Tagger for variable expansion
        
    Returns:
        List of GRANT statements
    """
    grantee_name = priv_data["grantee_name"]
    grantee_type = priv_data.get("grantee_type", "user")
    grant_blocks = priv_data.get("grant", [])
    
    ddl_statements = []
    
    for grant_block in grant_blocks:
        # Check if this is a role grant or database privilege grant
        role = grant_block.get("role")
        
        if role:
            # Role assignment: GRANT role TO user [WITH ADMIN OPTION]
            grant_stmt = f'GRANT "{role}" TO "{grantee_name}"'
            
            # Check for WITH ADMIN OPTION
            if with_admin := grant_block.get("with_admin"):
                if "ADMIN" in with_admin:
                    grant_stmt += " WITH ADMIN OPTION"
            
            grant_stmt += ";"
            ddl_statements.append(grant_stmt)
        else:
            # Database privilege grant
            database = grant_block.get("database")
            obj = grant_block.get("object")
            privileges = grant_block.get("privileges", [])
            privileges_with_grant = grant_block.get("privileges_with_grant_option", [])
            
            # Expand variables in database and object names
            if database:
                database = tgr.expand_statement(database)
            if obj:
                obj = tgr.expand_statement(obj)
            
            # Generate GRANT statements for privileges without grant option
            for priv in privileges:
                grant_stmt = f"GRANT {priv}"
                
                if database and obj:
                    grant_stmt += f' ON "{database}"."{obj}"'
                elif database:
                    grant_stmt += f' ON "{database}"'
                
                grant_stmt += f' TO "{grantee_name}"'
                grant_stmt += ";"
                ddl_statements.append(grant_stmt)
            
            # Generate GRANT statements for privileges with grant option
            for priv in privileges_with_grant:
                grant_stmt = f"GRANT {priv}"
                
                if database and obj:
                    grant_stmt += f' ON "{database}"."{obj}"'
                elif database:
                    grant_stmt += f' ON "{database}"'
                
                grant_stmt += f' TO "{grantee_name}"'
                grant_stmt += " WITH GRANT OPTION"
                grant_stmt += ";"
                ddl_statements.append(grant_stmt)
    
    return ddl_statements


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


def _confirm_deployment(
    environment: str,
    deploy_dir: Path,
    if_exists: str | None,
    total_objects: int,
    assume_yes: bool,
):
    """
    Confirm deployment with user.
    
    Args:
        environment: Target environment name
        deploy_dir: Deployment directory
        if_exists: Conflict strategy
        total_objects: Total number of objects to deploy
        assume_yes: Skip confirmation
    """
    if assume_yes:
        return
    
    console.print("\n[bold yellow]Deployment Confirmation[/bold yellow]")
    console.print(f"Environment: [bold]{environment}[/bold]")
    console.print(f"Deploy directory: {deploy_dir}")
    console.print(f"Total objects: {total_objects}")
    console.print(f"Conflict strategy: {if_exists if if_exists else 'default (skip)'}")
    
    answer = Prompt.ask(
        "\n[bold]Do you want to proceed?[/bold]",
        choices=["yes", "no"],
        default="no"
    )
    
    if answer.lower() != "yes":
        raise exc.DOperationsError("Deployment cancelled by user")


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


def _deploy_profiles(
    files: list[Path],
    tgr: tagger.Tagger,
    env_name: str,
    ext: AbstractDBI,
    if_exists: str,
    dry_run: bool,
    results: dict[str, list],
):
    """Deploy profile files (no retry needed - no dependencies)."""
    for filepath in files:
        try:
            data = _load_toml_file(filepath)
            data = _expand_variables(data, tgr)
            
            if not _should_deploy_for_env(data, env_name):
                logger.info(f"Skipping profile {data['name']} (overlay filter)")
                results["skipped"].append({"type": "profile", "name": data["name"]})
                continue
            
            # Check if profile already exists (skip check for IGNORE_STRATEGY)
            profile_name = data["name"]
            if if_exists != IGNORE_STRATEGY and _check_profile_exists(profile_name, ext):
                if if_exists == SKIP_STRATEGY:
                    logger.info(f"Skipping existing profile: {profile_name}")
                    results["skipped"].append({"type": "profile", "name": profile_name, "reason": "already exists"})
                    continue
                elif if_exists == DROP_STRATEGY:
                    logger.info(f"Dropping existing profile: {profile_name}")
                    ext.deploy_statements([f'DROP PROFILE "{profile_name}";'])
                # RAISE_STRATEGY will fail naturally when trying to create
            
            ddl_statements = _generate_profile_ddl(data)
            
            if dry_run:
                logger.info(f"[DRY-RUN] Would execute:\n" + "\n".join(ddl_statements))
            else:
                logger.info(f"Creating profile: {data['name']}")
                ext.deploy_statements(ddl_statements)
            
            results["deployed"].append({"type": "profile", "name": data["name"]})
        except exc.DBStatementError as e:
            # Check if profile already exists (Error 5612) - only handle for SKIP_STRATEGY
            error_msg = str(e).lower()
            if ("already exists" in error_msg or "5612" in str(e)) and if_exists == SKIP_STRATEGY:
                profile_name = data.get('name', 'unknown')
                logger.info(f"Skipping existing profile: {profile_name}")
                results["skipped"].append({"type": "profile", "name": profile_name, "reason": "already exists"})
                continue
            # For RAISE/IGNORE strategies, let error propagate normally
            logger.error(f"Failed to deploy profile from {filepath}: {e}")
            results["failed"].append({"type": "profile", "file": str(filepath), "error": str(e)})
            if if_exists == RAISE_STRATEGY:
                raise
        except Exception as e:
            logger.error(f"Failed to deploy profile from {filepath}: {e}")
            results["failed"].append({"type": "profile", "file": str(filepath), "error": str(e)})
            if if_exists == RAISE_STRATEGY:
                raise


def _deploy_roles(
    files: list[Path],
    tgr: tagger.Tagger,
    env_name: str,
    ext: AbstractDBI,
    if_exists: str,
    dry_run: bool,
    results: dict[str, list],
):
    """Deploy role files (no retry needed - no dependencies)."""
    for filepath in files:
        try:
            data = _load_toml_file(filepath)
            data = _expand_variables(data, tgr)
            
            if not _should_deploy_for_env(data, env_name):
                logger.info(f"Skipping role {data['name']} (overlay filter)")
                results["skipped"].append({"type": "role", "name": data["name"]})
                continue
            
            # Check if role already exists (skip check for IGNORE_STRATEGY)
            role_name = data["name"]
            if if_exists != IGNORE_STRATEGY and _check_role_exists(role_name, ext):
                if if_exists == SKIP_STRATEGY:
                    logger.info(f"Skipping existing role: {role_name}")
                    results["skipped"].append({"type": "role", "name": role_name, "reason": "already exists"})
                    continue
                elif if_exists == DROP_STRATEGY:
                    logger.info(f"Dropping existing role: {role_name}")
                    ext.deploy_statements([f'DROP ROLE "{role_name}";'])
                # RAISE_STRATEGY will fail naturally when trying to create
            
            ddl_statements = _generate_role_ddl(data)
            
            if dry_run:
                logger.info(f"[DRY-RUN] Would execute:\n" + "\n".join(ddl_statements))
            else:
                logger.info(f"Creating role: {data['name']}")
                ext.deploy_statements(ddl_statements)
            
            results["deployed"].append({"type": "role", "name": data["name"]})
        except exc.DBStatementError as e:
            # Check if role already exists (Error 5612) - only handle for SKIP_STRATEGY
            error_msg = str(e).lower()
            if ("already exists" in error_msg or "5612" in str(e)) and if_exists == SKIP_STRATEGY:
                role_name = data.get('name', 'unknown')
                logger.info(f"Skipping existing role: {role_name}")
                results["skipped"].append({"type": "role", "name": role_name, "reason": "already exists"})
                continue
            # For RAISE/IGNORE strategies, let error propagate normally
            logger.error(f"Failed to deploy role from {filepath}: {e}")
            results["failed"].append({"type": "role", "file": str(filepath), "error": str(e)})
            if if_exists == RAISE_STRATEGY:
                raise
        except Exception as e:
            logger.error(f"Failed to deploy role from {filepath}: {e}")
            results["failed"].append({"type": "role", "file": str(filepath), "error": str(e)})
            if if_exists == RAISE_STRATEGY:
                raise


def _deploy_single_database(
    filepath: Path,
    tgr: tagger.Tagger,
    env_name: str,
    ext: AbstractDBI,
    dry_run: bool,
    if_exists: str = SKIP_STRATEGY,
    cumulative_space_map: dict[str, dict[str, str]] | None = None,
) -> tuple[bool, dict[str, Any], str | None]:
    """
    Deploy a single database.
    
    Args:
        filepath: Path to database TOML file
        tgr: Tagger for variable expansion
        env_name: Target environment name
        ext: Database interface
        dry_run: Dry run mode
        if_exists: Conflict strategy
        cumulative_space_map: Optional mapping of cumulative space for all objects
    
    Returns:
        (success, object_info, error_message)
    """
    try:
        data = _load_toml_file(filepath)
        data = _expand_variables(data, tgr)
        
        if not _should_deploy_for_env(data, env_name):
            return (True, {"type": "database", "name": data["name"], "status": "skipped"}, None)
        
        # Check if database already exists (skip check for IGNORE_STRATEGY)
        db_name = data["name"]
        if if_exists != IGNORE_STRATEGY and _check_database_exists(db_name, ext):
            if if_exists == SKIP_STRATEGY:
                logger.info(f"Skipping existing database: {db_name}")
                return (True, {"type": "database", "name": db_name, "status": "skipped (exists)"}, None)
            elif if_exists == DROP_STRATEGY:
                logger.info(f"Dropping existing database: {db_name}")
                ext.deploy_statements([f'DROP DATABASE "{db_name}";'])
            # RAISE_STRATEGY will fail naturally when trying to create
        
        ddl_statements = _generate_database_ddl(data, cumulative_space_map)
        
        if dry_run:
            logger.info(f"[DRY-RUN] Would execute:\n" + "\n".join(ddl_statements))
        else:
            logger.info(f"Creating database: {data['name']}")
            ext.deploy_statements(ddl_statements)
        
        return (True, {"type": "database", "name": data["name"]}, None)
    except exc.DBObjectDoesNotExist as e:
        # Dependency missing - will retry
        logger.debug(f"Database {data.get('name', 'unknown')} deferred - dependency missing: {e}")
        return (False, {"type": "database", "file": str(filepath)}, str(e))
    except exc.DBStatementError as e:
        # Check if it's a missing dependency error
        error_msg = str(e).lower()
        if "does not exist" in error_msg or "not found" in error_msg or "unknown" in error_msg:
            logger.debug(f"Database {data.get('name', 'unknown')} deferred - dependency error: {e}")
            return (False, {"type": "database", "file": str(filepath)}, str(e))
        # Check if object already exists (Error 5612) - only handle for SKIP_STRATEGY
        if ("already exists" in error_msg or "5612" in str(e)) and if_exists == SKIP_STRATEGY:
            db_name = data.get('name', 'unknown')
            logger.info(f"Skipping existing database: {db_name}")
            return (True, {"type": "database", "name": db_name, "status": "skipped (exists)"}, None)
        # Other statement errors are permanent (or propagate for RAISE/IGNORE strategies)
        logger.error(f"Failed to deploy database from {filepath}: {e}")
        return (False, {"type": "database", "file": str(filepath)}, str(e))
    except Exception as e:
        # Check if error message indicates missing dependency
        error_msg = str(e).lower()
        if "does not exist" in error_msg or "not found" in error_msg or "unknown" in error_msg:
            logger.debug(f"Database {data.get('name', 'unknown')} deferred - dependency error: {e}")
            return (False, {"type": "database", "file": str(filepath)}, str(e))
        # Check if object already exists (Error 5612) - only handle for SKIP_STRATEGY
        if ("already exists" in error_msg or "5612" in str(e)) and if_exists == SKIP_STRATEGY:
            db_name = data.get('name', 'unknown')
            logger.info(f"Skipping existing database: {db_name}")
            return (True, {"type": "database", "name": db_name, "status": "skipped (exists)"}, None)
        # Other errors are permanent (or propagate for RAISE/IGNORE strategies)
        logger.error(f"Failed to deploy database from {filepath}: {e}")
        return (False, {"type": "database", "file": str(filepath)}, str(e))


def _deploy_single_user(
    filepath: Path,
    tgr: tagger.Tagger,
    env_name: str,
    ext: AbstractDBI,
    dry_run: bool,
    if_exists: str = SKIP_STRATEGY,
    cumulative_space_map: dict[str, dict[str, str]] | None = None,
) -> tuple[bool, dict[str, Any], str | None]:
    """
    Deploy a single user.
    
    Args:
        filepath: Path to user TOML file
        tgr: Tagger for variable expansion
        env_name: Target environment name
        ext: Database interface
        dry_run: Dry run mode
        if_exists: Conflict strategy
        cumulative_space_map: Optional mapping of cumulative space for all objects
    
    Returns:
        (success, object_info, error_message)
    """
    try:
        data = _load_toml_file(filepath)
        data = _expand_variables(data, tgr)
        
        if not _should_deploy_for_env(data, env_name):
            return (True, {"type": "user", "name": data["name"], "status": "skipped"}, None)
        
        # Check if user already exists (skip check for IGNORE_STRATEGY)
        user_name = data["name"]
        if if_exists != IGNORE_STRATEGY and _check_database_exists(user_name, ext):  # Users are in DBC.DatabasesV too
            if if_exists == SKIP_STRATEGY:
                logger.info(f"Skipping existing user: {user_name}")
                return (True, {"type": "user", "name": user_name, "status": "skipped (exists)"}, None)
            elif if_exists == DROP_STRATEGY:
                logger.info(f"Dropping existing user: {user_name}")
                ext.deploy_statements([f'DROP USER "{user_name}";'])
            # RAISE_STRATEGY will fail naturally when trying to create
        
        ddl_statements = _generate_user_ddl(data, cumulative_space_map)
        
        if dry_run:
            logger.info(f"[DRY-RUN] Would execute:\n" + "\n".join(ddl_statements))
        else:
            logger.info(f"Creating user: {data['name']}")
            ext.deploy_statements(ddl_statements)
        
        return (True, {"type": "user", "name": data["name"]}, None)
    except exc.DBObjectDoesNotExist as e:
        # Dependency missing - will retry
        logger.debug(f"User {data.get('name', 'unknown')} deferred - dependency missing: {e}")
        return (False, {"type": "user", "file": str(filepath)}, str(e))
    except exc.DBStatementError as e:
        # Check if it's a missing dependency error
        error_msg = str(e).lower()
        if "does not exist" in error_msg or "not found" in error_msg or "unknown" in error_msg:
            logger.debug(f"User {data.get('name', 'unknown')} deferred - dependency error: {e}")
            return (False, {"type": "user", "file": str(filepath)}, str(e))
        # Check if object already exists (Error 5612) - only handle for SKIP_STRATEGY
        if ("already exists" in error_msg or "5612" in str(e)) and if_exists == SKIP_STRATEGY:
            user_name = data.get('name', 'unknown')
            logger.info(f"Skipping existing user: {user_name}")
            return (True, {"type": "user", "name": user_name, "status": "skipped (exists)"}, None)
        # Other statement errors are permanent (or propagate for RAISE/IGNORE strategies)
        logger.error(f"Failed to deploy user from {filepath}: {e}")
        return (False, {"type": "user", "file": str(filepath)}, str(e))
    except Exception as e:
        # Check if error message indicates missing dependency
        error_msg = str(e).lower()
        if "does not exist" in error_msg or "not found" in error_msg or "unknown" in error_msg:
            logger.debug(f"User {data.get('name', 'unknown')} deferred - dependency error: {e}")
            return (False, {"type": "user", "file": str(filepath)}, str(e))
        # Check if object already exists (Error 5612) - only handle for SKIP_STRATEGY
        if ("already exists" in error_msg or "5612" in str(e)) and if_exists == SKIP_STRATEGY:
            user_name = data.get('name', 'unknown')
            logger.info(f"Skipping existing user: {user_name}")
            return (True, {"type": "user", "name": user_name, "status": "skipped (exists)"}, None)
        # Other errors are permanent (or propagate for RAISE/IGNORE strategies)
        logger.error(f"Failed to deploy user from {filepath}: {e}")
        return (False, {"type": "user", "file": str(filepath)}, str(e))


def _deploy_single_privilege(
    filepath: Path,
    tgr: tagger.Tagger,
    env_name: str,
    ext: AbstractDBI,
    dry_run: bool,
) -> tuple[bool, dict[str, Any], str | None]:
    """
    Deploy privileges from a single file.
    
    Returns:
        (success, object_info, error_message)
    """
    try:
        data = _load_toml_file(filepath)
        data = _expand_variables(data, tgr)
        
        if not _should_deploy_for_env(data, env_name):
            return (True, {"type": "privileges", "name": data["grantee_name"], "status": "skipped"}, None)
        
        grantee_name = data["grantee_name"]
        
        # Check if grantee exists (could be user, role, or database)
        if not _check_database_exists(grantee_name, ext) and not _check_role_exists(grantee_name, ext):
            logger.warning(f"Skipping privileges for {grantee_name} - grantee does not exist (may be filtered by only_in/not_only_in)")
            return (True, {"type": "privileges", "name": grantee_name, "status": "skipped (grantee not found)"}, None)
        
        # Validate that target databases/objects exist before generating DDL
        grant_blocks = data.get("grant", [])
        valid_grant_blocks = []
        
        for grant_block in grant_blocks:
            database = grant_block.get("database")
            
            # Expand variables in database name
            if database:
                expanded_database = tgr.expand_statement(database)
                
                # Check if target database exists
                if not _check_database_exists(expanded_database, ext):
                    logger.warning(f"Skipping privilege grant on database '{expanded_database}' for {grantee_name} - database does not exist (may be filtered by only_in/not_only_in)")
                    continue
            
            # This grant block is valid, keep it
            valid_grant_blocks.append(grant_block)
        
        # If no valid grant blocks remain, skip this privilege file
        if not valid_grant_blocks:
            logger.info(f"Skipping all privileges for {grantee_name} - no valid target databases/objects found")
            return (True, {"type": "privileges", "name": grantee_name, "status": "skipped (no valid targets)"}, None)
        
        # Update data with only valid grant blocks
        data["grant"] = valid_grant_blocks
        
        ddl_statements = _generate_privilege_ddl(data, tgr)
        
        if dry_run:
            logger.info(f"[DRY-RUN] Would execute {len(ddl_statements)} GRANT statements for {grantee_name}")
            for stmt in ddl_statements[:5]:
                logger.info(f"  {stmt}")
            if len(ddl_statements) > 5:
                logger.info(f"  ... and {len(ddl_statements) - 5} more")
        else:
            logger.info(f"Granting {len(ddl_statements)} privileges to: {grantee_name}")
            ext.deploy_statements(ddl_statements)
        
        return (True, {"type": "privileges", "name": grantee_name}, None)
    except exc.DBObjectDoesNotExist as e:
        # Dependency missing - will retry
        logger.debug(f"Privileges for {data.get('grantee_name', 'unknown')} deferred - dependency missing: {e}")
        return (False, {"type": "privileges", "file": str(filepath)}, str(e))
    except exc.DBStatementError as e:
        # Check if it's a missing dependency error
        error_msg = str(e).lower()
        if "does not exist" in error_msg or "not found" in error_msg or "unknown" in error_msg:
            logger.debug(f"Privileges for {data.get('grantee_name', 'unknown')} deferred - dependency error: {e}")
            return (False, {"type": "privileges", "file": str(filepath)}, str(e))
        # Other statement errors are permanent
        logger.error(f"Failed to deploy privileges from {filepath}: {e}")
        return (False, {"type": "privileges", "file": str(filepath)}, str(e))
    except Exception as e:
        # Check if error message indicates missing dependency
        error_msg = str(e).lower()
        if "does not exist" in error_msg or "not found" in error_msg or "unknown" in error_msg:
            logger.debug(f"Privileges for {data.get('grantee_name', 'unknown')} deferred - dependency error: {e}")
            return (False, {"type": "privileges", "file": str(filepath)}, str(e))
        # Other errors are permanent
        logger.error(f"Failed to deploy privileges from {filepath}: {e}")
        return (False, {"type": "privileges", "file": str(filepath)}, str(e))


def _deploy_with_retry(
    files: list[Path],
    deploy_func: Any,
    object_type: str,
    tgr: tagger.Tagger,
    env_name: str,
    ext: AbstractDBI,
    if_exists: str,
    dry_run: bool,
    results: dict[str, list],
    max_waves: int = 10,
):
    """
    Deploy files with retry strategy for dependency resolution.
    
    Uses wave-based deployment similar to cmd_deployment.py. Objects that fail
    due to missing dependencies are retried in subsequent waves until all
    dependencies are resolved or max waves reached.
    
    Args:
        files: List of files to deploy
        deploy_func: Function to deploy a single file
        object_type: Type of objects being deployed
        tgr: Tagger for variable expansion
        env_name: Target environment name
        ext: Database interface
        if_exists: Conflict strategy
        dry_run: Dry run mode
        results: Results dictionary to update
        max_waves: Maximum number of deployment waves
    """
    pending = list(files)
    wave = 1
    
    while pending and wave <= max_waves:
        if wave > 1:
            logger.info(f"Starting wave #{wave} for {object_type}s ({len(pending)} pending)")
        
        still_pending = []
        deployed_in_wave = 0
        
        for filepath in pending:
            success, obj_info, error = deploy_func(filepath, tgr, env_name, ext, dry_run)
            
            if success:
                if obj_info.get("status") == "skipped":
                    results["skipped"].append(obj_info)
                else:
                    results["deployed"].append(obj_info)
                    deployed_in_wave += 1
            else:
                # Check if it's a dependency issue (will retry) or permanent error
                if "does not exist" in str(error).lower() or "not found" in str(error).lower():
                    logger.debug(f"Deferring {filepath.name} due to missing dependency")
                    still_pending.append(filepath)
                else:
                    # Permanent error
                    obj_info["error"] = error
                    results["failed"].append(obj_info)
                    if if_exists == RAISE_STRATEGY:
                        raise exc.DOperationsError(f"Deployment failed: {error}")
        
        if deployed_in_wave == 0 and still_pending:
            # No progress made - remaining objects have unresolvable dependencies
            logger.warning(f"No progress in wave #{wave}. {len(still_pending)} {object_type}s have unresolved dependencies.")
            for filepath in still_pending:
                results["failed"].append({
                    "type": object_type,
                    "file": str(filepath),
                    "error": "Unresolved dependencies after maximum retry attempts"
                })
            break
        
        pending = still_pending
        wave += 1
    
    if pending and wave > max_waves:
        logger.warning(f"Reached maximum waves ({max_waves}). {len(pending)} {object_type}s still pending.")
        for filepath in pending:
            results["failed"].append({
                "type": object_type,
                "file": str(filepath),
                "error": f"Exceeded maximum deployment waves ({max_waves})"
            })


def _deploy_databases_and_users_combined(
    database_files: list[Path],
    user_files: list[Path],
    tgr: tagger.Tagger,
    env_name: str,
    ext: AbstractDBI,
    if_exists: str,
    dry_run: bool,
    results: dict[str, list],
    max_waves: int = 10,
):
    """
    Deploy databases and users together with retry strategy.
    
    This handles circular dependencies where users can own databases and 
    databases can be owned by users. By deploying them together, we can
    resolve these dependencies through multiple waves.
    
    Calculates cumulative space requirements so that parent databases/users
    have enough space to accommodate all their descendants.
    
    Args:
        database_files: List of database TOML files
        user_files: List of user TOML files
        tgr: Tagger for variable expansion
        env_name: Target environment name
        ext: Database interface
        if_exists: Conflict strategy
        dry_run: Dry run mode
        results: Results dictionary to update
        max_waves: Maximum number of deployment waves
    """
    # Calculate cumulative space requirements
    logger.info("Calculating cumulative space requirements for databases and users...")
    parent_to_children, object_data_map = _build_space_dependency_tree(
        database_files, user_files, env_name, tgr
    )
    cumulative_space_map = _calculate_cumulative_space(parent_to_children, object_data_map)
    
    # Log cumulative space info
    if cumulative_space_map:
        logger.debug("Cumulative space map:")
        for obj_name, spaces in cumulative_space_map.items():
            orig_data = object_data_map.get(obj_name, {})
            orig_perm = orig_data.get("perm_space", "0")
            cum_perm = spaces.get("perm_space", "0")
            if orig_perm != cum_perm:
                logger.debug(f"  {obj_name}: PERM {orig_perm} -> {cum_perm} (includes descendants)")
    
    # Combine both types with metadata about their type
    combined = [
        (f, "database", _deploy_single_database) for f in database_files
    ] + [
        (f, "user", _deploy_single_user) for f in user_files
    ]
    
    pending = list(combined)
    wave = 1
    
    while pending and wave <= max_waves:
        if wave > 1:
            logger.info(f"Starting wave #{wave} for databases/users ({len(pending)} pending)")
        
        still_pending = []
        deployed_in_wave = 0
        
        for filepath, obj_type, deploy_func in pending:
            # Pass cumulative_space_map to deploy function
            success, obj_info, error = deploy_func(
                filepath, tgr, env_name, ext, dry_run, if_exists, cumulative_space_map
            )
            
            if success:
                if obj_info.get("status") == "skipped":
                    results["skipped"].append(obj_info)
                else:
                    results["deployed"].append(obj_info)
                    deployed_in_wave += 1
            else:
                # Check if it's a dependency issue (will retry) or permanent error
                if "does not exist" in str(error).lower() or "not found" in str(error).lower():
                    logger.debug(f"Deferring {filepath.name} ({obj_type}) due to missing dependency")
                    still_pending.append((filepath, obj_type, deploy_func))
                else:
                    # Permanent error
                    obj_info["error"] = error
                    results["failed"].append(obj_info)
                    if if_exists == RAISE_STRATEGY:
                        raise exc.DOperationsError(f"Deployment failed: {error}")
        
        if deployed_in_wave == 0 and still_pending:
            # No progress made - remaining objects have unresolvable dependencies
            logger.warning(f"No progress in wave #{wave}. {len(still_pending)} databases/users have unresolved dependencies.")
            for filepath, obj_type, _ in still_pending:
                results["failed"].append({
                    "type": obj_type,
                    "file": str(filepath),
                    "error": "Unresolved dependencies after maximum retry attempts"
                })
            break
        
        pending = still_pending
        wave += 1
    
    if pending and wave > max_waves:
        logger.warning(f"Reached maximum waves ({max_waves}). {len(pending)} databases/users still pending.")
        for filepath, obj_type, _ in pending:
            results["failed"].append({
                "type": obj_type,
                "file": str(filepath),
                "error": f"Exceeded maximum deployment waves ({max_waves})"
            })


def _deploy_with_retry(
    files: list[Path],
    deploy_func: Any,
    object_type: str,
    tgr: tagger.Tagger,
    env_name: str,
    ext: AbstractDBI,
    if_exists: str,
    dry_run: bool,
    results: dict[str, list],
    max_waves: int = 10,
):
    """
    Deploy files with retry strategy for dependency resolution.
    
    Uses wave-based deployment similar to cmd_deployment.py. Objects that fail
    due to missing dependencies are retried in subsequent waves until all
    dependencies are resolved or max waves reached.
    
    Args:
        files: List of files to deploy
        deploy_func: Function to deploy a single file
        object_type: Type of objects being deployed
        tgr: Tagger for variable expansion
        env_name: Target environment name
        ext: Database interface
        if_exists: Conflict strategy
        dry_run: Dry run mode
        results: Results dictionary to update
        max_waves: Maximum number of deployment waves
    """
    pending = list(files)
    wave = 1
    
    while pending and wave <= max_waves:
        if wave > 1:
            logger.info(f"Starting wave #{wave} for {object_type}s ({len(pending)} pending)")
        
        still_pending = []
        deployed_in_wave = 0
        
        for filepath in pending:
            success, obj_info, error = deploy_func(filepath, tgr, env_name, ext, dry_run)
            
            if success:
                if obj_info.get("status") == "skipped":
                    results["skipped"].append(obj_info)
                else:
                    results["deployed"].append(obj_info)
                    deployed_in_wave += 1
            else:
                # Check if it's a dependency issue (will retry) or permanent error
                if "does not exist" in str(error).lower() or "not found" in str(error).lower():
                    logger.debug(f"Deferring {filepath.name} due to missing dependency")
                    still_pending.append(filepath)
                else:
                    # Permanent error
                    obj_info["error"] = error
                    results["failed"].append(obj_info)
                    if if_exists == RAISE_STRATEGY:
                        raise exc.DOperationsError(f"Deployment failed: {error}")
        
        if deployed_in_wave == 0 and still_pending:
            # No progress made - remaining objects have unresolvable dependencies
            logger.warning(f"No progress in wave #{wave}. {len(still_pending)} {object_type}s have unresolved dependencies.")
            for filepath in still_pending:
                results["failed"].append({
                    "type": object_type,
                    "file": str(filepath),
                    "error": "Unresolved dependencies after maximum retry attempts"
                })
            break
        
        pending = still_pending
        wave += 1
    
    if pending and wave > max_waves:
        logger.warning(f"Reached maximum waves ({max_waves}). {len(pending)} {object_type}s still pending.")
        for filepath in pending:
            results["failed"].append({
                "type": object_type,
                "file": str(filepath),
                "error": f"Exceeded maximum deployment waves ({max_waves})"
            })


def _confirm_deployment(
    environment: str,
    deploy_dir: Path,
    if_exists: str | None,
    total_objects: int,
    assume_yes: bool,
):
    """
    Confirm deployment with user.
    
    Args:
        environment: Target environment name
        deploy_dir: Deployment directory
        if_exists: Conflict strategy
        total_objects: Total number of objects to deploy
        assume_yes: Skip confirmation
    """
    if assume_yes:
        return
    
    console.print("\n[bold yellow]Deployment Confirmation[/bold yellow]")
    console.print(f"Environment: [bold]{environment}[/bold]")
    console.print(f"Deploy directory: {deploy_dir}")
    console.print(f"Total objects: {total_objects}")
    console.print(f"Conflict strategy: {if_exists if if_exists else 'default (skip)'}")
    
    answer = Prompt.ask(
        "\n[bold]Do you want to proceed?[/bold]",
        choices=["yes", "no"],
        default="no"
    )
    
    if answer.lower() != "yes":
        raise exc.DOperationsError("Deployment cancelled by user")


def deploy_env_def(
    deploy_dir: Path,
    *,
    cfg: config_model.Config,
    env: config_model.EnvironParameters,
    env_name: str,
    ctx: Context,
    ext: AbstractDBI,
    if_exists: str | None,
    assume_yes: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Deploy environment definitions from TOML files to Teradata.
    
    Args:
        deploy_dir: Directory containing TOML definition files
        cfg: Configuration
        env: Environment parameters
        env_name: Target environment name
        ctx: Context
        ext: Database interface
        if_exists: Conflict strategy (raise, drop, skip, ignore)
        assume_yes: Skip confirmations
        dry_run: Don't actually execute, just show what would be done
        
    Returns:
        Dictionary with deployment results
    """
    logger.info(f"Starting environment definition deployment for: {env_name}")
    logger.info(f"Source directory: {deploy_dir}")
    
    # Validate conflict strategy
    if if_exists is not None and if_exists not in _DEPLOYMENT_STRATEGIES:
        msg = f"Invalid value: {if_exists=}\nexpected one of: {_DEPLOYMENT_STRATEGIES}"
        raise exc.DOperationsError(msg)
    
    if if_exists is None:
        if_exists = SKIP_STRATEGY
    
    # Initialize tagger for variable expansion
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
    privileges_dir = deploy_dir / "privileges"
    
    profile_files = list(profiles_dir.glob("*.toml")) if profiles_dir.exists() else []
    role_files = list(roles_dir.glob("*.toml")) if roles_dir.exists() else []
    database_files = list(databases_dir.glob("*.toml")) if databases_dir.exists() else []
    user_files = list(users_dir.glob("*.toml")) if users_dir.exists() else []
    privilege_files = []
    if privileges_dir.exists():
        privilege_files.extend(privileges_dir.rglob("*.toml"))
    
    total_objects = len(profile_files) + len(role_files) + len(database_files) + len(user_files) + len(privilege_files)
    
    # Confirm deployment
    _confirm_deployment(
        environment=env_name,
        deploy_dir=deploy_dir,
        if_exists=if_exists,
        total_objects=total_objects,
        assume_yes=assume_yes,
    )
    
    results = {
        "deployed": [],
        "skipped": [],
        "failed": [],
    }
    
    # Smart deployment order with retry strategy for dependency resolution:
    # 1. Profiles (no dependencies)
    # 2. Databases AND Users together (users can own databases and databases can own users)
    # 3. Roles (may reference users/databases)
    # 4. Privileges (depend on all grantees and target objects)
    
    # 1. Deploy profiles
    logger.info(f"Deploying {len(profile_files)} profiles...")
    _deploy_profiles(profile_files, tgr, env_name, ext, if_exists, dry_run, results)
    
    # 2. Deploy databases AND users together with retry strategy
    # This handles circular dependencies where users can own databases and vice versa
    combined_db_user_files = database_files + user_files
    if combined_db_user_files:
        logger.info(f"Deploying {len(database_files)} databases and {len(user_files)} users together...")
        _deploy_databases_and_users_combined(
            database_files=database_files,
            user_files=user_files,
            tgr=tgr,
            env_name=env_name,
            ext=ext,
            if_exists=if_exists,
            dry_run=dry_run,
            results=results,
        )
    
    # 3. Deploy roles
    logger.info(f"Deploying {len(role_files)} roles...")
    _deploy_roles(role_files, tgr, env_name, ext, if_exists, dry_run, results)
    
    # 4. Deploy privileges with retry strategy
    logger.info(f"Deploying privileges from {len(privilege_files)} files...")
    _deploy_with_retry(
        privilege_files,
        deploy_func=_deploy_single_privilege,
        object_type="privileges",
        tgr=tgr,
        env_name=env_name,
        ext=ext,
        if_exists=if_exists,
        dry_run=dry_run,
        results=results,
    )
    
    # Summary
    logger.info("\n[bold green]Deployment Summary[/bold green]")
    logger.info(f"Deployed: {len(results['deployed'])}")
    logger.info(f"Skipped: {len(results['skipped'])}")
    logger.info(f"Failed: {len(results['failed'])}")
    
    if results["failed"]:
        logger.warning("Some objects failed to deploy. Check logs for details.")
    
    return results
