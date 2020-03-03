import datetime
import decimal
import hashlib
import threading
from collections import defaultdict, deque
from typing import Any, Dict, Iterable, List, Tuple, Union

from requests import Response, Session, post

from erepublik import utils
from erepublik.access_points import CitizenAPI

try:
    import simplejson as json
except ImportError:
    import json


class ErepublikException(Exception):
    def __init__(self, message):
        super().__init__(message)


class ErepublikNetworkException(ErepublikException):
    def __init__(self, message, request):
        super().__init__(message)
        self.request = request


class MyCompanies:
    work_units: int = 0
    next_ot_time: datetime.datetime
    holdings: Dict[int, Dict] = None
    companies: Dict[int, Dict] = None
    ff_lockdown: int = 0

    def __init__(self):
        self.holdings = dict()
        self.companies = dict()
        self.next_ot_time = utils.now()

    def prepare_holdings(self, holdings: dict):
        """
        :param holdings: Parsed JSON to dict from en/economy/myCompanies
        """
        self.holdings.clear()
        template = dict(id=0, num_factories=0, region_id=0, companies=[])

        for holding_id, holding in holdings.items():
            tmp: Dict[str, Union[Iterable[Any], Any]] = {}
            for key in template:
                if key == 'companies':
                    tmp.update({key: []})
                else:
                    tmp.update({key: holding[key]})
            self.holdings.update({int(holding_id): tmp})
        self.holdings.update({0: template})  # unassigned

    def prepare_companies(self, companies: dict):
        """
        :param companies: Parsed JSON to dict from en/economy/myCompanies
        """
        self.companies.clear()
        template = dict(id=None, quality=0, is_raw=False, resource_bonus=0, effective_bonus=0, raw_usage=0,
                        base_production=0, wam_enabled=False, can_work_as_manager=False, industry_id=0, todays_works=0,
                        preset_own_work=0, already_worked=False, can_assign_employees=False, preset_works=0,
                        holding_company_id=None, is_assigned_to_holding=False, cannot_work_as_manager_reason=False)

        for c_id, company in companies.items():
            tmp = {}
            for key in template.keys():
                if key in ['id', 'holding_company_id']:
                    company[key] = int(company[key])
                elif key == "raw_usage":
                    if not company.get("is_raw") and company.get('upgrades'):
                        company[key] = company.get('upgrades').get(str(company["quality"])).get('raw_usage')
                tmp.update({key: company[key]})
            self.companies.update({int(c_id): tmp})

    def update_holding_companies(self):
        for company_id, company_data in self.companies.items():
            if company_id not in self.holdings[company_data['holding_company_id']]['companies']:
                self.holdings[company_data['holding_company_id']]['companies'].append(company_id)
        for holding_id in self.holdings:
            self.holdings[holding_id]['companies'].sort()

    def get_employable_factories(self) -> Dict[int, int]:
        ret = {}
        for company_id, company in self.companies.items():
            if company.get('preset_works'):
                ret[company_id] = int(company.get('preset_works', 0))
        return ret

    def get_total_wam_count(self) -> int:
        ret = 0
        for holding_id in self.holdings:
            ret += self.get_holding_wam_count(holding_id)
        return ret

    def get_holding_wam_count(self, holding_id: int, raw_factory=None) -> int:
        """
        Returns amount of wam enabled companies in the holding
        :param holding_id: holding id
        :param raw_factory: True - only raw, False - only factories, None - both
        :return: int
        """
        return len(self.get_holding_wam_companies(holding_id, raw_factory))

    def get_holding_employee_count(self, holding_id):
        employee_count = 0
        if holding_id in self.holdings:
            for company_id in self.holdings.get(holding_id, {}).get('companies', []):
                employee_count += self.companies.get(company_id).get('preset_works', 0)
        return employee_count

    def get_holding_wam_companies(self, holding_id: int, raw_factory: bool = None) -> List[int]:
        """
        Returns WAM enabled companies in the holding, True - only raw, False - only factories, None - both
        :param holding_id: holding id
        :param raw_factory: bool or None
        :return: list
        """
        raw = []
        factory = []
        if holding_id in self.holdings:
            for company_id in sorted(self.holdings.get(holding_id, {}).get('companies', []),
                                     key=lambda cid: (-self.companies[cid].get('is_raw'),  # True, False
                                                      self.companies[cid].get('industry_id'),  # F W H A
                                                      -self.companies[cid].get('quality'),)):  # 7, 6, .. 2, 1
                company = self.companies.get(company_id, {})
                wam_enabled = bool(company.get('wam_enabled', {}))
                already_worked = not company.get('already_worked', {})
                cannot_work_war = company.get("cannot_work_as_manager_reason", {}) == "war"
                if wam_enabled and already_worked and not cannot_work_war:
                    if company.get('is_raw', False):
                        raw.append(company_id)
                    else:
                        factory.append(company_id)
        if raw_factory is not None and not raw_factory:
            return factory
        elif raw_factory is not None and raw_factory:
            return raw
        elif raw_factory is None:
            return raw + factory
        else:
            raise ErepublikException("raw_factory should be True/False/None")

    def get_needed_inventory_usage(self, company_id: int = None, companies: list = None) -> float:
        if not any([companies, company_id]):
            return 0.
        if company_id:
            if company_id not in self.companies:
                raise ErepublikException("Company ({}) not in all companies list".format(company_id))
            company = self.companies[company_id]
            if company.get("is_raw"):
                return float(company["base_production"]) * company["effective_bonus"]
            else:
                products_made = company["base_production"] * company["effective_bonus"] / 100
                # raw_used = products_made * company['upgrades'][str(company['quality'])]['raw_usage'] * 100
                return float(products_made - company['raw_usage'])
        if companies:
            return float(sum([self.get_needed_inventory_usage(company_id=cid) for cid in companies]))

        raise ErepublikException("Wrong function call")

    def get_wam_raw_usage(self) -> Dict[str, float]:
        frm = 0.00
        wrm = 0.00
        for company in self.companies.values():
            if company['wam_enabled']:
                effective_bonus = float(company["effective_bonus"])
                base_prod = float(company["base_production"])
                raw = base_prod * effective_bonus / 100
                if not company["is_raw"]:
                    raw *= -company["raw_usage"]
                if company["industry_id"] in [1, 7, 8, 9, 10, 11]:
                    frm += raw
                elif company["industry_id"] in [2, 12, 13, 14, 15, 16]:
                    wrm += raw
        return {'frm': int(frm * 1000) / 1000, 'wrm': int(wrm * 1000) / 1000}

    def __str__(self):
        name = []
        for holding_id in sorted(self.holdings.keys()):
            if not holding_id:
                name.append(f"Unassigned - {len(self.holdings[0]['companies'])}")
            else:
                name.append(f"{holding_id} - {len(self.holdings[holding_id]['companies'])}")
        return " | ".join(name)

    # @property
    # def __dict__(self):
    #     ret = {}
    #     for key in dir(self):
    #         if not key.startswith('_'):
    #             ret[key] = getattr(self, key)
    #     return ret


