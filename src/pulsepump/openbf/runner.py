from __future__ import annotations

from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QIODeviceBase,
    QObject,
    QProcess,
    QStringConverter,
    QTextStream,
    Signal,
)


def _qba_to_lines(qba: QByteArray) -> list[str]:
    """Convert a QByteArray to a list of text lines via QBuffer + QTextStream."""
    buf = QBuffer()
    buf.setData(qba)
    buf.open(QIODeviceBase.OpenModeFlag.ReadOnly)
    stream = QTextStream(buf)
    stream.setEncoding(QStringConverter.Encoding.Utf8)
    text: str = stream.readAll()
    buf.close()
    return text.splitlines()


class OpenBFRunner(QObject):
    stdout = Signal(str)
    stderr = Signal(str)
    started = Signal()
    finished = Signal(int)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self._proc.started.connect(self._on_started)
        self._proc.finished.connect(self._on_finished)
        self._proc.errorOccurred.connect(self._on_error)
        self._proc.readyReadStandardOutput.connect(self._read_stdout)
        self._proc.readyReadStandardError.connect(self._read_stderr)

    def run(self, working_dir: str, script_path: str, yaml_name: str) -> None:
        if self._proc.state() != QProcess.ProcessState.NotRunning:
            return
        self._proc.setWorkingDirectory(working_dir)
        self._proc.start("julia", [script_path, yaml_name])

    def kill(self) -> None:
        if self._proc.state() != QProcess.ProcessState.NotRunning:
            self._proc.kill()
            self._proc.waitForFinished(2000)

    def is_running(self) -> bool:
        return self._proc.state() != QProcess.ProcessState.NotRunning

    def _on_started(self) -> None:
        self.started.emit()

    def _on_finished(self, exit_code: int, _exit_status: object) -> None:
        self._read_stdout()
        self._read_stderr()
        self.finished.emit(exit_code)

    def _on_error(self, error: QProcess.ProcessError) -> None:
        self.failed.emit(f"Process error: {error.name}")

    def _read_stdout(self) -> None:
        for line in _qba_to_lines(self._proc.readAllStandardOutput()):
            self.stdout.emit(line)

    def _read_stderr(self) -> None:
        for line in _qba_to_lines(self._proc.readAllStandardError()):
            self.stderr.emit(line)
