import shutil
from pathlib import Path
from tempfile import mkdtemp


class AssetStorage:
    def __init__(self, root: str):
        self.root = Path(root).resolve()

    def prepare(self, asset_id: str, files):
        temporary_root = self.root / ".temporary"
        temporary_root.mkdir(parents=True, exist_ok=True)
        temporary = Path(mkdtemp(dir=temporary_root))
        try:
            for _, filename, _, _, data in files:
                (temporary / filename).write_bytes(data)
            temporary.rename(self.root / asset_id)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    def remove(self, asset_id: str):
        target = self.root / asset_id
        if target.exists():
            shutil.rmtree(target)

    def maintain(self, registered: set[str]):
        self.root.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(self.root / ".temporary", ignore_errors=True)
        for directory in self.root.iterdir():
            if directory.is_dir() and directory.name not in registered:
                shutil.rmtree(directory)
