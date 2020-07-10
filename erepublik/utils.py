import datetime
import inspect
import os
import re
import sys
import textwrap
import time
import traceback
import unicodedata
from decimal import Decimal
from pathlib import Path
from typing import Any, List, Mapping, Optional, Union

import requests

from . import __version__, constants

try:
    import simplejson as json
except ImportError:
    import json

__all__ = ['VERSION', 'calculate_hit', 'caught_error', 'date_from_eday', 'eday_from_date',
           'get_air_hit_dmg_value', 'get_file', 'get_ground_hit_dmg_value', 'get_sleep_seconds', 'good_timedelta',
           'interactive_sleep', 'json', 'localize_dt', 'localize_timestamp', 'normalize_html_json', 'now',
           'process_error', 'process_warning', 'send_email', 'silent_sleep', 'slugify', 'write_file',
           'write_interactive_log', 'write_silent_log']

if not sys.version_info >= (3, 7):
    raise AssertionError('This script requires Python version 3.7 and higher\n'
                         'But Your version is v{}.{}.{}'.format(*sys.version_info))

VERSION: str = __version__


def now() -> datetime.datetime:
    return datetime.datetime.now(constants.erep_tz).replace(microsecond=0)


def localize_timestamp(timestamp: int) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(timestamp, constants.erep_tz)


def localize_dt(dt: Union[datetime.date, datetime.datetime]) -> datetime.datetime:
    try:
        try:
            return constants.erep_tz.localize(dt)
        except AttributeError:
            return constants.erep_tz.localize(datetime.datetime.combine(dt, datetime.time(0, 0, 0)))
    except ValueError:
        return dt.astimezone(constants.erep_tz)


def good_timedelta(dt: datetime.datetime, td: datetime.timedelta) -> datetime.datetime:
    """Normalize timezone aware datetime object after timedelta to correct jumps over DST switches

    :param dt: Timezone aware datetime object
    :type dt: datetime.datetime
    :param td: timedelta object
    :type td: datetime.timedelta
    :return: datetime object with correct timezone when jumped over DST
    :rtype: datetime.datetime
    """
    return constants.erep_tz.normalize(dt + td)


def eday_from_date(date: Union[datetime.date, datetime.datetime] = now()) -> int:
    if isinstance(date, datetime.date):
        date = datetime.datetime.combine(date, datetime.time(0, 0, 0))
    return (date - datetime.datetime(2007, 11, 20, 0, 0, 0)).days


def date_from_eday(eday: int) -> datetime.date:
    return localize_dt(datetime.date(2007, 11, 20)) + datetime.timedelta(days=eday)


def get_sleep_seconds(time_until: datetime.datetime) -> int:
    """ time_until aware datetime object Wrapper for sleeping until """
    sleep_seconds = int((time_until - now()).total_seconds())
    return sleep_seconds if sleep_seconds > 0 else 0


def interactive_sleep(sleep_seconds: int):
    while sleep_seconds > 0:
        seconds = sleep_seconds
        if (seconds - 1) // 1800:
            seconds = seconds % 1800 if seconds % 1800 else 1800
        elif (seconds - 1) // 300:
            seconds = seconds % 300 if seconds % 300 else 300
        elif (seconds - 1) // 60:
            seconds = seconds % 60 if seconds % 60 else 60
        # elif (seconds - 1) // 30:
        #     seconds = seconds % 30 if seconds % 30 else 30
        else:
            seconds = 1
        sys.stdout.write("\rSleeping for {:4} more seconds".format(sleep_seconds))
        sys.stdout.flush()
        time.sleep(seconds)
        sleep_seconds -= seconds
    sys.stdout.write("\r")


silent_sleep = time.sleep


def _write_log(msg, timestamp: bool = True, should_print: bool = False):
    erep_time_now = now()
    txt = "[{}] {}".format(erep_time_now.strftime('%F %T'), msg) if timestamp else msg
    txt = "\n".join(["\n".join(textwrap.wrap(line, 120)) for line in txt.splitlines()])
    if not os.path.isdir('log'):
        os.mkdir('log')
    with open("log/%s.log" % erep_time_now.strftime('%F'), 'a', encoding="utf-8") as f:
        f.write("%s\n" % txt)
    if should_print:
        print(txt)


def write_interactive_log(*args, **kwargs):
    _write_log(should_print=True, *args, **kwargs)


def write_silent_log(*args, **kwargs):
    _write_log(should_print=False, *args, **kwargs)


