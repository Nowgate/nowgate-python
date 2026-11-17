"""make sdk-package's check: the wheel installed into a clean virtual environment, imported by
its name, verifies a published signature vector.

Usage: python -I installed.py <signature-vectors.json> <version>
"""

import sys
import time

# The import, timed first, with nothing but sys and time loaded before it.
began = time.perf_counter()
import nowgate  # noqa: E402
from nowgate import API_VERSION, VERSION, Nowgate, Webhook  # noqa: E402

import_ms = (time.perf_counter() - began) * 1000

import json  # noqa: E402
from pathlib import Path  # noqa: E402


def check(ok: bool, what: str) -> None:
    if not ok:
        raise SystemExit(f"installed check failed: {what}")


def main() -> None:
    vectors_file, version = sys.argv[1], sys.argv[2]
    module = Path(nowgate.__file__).resolve()
    check(module.is_relative_to(Path(sys.prefix).resolve()), f"nowgate loaded from {module}")

    vector = json.loads(Path(vectors_file).read_text(encoding="utf-8"))["vectors"][0]
    event = Webhook.construct_event(
        vector["body"], vector["header"], vector["secrets"], now=vector["now"]
    )
    check(event["type"] == "payment.finished", "the vector's event")
    check(event["api_version"] == API_VERSION, "the API version")
    check(VERSION == version == nowgate.__version__, f"the version {VERSION}, not {version}")
    client = Nowgate(api_key="ngk_sandbox_" + "0123456789" * 4 + "abc")
    check(client.base_url == "https://sandbox-api.nowgate.io/v1", "the sandbox's base URL")
    files = [f for f in module.parent.rglob("*") if f.is_file() and "__pycache__" not in f.parts]
    size = sum(f.stat().st_size for f in files)
    print(
        f"nowgate {VERSION} on Python {sys.version.split()[0]}: installed ({size} bytes in "
        f"{len(files)} files, without bytecode), imported in {import_ms:.1f} ms, a vector verified"
    )


if __name__ == "__main__":
    main()
