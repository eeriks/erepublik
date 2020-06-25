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
from typing import Any, Dict, List, Mapping, Optional, Union

import pytz
import requests

from . import __commit_id__, __version__

try:
    import simplejson as json
except ImportError:
    import json

__all__ = ["FOOD_ENERGY", "COMMIT_ID", "COUNTRIES", "erep_tz", 'COUNTRY_LINK',
           "now", "localize_dt", "localize_timestamp", "good_timedelta", "eday_from_date", "date_from_eday",
           "get_sleep_seconds", "interactive_sleep", "silent_sleep",
           "write_silent_log", "write_interactive_log", "get_file", "write_file",
           "send_email", "normalize_html_json", "process_error", "process_warning",
           'calculate_hit', 'get_ground_hit_dmg_value', 'get_air_hit_dmg_value']

if not sys.version_info >= (3, 7):
    raise AssertionError('This script requires Python version 3.7 and higher\n'
                         'But Your version is v{}.{}.{}'.format(*sys.version_info))

FOOD_ENERGY: Dict[str, int] = dict(q1=2, q2=4, q3=6, q4=8, q5=10, q6=12, q7=20)
COMMIT_ID: str = __commit_id__
VERSION: str = __version__

erep_tz = pytz.timezone('US/Pacific')
AIR_RANKS: Dict[int, str] = {
    1: "Airman", 2: "Airman 1st Class", 3: "Airman 1st Class*", 4: "Airman 1st Class**", 5: "Airman 1st Class***",
    6: "Airman 1st Class****", 7: "Airman 1st Class*****", 8: "Senior Airman", 9: "Senior Airman*",
    10: "Senior Airman**", 11: "Senior Airman***", 12: "Senior Airman****", 13: "Senior Airman*****",
    14: "Staff Sergeant", 15: "Staff Sergeant*", 16: "Staff Sergeant**", 17: "Staff Sergeant***",
    18: "Staff Sergeant****", 19: "Staff Sergeant*****", 20: "Aviator", 21: "Aviator*", 22: "Aviator**",
    23: "Aviator***", 24: "Aviator****", 25: "Aviator*****", 26: "Flight Lieutenant", 27: "Flight Lieutenant*",
    28: "Flight Lieutenant**", 29: "Flight Lieutenant***", 30: "Flight Lieutenant****", 31: "Flight Lieutenant*****",
    32: "Squadron Leader", 33: "Squadron Leader*", 34: "Squadron Leader**", 35: "Squadron Leader***",
    36: "Squadron Leader****", 37: "Squadron Leader*****", 38: "Chief Master Sergeant", 39: "Chief Master Sergeant*",
    40: "Chief Master Sergeant**", 41: "Chief Master Sergeant***", 42: "Chief Master Sergeant****",
    43: "Chief Master Sergeant*****", 44: "Wing Commander", 45: "Wing Commander*", 46: "Wing Commander**",
    47: "Wing Commander***", 48: "Wing Commander****", 49: "Wing Commander*****", 50: "Group Captain",
    51: "Group Captain*", 52: "Group Captain**", 53: "Group Captain***", 54: "Group Captain****",
    55: "Group Captain*****", 56: "Air Commodore", 57: "Air Commodore*", 58: "Air Commodore**", 59: "Air Commodore***",
    60: "Air Commodore****", 61: "Air Commodore*****",
}

GROUND_RANKS: Dict[int, str] = {
    1: "Recruit", 2: "Private", 3: "Private*", 4: "Private**", 5: "Private***",
    6: "Corporal", 7: "Corporal*", 8: "Corporal**", 9: "Corporal***",
    10: "Sergeant", 11: "Sergeant*", 12: "Sergeant**", 13: "Sergeant***",
    14: "Lieutenant", 15: "Lieutenant*", 16: "Lieutenant**", 17: "Lieutenant***",
    18: "Captain", 19: "Captain*", 20: "Captain**", 21: "Captain***",
    22: "Major", 23: "Major*", 24: "Major**", 25: "Major***",
    26: "Commander", 27: "Commander*", 28: "Commander**", 29: "Commander***",
    30: "Lt Colonel", 31: "Lt Colonel*", 32: "Lt Colonel**", 33: "Lt Colonel***",
    34: "Colonel", 35: "Colonel*", 36: "Colonel**", 37: "Colonel***",
    38: "General", 39: "General*", 40: "General**", 41: "General***",
    42: "Field Marshal", 43: "Field Marshal*", 44: "Field Marshal**", 45: "Field Marshal***",
    46: "Supreme Marshal", 47: "Supreme Marshal*", 48: "Supreme Marshal**", 49: "Supreme Marshal***",
    50: "National Force", 51: "National Force*", 52: "National Force**", 53: "National Force***",
    54: "World Class Force", 55: "World Class Force*", 56: "World Class Force**", 57: "World Class Force***",
    58: "Legendary Force", 59: "Legendary Force*", 60: "Legendary Force**", 61: "Legendary Force***",
    62: "God of War", 63: "God of War*", 64: "God of War**", 65: "God of War***",
    66: "Titan", 67: "Titan*", 68: "Titan**", 69: "Titan***",
    70: "Legends I", 71: "Legends II", 72: "Legends III", 73: "Legends IV", 74: "Legends V", 75: "Legends VI",
    76: "Legends VII", 77: "Legends VIII", 78: "Legends IX", 79: "Legends X", 80: "Legends XI", 81: "Legends XII",
    82: "Legends XIII", 83: "Legends XIV", 84: "Legends XV", 85: "Legends XVI", 86: "Legends XVII", 87: "Legends XVIII",
    88: "Legends XIX", 89: "Legends XX",
}

