import re


def validate_url(url: str) -> bool:
    """
    Validates the format of the given URL.

    Args:
        url (str): The URL to validate.

    Returns:
        bool: True if the URL is valid, False otherwise.
    """
    regex = re.compile(
        r"^(http|https)://"  # Protocol
        r"(([a-zA-Z0-9_-]+\.)+[a-zA-Z]{2,}|"  # Domain name
        r"localhost|"  # Or localhost
        r"\d{1,3}(\.\d{1,3}){3})"  # Or IPv4 address
        r"(:\d+)?"  # Optional port
        r"(/.*)?$"  # Optional path
    )
    return bool(regex.match(url))
