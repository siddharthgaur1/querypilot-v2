"""Render docs/injection-bench.svg from a real run of eval/injection_bench.py.

    git clone https://github.com/siddharthgaur1/query-injection-bench ../query-injection-bench
    python scripts/make_readme_capture.py

Zero keys: the bench exercises safety layers 1-2 and the read-only authorizer only.
"""
import io
import os
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.text import Text

ROOT = Path(__file__).resolve().parents[1]
env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8"}
out = subprocess.run([sys.executable, "eval/injection_bench.py"], cwd=ROOT, env=env,
                     capture_output=True, text=True, encoding="utf-8", check=True).stdout

console = Console(record=True, width=112, file=io.StringIO())
console.print(Text("$ python eval/injection_bench.py", style="bold green"))
console.print(Text(out.rstrip()))
console.save_svg(str(ROOT / "docs" / "injection-bench.svg"), title="querypilot-v2 vs query-injection-bench")
print("wrote docs/injection-bench.svg")
