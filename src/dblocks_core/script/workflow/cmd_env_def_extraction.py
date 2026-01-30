"""
Workflow for extracting environment definitions (databases, users, roles, profiles, privileges)
from Teradata and storing them as TOML configuration files.
"""

from pathlib import Path

from dblocks_core import exc, tagger
from dblocks_core.config.config import logger
from dblocks_core.context import Context
from dblocks_core.dbi import AbstractDBI
from dblocks_core.git import git
from dblocks_core.model import config_model, meta_model
from dblocks_core.writer import env_def_writer


def _matches_filter(name: str, filter_pattern: str) -> bool:
    """
    Check if a name matches a SQL LIKE filter pattern.
    
    Args:
        name: The name to check
        filter_pattern: SQL LIKE pattern where % matches any characters
        
    Returns:
        True if name matches the pattern, False otherwise
    """
    import re
    # Convert SQL LIKE pattern to regex (% -> .*, escape special regex chars)
    regex_pattern = filter_pattern.replace("%", ".*")
    return re.match(regex_pattern, name, re.IGNORECASE) is not None


def run_env_def_extraction(
    ctx: Context,
    env: config_model.EnvironParameters,
    env_name: str,
    ext: AbstractDBI,
    env_def_dir: Path,
    repo: git.Repo | None,
    *,
    commit: bool = False,
    filter_databases: str | None = None,
    filter_roles: str | None = None,
    filter_profiles: str | None = None,
):
    """
    Executes extraction of environment definitions from Teradata database.
    
    Extracts databases, users, roles, profiles, and privileges and stores them
    as TOML configuration files. Uses the same scoping logic as env-extract,
    extracting only root databases/users defined in env.extraction.databases
    and their children.

    Args:
        ctx: The context for the operation
        env: Environment parameters (including extraction.databases configuration)
        env_name: Name of the environment
        ext: Database interface for extraction
        env_def_dir: Directory to store environment definitions
        repo: Git repository instance
        commit: Whether to commit changes to the repository
        filter_databases: Optional filter mask for databases/users (SQL LIKE pattern with %)
        filter_roles: Optional filter mask for roles (SQL LIKE pattern with %)
        filter_profiles: Optional filter mask for profiles (SQL LIKE pattern with %)

    Returns:
        None
    """
    logger.info(f"Starting environment definition extraction for: {env_name}")
    logger.info(f"Target directory: {env_def_dir}")
    logger.info(f"Root databases configured: {env.extraction.databases}")
    
    # Log active filters
    if filter_databases:
        logger.info(f"Database/user filter: {filter_databases}")
    if filter_roles:
        logger.info(f"Role filter: {filter_roles}")
    if filter_profiles:
        logger.info(f"Profile filter: {filter_profiles}")
    
    # Initialize writer
    writer = env_def_writer.EnvDefWriter(
        base_dir=env_def_dir,
        encoding=env.writer.encoding
    )
    
    # Handle git branch if configured
    if env.git_branch is not None:
        if repo is None:
            message = "\n".join(
                [
                    f"This environment has configured git branch: {env.git_branch}",
                    "However, we are not in a git repository.",
                    "Either run 'dbe init' (recommended) or 'git init'.",
                ]
            )
            raise exc.DOperationsError(message)
        
        # Check if repo is clean
        if not ctx.is_in_progress():
            logger.info("Checking if repo is clean")
            if repo.is_dirty():
                raise exc.DOperationsError(
                    "Repository is dirty, cannot proceed with extraction."
                    "\nYou should:"
                    "\n- check what changes are in the repo (git status; git diff)"
                    "\n- decide if you want to DROP all changes (git stash --all && git stash drop); or"
                    "\n- commit everything (git add --all && git commit)"
                )
        
        # Checkout the branch
        repo.checkout(env.git_branch, missing_ok=True)
    
    # Get all databases and determine scope (same logic as env-extract)
    logger.info("Retrieving all databases from system...")
    all_databases = ext.get_databases()
    logger.info(f"Found {len(all_databases)} total databases in system")
    
    # Initialize tagger for making names environment-agnostic
    tgr = tagger.Tagger(
        env.tagging_variables,
        env.tagging_rules,
        tagging_strip_db_with_no_rules=env.tagging_strip_db_with_no_rules,
    )
    
    # Build tagger database replacements
    tgr.build(databases=[db.database_name for db in all_databases])
    logger.info(f"Tagger initialized with {len(tgr.database_replacements)} database name mappings")
    
    # Apply scoping logic - only extract databases in scope
    databases_in_scope = _get_databases_in_scope(
        env=env,
        databases=all_databases
    )
    logger.info(f"Databases in scope (based on extraction.databases config): {len(databases_in_scope)}")
    
    # Separate actual databases from users (in Teradata, users are databases with dbKind='U')
    actual_databases = []
    user_databases = []
    
    for db in databases_in_scope:
        if db.database_details and db.database_details.db_kind == "U":
            user_databases.append(db)
        else:
            actual_databases.append(db)
    
    logger.info(f"  - Actual databases: {len(actual_databases)}")
    logger.info(f"  - Users (dbKind='U'): {len(user_databases)}")
    
    # Apply database filter if specified (filter in Python after scoping)
    if filter_databases:
        original_count = len(actual_databases)
        actual_databases = [
            db for db in actual_databases 
            if _matches_filter(db.database_name, filter_databases)
        ]
        logger.info(f"Databases after filter: {len(actual_databases)} (filtered out {original_count - len(actual_databases)})")
    
    # Extract actual databases (not users)
    logger.info("Extracting databases...")
    for db in actual_databases:
        writer.write_database(db, tagger=tgr)
    
    # Get all users from DBC.UsersV and determine scope
    logger.info("Retrieving all users from system...")
    all_users = ext.get_users(filter_users=filter_databases)  # Apply filter at SQL level
    logger.info(f"Found {len(all_users)} total users in system")
    
    # Enrich users with owner information from all_databases (from databasesV)
    # DBC.UsersV doesn't contain owner info, but DBC.databasesV does
    user_owner_map = {}
    for db in all_databases:
        if db.database_details and db.database_details.db_kind == "U":
            if isinstance(db.database_details, meta_model.DescribedTeradataDatabase):
                user_owner_map[db.database_name.upper()] = db.database_details.owner_name
    
    logger.debug(f"User owner map has {len(user_owner_map)} entries")
    
    # Apply owner information to users from UsersV
    for user in all_users:
        if user.user_details and isinstance(user.user_details, meta_model.DescribedTeradataUser):
            owner = user_owner_map.get(user.user_name.upper(), "")
            user.user_details.owner_name = owner
            if owner:
                logger.debug(f"User {user.user_name} has owner: {owner}")
    
    # Apply scoping logic - only extract users in scope
    users_in_scope = _get_users_in_scope(
        env=env,
        users=all_users,
        databases_in_scope=databases_in_scope  # All databases including users
    )
    logger.info(f"Users in scope: {len(users_in_scope)}")
    
    # Note: Users were already filtered at SQL level by get_users(filter_users=filter_databases)
    # No additional filtering needed here
    
    # Extract users in scope
    logger.info("Extracting users...")
    for user in users_in_scope:
        # Set password placeholder for TOML output
        user.password = "<REDACTED>"  # Password should be managed separately
        writer.write_user(user, tagger=tgr)
    
    # Extract roles
    logger.info("Extracting roles...")
    roles = ext.get_roles(filter_roles=filter_roles)  # Apply filter at SQL level
    logger.info(f"Found {len(roles)} roles")
    
    for role in roles:
        writer.write_role(role, tagger=tgr)
        
        # Extract privileges for this role
        privileges = ext.get_privileges_for_grantee(
            grantee_name=role.role_name,
            grantee_type="role"
        )
        
        if privileges.privileges:  # Only write if there are privileges
            writer.write_privileges(privileges, tagger=tgr)
    
    # Extract profiles
    logger.info("Extracting profiles...")
    profiles = ext.get_profiles(filter_profiles=filter_profiles)  # Apply filter at SQL level
    logger.info(f"Found {len(profiles)} profiles")
    
    for profile in profiles:
        writer.write_profile(profile, tagger=tgr)
    
    # Extract privileges for users in scope
    logger.info("Extracting user privileges...")
    for user in users_in_scope:
        privileges = ext.get_privileges_for_grantee(
            grantee_name=user.user_name,
            grantee_type="user"
        )
        
        if privileges.privileges:  # Only write if there are privileges
            writer.write_privileges(privileges, tagger=tgr)
    
    # Extract privileges for databases in scope (actual databases, not users)
    logger.info("Extracting database privileges...")
    for db in actual_databases:
        privileges = ext.get_privileges_for_grantee(
            grantee_name=db.database_name,
            grantee_type="database"
        )
        
        if privileges.privileges:  # Only write if there are privileges
            writer.write_privileges(privileges, tagger=tgr)
    
    # Commit changes if requested
    if repo is not None and commit:
        if not repo.is_clean():
            repo.add()
            repo.commit(f"dbe env-def-extract {env_name}: environment definitions")
            logger.info("Changes committed to repository")
        else:
            logger.info("No changes to commit")
    elif repo is not None and not repo.is_clean():
        logger.warning("Repository has changes but commit flag is False. Please commit manually.")
    
    logger.info("Environment definition extraction completed successfully")


