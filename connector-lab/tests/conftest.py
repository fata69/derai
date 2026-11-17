"""Allow lab tests to be selected from the repository root or the lab directory."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
