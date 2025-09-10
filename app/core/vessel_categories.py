"""
Vessel category mapping service for AIS data.
Maps shipCargoType codes to human-readable categories based on the AIS Type Code list.
"""

from typing import Dict, Optional, Tuple
import logging
import pandas as pd

logger = logging.getLogger(__name__)

# AIS Type Code to Category mapping based on the provided list
AIS_TYPE_CATEGORIES = {
    # Reserved/Default (0-18)
    0: "Not Available",
    1: "Reserved",
    2: "Reserved", 
    3: "Reserved",
    4: "Reserved",
    5: "Reserved",
    6: "Reserved",
    7: "Reserved",
    8: "Reserved",
    9: "Reserved",
    10: "Reserved",
    11: "Reserved",
    12: "Reserved",
    13: "Reserved",
    14: "Reserved",
    15: "Reserved",
    16: "Reserved",
    17: "Reserved",
    18: "Reserved",
    
    # Wing in Ground - WIG Vessels (19-28)
    19: "WIG Vessel",
    20: "WIG Vessel (Hazardous A)",
    21: "WIG Vessel (Hazardous B)",
    22: "WIG Vessel (Hazardous C)",
    23: "WIG Vessel (Hazardous D)",
    24: "WIG Vessel (Reserved)",
    25: "WIG Vessel (Reserved)",
    26: "WIG Vessel (Reserved)",
    27: "WIG Vessel (Reserved)",
    28: "WIG Vessel (Reserved)",
    
    # Operational Status/General Vessel Types (29-36)
    29: "Fishing",
    30: "Towing",
    31: "Towing (Large)",
    32: "Dredging/Underwater Ops",
    33: "Diving Ops",
    34: "Military Ops",
    35: "Sailing",
    36: "Pleasure Craft",
    
    # Reserved (37-38)
    37: "Reserved",
    38: "Reserved",
    
    # High Speed Craft - HSC (39-48)
    39: "High Speed Craft",
    40: "HSC (Hazardous A)",
    41: "HSC (Hazardous B)",
    42: "HSC (Hazardous C)",
    43: "HSC (Hazardous D)",
    44: "HSC (Reserved)",
    45: "HSC (Reserved)",
    46: "HSC (Reserved)",
    47: "HSC (Reserved)",
    48: "HSC (No Additional Info)",
    
    # Special Purpose Vessels/Noncombatant (49-58)
    49: "Pilot Vessel",
    50: "Search and Rescue",
    51: "Tug",
    52: "Port Tender",
    53: "Anti-pollution Equipment",
    54: "Law Enforcement",
    55: "Local Vessel",
    56: "Local Vessel",
    57: "Medical Transport",
    58: "Noncombatant Ship",
    
    # Passenger Vessels (59-68)
    59: "Passenger",
    60: "Passenger (Hazardous A)",
    61: "Passenger (Hazardous B)",
    62: "Passenger (Hazardous C)",
    63: "Passenger (Hazardous D)",
    64: "Passenger (Reserved)",
    65: "Passenger (Reserved)",
    66: "Passenger (Reserved)",
    67: "Passenger (Reserved)",
    68: "Passenger (No Additional Info)",
    
    # Cargo Vessels (69-78)
    69: "Cargo",
    70: "Cargo (Hazardous A)",
    71: "Cargo (Hazardous B)",
    72: "Cargo (Hazardous C)",
    73: "Cargo (Hazardous D)",
    74: "Cargo (Reserved)",
    75: "Cargo (Reserved)",
    76: "Cargo (Reserved)",
    77: "Cargo (Reserved)",
    78: "Cargo (No Additional Info)",
    
    # Tanker Vessels (79-88)
    79: "Tanker",
    80: "Tanker (Hazardous A)",
    81: "Tanker (Hazardous B)",
    82: "Tanker (Hazardous C)",
    83: "Tanker (Hazardous D)",
    84: "Tanker (Reserved)",
    85: "Tanker (Reserved)",
    86: "Tanker (Reserved)",
    87: "Tanker (Reserved)",
    88: "Tanker (No Additional Info)",
    
    # Other Type Vessels (89-98)
    89: "Other Type",
    90: "Other Type (Hazardous A)",
    91: "Other Type (Hazardous B)",
    92: "Other Type (Hazardous C)",
    93: "Other Type (Hazardous D)",
    94: "Other Type (Reserved)",
    95: "Other Type (Reserved)",
    96: "Other Type (Reserved)",
    97: "Other Type (Reserved)",
    98: "Other Type (No Additional Info)",
}