GROUND_RANK_POINTS: Dict[int, int] = {
    1: 0, 2: 15, 3: 45, 4: 80, 5: 120, 6: 170, 7: 250, 8: 350, 9: 450, 10: 600, 11: 800, 12: 1000,
    13: 1400, 14: 1850, 15: 2350, 16: 3000, 17: 3750, 18: 5000, 19: 6500, 20: 9000, 21: 12000,
    22: 15500, 23: 20000, 24: 25000, 25: 31000, 26: 40000, 27: 52000, 28: 67000, 29: 85000,
    30: 110000, 31: 140000, 32: 180000, 33: 225000, 34: 285000, 35: 355000, 36: 435000, 37: 540000,
    38: 660000, 39: 800000, 40: 950000, 41: 1140000, 42: 1350000, 43: 1600000, 44: 1875000,
    45: 2185000, 46: 2550000, 47: 3000000, 48: 3500000, 49: 4150000, 50: 4900000, 51: 5800000,
    52: 7000000, 53: 9000000, 54: 11500000, 55: 14500000, 56: 18000000, 57: 22000000, 58: 26500000,
    59: 31500000, 60: 37000000, 61: 43000000, 62: 50000000, 63: 100000000, 64: 200000000,
    65: 500000000, 66: 1000000000, 67: 2000000000, 68: 4000000000, 69: 10000000000, 70: 20000000000,
    71: 30000000000, 72: 40000000000, 73: 50000000000, 74: 60000000000, 75: 70000000000,
    76: 80000000000, 77: 90000000000, 78: 100000000000, 79: 110000000000, 80: 120000000000,
    81: 130000000000, 82: 140000000000, 83: 150000000000, 84: 160000000000, 85: 170000000000,
    86: 180000000000, 87: 190000000000, 88: 200000000000, 89: 210000000000
}

COUNTRIES: Dict[int, str] = {
    1: 'Romania', 9: 'Brazil', 10: 'Italy', 11: 'France', 12: 'Germany', 13: 'Hungary', 14: 'China', 15: 'Spain',
    23: 'Canada', 24: 'USA', 26: 'Mexico', 27: 'Argentina', 28: 'Venezuela', 29: 'United Kingdom', 30: 'Switzerland',
    31: 'Netherlands', 32: 'Belgium', 33: 'Austria', 34: 'Czech Republic', 35: 'Poland', 36: 'Slovakia', 37: 'Norway',
    38: 'Sweden', 39: 'Finland', 40: 'Ukraine', 41: 'Russia', 42: 'Bulgaria', 43: 'Turkey', 44: 'Greece', 45: 'Japan',
    47: 'South Korea', 48: 'India', 49: 'Indonesia', 50: 'Australia', 51: 'South Africa', 52: 'Republic of Moldova',
    53: 'Portugal', 54: 'Ireland', 55: 'Denmark', 56: 'Iran', 57: 'Pakistan', 58: 'Israel', 59: 'Thailand',
    61: 'Slovenia', 63: 'Croatia', 64: 'Chile', 65: 'Serbia', 66: 'Malaysia', 67: 'Philippines', 68: 'Singapore',
    69: 'Bosnia and Herzegovina', 70: 'Estonia', 71: 'Latvia', 72: 'Lithuania', 73: 'North Korea', 74: 'Uruguay',
    75: 'Paraguay', 76: 'Bolivia', 77: 'Peru', 78: 'Colombia', 79: 'Republic of Macedonia (FYROM)', 80: 'Montenegro',
    81: 'Republic of China (Taiwan)', 82: 'Cyprus', 83: 'Belarus', 84: 'New Zealand', 164: 'Saudi Arabia', 165: 'Egypt',
    166: 'United Arab Emirates', 167: 'Albania', 168: 'Georgia', 169: 'Armenia', 170: 'Nigeria', 171: 'Cuba'
}

