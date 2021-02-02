import base64
import datetime
import inspect
import logging
import os
import sys
import weakref
from pathlib import Path

import requests
from logging import handlers, LogRecord
from typing import Union, Dict, Any

from erepublik.classes import Reporter
from erepublik.constants import erep_tz
from erepublik.utils import slugify, json_loads, json, now, json_dumps


class ErepublikFileHandler(handlers.TimedRotatingFileHandler):
    _file_path: Path

    def __init__(self, filename: str = 'log/erepublik.log', *args, **kwargs):
        log_path = Path(filename)
        self._file_path = log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        at_time = erep_tz.localize(datetime.datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0)
        kwargs.update(atTime=at_time)
        super().__init__(filename, *args, **kwargs)

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
        return datetime.datetime.utcfromtimestamp(timestamp).astimezone(erep_tz)

    def format(self, record: logging.LogRecord) -> str:
        if record.levelno == logging.DEBUG:
            self._fmt = self.dbg_fmt
        elif record.levelno == logging.INFO:
            self._fmt = self.info_fmt
        else:
            self._fmt = self.default_fmt
        self._style = logging.PercentStyle(self._fmt)
        return super().format(record)

    def formatTime(self, record, datefmt=None):
        dt = self.converter(record.created)
        if datefmt:
            s = dt.strftime(datefmt)
        else:
            s = dt.strftime('%Y-%m-%d %H:%M:%S')
        return s


class ErepublikErrorHTTTPHandler(handlers.HTTPHandler):
    def __init__(self, reporter: Reporter):
        logging.Handler.__init__(self, level=logging.ERROR)
        self._reporter = weakref.ref(reporter)
        self.host = 'erep.lv'
        self.url = '/ebot/error/'
        self.method = 'POST'
        self.secure = True
        self.credentials = (str(reporter.citizen_id), reporter.key)
        self.context = None

    @property
    def reporter(self):
        return self._reporter()

    def mapLogRecord(self, record: logging.LogRecord) -> Dict[str, Any]:
        data = super().mapLogRecord(record)

        # Log last response
        response = self.reporter.citizen.r
        url = response.url
        last_index = url.index("?") if "?" in url else len(response.url)

        name = slugify(response.url[len(self.reporter.citizen.url):last_index])
        html = response.text

        try:
            json_loads(html)
            ext = 'json'
        except json.decoder.JSONDecodeError:
            ext = 'html'
        try:
            resp_time = datetime.datetime.strptime(
                response.headers.get('date'), '%a, %d %b %Y %H:%M:%S %Z'
            ).replace(tzinfo=datetime.timezone.utc).astimezone(erep_tz).strftime('%F_%H-%M-%S')
        except:
            resp_time = slugify(response.headers.get('date'))

        resp = dict(name=f"{resp_time}_{name}.{ext}", content=html.encode('utf-8'),
                    mimetype="application/json" if ext == 'json' else "text/html")

        files = [('file', (resp.get('name'), resp.get('content'), resp.get('mimetype'))), ]
        filename = f'log/{now().strftime("%F")}.log'
        if os.path.isfile(filename):
            files.append(('file', (filename[4:], open(filename, 'rb'), 'text/plain')))
        trace = inspect.trace()
        local_vars = {}
        if trace:
            local_vars = trace[-1][0].f_locals
            if local_vars.get('__name__') == '__main__':
                local_vars.update(commit_id=local_vars.get('COMMIT_ID'), interactive=local_vars.get('INTERACTIVE'),
                                  version=local_vars.get('__version__'), config=local_vars.get('CONFIG'))

        if local_vars:
            if 'state_thread' in local_vars:
                local_vars.pop('state_thread', None)

            if isinstance(local_vars.get('self'), self.reporter.citizen.__class__):
                local_vars['self'] = repr(local_vars['self'])
            if isinstance(local_vars.get('player'), self.reporter.citizen.__class__):
                local_vars['player'] = repr(local_vars['player'])
            if isinstance(local_vars.get('citizen'), self.reporter.citizen.__class__):
                local_vars['citizen'] = repr(local_vars['citizen'])

            files.append(('file', ('local_vars.json', json_dumps(local_vars), "application/json")))
        files.append(('file', ('instance.json', self.reporter.citizen.to_json(indent=True), "application/json")))
        data.update(files=files)
        return data

    def emit(self, record):
        """
        Emit a record.

        Send the record to the Web server as a percent-encoded dictionary
        """
        try:
            proto = 'https' if self.secure else 'http'
            u, p = self.credentials
            s = 'Basic ' + base64.b64encode(f'{u}:{p}'.encode('utf-8')).strip().decode('ascii')
            headers = {'Authorization': s}
            data = self.mapLogRecord(record)
            files = data.pop('files') if 'files' in data else None
            requests.post(f"{proto}://{self.host}{self.url}", headers=headers, data=data, files=files)
        except Exception:
            self.handleError(record)