# Simplified category groups for better UI display
CATEGORY_GROUPS = {
    "Fishing": ["Fishing"],
    "Commercial": ["Cargo", "Tanker", "Passenger", "Towing", "Towing (Large)"],
    "Special": ["Pilot Vessel", "Search and Rescue", "Tug", "Port Tender", "Anti-pollution Equipment", "Law Enforcement", "Medical Transport"],
    "Recreational": ["Sailing", "Pleasure Craft"],
    "Military": ["Military Ops", "Noncombatant Ship"],
    "High Speed": ["High Speed Craft", "HSC (Hazardous A)", "HSC (Hazardous B)", "HSC (Hazardous C)", "HSC (Hazardous D)", "HSC (No Additional Info)"],
    "WIG": ["WIG Vessel", "WIG Vessel (Hazardous A)", "WIG Vessel (Hazardous B)", "WIG Vessel (Hazardous C)", "WIG Vessel (Hazardous D)"],
    "Operations": ["Dredging/Underwater Ops", "Diving Ops"],
    "Local": ["Local Vessel"],
    "Unknown": ["Not Available", "Reserved", "Other Type", "Other Type (No Additional Info)"]
}

# Color coding for different vessel types
CATEGORY_COLORS = {
    "Fishing": "primary",
    "Commercial": "success", 
    "Special": "info",
    "Recreational": "secondary",
    "Military": "warning",
    "High Speed": "danger",
    "WIG": "dark",
    "Operations": "light",
    "Local": "outline-secondary",
    "Unknown": "secondary"
}

# Hazardous cargo indicators
HAZARDOUS_INDICATORS = ["Hazardous A", "Hazardous B", "Hazardous C", "Hazardous D"]


def get_vessel_category(ship_cargo_type: Optional[int]) -> Tuple[str, str, str]:
    """
    Get vessel category information from shipCargoType code.
    
    Args:
        ship_cargo_type: The shipCargoType code from AIS data
        
    Returns:
        Tuple of (category, group, color) for display
    """
    if ship_cargo_type is None or pd.isna(ship_cargo_type):
        return "Unknown", "Unknown", "secondary"
    
    try:
        ship_cargo_type = int(ship_cargo_type)
        category = AIS_TYPE_CATEGORIES.get(ship_cargo_type, "Unknown")
        
        # Find the group this category belongs to
        group = "Unknown"
        for group_name, categories in CATEGORY_GROUPS.items():
            if any(cat in category for cat in categories):
                group = group_name
                break
        
        # Get color for the group
        color = CATEGORY_COLORS.get(group, "secondary")
        
        return category, group, color
        
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid shipCargoType value: {ship_cargo_type}, error: {e}")
        return "Unknown", "Unknown", "secondary"


def is_hazardous_vessel(ship_cargo_type: Optional[int]) -> bool:
    """
    Check if vessel carries hazardous cargo.
    
    Args:
        ship_cargo_type: The shipCargoType code from AIS data
        
    Returns:
        True if vessel carries hazardous cargo
    """
    if ship_cargo_type is None or pd.isna(ship_cargo_type):
        return False
    
    try:
        ship_cargo_type = int(ship_cargo_type)
        category = AIS_TYPE_CATEGORIES.get(ship_cargo_type, "")
        return any(indicator in category for indicator in HAZARDOUS_INDICATORS)
    except (ValueError, TypeError):
        return False


def get_ais_class_info(ais_class: Optional[str]) -> Tuple[str, str]:
    """
    Get AIS class information and styling.
    
    Args:
        ais_class: The aisClass from AIS data (A or B)
        
    Returns:
        Tuple of (class_display, color) for display
    """
    if ais_class is None or pd.isna(ais_class):
        return "Unknown", "secondary"
    
    ais_class = str(ais_class).upper().strip()
    
    if ais_class == "A":
        return "Class A", "primary"
    elif ais_class == "B":
        return "Class B", "info"
    else:
        return f"Class {ais_class}", "secondary"


def get_vessel_summary_stats(vessels: list) -> Dict[str, any]:
    """
    Generate summary statistics for a list of vessels.
    
    Args:
        vessels: List of vessel dictionaries
        
    Returns:
        Dictionary with summary statistics
    """
    if not vessels:
        return {
            "total_vessels": 0,
            "class_a_count": 0,
            "class_b_count": 0,
            "hazardous_count": 0,
            "category_breakdown": {},
            "group_breakdown": {}
        }
    
    stats = {
        "total_vessels": len(vessels),
        "class_a_count": 0,
        "class_b_count": 0,
        "hazardous_count": 0,
        "category_breakdown": {},
        "group_breakdown": {}
    }
    
    for vessel in vessels:
        # Count AIS classes
        ais_class = vessel.get("AISClass", "").upper().strip()
        if ais_class == "A":
            stats["class_a_count"] += 1
        elif ais_class == "B":
            stats["class_b_count"] += 1
        
        # Count hazardous vessels
        if vessel.get("IsHazardous", False):
            stats["hazardous_count"] += 1
        
        # Count categories
        category = vessel.get("Category", "Unknown")
        group = vessel.get("Group", "Unknown")
        
        stats["category_breakdown"][category] = stats["category_breakdown"].get(category, 0) + 1
        stats["group_breakdown"][group] = stats["group_breakdown"].get(group, 0) + 1
    
    return stats
