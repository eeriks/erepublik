import datetime
import inspect
import json
import os
import re
import sys
import time
import traceback
from collections import deque
from decimal import Decimal
from json import JSONEncoder
from pathlib import Path
from typing import Union

import pytz
import requests
from requests import Response
from slugify import slugify


__all__ = ["FOOD_ENERGY", "VERSION", "COMMIT_ID", "COUNTRIES", "erep_tz",
           "now", "localize_dt", "localize_timestamp", "good_timedelta", "eday_from_date", "date_from_eday",
           "get_sleep_seconds", "interactive_sleep", "silent_sleep",
           "write_silent_log", "write_interactive_log", "get_file", "write_file",
           "send_email", "normalize_html_json", "process_error", ]


FOOD_ENERGY = dict(q1=2, q2=4, q3=6, q4=8, q5=10, q6=12, q7=20)
VERSION = "v0.14.1"
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


def now():
    return datetime.datetime.now(erep_tz).replace(microsecond=0)


def localize_timestamp(timestamp: int):
    return datetime.datetime.fromtimestamp(timestamp, erep_tz)


def localize_dt(dt: Union[datetime.date, datetime.datetime]):
    if isinstance(dt, datetime.date):
        dt = datetime.datetime.combine(dt, datetime.time(0, 0, 0))
    return erep_tz.localize(dt)


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
    from erepublik_script import Citizen
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


def send_email(name, content: list, player=None, local_vars=dict, promo: bool = False, captcha: bool = False):
    from erepublik_script import Citizen

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


def parse_input(msg: str) -> bool:
    msg += " (y|n):"
    data = None
    while data not in ['', 'y', 'Y', 'n', 'N']:
        try:
            data = input(msg)
        except EOFError:
            data = 'n'

    return data in ['', 'y', 'Y']


def parse_config(config=None) -> dict:
    if config is None:
        config = {}

    if not config.get('email'):
        config['email'] = input("Player email: ")

    if not config.get('password'):
        config['password'] = input("Player password: ")

    if 'wt' in config:
        config['work'] = config['wt']
        config['train'] = config['wt']

    if 'work' not in config:
        config['work'] = parse_input('Should I work')

    if 'train' not in config:
        config['train'] = parse_input('Should I train')

    if 'ot' not in config:
        config['ot'] = parse_input('Should I work overtime')

    if 'wam' not in config:
        config['wam'] = parse_input('Should I WAM')

    if 'employ' not in config:
        config['employ'] = parse_input('Should I employ employees')

    if config['wam'] or config['employ']:
        if "autosell" in config:
            config.pop("autosell")
        if "autosell_raw" in config:
            config.pop("autosell_raw")
        if "autosell_final" in config:
            config.pop("autosell_final")

        if 'auto_sell' not in config or not isinstance(config['auto_sell'], list):
            if parse_input('Should I auto sell produced products'):
                config['auto_sell'] = []
                if parse_input("Should I auto sell Food products"):
                    if parse_input("Should I auto sell Food products"):
                        config['auto_sell'].append("food")
                    if parse_input("Should I auto sell Weapon products"):
                        config['auto_sell'].append("weapon")
                    if parse_input("Should I auto sell House products"):
                        config['auto_sell'].append("house")
                    if parse_input("Should I auto sell Aircraft products"):
                        config['auto_sell'].append("airplane")
                if parse_input("Should I auto sell raw products"):
                    if parse_input("Should I auto sell Food raw"):
                        config['auto_sell'].append("foodRaw")
                    if parse_input("Should I auto sell Weapon raw"):
                        config['auto_sell'].append("weaponRaw")
                    if parse_input("Should I auto sell House raw"):
                        config['auto_sell'].append("houseRaw")
                    if parse_input("Should I auto sell Airplane raw"):
                        config['auto_sell'].append("airplaneRaw")
        if config['auto_sell']:
            if 'auto_sell_all' not in config:
                print("When selling produced items should I also sell items already in inventory?")
                config['auto_sell_all'] = parse_input('Y - sell all, N - only just produced')
        else:
            config['auto_sell_all'] = False

        if 'auto_buy_raw' not in config:
            config['auto_buy_raw'] = parse_input('Should I auto buy raw deficit at WAM or employ')
    else:
        config['auto_sell'] = []
        config['auto_sell_all'] = False
        config['auto_buy_raw'] = False

    if 'fight' not in config:
        config['fight'] = parse_input('Should I fight')

    if config.get('fight'):
        if 'air' not in config:
            config['air'] = parse_input('Should I fight in AIR')

        if 'ground' not in config:
            config['ground'] = parse_input('Should I fight in GROUND')

        if 'all_in' not in config:
            print("When full energy should I go all in")
            config['all_in'] = parse_input('Y - all in, N - 1h worth of energy')

        if 'next_energy' not in config:
            config['next_energy'] = parse_input('Should I fight when next pp +1 energy available')

        if 'boosters' not in config:
            config['boosters'] = parse_input('Should I use +50% dmg boosters')

        if 'travel_to_fight' not in config:
            config['travel_to_fight'] = parse_input('Should I travel to fight')

        if 'epic_hunt' not in config:
            config['epic_hunt'] = parse_input('Should I check for epic battles')
            if not config['epic_hunt']:
                config['epic_hunt_ebs'] = False

        if not config['epic_hunt']:
            config['epic_hunt_ebs'] = False
        elif 'epic_hunt_ebs' not in config:
            config['epic_hunt_ebs'] = parse_input('Should I eat EBs when fighting in epic battle')

        if 'rw_def_side' not in config:
            config['rw_def_side'] = parse_input('Should I fight on defenders side in RWs')

        if 'continuous_fighting' not in config:
            config['continuous_fighting'] = parse_input('If already fought in any battle, \n'
                                                        'should I continue to fight all FF in that battle')
    else:
        config['air'] = False
        config['ground'] = False
        config['all_in'] = False
        config['next_energy'] = False
        config['boosters'] = False
        config['travel_to_fight'] = False
        config['epic_hunt'] = False
        config['epic_hunt_ebs'] = False
        config['rw_def_side'] = False
        config['continuous_fighting'] = False

    if 'debug' not in config:
        config['debug'] = parse_input('Should I generate debug files')

    if 'random_sleep' not in config:
        config['random_sleep'] = parse_input('Should I add random amount (0-120sec) to sleep time')

    if 'gold_buy' not in config:
        config['gold_buy'] = parse_input('Should I auto buy 10g every day')

    if 'interactive' not in config:
        config['interactive'] = parse_input('Should I print output to console?')

    return config


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
    :param error:
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
    send_email(name, bugtrace, citizen, local_vars=inspect.trace()[-1][0].f_locals)


