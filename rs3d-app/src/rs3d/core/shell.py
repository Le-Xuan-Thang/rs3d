"""SSH/SFTP session to a Shake (paramiko). The status checks only read; the clock fix runs sudo commands."""

from __future__ import annotations

import socket
from pathlib import Path

import paramiko

from rs3d.core.models import Device


class ShellError(Exception):
    """kind: auth | unreachable | hostkey | command"""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def classify(exc: BaseException) -> ShellError:
    if isinstance(exc, ShellError):
        return exc
    if isinstance(exc, paramiko.AuthenticationException):
        return ShellError("auth", "wrong user name, password or key")
    if isinstance(exc, paramiko.BadHostKeyException):
        return ShellError("hostkey", "the Shake's host key changed")
    if isinstance(exc, (socket.timeout, TimeoutError, paramiko.ssh_exception.NoValidConnectionsError,
                        ConnectionError, OSError)):
        return ShellError("unreachable", str(exc) or "cannot reach the Shake on port 22")
    return ShellError("unreachable", f"{type(exc).__name__}: {exc}")


class Shell:
    """Use as a context manager. Host keys are trusted on first use and kept in known_hosts."""

    def __init__(self, device: Device, password: str | None, known_hosts: Path, timeout: float = 8.0) -> None:
        self.device, self.password, self.known_hosts, self.timeout = device, password, Path(known_hosts), timeout
        self._client: paramiko.SSHClient | None = None

    def __enter__(self) -> "Shell":
        client = paramiko.SSHClient()
        if self.known_hosts.exists():
            client.load_host_keys(str(self.known_hosts))
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                self.device.host, port=22, username=self.device.ssh_user, password=self.password,
                key_filename=str(self.device.key_path) if self.device.key_path else None,
                timeout=self.timeout, banner_timeout=self.timeout, auth_timeout=self.timeout,
            )
        except Exception as exc:
            client.close()
            raise classify(exc) from exc
        self.known_hosts.parent.mkdir(parents=True, exist_ok=True)
        client.save_host_keys(str(self.known_hosts))
        self._client = client
        return self

    def __exit__(self, *exc) -> None:
        if self._client is not None:
            self._client.close()

    def run(self, command: str, timeout: float = 20.0) -> str:
        assert self._client is not None, "use Shell as a context manager"
        try:
            _, stdout, stderr = self._client.exec_command(command, timeout=timeout)
            out = stdout.read().decode("utf-8", "replace")
            if stdout.channel.recv_exit_status() != 0:
                raise ShellError("command", stderr.read().decode("utf-8", "replace").strip() or out.strip())
            return out
        except ShellError:
            raise
        except Exception as exc:
            raise classify(exc) from exc

    def sftp(self) -> paramiko.SFTPClient:
        assert self._client is not None, "use Shell as a context manager"
        return self._client.open_sftp()
