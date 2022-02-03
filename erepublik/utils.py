import datetime
import os
import re
import sys
import time
import unicodedata
import warnings
from base64 import b64encode
from decimal import Decimal
from logging import Logger
from pathlib import Path
from typing import Any, Dict, List, Union

import pytz
import requests
from requests import Response

from erepublik import __version__, constants

try:
    import simplejson as json
except ImportError:
    import json

__all__ = [
    "ErepublikJSONEncoder",
    "VERSION",
    "b64json",
    "calculate_hit",
    "date_from_eday",
    "deprecation",
    "eday_from_date",
    "get_air_hit_dmg_value",
    "get_file",
    "get_final_hit_dmg",
    "get_ground_hit_dmg_value",
    "get_sleep_seconds",
    "good_timedelta",
    "interactive_sleep",
    "json",
    "json_decode_object_hook",
    "json_dump",
    "json_dumps",
    "json_load",
    "json_loads",
    "localize_dt",
    "localize_timestamp",
    "normalize_html_json",
    "now",
    "silent_sleep",
    "slugify",
    "write_file",
]

VERSION: str = __version__


def now() -> datetime.datetime:
    return datetime.datetime.now(constants.erep_tz).replace(microsecond=0)


def localize_timestamp(timestamp: int) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(timestamp, constants.erep_tz)


def localize_dt(dt: Union[datetime.date, datetime.datetime]) -> datetime.datetime:
    if isinstance(dt, datetime.datetime):
        return constants.erep_tz.localize(dt)
    elif isinstance(dt, datetime.date):
        return constants.erep_tz.localize(datetime.datetime.combine(dt, datetime.time(0, 0, 0)))
    else:
        raise TypeError(f"Argument dt must be and instance of datetime.datetime or datetime.date not {type(dt)}")


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


def eday_from_date(date: Union[datetime.date, datetime.datetime] = None) -> int:
    if date is None:
        date = now()
    if isinstance(date, datetime.date):
        date = datetime.datetime.combine(date, datetime.time(0, 0, 0))
    return (date - datetime.datetime(2007, 11, 20, 0, 0, 0)).days


def date_from_eday(eday: int) -> datetime.datetime:
    return localize_dt(datetime.date(2007, 11, 20)) + datetime.timedelta(days=eday)


def get_sleep_seconds(time_until: datetime.datetime) -> int:
    """time_until aware datetime object Wrapper for sleeping until"""
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
        sys.stdout.write(f"\rSleeping for {sleep_seconds:4} more seconds")
        sys.stdout.flush()
        time.sleep(seconds)
        sleep_seconds -= seconds
    sys.stdout.write("\r")


silent_sleep = time.sleep


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
    with open(filename, "ab") as f:
        ret = f.write(content.encode("utf-8"))
    return ret


def normalize_html_json(js: str) -> str:
    js = re.sub(r" \'(.*?)\'", lambda a: f'"{a.group(1)}"', js)
    js = re.sub(r"(\d\d):(\d\d):(\d\d)", r"\1\2\3", js)
    js = re.sub(r'([{\s,])(\w+)(:)(?!"})', r'\1"\2"\3', js)
    js = re.sub(r",\s*}", "}", js)
    return js


def slugify(value, allow_unicode=False) -> str:
    """
    Function copied from Django2.2.1 django.utils.text.slugify
    Convert to ASCII if 'allow_unicode' is False. Convert spaces to hyphens.
    Remove characters that aren't alphanumerics, underscores, or hyphens.
    Convert to lowercase. Also strip leading and trailing whitespace.
    """
    value = str(value)
    if allow_unicode:
        value = unicodedata.normalize("NFKC", value)
    else:
        value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "_", value).strip().lower()
    return re.sub(r"[-\s]+", "-", value)


def calculate_hit(
    strength: float,
    rang: int,
    tp: bool,
    elite: bool,
    ne: bool,
    booster: int = 0,
    weapon: int = 200,
    is_deploy: bool = False,
) -> Decimal:
    dec = 3 if is_deploy else 0
    base_str = 1 + Decimal(str(round(strength, 3))) / 400
    base_rnk = 1 + Decimal(str(rang / 5))
    base_wpn = 1 + Decimal(str(weapon / 100))
    dmg = 10 * base_str * base_rnk * base_wpn

    dmg = get_final_hit_dmg(dmg, rang, tp=tp, elite=elite, ne=ne, booster=booster)
    return Decimal(round(dmg, dec))


def get_ground_hit_dmg_value(
    citizen_id: int, natural_enemy: bool = False, true_patriot: bool = False, booster: int = 0, weapon_power: int = 200
) -> Decimal:
    r = requests.get(f"https://www.erepublik.com/en/main/citizen-profile-json/{citizen_id}").json()
    rang = r["military"]["militaryData"]["ground"]["rankNumber"]
    strength = r["military"]["militaryData"]["ground"]["strength"]
    elite = r["citizenAttributes"]["level"] > 100
    if natural_enemy:
        true_patriot = True

    return calculate_hit(strength, rang, true_patriot, elite, natural_enemy, booster, weapon_power)


