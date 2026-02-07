"""Upload and execute shell scripts on GNS3 nodes via telnet."""

from __future__ import annotations

import asyncio
import base64
import posixpath
import textwrap
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence
import shlex

from .telnet_client import TelnetSettings, open_console, TelnetConsole


@dataclass(slots=True)
class ScriptSpec:
    """Specification describing how a script should be pushed to a node.
    
    Either `content` or `local_path` must be provided. If `content` is set,
    the script content is used directly. Otherwise, `local_path` is read.
    """

    remote_path: str
    content: str | None = None
    local_path: Path | None = None
    run_after_upload: bool = False
    executable: bool = True
    overwrite: bool = True
    run_timeout: float = 10.0
    shell: str = "sh"


@dataclass(slots=True)
class ScriptUploadResult:
    node_name: str
    host: str
    port: int
    remote_path: str
    success: bool
    skipped: bool
    reason: str | None
    output: str
    error: str | None
    timestamp: float


@dataclass(slots=True)
class ScriptExecutionResult:
    node_name: str
    host: str
    port: int
    remote_path: str
    success: bool
    exit_code: int | None
    output: str
    error: str | None
    timestamp: float


@dataclass(slots=True)
class ScriptPushResult:
    upload: ScriptUploadResult
    execution: ScriptExecutionResult | None


@dataclass(slots=True)
class ScriptTask:
    node_name: str
    host: str
    port: int
    spec: ScriptSpec


