import argparse
import json
import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import py7zr

from echo_commons.app.settings import load_settings
from echo_commons.infrastructure.game_analysis.rapfi.contracts import release_manifest


def install(settings_path: Path, archive_path: Path | None = None) -> Path:
    settings = load_settings(settings_path).game_analysis.rapfi
    executable = settings.executable_path()
    destination = executable.parent
    manifest = release_manifest()
    record = destination / "installation.json"
    if record.exists():
        installed = json.loads(record.read_text(encoding="utf-8"))
        if installed["release"] == manifest["release"] and all(
            (destination / name).is_file()
            for name in (*manifest["files"], executable.name, "Copying.txt")
        ):
            return executable
        raise ValueError("The existing Rapfi installation is incomplete; choose an empty directory")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Rapfi installation requires an empty destination directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="rapfi-install-", dir=destination.parent) as temporary:
        stage = Path(temporary)
        with httpx.Client(follow_redirects=True, timeout=120) as client:
            if archive_path is None:
                archive_path = stage / "engine.7z"
                with client.stream("GET", manifest["archive_url"]) as response:
                    response.raise_for_status()
                    with archive_path.open("wb") as handle:
                        for chunk in response.iter_bytes():
                            handle.write(chunk)
            unpacked = stage / "unpacked"
            targets = [*manifest["files"], executable.name]
            with py7zr.SevenZipFile(archive_path) as archive:
                if not set(targets) <= set(archive.getnames()):
                    raise ValueError("The archive does not contain the configured Rapfi resources")
                archive.extract(path=unpacked, targets=targets)
            license_text = client.get(manifest["license_url"])
            license_text.raise_for_status()
            (unpacked / "Copying.txt").write_bytes(license_text.content)
        (unpacked / "installation.json").write_text(
            json.dumps(
                {
                    "release": manifest["release"],
                    "archive_url": manifest["archive_url"],
                    "source_url": manifest["source_url"],
                    "executable": executable.name,
                    "weight": manifest["weight"],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        if os.name != "nt":
            (unpacked / executable.name).chmod(0o755)
        destination.mkdir(exist_ok=True)
        for item in unpacked.iterdir():
            shutil.move(str(item), destination / item.name)
    return executable


def main() -> None:
    parser = argparse.ArgumentParser(description="安装固定版本 Rapfi 及配套权重")
    parser.add_argument("--settings", type=Path, default=Path("config/settings.toml"))
    parser.add_argument("--archive", type=Path, help="使用已经下载的官方发布包")
    arguments = parser.parse_args()
    print(install(arguments.settings, arguments.archive))


if __name__ == "__main__":
    main()