def aviator_support(citizen, send_food=False, free_food=None):
    forbidden_ids = []
    if free_food is None:
        free_food = {}  # {"q1": 0, "q2": 1000, ...}
    context = {'PLAYER_COUNT': 0, 'TABLE': "",
               'STARTING_ENERGY': sum([amount * FOOD_ENERGY[q] for q, amount in free_food.items()]),
               'TOTAL_CC': 0, 'TOTAL_ENERGY': 0, 'END_ENERGY': 0}
    from erepublik_script import Citizen
    if not isinstance(citizen, Citizen):
        from .classes import ErepublikException
        raise ErepublikException("\"citizen\" must be instance of erepublik.Citizen")
    citizen.config.interactive = True
    aviators = dict()
    time_string = "%Y-%m-%d %H:%M:%S"
    latest_article = requests.get('https://erep.lv/aviator/latest_article/').json()
    for quality, amount in latest_article.get('free_food', {}).items():
        free_food[quality] = free_food.get(quality, 0) + amount

    if not latest_article.get('status'):
        from .classes import ErepublikException
        raise ErepublikException('Article ID and week problem')
    context.update(WEEK=latest_article.get('week', 0) + 1)
    comments = citizen.post_article_comments(citizen.token, latest_article.get('article_id'), 1).json()
    ranking = citizen.get_leaderboards_kills_aircraft_rankings(71, 1, 0).json()

    if not comments.get("comments", {}):
        from .classes import ErepublikException
        raise ErepublikException("No comments found")
    for comment_data in comments.get("comments", {}).values():
        if comment_data.get('authorId') == 1954361:
            start_dt = localize_dt(datetime.datetime.strptime(comment_data.get('createdAt'), time_string))
            days_ahead = 1 - start_dt.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            end_dt = (good_timedelta(start_dt, datetime.timedelta(days_ahead))).replace(hour=0, minute=0, second=0)
            if not comment_data.get('replies', {}):
                from .classes import ErepublikException
                raise ErepublikException("No replies found")

            for reply_data in comment_data.get('replies').values():
                if localize_dt(datetime.datetime.strptime(reply_data.get('createdAt'), time_string)) > end_dt:
                    continue
                if re.search(r'piesakos', reply_data.get('message'), re.I):
                    aviators.update({int(reply_data.get('authorId')): dict(
                        id=reply_data.get('authorId'), name="", kills=0, rank=0, residency=None, health=0, extra=[],
                        factories=0
                    )})

    context['PLAYER_COUNT'] = len(aviators)
    write_interactive_log("{:^9} | {:<28} | {:4} | {:26} | {:6} | {}".format(
        "ID", "Vārds", "Kili", "Gaisa rangs", "Energy", "Aktivizētās mājas"
    ))

    for player_top_data in ranking.get('top'):
        player_id = int(player_top_data.get('id'))
        if player_id in aviators:
            aviators[player_id]["kills"] = int(player_top_data['values'])

    for aviator_id, aviator_data in aviators.items():
        aviator_info = citizen.get_citizen_profile(aviator_id).json()
        aviator_data.update({
            'rank': aviator_info['military']['militaryData']['aircraft']['rankNumber'],
            'name': aviator_info['citizen']['name'],
            'residency': aviator_info['city']['residenceCityId']
        })

        if aviator_info.get("isBanned"):
            aviator_data.update({'health': 0, 'extra': ["BANNED", ]})
        else:
            if aviator_data['rank'] < 44:
                if aviator_data['rank'] < 38:
                    health = aviator_data['kills'] * 30
                else:
                    health = aviator_data['kills'] * 20
                has_pp = False
                if aviator_info.get("activePacks"):
                    has_pp = bool(aviator_info.get("activePacks").get("power_pack"))
                max_health = 7 * 24 * (500 if has_pp else 300)
                if health < max_health:
                    aviator_data['health'] = health
                else:
                    aviator_data['health'] = max_health

                if not aviator_data["residency"]:
                    aviator_data['health'] = 0
                    aviator_data['extra'].append("No residency set")
                else:
                    residency = citizen.get_city_data_residents(
                        aviator_data["residency"], params={"search": aviator_data['name']}
                    ).json()

                    for resident in residency.get('widgets', {}).get('residents', {}).get('residents'):
                        if int(resident.get('citizenId')) == aviator_id:
                            if resident['numFactories']:
                                aviator_data['factories'] = resident['numFactories']
                            else:
                                aviator_data['factories'] = 0
                            if not resident.get('activeHouses'):
                                aviator_data['health'] = 0
                            if resident['numHouses']:
                                aviator_data['extra'].append(", ".join(resident['activeHouses']))
                            else:
                                aviator_data['extra'].append("Nav māja")
                                aviator_data['health'] = 0

            else:
                aviator_data['extra'].append("Rank")

        write_interactive_log("{id:>9} | {name:<28} | {kills:4} | {:26} | {health:6} | {}".format(
            AIR_RANKS[aviator_data['rank']],
            ", ".join(aviator_data["extra"]),
            **aviator_data)
        )

    db_post_data = []
    for aviator_id, aviator_data in aviators.items():
        db_post_data.append(dict(id=aviator_id, name=aviator_data['name'],
                                 rank=aviator_data['rank'], factory_count=aviator_data['factories']))
    requests.post('https://erep.lv/aviator/set/', json=db_post_data)

    for aviator_id, new in aviators.items():
        resp = requests.get('https://erep.lv/aviator/check/{}/'.format(aviator_id))
        if not resp.json()['status']:
            aviators[aviator_id]['health'] = 0
            aviators[aviator_id]['extra'] = ["Nav izmaiņas fabriku skaitā", ]

    for player_id in forbidden_ids:
        if player_id in aviators:
            aviators[player_id]['health'] = 0
            if "BANNED" not in aviators[player_id]['extra']:
                aviators[player_id]['extra'] = ["Aizliegta pieteikšanās", ]

    sent_data = []
    if send_food:
        for aviator_data in sorted(aviators.values(), key=lambda t: (-t["health"], -t['kills'])):
            remaining = aviator_data['health']
            if not remaining:
                sent_data.append({
                    "player_id": aviator_data['id'], "name": aviator_data['name'], "quality": 0,
                    "amount": 0, "energy": 0, "price": 0, "cost": 0,
                })
            while remaining > 0:
                o = []
                if free_food:
                    # Reversed because need to start with higher qualities so that q1 stays available
                    for quality in reversed(list(free_food.keys())):
                        if free_food[quality]:
                            o.append((quality, {'price': 0., 'amount': free_food[quality]}))
                        else:
                            free_food.pop(quality)
                if not free_food:
                    offers = citizen.get_market_offers(71, product="food")
                    o += sorted(offers.items(), key=lambda v: (v[1]['price'] / FOOD_ENERGY[v[0]],
                                                               -v[1]['amount'] * FOOD_ENERGY[v[0]]))

                for _o in o:
                    q, q_data = _o
                    if FOOD_ENERGY[q] <= remaining:
                        break
                else:
                    write_interactive_log(
                        "{name} needs to receive extra {remaining}hp".format(name=aviator_data['name'],
                                                                             remaining=remaining))
                    break

                if q_data['amount'] * FOOD_ENERGY[q] <= remaining:
                    amount = q_data['amount']
                else:
                    amount = remaining // FOOD_ENERGY[q]

                if q_data['price']:
                    # print(f"citizen._buy_market_offer(offer={q_data['offer_id']}, amount={amount})")
                    citizen.post_economy_marketplace_actions(citizen.token, amount=amount, buy=True,
                                                             offer=q_data["offer_id"])
                else:
                    free_food[q] -= amount

                # print(f"citizen.donate_items(citizen_id={aviator_data['id']},
                #                              amount={amount}, industry_id=1, quality={int(q[1])})")
                citizen.donate_items(citizen_id=aviator_data['id'], amount=amount, industry_id=1, quality=int(q[1]))
                remaining -= amount * FOOD_ENERGY[q]
                context['TOTAL_CC'] += q_data['price'] * amount
                context['TOTAL_ENERGY'] += amount * FOOD_ENERGY[q]
                sent_data.append(
                    {"player_id": aviator_data['id'], "name": aviator_data['name'], "quality": q, "amount": amount,
                     "energy": amount * FOOD_ENERGY[q], "price": q_data['price'],
                     "cost": q_data['price'] * amount, })

    with open(get_file("{eday}.csv".format(eday=eday_from_date(now()))), 'a') as f:
        f.write('PlayerID, Quality, Amount, Energy, Price, Cost\n')
        for player_data in sent_data:
            f.write('{player_id}, {quality}, {amount}, {energy}, {price}, {cost}\n'.format(**player_data))

    columns = ('[columns][b]Spēlētajs[/b]\n'
               '{players}[nextcol][b]Kili[/b]\n'
               '{kills}\n'
               '[nextcol][right][b]Enerģija[/b]\n'
               '{health}\n'
               '[/right][/columns]')
    player_template = '[b][url=https://www.erepublik.com/en/citizen/profile/{id}]{name}[/url][/b]'
    players = []
    kills = []
    health = []
    write_interactive_log("\n".join(["{}: {}".format(q, a) for q, a in free_food.items()]))
    context['TOTAL_CC'] = round(context['TOTAL_CC'], 2)
    context["END_ENERGY"] = sum([amount * FOOD_ENERGY[q] for q, amount in free_food.items()])
    data = {}
    for row in sent_data:
        pid = int(row['player_id'])
        if pid not in data:
            data.update({pid: dict(id=pid, name=row['name'], energy=0, cost=0, kills=aviators[pid]['kills'])})

        data[pid]["energy"] += row['energy']
        data[pid]["cost"] += row['cost']

    for pid, player_data in sorted(aviators.items(), key=lambda t: (-t[1]["health"], -t[1]['kills'])):
        players.append(player_template.format(id=pid, name=player_data['name']))
        kills.append(str(player_data['kills']))
        health.append(str(player_data['health'] or ", ".join(player_data['extra'])))
    else:
        context['TABLE'] = columns.format(
            players="\n".join(players),
            kills="\n".join(kills),
            health="\n".join(health)
        )

    if os.path.isfile("scripts/KM_piloti.txt"):
        with open("scripts/KM_piloti.txt") as f:
            template = f.read()
        article = template.format(**context)
        with open(get_file("{eday}.txt".format(eday=eday_from_date(now()))), "w") as f:
            f.write(article)
        if send_food:
            article_data = dict(
                title="[KM] Gaisa maizītes [d{} {}]".format(citizen.eday, citizen.now.strftime("%H:%M")),
                content=article,
                kind=3
            )
            from_eday = eday_from_date(good_timedelta(now(), - datetime.timedelta(days=now().weekday() + 6)))
            till_eday = eday_from_date(good_timedelta(now(), - datetime.timedelta(days=now().weekday())))
            comment_data = dict(
                message="★★★★ MAIZE PAR NEDĒĻU [DAY {}-{}] IZDALĪTA ★★★★\n★ Apgādei piesakāmies šī komentāra reply "
                        "komentāros ar saucienu - piesakos! ★".format(from_eday, till_eday))
            total_cc = int(round(context['TOTAL_CC']))
            wall_body = ("★★★ [ KONGRESA BALSOJUMS ] ★★★\n\nDotācija pilotiem par d{}-{} {}cc apmērā.\n\n"
                         "Balsot ar Par/Pret\nBalsošanas laiks 24h līdz d{} {}").format(
                from_eday, till_eday, total_cc, citizen.eday + 1, citizen.now.strftime("%H:%M"))

            citizen.write_log("Publishing info:\n\n### Article ###\n{}\n\n{}\n\n### Wall ###\n{}".format(
                article_data['title'], comment_data['message'], wall_body
            ))

            KM_account: Citizen = Citizen("kara-ministrija@erep.lv", "KMPar0le")
            KM_account.set_debug(True)
            KM_account.update_citizen_info()
            resp = KM_account.publish_article(**article_data)
            article_id = resp.history[1].url.split("/")[-3]
            comment_data.update({"article_id": article_id})
            KM_account.write_article_comment(**comment_data)
            citizen.write_on_country_wall(wall_body)
            requests.post('https://erep.lv/aviator/latest_article/',
                          data=dict(week=context["WEEK"], article_id=article_id))
