"""Execute the scalar image ABI offline in a disposable, resource-limited process."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from reefvision.domain.errors import ValidationError

Arguments = tuple[float, float, float, int]
WORKER_TIMEOUT_SECONDS = 20


def _measure(module_bytes: bytes, arguments: Arguments | None) -> float | None:
    import wasmtime as wasm

    config = wasm.Config()
    config.consume_fuel = True
    config.parallel_compilation = False
    config.wasm_threads = False
    config.wasm_memory64 = False
    config.wasm_multi_memory = False
    engine = wasm.Engine(config)
    module = wasm.Module(engine, module_bytes)
    if module.imports:
        raise ValueError("The RGB summary ABI permits no imported functions or resources.")
    store = wasm.Store(engine)
    store.set_limits(
        memory_size=2 * 1024 * 1024, table_elements=1024, instances=1, tables=2, memories=1
    )
    store.set_fuel(100_000)
    instance = wasm.Instance(store, module, [])
    measure = instance.exports(store).get("measure")
    if not isinstance(measure, wasm.Func):
        raise ValueError("The package must export a measure function.")
    signature = measure.type(store)
    if [str(t) for t in signature.params] != ["f64", "f64", "f64", "i64"] or [
        str(t) for t in signature.results
    ] != ["f64"]:
        raise ValueError(
            "The measure function must take three f64 means and one i64 count, and return f64."
        )
    if arguments is None:
        return None
    value = measure(store, *arguments)
    if not isinstance(value, float) or not math.isfinite(value):
        raise ValueError("The plugin returned a non-finite measurement.")
    return value


def run_plugin_worker(directory: Path) -> None:
    """Read a private request prepared by the desktop process."""

    module = (directory / "module.wasm").read_bytes()
    arguments: Arguments | None = json.loads((directory / "arguments.json").read_bytes())
    result: tuple[bool, float | str | None]
    try:
        value = _measure(module, arguments)
    except (ImportError, OSError):
        result = (
            False,
            "The bundled WebAssembly runtime could not start. Check installation diagnostics.",
        )
    except ValueError as exc:
        result = (False, str(exc))
    except Exception:
        # The caller needs a stable domain outcome, including for native Wasmtime traps.
        result = (False, "The plugin failed inside its isolated worker. No measurement was saved.")
    else:
        result = (True, value)
    (directory / "result.json").write_text(json.dumps(result, allow_nan=False), encoding="utf-8")


def run_plugin(module: bytes, arguments: Arguments | None = None) -> float | None:
    # Use an explicit worker entry point so the Windows desktop can start it
    # without replaying the API launcher or depending on its console handles.
    entrypoint = (
        ["--plugin-worker"]
        if getattr(sys, "frozen", False)
        else ["-m", "reefvision.ml.plugin_worker"]
    )
    with TemporaryDirectory(prefix="reefvision-plugin-") as scratch:
        directory = Path(scratch)
        (directory / "module.wasm").write_bytes(module)
        (directory / "arguments.json").write_text(json.dumps(arguments), encoding="utf-8")
        try:
            subprocess.run(
                [sys.executable, *entrypoint, str(directory)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=WORKER_TIMEOUT_SECONDS,
                check=True,
            )
            valid, result = json.loads((directory / "result.json").read_bytes())
        except subprocess.TimeoutExpired as exc:
            raise ValidationError(
                "The plugin exceeded its execution time. No measurement was saved."
            ) from exc
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            raise ValidationError("The plugin worker stopped. No measurement was saved.") from exc
        if not valid:
            raise ValidationError(str(result))
        return cast(float | None, result)


if __name__ == "__main__" and len(sys.argv) == 2:
    run_plugin_worker(Path(sys.argv[1]))
