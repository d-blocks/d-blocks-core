"""
Writer for environment definitions (databases, users, roles, profiles, privileges).
Handles writing environment structures to TOML configuration files.
"""

import sys
if sys.version_info < (3, 11):
    import tomli as tomllib
else:
    import tomllib

from pathlib import Path
from typing import Any, Optional
from collections import defaultdict

from dblocks_core.config.config import logger
from dblocks_core.model import config_model, meta_model
from dblocks_core.writer import privilege_codes
from dblocks_core import tagger as tagger_module


def _dict_to_toml_string(data: dict[str, Any]) -> str:
    """
    Convert a dictionary to TOML string format.
    
    Args:
        data: Dictionary to convert
        
    Returns:
        TOML formatted string
    """
    try:
        # Try using tomli_w if available
        import tomli_w
        return tomli_w.dumps(data)
    except ImportError:
        # Fallback: use manual TOML formatting
        lines = []
        for key, value in data.items():
            if value is None:
                continue
            elif isinstance(value, str):
                lines.append(f'{key} = "{value}"')
            elif isinstance(value, bool):
                lines.append(f'{key} = {str(value).lower()}')
            elif isinstance(value, (int, float)):
                lines.append(f'{key} = {value}')
            elif isinstance(value, list):
                if all(isinstance(item, str) for item in value):
                    items_str = ", ".join([f'"{item}"' for item in value])
                    lines.append(f'{key} = [{items_str}]')
                else:
                    lines.append(f'{key} = {value}')
            elif isinstance(value, dict):
                # Handle nested dicts (for privileges)
                lines.append(f'[[{key}]]')
                for k, v in value.items():
                    if isinstance(v, str):
                        lines.append(f'{k} = "{v}"')
                    elif isinstance(v, bool):
                        lines.append(f'{k} = {str(v).lower()}')
                    else:
                        lines.append(f'{k} = {v}')
        return '\n'.join(lines)


