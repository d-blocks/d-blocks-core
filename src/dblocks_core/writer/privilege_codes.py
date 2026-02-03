"""
Privilege code mapping and filtering for Teradata.
Handles decoding privilege abbreviations and filtering out self-privileges.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class PrivilegeInfo:
    """Information about a Teradata privilege."""
    name: str  # Full name (e.g., "SELECT")
    code: str  # Abbreviation (e.g., "R")
    is_creator_self_privilege: bool  # Automatically granted to creators
    is_created_self_privilege: bool  # Automatically granted to created user/database


# Privilege code mapping from Teradata documentation
PRIVILEGE_CODE_MAP = {
    # Privilege mapping: Code -> (Name, is_creator_self, is_created_self)
    "AS": ("ABORT SESSION", False, False),
    "AE": ("ALTER EXTERNAL PROCEDURE", False, False),
    "AF": ("ALTER FUNCTION", False, False),
    "AP": ("ALTER PROCEDURE", False, False),
    "AN": ("ANY", True, True),
    "CP": ("CHECKPOINT", True, True),
    "SA": ("CONSTRAINT ASSIGNMENT", False, False),
    "SD": ("CONSTRAINT DEFINITION", False, False),
    "CA": ("CREATE AUTHORIZATION", True, True),
    "CD": ("CREATE DATABASE", True, False),
    "C1": ("CREATE DATASET SCHEMA", False, False),
    "CE": ("CREATE EXTERNAL PROCEDURE", False, False),
    "CF": ("CREATE FUNCTION", False, False),
    "GC": ("CREATE GLOP", False, False),
    "CM": ("CREATE MACRO", True, True),
    "MC": ("CREATE MAP", False, False),
    "OP": ("CREATE OWNER PROCEDURE", False, False),
    "PC": ("CREATE PROCEDURE", False, False),
    "CO": ("CREATE PROFILE", False, False),
    "CR": ("CREATE ROLE", False, False),
    "CS": ("CREATE SERVER", False, False),
    "CT": ("CREATE TABLE", True, True),
    "CG": ("CREATE TRIGGER", True, True),
    "CU": ("CREATE USER", True, False),
    "CV": ("CREATE VIEW", True, True),
    "CZ": ("CREATE ZONE", False, False),
    "TH": ("CTCONTROL", False, False),
    "D": ("DELETE", True, True),
    "DA": ("DROP AUTHORIZATION", True, True),
    "DD": ("DROP DATABASE", True, False),
    "D1": ("DROP DATASET SCHEMA", True, False),
    "DF": ("DROP FUNCTION", True, True),
    "GD": ("DROP GLOP", False, False),
    "DM": ("DROP MACRO", True, True),
    "MD": ("DROP MAP", False, False),
    "PD": ("DROP PROCEDURE", True, True),
    "DO": ("DROP PROFILE", False, False),
    "DR": ("DROP ROLE", False, False),
    "DS": ("DROP SERVER", False, False),
    "DT": ("DROP TABLE", True, True),
    "DG": ("DROP TRIGGER", True, True),
    "DU": ("DROP USER", True, False),
    "DV": ("DROP VIEW", True, True),
    "DZ": ("DROP ZONE", False, False),
    "DP": ("DUMP", True, True),
    "E": ("EXECUTE", True, True),
    "EF": ("EXECUTE FUNCTION", False, False),
    "PE": ("EXECUTE PROCEDURE", False, False),
    "GM": ("GLOP MEMBER", False, False),
    "IX": ("INDEX", False, False),
    "I": ("INSERT", True, True),
    "MR": ("MONITOR RESOURCE", False, False),
    "MS": ("MONITOR SESSION", False, False),
    "NT": ("NONTEMPORAL", False, False),
    "OD": ("OVERRIDE DELETE", False, False),
    "OA": ("OVERRIDE DUMP", False, False),
    "OI": ("OVERRIDE INSERT", False, False),
    "OR": ("OVERRIDE RESTORE", False, False),
    "OS": ("OVERRIDE SELECT", False, False),
    "OU": ("OVERRIDE UPDATE", False, False),
    "RF": ("REFERENCES", False, False),
    "RS": ("RESTORE", True, True),
    "R": ("SELECT", True, True),
    "SR": ("SET RESOURCE RATE", False, False),
    "SS": ("SET SESSION RATE", False, False),
    "SH": ("SHOW", False, False),
    "ST": ("STATISTICS", True, True),
    "UM": ("UDT METHOD", False, False),
    "UT": ("UDT TYPE", False, False),
    "UU": ("UDT USAGE", False, False),
    "U": ("UPDATE", True, True),
    "W1": ("WITH DATASET SCHEMA", True, False),
    "ZO": ("ZONE OVERRIDE", False, False),
}


def decode_privilege(code: str) -> str:
    """
    Decode privilege code to full name.
    
    Args:
        code: Privilege code (e.g., "R", "I", "D")
        
    Returns:
        Full privilege name (e.g., "SELECT", "INSERT", "DELETE")
    """
    if code in PRIVILEGE_CODE_MAP:
        return PRIVILEGE_CODE_MAP[code][0]
    return code  # Return code if not found


def is_self_privilege(code: str, grantee_name: str, object_name: str) -> bool:
    """
    Check if a privilege is a self-privilege (automatically granted).
    
    A privilege is a self-privilege if:
    - It's marked as automatically granted to created user/database (column 4 in reference)
    - AND the grantee is the same as the object (self-reference)
    
    Args:
        code: Privilege code
        grantee_name: Name of the grantee (user/database receiving privilege)
        object_name: Name of the object (database/table the privilege is on)
        
    Returns:
        True if this is a self-privilege that should be filtered out
    """
    if code not in PRIVILEGE_CODE_MAP:
        return False
    
    _, _, is_created_self = PRIVILEGE_CODE_MAP[code]
    
    # Self-privilege if:
    # 1. It's marked as automatically granted to created user/database
    # 2. The grantee is the same as the object database (or object itself if "All")
    if is_created_self and grantee_name.upper() == object_name.upper():
        return True
    
    return False


def get_privilege_info(code: str) -> PrivilegeInfo:
    """
    Get full information about a privilege code.
    
    Args:
        code: Privilege code
        
    Returns:
        PrivilegeInfo object with decoded information
    """
    if code in PRIVILEGE_CODE_MAP:
        name, is_creator_self, is_created_self = PRIVILEGE_CODE_MAP[code]
        return PrivilegeInfo(
            name=name,
            code=code,
            is_creator_self_privilege=is_creator_self,
            is_created_self_privilege=is_created_self
        )
    else:
        return PrivilegeInfo(
            name=code,
            code=code,
            is_creator_self_privilege=False,
            is_created_self_privilege=False
        )
