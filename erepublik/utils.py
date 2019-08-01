import datetime
import inspect
import json
import os
import re
import sys
import time
import traceback
import unicodedata
from collections import deque
from decimal import Decimal
from json import JSONEncoder
from pathlib import Path
from typing import Union, Any, List, NoReturn, Mapping

import pytz
import requests
from requests import Response

__all__ = ["FOOD_ENERGY", "COMMIT_ID", "COUNTRIES", "erep_tz",
           "now", "localize_dt", "localize_timestamp", "good_timedelta", "eday_from_date", "date_from_eday",
           "get_sleep_seconds", "interactive_sleep", "silent_sleep",
           "write_silent_log", "write_interactive_log", "get_file", "write_file",
           "send_email", "normalize_html_json", "process_error", ]


FOOD_ENERGY = dict(q1=2, q2=4, q3=6, q4=8, q5=10, q6=12, q7=20)
COMMIT_ID = "7b92e19"

erep_tz = pytz.timezone('US/Pacific')
AIR_RANKS = {1: "Airman", 2: "Airman 1st Class", 3: "Airman 1st Class*", 4: "Airman 1st Class**",
             5: "Airman 1st Class***", 6: "Airman 1st Class****", 7: "Airman 1st Class*****",
             8: "Senior Airman", 9: "Senior Airman*", 10: "Senior Airman**", 11: "Senior Airman***",
             12: "Senior Airman****", 13: "Senior Airman*****",
             14: "Staff Sergeant", 15: "Staff Sergeant*", 16: "Staff Sergeant**", 17: "Staff Sergeant***",
             18: "Staff Sergeant****", 19: "Staff Sergeant*****",
             20: "Aviator", 21: "Aviator*", 22: "Aviator**", 23: "Aviator***", 24: "Aviator****", 25: "Aviator*****",
             26: "Flight Lieutenant", 27: "Flight Lieutenant*", 28: "Flight Lieutenant**", 29: "Flight Lieutenant***",
             30: "Flight Lieutenant****", 31: "Flight Lieutenant*****",
             32: "Squadron Leader", 33: "Squadron Leader*", 34: "Squadron Leader**", 35: "Squadron Leader***",
             36: "Squadron Leader****", 37: "Squadron Leader*****",
             38: "Chief Master Sergeant", 39: "Chief Master Sergeant*", 40: "Chief Master Sergeant**",
             41: "Chief Master Sergeant***", 42: "Chief Master Sergeant****", 43: "Chief Master Sergeant*****",
             44: "Wing Commander", 45: "Wing Commander*", 46: "Wing Commander**", 47: "Wing Commander***",
             48: "Wing Commander****", 49: "Wing Commander*****",
             50: "Group Captain", 51: "Group Captain*", 52: "Group Captain**", 53: "Group Captain***",
             54: "Group Captain****", 55: "Group Captain*****",
             56: "Air Commodore", 57: "Air Commodore*", 58: "Air Commodore**", 59: "Air Commodore***",
             60: "Air Commodore****", 61: "Air Commodore*****", }

GROUND_RANKS = {1: "Recruit", 2: "Private", 3: "Private*", 4: "Private**", 5: "Private***", 6: "Corporal",
                7: "Corporal*", 8: "Corporal**", 9: "Corporal***",
                10: "Sergeant", 11: "Sergeant*", 12: "Sergeant**", 13: "Sergeant***", 14: "Lieutenant",
                15: "Lieutenant*", 16: "Lieutenant**", 17: "Lieutenant***",
                18: "Captain", 19: "Captain*", 20: "Captain**", 21: "Captain***", 22: "Major", 23: "Major*",
                24: "Major**", 25: "Major***",
                26: "Commander", 27: "Commander*", 28: "Commander**", 29: "Commander***", 30: "Lt Colonel",
                31: "Lt Colonel*", 32: "Lt Colonel**", 33: "Lt Colonel***",
                34: "Colonel", 35: "Colonel*", 36: "Colonel**", 37: "Colonel***", 38: "General", 39: "General*",
                40: "General**", 41: "General***",
                42: "Field Marshal", 43: "Field Marshal*", 44: "Field Marshal**", 45: "Field Marshal***",
                46: "Supreme Marshal", 47: "Supreme Marshal*", 48: "Supreme Marshal**", 49: "Supreme Marshal***",
                50: "National Force", 51: "National Force*", 52: "National Force**", 53: "National Force***",
                54: "World Class Force", 55: "World Class Force*", 56: "World Class Force**",
                57: "World Class Force***", 58: "Legendary Force", 59: "Legendary Force*", 60: "Legendary Force**",
                61: "Legendary Force***",
                62: "God of War", 63: "God of War*", 64: "God of War**", 65: "God of War***", 66: "Titan", 67: "Titan*",
                68: "Titan**", 69: "Titan***",
                70: "Legends I", 71: "Legends II", 72: "Legends III", 73: "Legends IV", 74: "Legends V",
                75: "Legends VI", 76: "Legends VII", 77: "Legends VIII", 78: "Legends IX", 79: "Legends X",
                80: "Legends XI", 81: "Legends XII", 82: "Legends XIII", 83: "Legends XIV", 84: "Legends XV",
                85: "Legends XVI", 86: "Legends XVII", 87: "Legends XVIII", 88: "Legends XIX", 89: "Legends XX", }