class EnvDefWriter:
    """
    Writer for environment definitions to TOML files.
    """
    
    def __init__(self, base_dir: Path, encoding: str = "utf-8"):
        """
        Initialize the environment definition writer.
        
        Args:
            base_dir: Base directory for environment definitions
            encoding: File encoding (default: utf-8)
        """
        self.base_dir = Path(base_dir)
        self.encoding = encoding
        
        # Create subdirectories
        self.databases_dir = self.base_dir / "databases"
        self.users_dir = self.base_dir / "users"
        self.roles_dir = self.base_dir / "roles"
        self.profiles_dir = self.base_dir / "profiles"
        self.privileges_dir = self.base_dir / "privileges"
        self.privileges_roles_dir = self.privileges_dir / "roles"
        self.privileges_users_dir = self.privileges_dir / "users"
        self.privileges_databases_dir = self.privileges_dir / "databases"
        
    def _ensure_dir(self, directory: Path):
        """Ensure directory exists."""
        directory.mkdir(parents=True, exist_ok=True)
        
    def _sanitize_filename(self, name: str) -> str:
        """
        Sanitize a name to be used as a filename.
        
        Args:
            name: Object name
            
        Returns:
            Sanitized filename
        """
        # Replace special characters
        sanitized = name.replace('"', '').replace('/', '_').replace('\\', '_')
        return sanitized.lower()
        
    def write_database(self, db_def: meta_model.DescribedDatabase, tagger: tagger_module.Tagger | None = None):
        """
        Write database definition to TOML file.
        
        Merges with existing TOML file if present, preserving manual configurations
        like only_in and not_only_in.
        
        Args:
            db_def: DescribedDatabase from meta_model
            tagger: Optional Tagger for making names environment-agnostic
        """
        self._ensure_dir(self.databases_dir)
        
        # Tag database name if tagger provided
        db_name = db_def.database_name
        tagged_name = tagger.tag_database(db_name) if tagger else db_name
        
        filename = f"{self._sanitize_filename(tagged_name)}.toml"
        filepath = self.databases_dir / filename
        
        # Load existing TOML file if it exists (to preserve manual configurations)
        existing_data = {}
        if filepath.exists():
            try:
                with open(filepath, "rb") as f:
                    existing_data = tomllib.load(f)
                logger.debug(f"Loaded existing database definition: {filepath}")
            except Exception as e:
                logger.warning(f"Failed to load existing database definition {filepath}: {e}")
        
        # Determine kind from db_kind
        kind = "database" if (db_def.database_details and db_def.database_details.db_kind == "D") else "user"
        
        # Build new data from extraction
        data = {
            "name": tagged_name,
            "kind": kind,
        }
        
        if db_def.database_details:
            owner_name = db_def.database_details.owner_name
            data["owner"] = tagger.tag_database(owner_name) if tagger and owner_name else owner_name
            if db_def.database_details.perm_space is not None:
                data["perm_space"] = str(db_def.database_details.perm_space)
            if db_def.database_details.spool_space is not None:
                data["spool_space"] = str(db_def.database_details.spool_space)
            # TEMP space is only valid for users, not databases
            if kind == "user" and db_def.database_details.temp_space is not None:
                data["temp_space"] = str(db_def.database_details.temp_space)
        
        if db_def.comment_string:
            data["comment"] = db_def.comment_string
        
        # Merge: preserve only_in and not_only_in from existing file
        if "only_in" in existing_data:
            data["only_in"] = existing_data["only_in"]
            logger.debug(f"Preserved only_in: {data['only_in']} for {tagged_name}")
        if "not_only_in" in existing_data:
            data["not_only_in"] = existing_data["not_only_in"]
            logger.debug(f"Preserved not_only_in: {data['not_only_in']} for {tagged_name}")
            
        try:
            import tomli_w
            toml_str = tomli_w.dumps(data)
        except ImportError:
            toml_str = _dict_to_toml_string(data)
            
        filepath.write_text(toml_str, encoding=self.encoding)
        logger.debug(f"Wrote database definition: {filepath}")
        
    def write_user(self, user_def: meta_model.DescribedUser, tagger: tagger_module.Tagger | None = None):
        """
        Write user definition to TOML file.
        
        Merges with existing TOML file if present, preserving manual configurations
        like only_in and not_only_in.
        
        Args:
            user_def: DescribedUser from meta_model
            tagger: Optional Tagger for making names environment-agnostic
        """
        self._ensure_dir(self.users_dir)
        
        # Tag user name if tagger provided
        user_name = user_def.user_name
        tagged_name = tagger.tag_database(user_name) if tagger else user_name
        
        filename = f"{self._sanitize_filename(tagged_name)}.toml"
        filepath = self.users_dir / filename
        
        # Load existing TOML file if it exists (to preserve manual configurations)
        existing_data = {}
        if filepath.exists():
            try:
                with open(filepath, "rb") as f:
                    existing_data = tomllib.load(f)
                logger.debug(f"Loaded existing user definition: {filepath}")
            except Exception as e:
                logger.warning(f"Failed to load existing user definition {filepath}: {e}")
        
        # Build new data from extraction
        data = {
            "name": tagged_name,
            "kind": "user",
        }
        
        if user_def.user_details:
            owner_name = user_def.user_details.owner_name
            data["owner"] = tagger.tag_database(owner_name) if tagger and owner_name else owner_name
            if user_def.user_details.perm_space is not None:
                data["perm_space"] = str(user_def.user_details.perm_space)
            if user_def.user_details.spool_space is not None:
                data["spool_space"] = str(user_def.user_details.spool_space)
            if user_def.user_details.temp_space is not None:
                data["temp_space"] = str(user_def.user_details.temp_space)
            if user_def.user_details.default_database:
                default_db = user_def.user_details.default_database
                data["default_database"] = tagger.tag_database(default_db) if tagger else default_db
            if user_def.user_details.profile:
                profile = user_def.user_details.profile
                data["profile"] = tagger.tag_database(profile) if tagger else profile
            if user_def.user_details.account:
                data["account"] = user_def.user_details.account
        
        if user_def.password:
            data["password"] = user_def.password
        if user_def.comment_string:
            data["comment"] = user_def.comment_string
        
        # Merge: preserve only_in and not_only_in from existing file
        if "only_in" in existing_data:
            data["only_in"] = existing_data["only_in"]
            logger.debug(f"Preserved only_in: {data['only_in']} for {tagged_name}")
        if "not_only_in" in existing_data:
            data["not_only_in"] = existing_data["not_only_in"]
            logger.debug(f"Preserved not_only_in: {data['not_only_in']} for {tagged_name}")
            
        try:
            import tomli_w
            toml_str = tomli_w.dumps(data)
        except ImportError:
            toml_str = _dict_to_toml_string(data)
            
        filepath.write_text(toml_str, encoding=self.encoding)
        logger.debug(f"Wrote user definition: {filepath}")
        
    def write_role(self, role_def: meta_model.DescribedRole, tagger: tagger_module.Tagger | None = None):
        """
        Write role definition to TOML file.
        
        Merges with existing TOML file if present, preserving manual configurations
        like only_in and not_only_in.
        
        Args:
            role_def: DescribedRole from meta_model
            tagger: Optional Tagger for making names environment-agnostic
        """
        self._ensure_dir(self.roles_dir)
        
        # Tag role name if tagger provided
        role_name = role_def.role_name
        tagged_name = tagger.tag_database(role_name) if tagger else role_name
        
        filename = f"{self._sanitize_filename(tagged_name)}.toml"
        filepath = self.roles_dir / filename
        
        # Load existing TOML file if it exists (to preserve manual configurations)
        existing_data = {}
        if filepath.exists():
            try:
                with open(filepath, "rb") as f:
                    existing_data = tomllib.load(f)
                logger.debug(f"Loaded existing role definition: {filepath}")
            except Exception as e:
                logger.warning(f"Failed to load existing role definition {filepath}: {e}")
        
        # Build new data from extraction
        data = {
            "name": tagged_name,
            "kind": "role",
        }
        
        if role_def.comment_string:
            data["comment"] = role_def.comment_string
        
        # Merge: preserve only_in and not_only_in from existing file
        if "only_in" in existing_data:
            data["only_in"] = existing_data["only_in"]
            logger.debug(f"Preserved only_in: {data['only_in']} for {tagged_name}")
        if "not_only_in" in existing_data:
            data["not_only_in"] = existing_data["not_only_in"]
            logger.debug(f"Preserved not_only_in: {data['not_only_in']} for {tagged_name}")
            
        try:
            import tomli_w
            toml_str = tomli_w.dumps(data)
        except ImportError:
            toml_str = _dict_to_toml_string(data)
            
        filepath.write_text(toml_str, encoding=self.encoding)
        logger.debug(f"Wrote role definition: {filepath}")
        
    def write_profile(self, profile_def: meta_model.DescribedProfile, tagger: tagger_module.Tagger | None = None):
        """
        Write profile definition to TOML file.
        
        Merges with existing TOML file if present, preserving manual configurations
        like only_in and not_only_in.
        
        Args:
            profile_def: DescribedProfile from meta_model
            tagger: Optional Tagger for making names environment-agnostic
        """
        self._ensure_dir(self.profiles_dir)
        
        # Tag profile name if tagger provided
        profile_name = profile_def.profile_name
        tagged_name = tagger.tag_database(profile_name) if tagger else profile_name
        
        filename = f"{self._sanitize_filename(tagged_name)}.toml"
        filepath = self.profiles_dir / filename
        
        # Load existing TOML file if it exists (to preserve manual configurations)
        existing_data = {}
        if filepath.exists():
            try:
                with open(filepath, "rb") as f:
                    existing_data = tomllib.load(f)
                logger.debug(f"Loaded existing profile definition: {filepath}")
            except Exception as e:
                logger.warning(f"Failed to load existing profile definition {filepath}: {e}")
        
        # Build new data from extraction
        data = {
            "name": tagged_name,
            "kind": "profile",
        }
        
        if profile_def.profile_details:
            if profile_def.profile_details.spool_space is not None:
                data["spool_space"] = str(profile_def.profile_details.spool_space)
            if profile_def.profile_details.temp_space is not None:
                data["temp_space"] = str(profile_def.profile_details.temp_space)
            if profile_def.profile_details.account:
                data["account"] = profile_def.profile_details.account
            if profile_def.profile_details.default_database:
                default_db = profile_def.profile_details.default_database
                data["default_database"] = tagger.tag_database(default_db) if tagger else default_db
        
        if profile_def.comment_string:
            data["comment"] = profile_def.comment_string
        
        # Merge: preserve only_in and not_only_in from existing file
        if "only_in" in existing_data:
            data["only_in"] = existing_data["only_in"]
            logger.debug(f"Preserved only_in: {data['only_in']} for {tagged_name}")
        if "not_only_in" in existing_data:
            data["not_only_in"] = existing_data["not_only_in"]
            logger.debug(f"Preserved not_only_in: {data['not_only_in']} for {tagged_name}")
            
        try:
            import tomli_w
            toml_str = tomli_w.dumps(data)
        except ImportError:
            toml_str = _dict_to_toml_string(data)
            
        filepath.write_text(toml_str, encoding=self.encoding)
        logger.debug(f"Wrote profile definition: {filepath}")
        
    def write_privileges(self, priv_def: meta_model.DescribedPrivileges, tagger: Optional[tagger_module.Tagger] = None):
        """
        Write privileges to TOML file in grouped format.
        
        Privileges are grouped by object_database and split into:
        - privileges: List of privilege names without grant option
        - privileges_with_grant_option: List of privilege names with grant option
        
        Self-privileges (automatically granted) are filtered out.
        
        Args:
            priv_def: DescribedPrivileges from meta_model
            tagger: Optional tagger for environment-agnostic names
        """
        # Tag grantee name if tagger available
        grantee_name = tagger.tag_database(priv_def.grantee_name) if tagger else priv_def.grantee_name
        
        # Determine subdirectory based on grantee type
        if priv_def.grantee_type == "role":
            target_dir = self.privileges_roles_dir
        elif priv_def.grantee_type == "user":
            target_dir = self.privileges_users_dir
        elif priv_def.grantee_type == "database":
            target_dir = self.privileges_databases_dir
        else:
            logger.warning(f"Unknown grantee type: {priv_def.grantee_type}")
            return
            
        self._ensure_dir(target_dir)
        
        filename = f"{self._sanitize_filename(grantee_name)}.toml"
        filepath = target_dir / filename
        
        # Group privileges by object_database
        # Structure: {object_database: {object_name: {priv_name: grantable}}}
        grouped_privileges = defaultdict(lambda: defaultdict(dict))
        
        for priv in priv_def.privileges:
            # Decode privilege code to full name
            priv_name = privilege_codes.decode_privilege(priv.privilege_type)
            
            # Skip self-privileges (automatically granted)
            object_db = priv.object_database if priv.object_database else ""
            if privilege_codes.is_self_privilege(
                priv.privilege_type,
                priv_def.grantee_name,
                object_db
            ):
                logger.debug(f"Skipping self-privilege: {priv_name} on {object_db} for {priv_def.grantee_name}")
                continue
            
            # Use object_name or "All" if not specified
            obj_name = priv.object_name if priv.object_name else "All"
            
            # Store privilege with grantable flag
            grouped_privileges[object_db][obj_name][priv_name] = priv.grantable
        
        # Build TOML data structure
        data = {
            "grantee_name": grantee_name,
            "grantee_type": priv_def.grantee_type,
            "kind": "privileges",
        }
        
        # Create grant blocks for each object_database
        grant_blocks = []
        for object_db in sorted(grouped_privileges.keys()):
            for obj_name in sorted(grouped_privileges[object_db].keys()):
                privs_dict = grouped_privileges[object_db][obj_name]
                
                # Separate privileges by grantable flag
                privs_without_grant = sorted([
                    name for name, grantable in privs_dict.items() if not grantable
                ])
                privs_with_grant = sorted([
                    name for name, grantable in privs_dict.items() if grantable
                ])
                
                grant_block = {}
                if object_db:
                    # Tag database name if tagger available
                    tagged_db = tagger.tag_database(object_db) if tagger else object_db
                    grant_block["database"] = tagged_db
                if obj_name and obj_name != "All":
                    grant_block["object"] = obj_name
                
                if privs_without_grant:
                    grant_block["privileges"] = privs_without_grant
                if privs_with_grant:
                    grant_block["privileges_with_grant_option"] = privs_with_grant
                
                if grant_block:  # Only add if there are privileges
                    grant_blocks.append(grant_block)
        
        # Add grant blocks if any exist
        if grant_blocks:
            # Manual TOML formatting for better structure
            toml_lines = []
            toml_lines.append(f'grantee_name = "{data["grantee_name"]}"')
            toml_lines.append(f'grantee_type = "{data["grantee_type"]}"')
            toml_lines.append(f'kind = "{data["kind"]}"')
            toml_lines.append("")
            
            for grant_block in grant_blocks:
                toml_lines.append("[[grant]]")
                if "database" in grant_block:
                    toml_lines.append(f'database = "{grant_block["database"]}"')
                if "object" in grant_block:
                    toml_lines.append(f'object = "{grant_block["object"]}"')
                if "privileges" in grant_block:
                    privs_str = ", ".join([f'"{p}"' for p in grant_block["privileges"]])
                    toml_lines.append(f'privileges = [{privs_str}]')
                if "privileges_with_grant_option" in grant_block:
                    privs_str = ", ".join([f'"{p}"' for p in grant_block["privileges_with_grant_option"]])
                    toml_lines.append(f'privileges_with_grant_option = [{privs_str}]')
                toml_lines.append("")
            
            toml_str = "\n".join(toml_lines)
            filepath.write_text(toml_str, encoding=self.encoding)
            logger.debug(f"Wrote privileges definition: {filepath}")
        else:
            logger.debug(f"No privileges to write for {priv_def.grantee_name} (all were self-privileges)")

    def write_role_memberships(self, role_memberships: meta_model.DescribedRoleMemberships, tagger: Optional[tagger_module.Tagger] = None):
        """
        Write role memberships to user privileges TOML file, adding role grants to existing privileges.
        
        Role grants are added as [[grant]] blocks with role= instead of database=.
        
        Args:
            role_memberships: DescribedRoleMemberships from meta_model
            tagger: Optional tagger for environment-agnostic names
        """
        # Tag grantee name if tagger available
        grantee_name = tagger.tag_database(role_memberships.grantee_name) if tagger else role_memberships.grantee_name
        
        # Role memberships go in privileges/users/ directory
        target_dir = self.privileges_users_dir
        self._ensure_dir(target_dir)
        
        filename = f"{self._sanitize_filename(grantee_name)}.toml"
        filepath = target_dir / filename
        
        # Read existing file if it exists to append role grants
        existing_grants = []
        if filepath.exists():
            try:
                with open(filepath, "r", encoding=self.encoding) as f:
                    content = f.read()
                    # Extract existing [[grant]] blocks
                    if "[[grant]]" in content:
                        # Parse to preserve existing grants
                        import tomllib
                        with open(filepath, "rb") as fb:
                            existing_data = tomllib.load(fb)
                            if "grant" in existing_data:
                                existing_grants = existing_data["grant"]
            except Exception as e:
                logger.warning(f"Could not read existing file {filepath}: {e}")
        
        # Build TOML data structure
        data = {
            "grantee_name": grantee_name,
            "grantee_type": role_memberships.grantee_type,
            "kind": "privileges",
        }
        
        # Create grant blocks for roles
        role_grant_blocks = []
        for role_grant in sorted(role_memberships.role_grants, key=lambda r: r.role_name):
            grant_block = {
                "role": role_grant.role_name
            }
            
            # Add with_admin array based on flag
            if role_grant.with_admin:
                grant_block["with_admin"] = ["ADMIN"]
            
            role_grant_blocks.append(grant_block)
        
        # Merge with existing grants (privileges come first, then roles)
        all_grant_blocks = existing_grants + role_grant_blocks if existing_grants else role_grant_blocks
        
        if all_grant_blocks:
            # Manual TOML formatting
            toml_lines = []
            toml_lines.append(f'grantee_name = "{data["grantee_name"]}"')
            toml_lines.append(f'grantee_type = "{data["grantee_type"]}"')
            toml_lines.append(f'kind = "{data["kind"]}"')
            toml_lines.append("")
            
            # Write all grant blocks
            for grant_block in all_grant_blocks:
                toml_lines.append("[[grant]]")
                
                # Check if it's a role grant or privilege grant
                if "role" in grant_block:
                    toml_lines.append(f'role = "{grant_block["role"]}"')
                    if "with_admin" in grant_block:
                        admin_str = ", ".join([f'"{a}"' for a in grant_block["with_admin"]])
                        toml_lines.append(f'with_admin = [{admin_str}]')
                else:
                    # Existing privilege grant
                    if "database" in grant_block:
                        toml_lines.append(f'database = "{grant_block["database"]}"')
                    if "object" in grant_block:
                        toml_lines.append(f'object = "{grant_block["object"]}"')
                    if "privileges" in grant_block:
                        privs = grant_block["privileges"]
                        privs_str = ", ".join([f'"{p}"' for p in privs])
                        toml_lines.append(f'privileges = [{privs_str}]')
                    if "privileges_with_grant_option" in grant_block:
                        privs = grant_block["privileges_with_grant_option"]
                        privs_str = ", ".join([f'"{p}"' for p in privs])
                        toml_lines.append(f'privileges_with_grant_option = [{privs_str}]')
                
                toml_lines.append("")
            
            toml_str = "\n".join(toml_lines)
            filepath.write_text(toml_str, encoding=self.encoding)
            logger.debug(f"Wrote role memberships to: {filepath}")
        else:
            logger.debug(f"No role memberships to write for {role_memberships.grantee_name}")


def load_env_def_from_toml(filepath: Path) -> dict[str, Any]:
    """
    Load environment definition from TOML file.
    
    Args:
        filepath: Path to TOML file
        
    Returns:
        Dictionary with environment definition data
    """
    with open(filepath, "rb") as f:
        return tomllib.load(f)
