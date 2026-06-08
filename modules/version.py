import os
from datetime import datetime

def get_version() -> str:
    """Read full version from VERSION file"""
    version_file = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), 
        'VERSION'
    )
    
    try:
        with open(version_file, 'r', encoding='utf-8') as f:
            version = f.read().strip()
            if version:
                return version
    except Exception:
        pass  # Fall through to default

    # Fallback
    fallback = f"0.1.0.{datetime.now().strftime('%d%m%y')}"
    print(f"⚠️ Using fallback version: {fallback}")
    return fallback


def get_version_dict():
    """Return version breakdown"""
    full = get_version()
    parts = full.split('.')
    
    if len(parts) >= 4:
        major, minor, patch, date = parts[:4]
    else:
        major, minor, patch = parts[:3]
        date = datetime.now().strftime('%d%m%y')
    
    return {
        "major": int(major),
        "minor": int(minor),
        "patch": int(patch),
        "date": date,
        "full": full,
        "base": f"{major}.{minor}.{patch}"
    }


# What app.py imports
APP_VERSION = get_version()
VERSION = get_version_dict()


if __name__ == "__main__":
    print(f"APP_VERSION = {APP_VERSION}")
    print(f"VERSION = {VERSION}")