def get_air_hit_dmg_value(
    citizen_id: int, natural_enemy: bool = False, true_patriot: bool = False, booster: int = 0, weapon_power: int = 0
) -> Decimal:
    r = requests.get(f"https://www.erepublik.com/en/main/citizen-profile-json/{citizen_id}").json()
    rang = r["military"]["militaryData"]["aircraft"]["rankNumber"]
    elite = r["citizenAttributes"]["level"] > 100
    return calculate_hit(0, rang, true_patriot, elite, natural_enemy, booster, weapon_power)


def get_final_hit_dmg(
    base_dmg: Union[Decimal, float, str],
    rang: int,
    tp: bool = False,
    elite: bool = False,
    ne: bool = False,
    booster: int = 0,
) -> Decimal:
    dmg = Decimal(str(base_dmg))

    if elite:
        dmg = dmg * 11 / 10
    if tp and rang >= 70:
        dmg = dmg * (1 + Decimal((rang - 69) / 10))
    dmg = dmg * (100 + booster) / 100
    if ne:
        dmg = dmg * 11 / 10
    return Decimal(dmg)


def deprecation(message):
    warnings.warn(message, DeprecationWarning, stacklevel=2)


def json_decode_object_hook(
    o: Union[Dict[str, Any], List[Any], int, float, str]
) -> Union[Dict[str, Any], List[Any], int, float, str, datetime.date, datetime.datetime, datetime.timedelta]:
    """Convert classes.ErepublikJSONEncoder datetime, date and timedelta to their python objects

    :param o:
    :return: Union[Dict[str, Any], List[Any], int, float, str, datetime.date, datetime.datetime, datetime.timedelta]
    """
    if o.get("__type__"):
        _type = o.get("__type__")
        if _type == "datetime":
            dt = datetime.datetime.strptime(f"{o['date']} {o['time']}", "%Y-%m-%d %H:%M:%S")
            if o.get("tzinfo"):
                dt = pytz.timezone(o["tzinfo"]).localize(dt)
            return dt
        elif _type == "date":
            dt = datetime.datetime.strptime(f"{o['date']}", "%Y-%m-%d")
            return dt.date()
        elif _type == "timedelta":
            return datetime.timedelta(seconds=o["total_seconds"])
    return o


def json_load(f, **kwargs):
    # kwargs.update(object_hook=json_decode_object_hook)
    return json.load(f, **kwargs)


def json_loads(s: str, **kwargs):
    # kwargs.update(object_hook=json_decode_object_hook)
    return json.loads(s, **kwargs)


def json_dump(obj, fp, *args, **kwargs):
    if not kwargs.get("cls"):
        kwargs.update(cls=ErepublikJSONEncoder)
    return json.dump(obj, fp, *args, **kwargs)


def json_dumps(obj, *args, **kwargs):
    if not kwargs.get("cls"):
        kwargs.update(cls=ErepublikJSONEncoder)
    return json.dumps(obj, *args, **kwargs)


def b64json(obj: Union[Dict[str, Union[int, List[str]]], List[str]]):
    if isinstance(obj, list):
        return b64encode(json.dumps(obj, separators=(",", ":")).encode("utf-8")).decode("utf-8")
    elif isinstance(obj, (int, str)):
        return obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            obj[k] = b64json(v)
    else:
        from .classes import ErepublikException

        raise ErepublikException(f"Unhandled object type! obj is {type(obj)}")
    return b64encode(json.dumps(obj, separators=(",", ":")).encode("utf-8")).decode("utf-8")


class ErepublikJSONEncoder(json.JSONEncoder):
    def default(self, o):
        try:
            from erepublik.citizen import Citizen

            if isinstance(o, Decimal):
                return float(f"{o:.02f}")
            elif isinstance(o, datetime.datetime):
                return dict(
                    __type__="datetime",
                    date=o.strftime("%Y-%m-%d"),
                    time=o.strftime("%H:%M:%S"),
                    tzinfo=str(o.tzinfo) if o.tzinfo else None,
                )
            elif isinstance(o, datetime.date):
                return dict(__type__="date", date=o.strftime("%Y-%m-%d"))
            elif isinstance(o, datetime.timedelta):
                return dict(
                    __type__="timedelta",
                    days=o.days,
                    seconds=o.seconds,
                    microseconds=o.microseconds,
                    total_seconds=o.total_seconds(),
                )
            elif isinstance(o, Response):
                return dict(headers=dict(o.__dict__["headers"]), url=o.url, text=o.text, status_code=o.status_code)
            elif hasattr(o, "as_dict"):
                return o.as_dict
            elif isinstance(o, set):
                return list(o)
            elif isinstance(o, Citizen):
                return o.to_json()
            elif isinstance(o, Logger):
                return str(o)
            elif hasattr(o, "__dict__"):
                return o.__dict__
            else:
                return super().default(o)
        except Exception as e:  # noqa
            return str(e)
