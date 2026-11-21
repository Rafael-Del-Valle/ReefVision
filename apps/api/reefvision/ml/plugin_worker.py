"""Execute the scalar image ABI offline in a disposable, resource-limited process."""

from __future__ import annotations

import math
import multiprocessing
from multiprocessing.connection import Connection
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


def _run_child(channel: Connection, module: bytes, arguments: Arguments | None) -> None:
    try:
        value = _measure(module, arguments)
    except (ImportError, OSError):
        channel.send(
            (
                False,
                "The bundled WebAssembly runtime could not start. Check installation diagnostics.",
            )
        )
    except ValueError as exc:
        channel.send((False, str(exc)))
    except Exception:
        # The caller needs a stable domain outcome, including for native Wasmtime traps.
        channel.send(
            (False, "The plugin failed inside its isolated worker. No measurement was saved.")
        )
    else:
        channel.send((True, value))
    finally:
        channel.close()


def run_plugin(module: bytes, arguments: Arguments | None = None) -> float | None:
    context = multiprocessing.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=_run_child, args=(send, module, arguments))
    with receive, send:
        process.start()
        send.close()
        try:
            if not receive.poll(WORKER_TIMEOUT_SECONDS):
                raise ValidationError(
                    "The plugin exceeded its execution time. No measurement was saved."
                )
            try:
                valid, result = receive.recv()
            except EOFError as exc:
                raise ValidationError(
                    "The plugin worker stopped. No measurement was saved."
                ) from exc
            if not valid:
                raise ValidationError(str(result))
            return cast(float | None, result)
        finally:
            process.join(timeout=0.3)
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join()
            process.close()