class Config:
    email = ""
    password = ""
    work = True
    train = True
    wam = False
    ot = True
    auto_sell: List[str] = None
    auto_sell_all = False
    employees = False
    fight = False
    air = False
    ground = False
    all_in = False
    next_energy = False
    boosters = False
    travel_to_fight = False
    always_travel = False
    epic_hunt = False
    epic_hunt_ebs = False
    rw_def_side = False
    interactive = True
    continuous_fighting = False
    auto_buy_raw = False
    force_wam = False
    sort_battles_time = True
    force_travel = False
    telegram = True
    telegram_chat_id = 0
    telegram_token = ""

    def __init__(self):
        self.auto_sell = []

    def reset(self):
        self.work = True
        self.train = True
        self.wam = False
        self.ot = True
        self.auto_sell = list()
        self.auto_sell_all = False
        self.employees = False
        self.fight = False
        self.air = False
        self.ground = False
        self.all_in = False
        self.next_energy = False
        self.boosters = False
        self.travel_to_fight = False
        self.always_travel = False
        self.epic_hunt = False
        self.epic_hunt_ebs = False
        self.rw_def_side = False
        self.interactive = True
        self.continuous_fighting = False
        self.auto_buy_raw = False
        self.force_wam = False
        self.sort_battles_time = True
        self.force_travel = False
        self.telegram = True
        self.telegram_chat_id = 0
        self.telegram_token = ""

    @property
    def __dict__(self):
        return dict(email=self.email, work=self.work, train=self.train, wam=self.wam, ot=self.ot,
                    auto_sell=self.auto_sell, auto_sell_all=self.auto_sell_all, employees=self.employees,
                    fight=self.fight, air=self.air, ground=self.ground, all_in=self.all_in,
                    next_energy=self.next_energy, boosters=self.boosters, travel_to_fight=self.travel_to_fight,
                    always_travel=self.always_travel, epic_hunt=self.epic_hunt, epic_hunt_ebs=self.epic_hunt_ebs,
                    rw_def_side=self.rw_def_side, interactive=self.interactive,
                    continuous_fighting=self.continuous_fighting, auto_buy_raw=self.auto_buy_raw,
                    force_wam=self.force_wam, sort_battles_time=self.sort_battles_time, force_travel=self.force_travel,
                    telegram=self.telegram, telegram_chat_id=self.telegram_chat_id, telegram_token=self.telegram_token)


