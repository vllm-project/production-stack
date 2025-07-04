"""Types and enums for PII detection."""

from enum import Enum


class PIIAction(Enum):
    """Action to take when PII is detected."""

    BLOCK = "block"
    # REDACT = "redact"  # To be implemented when request rewrite is supported


class PIITarget(Enum):
    """What to check for PII."""

    REQUEST = "request"
    RESPONSE = "response"  # For future use
    BOTH = "both"  # For future use


class PIIType(Enum):
    """Essential types of PII that can be detected."""

    # Personal Information
    EMAIL = "email"
    PHONE = "phone"
    SSN = "ssn"
    CREDIT_CARD = "credit_card"
    IP_ADDRESS = "ip_address"
    API_KEY = "api_key"

    # Financial Information
    BANK_ACCOUNT = "bank_account"

    # Government IDs
    PASSPORT = "passport"
    DRIVERS_LICENSE = "drivers_license"
    TAX_ID = "tax_id"

    # Healthcare
    MEDICAL_RECORD = "medical_record"
    HEALTH_INFO = "health_info"

    # Digital
    MAC_ADDRESS = "mac_address"

    # Other
    NAME = "name"
    DOB = "date_of_birth"
    PASSWORD = "password"
    USERNAME = "username"
    ADDRESS = "address"