def _get_databases_in_scope(
    *,
    env: config_model.EnvironParameters,
    databases: list[meta_model.DescribedDatabase],
) -> list[meta_model.DescribedDatabase]:
    """
    Identifies databases in scope based on configured root databases and ownership
    hierarchy. Uses the same logic as env-extract.

    Args:
        env: Environment parameters containing extraction.databases configuration
        databases: List of all databases from the system

    Returns:
        List of databases considered in scope based on configuration and hierarchy

    The function iteratively checks:
    - Direct inclusion of databases specified in env.extraction.databases
    - Ownership relationships for databases, recursively adding parent-child dependencies
    - Supports only Teradata databases for recursive ownership evaluation
    """
    in_scope: list[meta_model.DescribedDatabase] = []
    root_databases = {d.upper() for d in env.extraction.databases}
    
    logger.debug(f"Root databases from config: {root_databases}")
    
    i = 0
    while True:
        i = i + 1
        prev_len = len(in_scope)
        
        for db in databases:
            database_name = db.database_name.upper()
            
            # If directly configured in extraction.databases, add to scope
            if database_name in root_databases:
                if db not in in_scope:
                    logger.debug(f"Adding database directly: {database_name}")
                    in_scope.append(db)
            
            # Check if database is recursively owned by a root database
            # This only works for Teradata databases
            if not isinstance(db.database_details, meta_model.DescribedTeradataDatabase):
                continue
            
            # If owner of this database is in root_databases, add it to scope
            # and also add it to root_databases (it can have children too)
            if (
                db.database_details.owner_name.upper() in root_databases
                and db not in in_scope
            ):
                logger.debug(f"Adding database, owner is in scope: {database_name}")
                in_scope.append(db)
                if database_name not in root_databases:
                    logger.debug(f"Adding database to parent list: {database_name}")
                    root_databases.add(database_name)
        
        # Stop when no new databases are added
        logger.debug(f"Iteration {i}: {len(in_scope)} databases in scope")
        if prev_len == len(in_scope):
            break
    
    return in_scope


