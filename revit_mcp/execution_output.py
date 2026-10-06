# -*- coding: UTF-8 -*-
"""Capture and diagnostics shared by synchronous and queued execution.

Requires serialized execution in one IronPython engine: sys streams are global.
"""
import sys
import traceback
try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO
try:
    text_type = unicode
    string_types = (basestring,)
except NameError:
    text_type = str
    string_types = (str,)


def safe_text(value):
    try:
        return text_type(value)
    except BaseException:
        return u"<unprintable {0}>".format(type(value).__name__)


class CaptureStream(object):
    """Retain written text even when the backing buffer fails to read/close."""
    encoding = "utf-8"

    def __init__(self, buffer_factory):
        self.buffer = buffer_factory()
        self.parts = []

    def write(self, value):
        if isinstance(value, bytes) and not isinstance(value, text_type):
            value = value.decode("utf-8", "replace")
        value = text_type(value)
        self.parts.append(value)
        return self.buffer.write(value)

    def flush(self):
        return self.buffer.flush()

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


def execute_script(code, namespace, script_name="<revit-script>", buffer_factory=StringIO,
                   runner=None):
    """Execute code and always restore both streams, including BaseException.

    This primitive does no routing, transaction management, or replay. The
    filename is a diagnostic basename only; no server-side file is read.
    """
    filename = script_name.replace("\\", "/").split("/")[-1]
    old_stdout, old_stderr = sys.stdout, sys.stderr
    stdout, stderr = None, None
    result = {"status": "success", "output": u"", "stderr": u"",
              "script_name": filename}
    cleanup_errors = []
    try:
        stdout = CaptureStream(buffer_factory)
        stderr = CaptureStream(buffer_factory)
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
            result[name] = u"".join(stream.parts)
            try:
                # The write journal includes attempted writes if the buffer failed.
                stream.buffer.getvalue()
            except BaseException as error:
                cleanup_errors.append({"stage": name + "_read", "error": safe_text(error)})
            try:
                stream.buffer.close()
            except BaseException as error:
                cleanup_errors.append({"stage": name + "_close", "error": safe_text(error)})
    if cleanup_errors:
        result["cleanup_errors"] = cleanup_errors
        if result["status"] == "success":
            result.update({"status": "error", "error_type": "OutputCleanupError",
                           "error": "Output capture cleanup failed"})
    if result["status"] == "error":
        result["partial_output"] = result["output"]
    return result
