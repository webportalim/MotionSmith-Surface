"""Package MotionSmith Surface addon into a clean, distributable ZIP file."""

import os
import zipfile
from pathlib import Path


def package_addon(output_zip: str = "motionsmith_surface.zip"):
    root = Path(__file__).resolve().parent
    addon_dir = root / "addon" / "motionsmith_surface"
    output_path = root / output_zip

    if not addon_dir.is_dir():
        raise FileNotFoundError(f"Addon directory not found: {addon_dir}")

    # Exclusions
    exclude_dirs = {"__pycache__", ".git", ".idea", ".vscode"}
    exclude_exts = {".pyc", ".pyo", ".pyd"}

    print(f"Packaging addon from: {addon_dir}")
    print(f"Creating release archive: {output_path}")

    files_added = 0
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root_dir, dirs, files in os.walk(addon_dir):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            for file in files:
                if any(file.endswith(ext) for ext in exclude_exts) or file.startswith("."):
                    continue
                file_path = Path(root_dir) / file
                rel_path = file_path.relative_to(addon_dir)
                archive_name = Path("motionsmith_surface") / rel_path
                zf.write(file_path, arcname=str(archive_name))
                files_added += 1

    # Verify integrity
    with zipfile.ZipFile(output_path, "r") as zf:
        bad_file = zf.testzip()
        if bad_file:
            raise RuntimeError(f"Corrupt file in ZIP: {bad_file}")

    print(f"SUCCESS: Packaged {files_added} files into '{output_zip}'. Integrity verified.")


if __name__ == "__main__":
    package_addon()