def get_file(filepath: str) -> str:
    file = Path(filepath)
    if file.exists():
        if file.is_dir():
            return str(file / "new_file.txt")
        else:
            version = 1
            try:
                version = int(file.suffix[1:]) + 1
                basename = file.stem
            except ValueError:
                basename = file.name
                version += 1

            full_name = file.parent / f"{basename}.{version}"
            while full_name.exists():
                version += 1
                full_name = file.parent / f"{basename}.{version}"
            return str(full_name)
    else:
        os.makedirs(file.parent, exist_ok=True)
        return str(file)


def write_file(filename: str, content: str) -> int:
    filename = get_file(filename)
    with open(filename, 'ab') as f:
        return f.write(content.encode("utf-8"))


def write_request(response: requests.Response, is_error: bool = False):
    from erepublik import Citizen
    # Remove GET args from url name
    url = response.url
    last_index = url.index("?") if "?" in url else len(response.url)

    name = slugify(response.url[len(Citizen.url):last_index])
    html = response.text

    try:
        json.loads(html)
        ext = "json"
    except json.decoder.JSONDecodeError:
        ext = "html"

    if not is_error:
        filename = "debug/requests/{}_{}.{}".format(now().strftime('%F_%H-%M-%S'), name, ext)
        write_file(filename, html)
    else:
        return {"name": "{}_{}.{}".format(now().strftime('%F_%H-%M-%S'), name, ext),
                "content": html.encode('utf-8'),
                "mimetype": "application/json" if ext == "json" else "text/html"}


def send_email(name: str, content: List[Any], player=None, local_vars: Mapping[Any, Any] = None,
               promo: bool = False, captcha: bool = False):
    if local_vars is None:
        local_vars = {}
    from erepublik import Citizen

    file_content_template = "<html><head><title>{title}</title></head><body>{body}</body></html>"
    if isinstance(player, Citizen) and player.r:
        resp = write_request(player.r, is_error=True)
    else:
        resp = {"name": "None.html", "mimetype": "text/html",
                "content": file_content_template.format(body="<br/>".join(content), title="Error"), }

    if promo:
        resp = {"name": "%s.html" % name, "mimetype": "text/html",
                "content": file_content_template.format(title="Promo", body="<br/>".join(content))}
        subject = "[eBot][{}] Promos: {}".format(now().strftime('%F %T'), name)

    elif captcha:
        resp = {"name": "%s.html" % name, "mimetype": "text/html",
                "content": file_content_template.format(title="ReCaptcha", body="<br/>".join(content))}
        subject = "[eBot][{}] RECAPTCHA: {}".format(now().strftime('%F %T'), name)
    else:
        subject = "[eBot][%s] Bug trace: %s" % (now().strftime('%F %T'), name)

    body = "".join(traceback.format_stack()) + \
           "\n\n" + \
           "\n".join(content)
    data = dict(send_mail=True, subject=subject, bugtrace=body)
    if promo:
        data.update({'promo': True})
    elif captcha:
        data.update({'captcha': True})
    else:
        data.update({"bug": True})

    files = [('file', (resp.get("name"), resp.get("content"), resp.get("mimetype"))), ]
    filename = "log/%s.log" % now().strftime('%F')
    if os.path.isfile(filename):
        files.append(('file', (filename[4:], open(filename, 'rb'), "text/plain")))
    if local_vars:
        if "state_thread" in local_vars:
            local_vars.pop('state_thread', None)
        from erepublik.classes import MyJSONEncoder
        files.append(('file', ("local_vars.json", json.dumps(local_vars, cls=MyJSONEncoder, sort_keys=True),
                               "application/json")))
    if isinstance(player, Citizen):
        files.append(('file', ("instance.json", player.to_json(indent=True), "application/json")))
    requests.post('https://pasts.72.lv', data=data, files=files)


def normalize_html_json(js: str) -> str:
    js = re.sub(r' \'(.*?)\'', lambda a: '"%s"' % a.group(1), js)
    js = re.sub(r'(\d\d):(\d\d):(\d\d)', r'\1\2\3', js)
    js = re.sub(r'([{\s,])(\w+)(:)(?!"})', r'\1"\2"\3', js)
    js = re.sub(r',\s*}', '}', js)
    return js


def caught_error(e: Exception):
    process_error(str(e), "Unclassified", sys.exc_info(), interactive=False)