COUNTRY_LINK: Dict[int, str] = {
    1: 'Romania', 9: 'Brazil', 11: 'France', 12: 'Germany', 13: 'Hungary', 82: 'Cyprus', 168: 'Georgia', 15: 'Spain',
    23: 'Canada', 26: 'Mexico', 27: 'Argentina', 28: 'Venezuela', 80: 'Montenegro', 24: 'USA', 29: 'United-Kingdom',
    50: 'Australia', 47: 'South-Korea', 171: 'Cuba', 79: 'Republic-of-Macedonia-FYROM', 30: 'Switzerland', 165: 'Egypt',
    31: 'Netherlands', 32: 'Belgium', 33: 'Austria', 34: 'Czech-Republic', 35: 'Poland', 36: 'Slovakia', 37: 'Norway',
    38: 'Sweden', 39: 'Finland', 40: 'Ukraine', 41: 'Russia', 42: 'Bulgaria', 43: 'Turkey', 44: 'Greece', 45: 'Japan',
    48: 'India', 49: 'Indonesia', 78: 'Colombia', 68: 'Singapore', 51: 'South Africa', 52: 'Republic-of-Moldova',
    53: 'Portugal', 54: 'Ireland', 55: 'Denmark', 56: 'Iran', 57: 'Pakistan', 58: 'Israel', 59: 'Thailand', 10: 'Italy',
    61: 'Slovenia', 63: 'Croatia', 64: 'Chile', 65: 'Serbia', 66: 'Malaysia', 67: 'Philippines', 70: 'Estonia',
    77: 'Peru', 71: 'Latvia', 72: 'Lithuania', 73: 'North-Korea', 74: 'Uruguay', 75: 'Paraguay', 76: 'Bolivia',
    81: 'Republic-of-China-Taiwan', 166: 'United-Arab-Emirates', 167: 'Albania', 69: 'Bosnia-Herzegovina', 14: 'China',
    169: 'Armenia', 83: 'Belarus', 84: 'New-Zealand', 164: 'Saudi-Arabia', 170: 'Nigeria'
}

ISO_CC: Dict[int, str] = {
    1: 'ROU', 9: 'BRA', 10: 'ITA', 11: 'FRA', 12: 'DEU', 13: 'HUN', 14: 'CHN', 15: 'ESP', 23: 'CAN', 24: 'USA',
    26: 'MEX', 27: 'ARG', 28: 'VEN', 29: 'GBR', 30: 'CHE', 31: 'NLD', 32: 'BEL', 33: 'AUT', 34: 'CZE', 35: 'POL',
    36: 'SVK', 37: 'NOR', 38: 'SWE', 39: 'FIN', 40: 'UKR', 41: 'RUS', 42: 'BGR', 43: 'TUR', 44: 'GRC', 45: 'JPN',
    47: 'KOR', 48: 'IND', 49: 'IDN', 50: 'AUS', 51: 'ZAF', 52: 'MDA', 53: 'PRT', 54: 'IRL', 55: 'DNK', 56: 'IRN',
    57: 'PAK', 58: 'ISR', 59: 'THA', 61: 'SVN', 63: 'HRV', 64: 'CHL', 65: 'SRB', 66: 'MYS', 67: 'PHL', 68: 'SGP',
    69: 'BiH', 70: 'EST', 71: 'LVA', 72: 'LTU', 73: 'PRK', 74: 'URY', 75: 'PRY', 76: 'BOL', 77: 'PER', 78: 'COL',
    79: 'MKD', 80: 'MNE', 81: 'TWN', 82: 'CYP', 83: 'BLR', 84: 'NZL', 164: 'SAU', 165: 'EGY', 166: 'UAE', 167: 'ALB',
    168: 'GEO', 169: 'ARM', 170: 'NGA', 171: 'CUB',
}


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
    """Normalize timezone aware datetime object after timedelta to correct jumps over DST switches

    :param dt: Timezone aware datetime object
    :type dt: datetime.datetime
    :param td: timedelta object
    :type td: datetime.timedelta
    :return: datetime object with correct timezone when jumped over DST
    :rtype: datetime.datetime
    """
    return erep_tz.normalize(dt + td)


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
    process_error(str(e), "Unclassified", sys.exc_info(), None, COMMIT_ID, False)


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
    content += [f"eRepublik version {VERSION}, commit id {COMMIT_ID}"]
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
