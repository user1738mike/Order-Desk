"""External hard deadline and bounded pipes for the memory-only PDF child."""

import json
import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path

from apps.orders.csv_extraction import MAX_RESULT_BYTES, ExtractionFailure

PARSER_VERSION = "order-text-pdf-v1"
WALL_SECONDS = 15
MAX_INPUT = 10 * 1024 * 1024
MAX_STDERR = 4096


def supervise(command, source, *, deadline=WALL_SECONDS):
    if sys.platform != "linux":
        raise ExtractionFailure("parser_unavailable")
    process = subprocess.Popen(  # noqa: S603 - fixed production invocation, no shell
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        },
        close_fds=True,
        start_new_session=True,
        shell=False,
    )  # noqa: S603
    output, errors, written = bytearray(), bytearray(), 0
    end = time.monotonic() + deadline
    try:
        with selectors.DefaultSelector() as polling:
            for stream in (process.stdin, process.stdout, process.stderr):
                os.set_blocking(stream.fileno(), False)
            polling.register(process.stdin, selectors.EVENT_WRITE, "input")
            polling.register(process.stdout, selectors.EVENT_READ, "output")
            polling.register(process.stderr, selectors.EVENT_READ, "errors")
            while polling.get_map():
                if time.monotonic() >= end:
                    raise ExtractionFailure("parser_timeout")
                for key, _ in polling.select(min(0.1, max(0, end - time.monotonic()))):
                    stream, kind = key.fileobj, key.data
                    if kind == "input":
                        if written == len(source):
                            polling.unregister(stream)
                            stream.close()
                            continue
                        try:
                            written += os.write(
                                stream.fileno(), source[written : written + 65536]
                            )
                        except BrokenPipeError:
                            polling.unregister(stream)
                            stream.close()
                    else:
                        chunk = os.read(stream.fileno(), 65536)
                        if not chunk:
                            polling.unregister(stream)
                            continue
                        target = output if kind == "output" else errors
                        limit = MAX_RESULT_BYTES if kind == "output" else MAX_STDERR
                        if len(target) + len(chunk) > limit:
                            raise ExtractionFailure("parser_output_limit")
                        target.extend(chunk)
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise ExtractionFailure("parser_timeout")
            try:
                code = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired as error:
                raise ExtractionFailure("parser_timeout") from error
            if code != 0:
                raise ExtractionFailure("parser_resource_limit")
            return bytes(output)
    finally:
        # Kill the group even after leader exit, so descendants cannot outlive it.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


def extract_pdf(stream):
    source = stream.read(MAX_INPUT + 1)
    if len(source) > MAX_INPUT:
        raise ExtractionFailure("input_limit")
    command = [sys.executable, "-I", str(Path(__file__).with_name("pdf_parser.py"))]
    try:
        output = supervise(command, source)
        data = json.loads(output)
    except (OSError, ValueError) as error:
        raise ExtractionFailure("parser_unavailable") from error
    if "error" in data:
        raise ExtractionFailure(data["error"])
    if (
        set(data) != {"result", "pages", "metrics"}
        or not isinstance(data["result"], list)
        or not 1 <= len(data["result"]) <= 500
        or not isinstance(data["pages"], list)
        or not 1 <= len(data["pages"]) <= 10
    ):
        raise ExtractionFailure("parser_output_limit")
    return data