def process_error(log_info: str, name: str, exc_info: tuple, citizen=None, commit_id: str = None,
                  interactive: Optional[bool] = None):
    """
    Process error logging and email sending to developer
    :param interactive: Should print interactively
    :type interactive: bool
    :param log_info: String to be written in output
    :type log_info: str
    :param name: String Instance name
    :type name: str
    :param exc_info: tuple output from sys.exc_info()
    :type exc_info: tuple
    :param citizen: Citizen instance
    :type citizen: Citizen
    :param commit_id: Caller's code version's commit id
    :type commit_id: str
    """
    type_, value_, traceback_ = exc_info
    content = [log_info]
    content += [f"eRepublik version {VERSION}"]
    if commit_id:
        content += [f"Commit id {commit_id}"]
    content += [str(value_), str(type_), ''.join(traceback.format_tb(traceback_))]

    if interactive:
        write_interactive_log(log_info)
    elif interactive is not None:
        write_silent_log(log_info)
    trace = inspect.trace()
    if trace:
        trace = trace[-1][0].f_locals
        if trace.get('__name__') == '__main__':
            trace = {'commit_id': trace.get('COMMIT_ID'),
                     'interactive': trace.get('INTERACTIVE'),
                     'version': trace.get('__version__'),
                     'config': trace.get('CONFIG')}
    else:
        trace = dict()
    send_email(name, content, citizen, local_vars=trace)


def process_warning(log_info: str, name: str, exc_info: tuple, citizen=None, commit_id: str = None):
    """
    Process error logging and email sending to developer
    :param log_info: String to be written in output
    :param name: String Instance name
    :param exc_info: tuple output from sys.exc_info()
    :param citizen: Citizen instance
    :param commit_id: Code's version by commit id
    """
    type_, value_, traceback_ = exc_info
    content = [log_info]
    if commit_id:
        content += ["Commit id: %s" % commit_id]
    content += [str(value_), str(type_), ''.join(traceback.format_tb(traceback_))]

    trace = inspect.trace()
    if trace:
        trace = trace[-1][0].f_locals
    else:
        trace = dict()
    send_email(name, content, citizen, local_vars=trace)


def slugify(value, allow_unicode=False) -> str:
    """
    Function copied from Django2.2.1 django.utils.text.slugify
    Convert to ASCII if 'allow_unicode' is False. Convert spaces to hyphens.
    Remove characters that aren't alphanumerics, underscores, or hyphens.
    Convert to lowercase. Also strip leading and trailing whitespace.
    """
    value = str(value)
    if allow_unicode:
        value = unicodedata.normalize('NFKC', value)
    else:
        value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^\w\s-]', '_', value).strip().lower()
    return re.sub(r'[-\s]+', '-', value)


def calculate_hit(strength: float, rang: int, tp: bool, elite: bool, ne: bool, booster: int = 0,
                  weapon: int = 200, is_deploy: bool = False) -> Decimal:
    dec = 3 if is_deploy else 0
    base_str = (1 + Decimal(str(round(strength, 3))) / 400)
    base_rnk = (1 + Decimal(str(rang / 5)))
    base_wpn = (1 + Decimal(str(weapon / 100)))
    dmg = 10 * base_str * base_rnk * base_wpn

    if elite:
        dmg = dmg * 11 / 10

    if tp and rang >= 70:
        dmg = dmg * (1 + Decimal((rang - 69) / 10))

    dmg = dmg * (100 + booster) / 100

    if ne:
        dmg = dmg * 11 / 10
    return round(dmg, dec)


def get_ground_hit_dmg_value(citizen_id: int, natural_enemy: bool = False, true_patriot: bool = False,
                             booster: int = 0, weapon_power: int = 200) -> Decimal:
    r = requests.get(f"https://www.erepublik.com/en/main/citizen-profile-json/{citizen_id}").json()
    rang = r['military']['militaryData']['ground']['rankNumber']
    strength = r['military']['militaryData']['ground']['strength']
    elite = r['citizenAttributes']['level'] > 100
    if natural_enemy:
        true_patriot = True

    return calculate_hit(strength, rang, true_patriot, elite, natural_enemy, booster, weapon_power)


def get_air_hit_dmg_value(citizen_id: int, natural_enemy: bool = False, true_patriot: bool = False, booster: int = 0,
                          weapon_power: int = 0) -> Decimal:
    r = requests.get(f"https://www.erepublik.com/en/main/citizen-profile-json/{citizen_id}").json()
    rang = r['military']['militaryData']['aircraft']['rankNumber']
    elite = r['citizenAttributes']['level'] > 100
    return calculate_hit(0, rang, true_patriot, elite, natural_enemy, booster, weapon_power)
