import json
import sys
from pathlib import Path

import uvicorn

from echo_commons.app.main import create_app
from echo_commons.app.settings import Settings

if __name__ == "__main__":
    settings = Settings.model_validate(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    uvicorn.run(create_app(settings), host="127.0.0.1", port=int(sys.argv[2]), log_level="warning")
