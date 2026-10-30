"""Fail a build before invalid committed client snapshots reach production."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from blueprints.featured import catalog
from blueprints.launcher import launcher_manifest
from blueprints.launcher_project import launcher_project_snapshot
from blueprints.launcher_release import launcher_release_manifest
from blueprints.version import get_version_info
from utils.json_data import load_json_file


def main():
    get_version_info()
    launcher_manifest()
    launcher_project_snapshot()
    launcher_release_manifest()
    catalog()
    sponsors = load_json_file("sponsors.json")
    names = sponsors.get("sponsors") if isinstance(sponsors, dict) else sponsors
    if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
        raise ValueError("Invalid sponsors snapshot")
    print("Validated DIY version, launcher notifications, launcher project, stable launcher release, featured catalog and sponsors snapshots.")


if __name__ == "__main__":
    main()
