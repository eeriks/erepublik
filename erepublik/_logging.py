import base64
import datetime
import inspect
import logging
import os
import sys
import weakref
from logging import LogRecord, handlers
from pathlib import Path
from typing import Any, Dict, Union

import requests

from erepublik.classes import Reporter
from erepublik.constants import erep_tz
from erepublik.utils import json, json_dumps, json_loads, slugify


class ErepublikFileHandler(handlers.TimedRotatingFileHandler):
    _file_path: Path

    def __init__(self, filename: str = "log/erepublik.log", *args, **kwargs):
        log_path = Path(filename)
        self._file_path = log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        at_time = erep_tz.localize(datetime.datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0)
        kwargs.update(atTime=at_time)
        super().__init__(filename, when="d", *args, **kwargs)

    def doRollover(self) -> None:
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        super().doRollover()

    def emit(self, record: LogRecord) -> None:
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        super().emit(record)


class ErepublikLogConsoleHandler(logging.StreamHandler):
    def __init__(self, *_):
        super().__init__(sys.stdout)


class ErepublikFormatter(logging.Formatter):
    """override logging.Formatter to use an aware datetime object"""

    dbg_fmt = "[%(asctime)s] DEBUG: %(module)s: %(lineno)d: %(msg)s"
    info_fmt = "[%(asctime)s] %(msg)s"
    default_fmt = "[%(asctime)s] %(levelname)s: %(msg)s"

    def converter(self, timestamp: Union[int, float]) -> datetime.datetime:
        return datetime.datetime.fromtimestamp(timestamp).astimezone(erep_tz)

    def format(self, record: logging.LogRecord) -> str:
        """
        Format the specified record as text.

        The record's attribute dictionary is used as the operand to a
        string formatting operation which yields the returned string.
        Before formatting the dictionary, a couple of preparatory steps
        are carried out. The message attribute of the record is computed
        using LogRecord.getMessage(). If the formatting string uses the
        time (as determined by a call to usesTime(), formatTime() is
        called to format the event time. If there is exception information,
        it is formatted using formatException() and appended to the message.
        """
        if record.levelno == logging.DEBUG:
            self._fmt = self.dbg_fmt
        elif record.levelno == logging.INFO:
            self._fmt = self.info_fmt
        else:
            self._fmt = self.default_fmt
        self._style = logging.PercentStyle(self._fmt)

        record.message = record.getMessage()
        if self.usesTime():
            record.asctime = self.formatTime(record, self.datefmt)
        s = self.formatMessage(record)
        if record.exc_info:
            # Cache the traceback text to avoid converting it multiple times
            # (it's constant anyway)
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
        return s

    def formatTime(self, record, datefmt=None):
        dt = self.converter(record.created)
        if datefmt:
            s = dt.strftime(datefmt)
        else:
            s = dt.strftime("%Y-%m-%d %H:%M:%S")
        return s

    def usesTime(self):
        return self._style.usesTime()


class ErepublikErrorHTTTPHandler(handlers.HTTPHandler):
    def __init__(self, reporter: Reporter):
        logging.Handler.__init__(self, level=logging.ERROR)
        self._reporter = weakref.ref(reporter)
        self.host = "erep.lv"
        self.url = "/ebot/error/"
        self.method = "POST"
        self.secure = True
        self.credentials = (str(reporter.citizen_id), reporter.key)
        self.context = None

    @property
    def reporter(self):
        return self._reporter()

    def _get_last_response(self) -> Dict[str, str]:
        response = self.reporter.citizen.r
        url = response.url
        last_index = url.index("?") if "?" in url else len(response.url)

        name = slugify(response.url[len(self.reporter.citizen.url) : last_index])
        html = response.text

        try:
            json_loads(html)
            ext = "json"
        except json.decoder.JSONDecodeError:
            ext = "html"
        try:
            resp_time = (
                datetime.datetime.strptime(response.headers.get("date"), "%a, %d %b %Y %H:%M:%S %Z")
                .replace(tzinfo=datetime.timezone.utc)
                .astimezone(erep_tz)
                .strftime("%F_%H-%M-%S")
            )
        except:  # noqa
            resp_time = slugify(response.headers.get("date"))
        return dict(
            name=f"{resp_time}_{name}.{ext}",
            content=html.encode("utf-8"),
            mimetype="application/json" if ext == "json" else "text/html",
        )

    def _get_local_vars(self) -> str:
        trace = inspect.trace()
        local_vars = {}
        if trace:
            local_vars = trace[-1][0].f_locals
            if local_vars.get("__name__") == "__main__":
                local_vars.update(
                    commit_id=local_vars.get("COMMIT_ID"),
                    interactive=local_vars.get("INTERACTIVE"),
                    version=local_vars.get("__version__"),
                    config=local_vars.get("CONFIG"),
                )
        else:
            stack = inspect.stack()
            report_error_caller_found = False
            for frame in stack:
                if report_error_caller_found:
                    local_vars = frame.frame.f_locals
                    break
                if "report_error" in str(frame.frame):
                    report_error_caller_found = True

        if "state_thread" in local_vars:
            local_vars.pop("state_thread", None)
        from erepublik import Citizen

        if isinstance(local_vars.get("self"), Citizen):
            local_vars["self"] = repr(local_vars["self"])
        if isinstance(local_vars.get("player"), Citizen):
            local_vars["player"] = repr(local_vars["player"])
        if isinstance(local_vars.get("citizen"), Citizen):
            local_vars["citizen"] = repr(local_vars["citizen"])
        return json_dumps(local_vars)

    def _get_instance_json(self) -> str:
        if self.reporter:
            return self.reporter.citizen.to_json(False)
        return ""

    def mapLogRecord(self, record: logging.LogRecord) -> Dict[str, Any]:
        data = super().mapLogRecord(record)

        # Log last response
        resp = self._get_last_response()
        files = [
            ("file", (resp.get("name"), resp.get("content"), resp.get("mimetype"))),
        ]

        files += list(("file", (f, open(f"log/{f}", "rb"))) for f in os.listdir("log") if f.endswith(".log"))
        local_vars_json = self._get_local_vars()
        if local_vars_json:
            files.append(("file", ("local_vars.json", local_vars_json, "application/json")))
        instance_json = self._get_instance_json()
        if instance_json:
            files.append(("file", ("instance.json", instance_json, "application/json")))
        data.update(files=files)
        return data

    def emit(self, record):
        """
        Emit a record.

        Send the record to the Web server as a percent-encoded dictionary
        """
        try:
            proto = "https" if self.secure else "http"
            u, p = self.credentials
            s = "Basic " + base64.b64encode(f"{u}:{p}".encode("utf-8")).strip().decode("ascii")
            headers = {"Authorization": s}
            data = self.mapLogRecord(record)
            files = data.pop("files") if "files" in data else None
            requests.post(f"{proto}://{self.host}{self.url}", headers=headers, data=data, files=files)
        except Exception:
            self.handleError(record)