class ScriptPusher:
    """Push scripts to remote nodes over telnet."""

    def __init__(self, scripts_base_dir: Path | None = None) -> None:
        self._base_dir = scripts_base_dir

    def resolve_local_path(self, path: Path | str) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            if self._base_dir is not None:
                candidate = self._base_dir / candidate
            else:
                candidate = Path.cwd() / candidate
        candidate = candidate.resolve()
        if self._base_dir is not None:
            base = self._base_dir.resolve()
            try:
                candidate.relative_to(base)
            except ValueError as exc:
                raise ValueError(f"{candidate} is outside allowed scripts directory {base}") from exc
        if not candidate.exists():
            raise FileNotFoundError(candidate)
        return candidate

    def _get_payload(self, spec: ScriptSpec) -> bytes:
        """Get script content as bytes, from content string or local file."""
        if spec.content is not None:
            return spec.content.encode("utf-8")
        if spec.local_path is not None:
            local_path = self.resolve_local_path(spec.local_path)
            return local_path.read_bytes()
        raise ValueError("ScriptSpec must have either 'content' or 'local_path'")

    async def push(
        self,
        node_name: str,
        host: str,
        port: int,
        spec: ScriptSpec,
    ) -> ScriptPushResult:
        payload = self._get_payload(spec)
        b64_payload = base64.b64encode(payload).decode("ascii")
        b64_lines = textwrap.wrap(b64_payload, 120)
        tmp_remote = f"/tmp/.upload_{uuid.uuid4().hex}.b64"
        remote_path = spec.remote_path

        settings = TelnetSettings(host=host, port=port)
        source_desc = "content" if spec.content else str(spec.local_path)
        print(f"Pushing {source_desc} to {node_name} ({host}:{port}) as {remote_path}")
        try:
            async with open_console(settings) as console:
                if not spec.overwrite and await self._remote_file_exists(console, remote_path):
                    upload_result = ScriptUploadResult(
                        node_name=node_name,
                        host=host,
                        port=port,
                        remote_path=remote_path,
                        success=False,
                        skipped=True,
                        reason="exists",
                        output="",
                        error=None,
                        timestamp=time.time(),
                    )
                    return ScriptPushResult(upload=upload_result, execution=None)

                await self._upload_base64(console, tmp_remote, b64_lines)

                parent_dir = posixpath.dirname(remote_path)
                if parent_dir and parent_dir not in {"", "."}:
                    await console.run_command_with_status(f"mkdir -p {shlex.quote(parent_dir)}", read_duration=2.0)

                decode_output, decode_exit = await console.run_command_with_status(
                    f"base64 -d {shlex.quote(tmp_remote)} > {shlex.quote(remote_path)}",
                    read_duration=5.0,
                )

                await console.run_command_with_status(f"rm -f {shlex.quote(tmp_remote)}", read_duration=1.0)

                if decode_exit != 0:
                    upload_result = ScriptUploadResult(
                        node_name=node_name,
                        host=host,
                        port=port,
                        remote_path=remote_path,
                        success=False,
                        skipped=False,
                        reason="decode_failed",
                        output=decode_output,
                        error=f"base64 decode exited with {decode_exit}",
                        timestamp=time.time(),
                    )
                    return ScriptPushResult(upload=upload_result, execution=None)

                chmod_output = ""
                if spec.executable:
                    chmod_output, chmod_exit = await console.run_command_with_status(
                        f"chmod +x {shlex.quote(remote_path)}",
                        read_duration=2.0,
                    )
                    if chmod_exit != 0:
                        upload_result = ScriptUploadResult(
                            node_name=node_name,
                            host=host,
                            port=port,
                            remote_path=remote_path,
                            success=False,
                            skipped=False,
                            reason="chmod_failed",
                            output=chmod_output,
                            error=f"chmod exited with {chmod_exit}",
                            timestamp=time.time(),
                        )
                        return ScriptPushResult(upload=upload_result, execution=None)

                upload_messages = "\n".join(filter(None, [decode_output.strip(), chmod_output.strip()])).strip()
                upload_result = ScriptUploadResult(
                    node_name=node_name,
                    host=host,
                    port=port,
                    remote_path=remote_path,
                    success=True,
                    skipped=False,
                    reason=None,
                    output=upload_messages,
                    error=None,
                    timestamp=time.time(),
                )

                execution_result = None
                if spec.run_after_upload:
                    execution_result = await self._execute_script(
                        console,
                        node_name=node_name,
                        host=host,
                        port=port,
                        remote_path=remote_path,
                        shell=spec.shell,
                        timeout=spec.run_timeout,
                    )

                return ScriptPushResult(upload=upload_result, execution=execution_result)
        except Exception as exc:
            upload_result = ScriptUploadResult(
                node_name=node_name,
                host=host,
                port=port,
                remote_path=remote_path,
                success=False,
                skipped=False,
                reason="connection_failed",
                output="",
                error=str(exc),
                timestamp=time.time(),
            )
            return ScriptPushResult(upload=upload_result, execution=None)

    async def run(
        self,
        node_name: str,
        host: str,
        port: int,
        remote_path: str,
        *,
        shell: str = "sh",
        timeout: float = 10.0,
    ) -> ScriptExecutionResult:
        settings = TelnetSettings(host=host, port=port)
        async with open_console(settings) as console:
            return await self._execute_script(
                console,
                node_name=node_name,
                host=host,
                port=port,
                remote_path=remote_path,
                shell=shell,
                timeout=timeout,
            )

    async def push_many(
        self,
        tasks: Sequence[ScriptTask],
        *,
        concurrency: int = 5,
    ) -> list[ScriptPushResult]:
        semaphore = asyncio.Semaphore(max(1, concurrency))

        async def worker(task: ScriptTask) -> ScriptPushResult:
            async with semaphore:
                return await self.push(task.node_name, task.host, task.port, task.spec)

        return await asyncio.gather(*(worker(task) for task in tasks))

    async def _upload_base64(
        self,
        console: TelnetConsole,
        tmp_remote: str,
        lines: Iterable[str],
    ) -> None:
        await console.send(f"cat <<'EOF' > {shlex.quote(tmp_remote)}")
        for line in lines:
            await console.send(line)
        await console.send("EOF")
        await asyncio.sleep(0.2)
        await console.read_for(0.2)

    async def _remote_file_exists(self, console: TelnetConsole, remote_path: str) -> bool:
        _, exit_code = await console.run_command_with_status(f"[ -e {shlex.quote(remote_path)} ]", read_duration=1.0)
        return exit_code == 0

    async def _execute_script(
        self,
        console: TelnetConsole,
        *,
        node_name: str,
        host: str,
        port: int,
        remote_path: str,
        shell: str,
        timeout: float,
    ) -> ScriptExecutionResult:
        command = f"{shell} {shlex.quote(remote_path)}"
        output, exit_code = await console.run_command_with_status(command, read_duration=timeout)
        success = exit_code == 0
        return ScriptExecutionResult(
            node_name=node_name,
            host=host,
            port=port,
            remote_path=remote_path,
            success=success,
            exit_code=exit_code,
            output=output,
            error=None if success else f"exit={exit_code}",
            timestamp=time.time(),
        )