COUNTRIES = {1: 'Romania', 9: 'Brazil', 10: 'Italy', 11: 'France', 12: 'Germany', 13: 'Hungary', 14: 'China',
             15: 'Spain', 23: 'Canada', 24: 'USA', 26: 'Mexico', 27: 'Argentina', 28: 'Venezuela', 29: 'United Kingdom',
             30: 'Switzerland', 31: 'Netherlands', 32: 'Belgium', 33: 'Austria', 34: 'Czech Republic', 35: 'Poland',
             36: 'Slovakia', 37: 'Norway', 38: 'Sweden', 39: 'Finland', 40: 'Ukraine', 41: 'Russia', 42: 'Bulgaria',
             43: 'Turkey', 44: 'Greece', 45: 'Japan', 47: 'South Korea', 48: 'India', 49: 'Indonesia', 50: 'Australia',
             51: 'South Africa', 52: 'Republic of Moldova', 53: 'Portugal', 54: 'Ireland', 55: 'Denmark', 56: 'Iran',
             57: 'Pakistan', 58: 'Israel', 59: 'Thailand', 61: 'Slovenia', 63: 'Croatia', 64: 'Chile', 65: 'Serbia',
             66: 'Malaysia', 67: 'Philippines', 68: 'Singapore', 69: 'Bosnia and Herzegovina', 70: 'Estonia',
             71: 'Latvia', 72: 'Lithuania', 73: 'North Korea', 74: 'Uruguay', 75: 'Paraguay', 76: 'Bolivia', 77: 'Peru',
             78: 'Colombia', 79: 'Republic of Macedonia (FYROM)', 80: 'Montenegro', 81: 'Republic of China (Taiwan)',
             82: 'Cyprus', 83: 'Belarus', 84: 'New Zealand', 164: 'Saudi Arabia', 165: 'Egypt',
             166: 'United Arab Emirates', 167: 'Albania', 168: 'Georgia', 169: 'Armenia', 170: 'Nigeria', 171: 'Cuba'}

COUNTRY_LINK = {1: 'Romania', 9: 'Brazil', 11: 'France', 12: 'Germany', 13: 'Hungary', 82: 'Cyprus', 168: 'Georgia',
                15: 'Spain', 23: 'Canada', 26: 'Mexico', 27: 'Argentina', 28: 'Venezuela', 80: 'Montenegro', 24: 'USA',
                29: 'United-Kingdom', 50: 'Australia', 47: 'South-Korea',171: 'Cuba', 79: 'Republic-of-Macedonia-FYROM',
                30: 'Switzerland', 31: 'Netherlands', 32: 'Belgium', 33: 'Austria', 34: 'Czech-Republic', 35: 'Poland',
                36: 'Slovakia', 37: 'Norway', 38: 'Sweden', 39: 'Finland', 40: 'Ukraine', 41: 'Russia', 42: 'Bulgaria',
                43: 'Turkey', 44: 'Greece', 45: 'Japan', 48: 'India', 49: 'Indonesia', 78: 'Colombia', 68: 'Singapore',
                51: 'South Africa', 52: 'Republic-of-Moldova', 53: 'Portugal', 54: 'Ireland', 55: 'Denmark', 56: 'Iran',
                57: 'Pakistan', 58: 'Israel', 59: 'Thailand', 61: 'Slovenia', 63: 'Croatia', 64: 'Chile', 65: 'Serbia',
                66: 'Malaysia', 67: 'Philippines', 70: 'Estonia', 165: 'Egypt', 14: 'China', 77: 'Peru', 10: 'Italy',
                71: 'Latvia', 72: 'Lithuania', 73: 'North-Korea', 74: 'Uruguay', 75: 'Paraguay', 76: 'Bolivia',
                81: 'Republic-of-China-Taiwan', 166: 'United-Arab-Emirates', 167: 'Albania', 69: 'Bosnia-Herzegovina',
                169: 'Armenia', 83: 'Belarus', 84: 'New-Zealand', 164: 'Saudi-Arabia', 170: 'Nigeria', }