def _get_users_in_scope(
    *,
    env: config_model.EnvironParameters,
    users: list[meta_model.DescribedUser],
    databases_in_scope: list[meta_model.DescribedDatabase],
) -> list[meta_model.DescribedUser]:
    """
    Identifies users in scope based on configured root databases/users and ownership
    hierarchy. Uses similar logic as database scoping.

    Args:
        env: Environment parameters containing extraction.databases configuration
        users: List of all users from the system
        databases_in_scope: List of databases already determined to be in scope

    Returns:
        List of users considered in scope based on configuration and hierarchy

    Users are included if:
    - They are directly specified in env.extraction.databases (root users)
    - They are owned by databases/users already in scope
    """
    in_scope: list[meta_model.DescribedUser] = []
    root_items = {d.upper() for d in env.extraction.databases}
    
    # Also consider all databases in scope as potential owners of users
    # This includes both actual databases AND users (since users are databases in Teradata)
    owners_in_scope = {db.database_name.upper() for db in databases_in_scope}
    owners_in_scope.update(root_items)  # Start with root items too
    
    logger.debug(f"Root items from config: {root_items}")
    logger.debug(f"Initial owners in scope: {owners_in_scope}")
    
    i = 0
    while True:
        i = i + 1
        prev_len = len(in_scope)
        
        for user in users:
            user_name = user.user_name.upper()
            
            # Skip if already in scope
            if user in in_scope:
                continue
            
            # If directly configured in extraction.databases, add to scope
            if user_name in root_items:
                logger.debug(f"Adding user directly: {user_name}")
                in_scope.append(user)
                owners_in_scope.add(user_name)
                continue
            
            # Check if user is owned by a database/user in scope
            # This only works for Teradata users
            if not isinstance(user.user_details, meta_model.DescribedTeradataUser):
                continue
            
            owner_name = user.user_details.owner_name.upper() if user.user_details.owner_name else ""
            
            # If owner is in scope, add user
            if owner_name and owner_name in owners_in_scope:
                logger.debug(f"Adding user, owner is in scope: {user_name} (owner: {owner_name})")
                in_scope.append(user)
                owners_in_scope.add(user_name)
        
        # Stop when no new users are added
        logger.debug(f"Iteration {i}: {len(in_scope)} users in scope")
        if prev_len == len(in_scope):
            break
    
    return in_scope