class Energy:
    limit = 500  # energyToRecover
    interval = 10  # energyPerInterval
    recoverable = 0  # energyFromFoodRemaining
    recovered = 0  # energy
    _recovery_time = None

    def __init__(self):
        self._recovery_time = utils.now()

    def __repr__(self):
        return "{:4}/{:4} + {:4}, {:3}hp/6min".format(self.recovered, self.limit, self.recoverable, self.interval)

    def set_reference_time(self, recovery_time: datetime.datetime):
        self._recovery_time = recovery_time.replace(microsecond=0)

    @property
    def food_fights(self):
        return self.available // 10

    @property
    def reference_time(self):
        if self.is_recovered_full or self._recovery_time < utils.now():
            ret = utils.now()
        else:
            ret = self._recovery_time
        return ret

    @property
    def is_recoverable_full(self):
        return self.recoverable >= self.limit - 5 * self.interval

    @property
    def is_recovered_full(self):
        return self.recovered >= self.limit - self.interval

    @property
    def is_energy_full(self):
        return self.is_recoverable_full and self.is_recovered_full

    @property
    def available(self):
        return self.recovered + self.recoverable


class Details:
    xp = 0
    cc = 0
    pp = 0
    pin = None
    gold = 0
    next_pp: List[int] = None
    citizen_id = 0
    citizenship = 0
    current_region = 0
    current_country = 0
    residence_region = 0
    residence_country = 0
    daily_task_done = False
    daily_task_reward = False
    mayhem_skills = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0, 9: 0, 10: 0, 11: 0, 12: 0, 13: 0, 14: 0, }

    def __init__(self):
        self.next_pp = []

    @property
    def xp_till_level_up(self):
        if self.xp >= 10000:
            next_level_up = (1 + (self.xp // 5000)) * 5000
        elif self.xp >= 7000:
            next_level_up = 10000
        elif self.xp >= 3000:
            next_level_up = (1 + ((self.xp - 1000) // 2000)) * 2000 + 1000
        elif self.xp >= 2000:
            next_level_up = 3000
        elif self.xp >= 450:
            next_level_up = (1 + (self.xp // 500)) * 500
        elif self.xp >= 370:
            next_level_up = (1 + ((self.xp - 10) // 40)) * 40 + 10
        elif self.xp >= 300:
            next_level_up = (1 + ((self.xp - 20) // 35)) * 35 + 20
        elif self.xp >= 150:
            next_level_up = (1 + (self.xp // 30)) * 30
        elif self.xp >= 50:
            next_level_up = (1 + ((self.xp - 10) // 20)) * 20 + 10
        elif self.xp >= 20:
            next_level_up = (1 + ((self.xp - 5) // 15)) * 15 + 5
        else:
            next_level_up = (1 + (self.xp // 10)) * 10
        return next_level_up - self.xp


class Politics:
    is_party_member: bool = False

    party_id: int = 0
    party_slug: str = ""
    is_party_president: bool = False
    is_congressman: bool = False
    is_country_president: bool = False


class House:
    quality = None
    unactivated_count = 0
    active_untill = utils.good_timedelta(utils.now(), -datetime.timedelta(days=1))

    def __init__(self, quality: int):
        if 0 < quality < 6:
            self.quality = quality

    @property
    def next_ot_point(self) -> datetime.datetime:
        return self.active_untill


class Reporter:
    __to_update: List[Dict[Any, Any]] = None
    name: str = ""
    email: str = ""
    citizen_id: int = 0
    key: str = ""
    allowed: bool = False

    @property
    def __dict__(self):
        return dict(name=self.name, email=self.email, citizen_id=self.citizen_id, key=self.key, allowed=self.allowed,
                    queue=self.__to_update)

    def __init__(self):
        self._req = Session()
        self.url = "https://api.erep.lv"
        self._req.headers.update({"user-agent": "Bot reporter v2"})
        self.__to_update = []
        self.__registered: bool = False

    def do_init(self, name: str = "", email: str = "", citizen_id: int = 0):
        self.name: str = name
        self.email: str = email
        self.citizen_id: int = citizen_id
        self.key: str = ""
        self.__update_key()
        self.allowed = True

    def __update_key(self):
        self.key = hashlib.md5(bytes(f"{self.name}:{self.email}", encoding="UTF-8")).hexdigest()
        self.allowed = True
        self.register_account()

    def __bot_update(self, data: dict) -> Response:
        if self.__to_update:
            for unreported_data in self.__to_update:
                unreported_data.update(player_id=self.citizen_id, key=self.key)
                self._req.post("{}/bot/update".format(self.url), json=unreported_data)
            self.__to_update.clear()
        r = self._req.post("{}/bot/update".format(self.url), json=data)
        return r

    def register_account(self):
        if not self.__registered:
            try:
                r = self.__bot_update(dict(key=self.key, check=True, player_id=self.citizen_id))
                if not r.json().get("status"):
                    self._req.post("{}/bot/register".format(self.url), json=dict(name=self.name, email=self.email,
                                                                                 player_id=self.citizen_id))
            finally:
                self.__registered = True
                self.report_action("STARTED", value=utils.now().strftime("%F %T"))

    def send_state_update(self, xp: int, cc: float, gold: float, inv_total: int, inv: int,
                          hp_limit: int, hp_interval: int, hp_available: int, food: int, pp: int):

        data = dict(key=self.key, player_id=self.citizen_id, state=dict(
            xp=xp, cc=cc, gold=gold, inv_total=inv_total, inv_free=inv_total - inv, inv=inv, food=food,
            pp=pp, hp_limit=hp_limit, hp_interval=hp_interval, hp_available=hp_available,
        ))

        if self.allowed:
            self.__bot_update(data)

    def report_action(self, action: str, json_val: Dict[Any, Any] = None, value: str = None):
        if all([self.key, self.email, self.name, self.citizen_id]):
            return
        json_data = {'player_id': self.citizen_id, 'key': self.key, 'log': dict(action=action)}
        if json_val:
            json_data['log'].update(dict(json=json_val))
        if value:
            json_data['log'].update(dict(value=value))
        if self.allowed:
            self.__bot_update(json_data)
        else:
            self.__to_update.append(json_data)


class MyJSONEncoder(json.JSONEncoder):
    def default(self, o):
        from erepublik.citizen import Citizen
        if isinstance(o, decimal.Decimal):
            return float("{:.02f}".format(o))
        elif isinstance(o, datetime.datetime):
            return dict(__type__='datetime', date=o.strftime("%Y-%m-%d"), time=o.strftime("%H:%M:%S"),
                        tzinfo=o.tzinfo.zone if o.tzinfo else None)
        elif isinstance(o, datetime.date):
            return dict(__type__='date', date=o.strftime("%Y-%m-%d"))
        elif isinstance(o, datetime.timedelta):
            return dict(__type__='timedelta', days=o.days, seconds=o.seconds,
                        microseconds=o.microseconds, total_seconds=o.total_seconds())
        elif isinstance(o, Response):
            return dict(headers=o.headers.__dict__, url=o.url, text=o.text)
        elif hasattr(o, '__dict__'):
            return o.__dict__
        elif isinstance(o, (deque, set)):
            return list(o)
        elif isinstance(o, Citizen):
            return o.to_json()
        return super().default(o)


class BattleSide:
    id: int
    points: int
    deployed: List[int] = None
    allies: List[int] = None

    def __init__(self, country_id: int, points: int, allies: List[int], deployed: List[int]):
        self.id = country_id
        self.points = points
        self.allies = [int(ally) for ally in allies]
        self.deployed = [int(ally) for ally in deployed]


class BattleDivision:
    end: datetime.datetime
    epic: bool
    dom_pts: Dict[str, int]
    wall: Dict[str, Union[int, float]]
    battle_zone_id: int
    def_medal: Dict[str, int]
    inv_medal: Dict[str, int]

    @property
    def div_end(self) -> bool:
        return utils.now() >= self.end

    def __init__(self, **kwargs):
        """Battle division helper class

        :param kwargs: must contain keys:
            div_id: int, end: datetime.datetime, epic: bool, inv_pts: int, def_pts: int,
            wall_for: int, wall_dom: float, def_medal: Tuple[int, int], inv_medal: Tuple[int, int]
        """

        self.battle_zone_id = kwargs.get("div_id", 0)
        self.end = kwargs.get("end", 0)
        self.epic = kwargs.get("epic", 0)
        self.dom_pts = dict({"inv": kwargs.get("inv_pts", 0), "def": kwargs.get("def_pts", 0)})
        self.wall = dict({"for": kwargs.get("wall_for", 0), "dom": kwargs.get("wall_dom", 0)})
        self.def_medal = {"id": kwargs.get("def_medal", 0)[0], "dmg": kwargs.get("def_medal", 0)[1]}
        self.inv_medal = {"id": kwargs.get("inv_medal", 0)[0], "dmg": kwargs.get("inv_medal", 0)[1]}

    @property
    def id(self):
        return self.battle_zone_id


class Battle:
    id: int
    war_id: int
    zone_id: int
    is_rw: bool
    is_dict_lib: bool
    start: datetime.datetime
    invader: BattleSide
    defender: BattleSide
    div: Dict[int, BattleDivision]

    @property
    def is_air(self) -> bool:
        return not bool(self.zone_id % 4)

    def __init__(self, battle: Dict[str, Any]):
        """Object representing eRepublik battle.

        :param battle: Dict object for single battle from '/military/campaignsJson/list' response's 'battles' object
        """

        self.id = int(battle.get('id'))
        self.war_id = int(battle.get('war_id'))
        self.zone_id = int(battle.get('zone_id'))
        self.is_rw = bool(battle.get('is_rw'))
        self.is_as = bool(battle.get('is_as'))
        self.is_dict_lib = bool(battle.get('is_dict')) or bool(battle.get('is_lib'))
        self.start = datetime.datetime.fromtimestamp(int(battle.get('start', 0)), tz=utils.erep_tz)

        self.invader = BattleSide(
            battle.get('inv', {}).get('id'), battle.get('inv', {}).get('points'),
            [row.get('id') for row in battle.get('inv', {}).get('ally_list')],
            [row.get('id') for row in battle.get('inv', {}).get('ally_list') if row['deployed']]
        )

        self.defender = BattleSide(
            battle.get('def', {}).get('id'), battle.get('def', {}).get('points'),
            [row.get('id') for row in battle.get('def', {}).get('ally_list')],
            [row.get('id') for row in battle.get('def', {}).get('ally_list') if row['deployed']]
        )

        self.div = defaultdict(BattleDivision)
        for div, data in battle.get('div', {}).items():
            div = int(data.get('div'))
            if data.get('end'):
                end = datetime.datetime.fromtimestamp(data.get('end'), tz=utils.erep_tz)
            else:
                end = utils.localize_dt(datetime.datetime.max - datetime.timedelta(days=1))

            if not data['stats']['def']:
                def_medal = (0, 0)
            else:
                def_medal = (data['stats']['def']['citizenId'], data['stats']['def']['damage'])
            if not data['stats']['inv']:
                inv_medal = (0, 0)
            else:
                inv_medal = (data['stats']['inv']['citizenId'], data['stats']['inv']['damage'])
            battle_div = BattleDivision(end=end, epic=data.get('epic_type') in [1, 5], div_id=data.get('id'),
                                        inv_pts=data.get('dom_pts').get("inv"), def_pts=data.get('dom_pts').get("def"),
                                        wall_for=data.get('wall').get("for"), wall_dom=data.get('wall').get("dom"),
                                        def_medal=def_medal, inv_medal=inv_medal)

            self.div.update({div: battle_div})

    def __repr__(self):
        now = utils.now()
        is_started = self.start < utils.now()
        if is_started:
            time_part = " {}".format(now - self.start)
        else:
            time_part = "-{}".format(self.start - now)

        return f"Battle {self.id} | " \
               f"{utils.ISO_CC[self.invader.id]} : {utils.ISO_CC[self.defender.id]} | " \
               f"Round {self.zone_id:2} | " \
               f"Round time {time_part}"


class EnergyToFight:
    energy: int = 0

    def __init__(self, energy: int = 0):
        self.energy = energy

    def __int__(self):
        return self.energy

    def __str__(self):
        return str(self.energy)

    def __repr__(self):
        return str(self.energy)

    @property
    def i(self):
        return self.__int__()

    @property
    def s(self):
        return self.__str__()

    def check(self, new_energy: int):
        if not isinstance(new_energy, (tuple, int)):
            return self.energy
        if 0 < new_energy < self.energy:
            self.energy = new_energy
        return self.energy


class TelegramBot:
    __initialized: bool = False
    __queue: List[str]
    chat_id: int = 0
    api_url: str = ""
    player_name: str = ""
    __thread_stopper: threading.Event
    _last_time: datetime.datetime
    _last_full_energy_report: datetime.datetime
    _next_time: datetime.datetime
    _threads: List[threading.Thread]

    def __init__(self, stop_event: threading.Event = None):
        self._threads = []
        self.__queue = []
        self.__thread_stopper = threading.Event() if stop_event is None else stop_event
        self._last_full_energy_report = self._last_time = utils.good_timedelta(utils.now(), datetime.timedelta(hours=1))
        self._next_time = utils.now()

    @property
    def __dict__(self):
        return {'chat_id': self.chat_id, 'api_url': self.api_url, 'player': self.player_name,
                'last_time': self._last_time, 'next_time': self._next_time, 'queue': self.__queue,
                'initialized': self.__initialized, 'has_threads': bool(len(self._threads))}

    def do_init(self, chat_id: int, token: str, player_name: str = ""):
        self.chat_id = chat_id
        self.api_url = "https://api.telegram.org/bot{}/sendMessage".format(token)
        self.player_name = player_name
        self.__initialized = True
        self._last_time = utils.good_timedelta(utils.now(), datetime.timedelta(minutes=-5))
        self._last_full_energy_report = utils.good_timedelta(utils.now(), datetime.timedelta(minutes=-30))
        if self.__queue:
            self.send_message("\n\n––––––––––––––––––––––\n\n".join(self.__queue))

    def send_message(self, message: str) -> bool:
        self.__queue.append(message)
        if not self.__initialized:
            if self._last_time < utils.now():
                self.__queue.clear()
            return True
        self._threads = [t for t in self._threads if t.is_alive()]
        self._next_time = utils.good_timedelta(utils.now(), datetime.timedelta(seconds=20))
        if not self._threads:
            name = "telegram_{}send".format(f"{self.player_name}_" if self.player_name else "")
            send_thread = threading.Thread(target=self.__send_messages, name=name)
            send_thread.start()
            self._threads.append(send_thread)

        return True

    def report_free_bhs(self, battles: List[Tuple[int, int, int, int, datetime.timedelta]]):
        battle_links = []
        for battle_id, side_id, against_id, damage, time_left in battles:
            total_seconds = int(time_left.total_seconds())
            time_start = ""
            hours, remainder = divmod(total_seconds, 3600)
            if hours:
                time_start = f"{hours}h "
            minutes, seconds = divmod(remainder, 60)
            time_start += f"{minutes:02}m {seconds:02}s"
            damage = "{:,}".format(damage).replace(',', ' ')
            battle_links.append(f"*{damage}*dmg bh for [{utils.COUNTRIES[side_id]} vs {utils.COUNTRIES[against_id]}]"
                                f"(https://www.erepublik.com/en/military/battlefield/{battle_id}) "
                                f"_time since start {time_start}_")
        self.send_message("Free BHs:\n" + "\n".join(battle_links))

    def report_full_energy(self, available: int, limit: int, interval: int):
        if (utils.now() - self._last_full_energy_report).total_seconds() >= 30 * 60:
            self._last_full_energy_report = utils.now()
            message = f"Full energy ({available}hp/{limit}hp +{interval}hp/6min)"
            self.send_message(message)

    def report_medal(self, msg, multiple: bool=True):
        new_line = '\n' if multiple else ''
        self.send_message(f"New award: {new_line}*{msg}*")

    def __send_messages(self):
        while self._next_time > utils.now():
            if self.__thread_stopper.is_set():
                break
            self.__thread_stopper.wait(utils.get_sleep_seconds(self._next_time))

        message = "\n\n––––––––––––––––––––––\n\n".join(self.__queue)
        if self.player_name:
            message = f"Player *{self.player_name}*\n" + message
        response = post(self.api_url, json=dict(chat_id=self.chat_id, text=message, parse_mode="Markdown"))
        self._last_time = utils.now()
        if response.json().get('ok') and not self.__queue:
            self.__queue.clear()
            return True
        return False