class MyJSONEncoder(JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float("{:.02f}".format(o))
        elif isinstance(o, datetime.datetime):
            return dict(__type__='datetime', year=o.year, month=o.month, day=o.day, hour=o.hour, minute=o.minute,
                        second=o.second, microsecond=o.microsecond)
        elif isinstance(o, datetime.date):
            return dict(__type__='date', year=o.year, month=o.month, day=o.day)
        elif isinstance(o, datetime.timedelta):
            return dict(__type__='timedelta', days=o.days, seconds=o.seconds,
                        microseconds=o.microseconds, total_seconds=o.total_seconds())
        elif isinstance(o, Response):
            return dict(headers=o.headers.__dict__, url=o.url, text=o.text)
        elif hasattr(o, '__dict__'):
            return o.__dict__
        elif isinstance(o, deque):
            return list(o)
        return super().default(o)


def now() -> datetime.datetime:
    return datetime.datetime.now(erep_tz).replace(microsecond=0)


def localize_timestamp(timestamp: int) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(timestamp, erep_tz)


def localize_dt(dt: Union[datetime.date, datetime.datetime]) -> datetime.datetime:
    try:
        try:
            return erep_tz.localize(dt)
        except AttributeError:
            return erep_tz.localize(datetime.datetime.combine(dt, datetime.time(0, 0, 0)))
    except ValueError:
        return dt.astimezone(erep_tz)


def good_timedelta(dt: datetime.datetime, td: datetime.timedelta) -> datetime.datetime:
    return erep_tz.normalize(dt + td)


def eday_from_date(date: Union[datetime.date, datetime.datetime] = now()) -> int:
    if isinstance(date, datetime.date):
        date = datetime.datetime.combine(date, datetime.time(0, 0, 0))
    return (date - datetime.datetime(2007, 11, 20, 0, 0, 0)).days


def date_from_eday(eday: int) -> datetime.date:
    return localize_dt(datetime.date(2007, 11, 20)) + datetime.timedelta(days=eday)


def get_sleep_seconds(time_untill: datetime.datetime) -> int:
    """ time_until aware datetime object Wrapper for sleeping until """
    sleep_seconds = int((time_untill - now()).total_seconds())
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
    if isinstance(player, Citizen):
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
        files.append(('file', ("local_vars.json", json.dumps(local_vars, indent=2,
                                                             cls=MyJSONEncoder, sort_keys=True), "application/json")))
    if isinstance(player, Citizen):
        files.append(('file', ("instance.json", player.to_json(indent=True), "application/json")))
    requests.post('https://pasts.72.lv', data=data, files=files)


def normalize_html_json(js: str) -> str:
    js = re.sub(r' \'(.*?)\'', lambda a: '"%s"' % a.group(1), js)
    js = re.sub(r'(\d\d):(\d\d):(\d\d)', r'\1\2\3', js)
    js = re.sub(r'([{\s,])(\w+)(:)(?!"})', r'\1"\2"\3', js)
    js = re.sub(r',\s*}', '}', js)
    return js


def process_error(log_info: str, name: str, exc_info: tuple, citizen=None, commit_id: str = None,
                  interactive: bool = False):
    """
    Process error logging and email sending to developer
    :param interactive: Should print interactively
    :param log_info: String to be written in output
    :param name: String Instance name
    :param exc_info: tuple output from sys.exc_info()
    :param citizen: Citizen instance
    :param commit_id: Code's version by commit id
    """
    type_, value_, traceback_ = exc_info
    bugtrace = [] if not commit_id else ["Commit id: %s" % commit_id, ]
    bugtrace += [str(value_), str(type_), ''.join(traceback.format_tb(traceback_))]

    if interactive:
        write_interactive_log(log_info)
    else:
        write_silent_log(log_info)
    trace = inspect.trace()
    if trace:
        trace = trace[-1][0].f_locals
    else:
        trace = dict()
    send_email(name, bugtrace, citizen, local_vars=trace)


def report_promo(kind: str, time_untill: datetime.datetime) -> NoReturn:
    requests.post('https://api.erep.lv/promos/add/', data=dict(kind=kind, time_untill=time_untill))


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
    value = re.sub(r'[^\w\s-]', '', value).strip().lower()
    return re.sub(r'[-\s]+', '-', value)
