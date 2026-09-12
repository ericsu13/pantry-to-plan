"""Run one real OpenAI vision request against a fixture photo.

Prerequisites:
    export OPENAI_API_KEY="..."
    # Optional: export OPENAI_VISION_MODEL="gpt-5.6-luna"
    python examples/run_vision_live.py [optional-image-path]
"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vision import OpenAIVisionProvider, VisionPipelineError, parse_pantry_image  # noqa: E402


default_photo = ROOT / "fixtures" / "photos" / "01_well_stocked_veg_italian_messy.png"
photo = Path(sys.argv[1]) if len(sys.argv) > 1 else default_photo

try:
    result = parse_pantry_image(photo.read_bytes(), provider=OpenAIVisionProvider())
except VisionPipelineError as exc:
    print(exc.issue.model_dump_json(indent=2))
    raise SystemExit(1) from exc

print(result.model_dump_json(indent=2))
