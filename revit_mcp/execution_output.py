# -*- coding: UTF-8 -*-
"""Capture and diagnostics shared by synchronous and queued execution.

Requires serialized execution in one IronPython engine: sys streams are global.
"""
import sys
import threading
import traceback
try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO
try:
    text_type = unicode
    string_types = (basestring,)
    integer_types = (int, long)
except NameError:
    text_type = str
    string_types = (str,)
    integer_types = (int,)


DEFAULT_OUTPUT_LIMIT_CHARS = 1000000


def validate_output_limit(limit):
    if isinstance(limit, bool) or not isinstance(limit, integer_types) or limit < 0:
        raise ValueError("output_limit_chars must be a nonnegative integer")


class CaptureBudget(object):
    """One retained-character budget shared by stdout and stderr."""
    def __init__(self, limit):
        validate_output_limit(limit)
        self.limit = limit
        self.retained = 0
        self.lock = threading.RLock()


def safe_text(value):
    try:
        return text_type(value)
    except BaseException:
        return u"<unprintable {0}>".format(type(value).__name__)


class CaptureStream(object):
    """One retained journal, with an optional diagnostic buffer injection."""
    encoding = "utf-8"

    def __init__(self, buffer_factory, budget, name="output"):
        self.buffer = None if buffer_factory is None else buffer_factory()
        self.parts = []
        self.budget = budget
        self.dropped = 0
        self.name = name
        self.closed = False
        self.errors = []
        self._failed_stages = set()

    def _record_error(self, stage, error):
        if stage not in self._failed_stages:
            self._failed_stages.add(stage)
            self.errors.append({"stage": self.name + "_" + stage, "error": safe_text(error)})

    def write(self, value):
        if isinstance(value, bytes) and not isinstance(value, text_type):
            value = value.decode("utf-8", "replace")
        value = text_type(value)
        length = len(value)
        with self.budget.lock:
            if self.closed:
                raise ValueError("I/O operation on closed capture stream")
            retained = value[:max(0, self.budget.limit - self.budget.retained)]
            self.dropped += length - len(retained)
            if retained:
                # Never append empty writes/overflows: list overhead is bounded
                # by the retained budget, even for arbitrarily many small writes.
                self.budget.retained += len(retained)
                self.parts.append(retained)
                if self.buffer is not None and "write" not in self._failed_stages:
                    try:
                        self.buffer.write(retained)
                    except BaseException as error:
                        # The journal already contains the retained output. A
                        # diagnostic sink failure must not interrupt model work.
                        self._record_error("write", error)
        # Truncation is diagnostic only and never aborts model execution.
        return length

    def flush(self):
        with self.budget.lock:
            if self.closed:
                raise ValueError("I/O operation on closed capture stream")
            if self.buffer is not None and "flush" not in self._failed_stages:
                try:
                    self.buffer.flush()
                except BaseException as error:
                    self._record_error("flush", error)

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def close(self):
        with self.budget.lock:
            if self.closed:
                return
            try:
                if self.buffer is not None:
                    self.buffer.close()
            except BaseException as error:
                self._record_error("close", error)
            finally:
                self.closed = True

    def fileno(self):
        raise IOError("Capture stream has no file descriptor")

    def isatty(self):
        return False


def exception_details(error, exc_info, filename):
    location = {"filename": filename, "line": None, "column": None}
    if isinstance(error, SyntaxError):
        location["line"] = error.lineno
        location["column"] = error.offset
    else:
        tb = exc_info[2]
        while tb is not None:
            if tb.tb_frame.f_code.co_filename == filename:
                location["line"] = tb.tb_lineno
            tb = tb.tb_next
    try:
        trace = u"".join(traceback.format_exception(*exc_info))
    except BaseException:
        trace = u"{0}: {1}".format(type(error).__name__, safe_text(error))
    return {"error": u"{0}: {1}".format(type(error).__name__, safe_text(error)),
            "error_type": type(error).__name__, "traceback": trace,
            "script_location": location}


def execute_script(code, namespace, script_name="<revit-script>", buffer_factory=None,
                   runner=None, output_limit_chars=DEFAULT_OUTPUT_LIMIT_CHARS):
    """Execute code and always restore both streams, including BaseException.

    This primitive does no routing, transaction management, or replay. The
    filename is a diagnostic basename only; no server-side file is read.
    """
    filename = script_name.replace("\\", "/").split("/")[-1]
    budget = CaptureBudget(output_limit_chars)
    old_stdout, old_stderr = sys.stdout, sys.stderr
    stdout, stderr = None, None
    result = {"status": "success", "output": u"", "stderr": u"",
              "script_name": filename}
    cleanup_errors = []
    try:
        stdout = CaptureStream(buffer_factory, budget, "output")
        stderr = CaptureStream(buffer_factory, budget, "stderr")
        sys.stdout, sys.stderr = stdout, stderr
        compiled = compile(code, filename, "exec")
        # eval accepts exec-mode code objects on Python 2 and 3. Calling the
        # Python 3 exec function syntax would be a tuple statement on Python 2.
        if runner is None:
            eval(compiled, namespace, namespace)
        else:
            runner(compiled, namespace)
    except BaseException as error:
        result["status"] = "error"
        result.update(exception_details(error, sys.exc_info(), filename))
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
        for name, stream in (("output", stdout), ("stderr", stderr)):
            if stream is None:
                continue
            with budget.lock:
                result[name] = u"".join(stream.parts)
                if stream.buffer is not None and not stream.closed:
                    try:
                        stream.buffer.getvalue()
                    except BaseException as error:
                        stream._record_error("read", error)
                stream.close()
                cleanup_errors.extend(stream.errors)
    if cleanup_errors:
        result["cleanup_errors"] = cleanup_errors
        if result["status"] == "success":
            result.update({"status": "error", "error_type": "OutputCleanupError",
                           "error": "Output capture cleanup failed"})
    if result["status"] == "error":
        result["partial_output"] = result["output"]
    stdout_dropped = stdout.dropped if stdout is not None else 0
    stderr_dropped = stderr.dropped if stderr is not None else 0
    result["output_truncated"] = bool(stdout_dropped)
    result["stderr_truncated"] = bool(stderr_dropped)
    result["output_capture"] = {"limit_chars": budget.limit, "retained_chars": budget.retained,
                                "stdout_dropped_chars": stdout_dropped,
                                "stderr_dropped_chars": stderr_dropped}
    return result
