import datetime
import hashlib
import threading
import weakref
from decimal import Decimal
from typing import Any, Dict, Generator, Iterable, List, NamedTuple, NoReturn, Union

from requests import Response, Session, post

from . import constants, types, utils

__all__ = ['Battle', 'BattleDivision', 'BattleSide', 'Company', 'Config', 'Details', 'Energy', 'ErepublikException',
           'ErepublikJSONEncoder', 'ErepublikNetworkException', 'EnergyToFight', 'Holding', 'Inventory', 'MyCompanies',
           'OfferItem', 'Politics', 'Reporter', 'TelegramReporter', ]


class ErepublikException(Exception):
    def __init__(self, message):
        super().__init__(message)


class ErepublikNetworkException(ErepublikException):
    def __init__(self, message, request):
        super().__init__(message)
        self.request = request


class Holding:
    id: int
    region: int
    companies: List['Company']
    name: str
    _citizen = weakref.ReferenceType

    def __init__(self, _id: int, region: int, citizen, name: str = None):
        self._citizen = weakref.ref(citizen)
        self.id: int = _id
        self.region: int = region
        self.companies: List['Company'] = list()
        if name:
            self.name = name
        else:
            comp_sum = len(self.companies)
            name = f"Holding (#{self.id}) with {comp_sum} "
            if comp_sum == 1:
                name += 'company'
            else:
                name += 'companies'
            self.name = name

    @property
    def wam_count(self) -> int:
        return len([1 for company in self.companies if company.wam_enabled and not company.already_worked])

    @property
    def wam_companies(self) -> Iterable['Company']:
        return [company for company in self.companies if company.wam_enabled]

    @property
    def employable_companies(self) -> Iterable['Company']:
        return [company for company in self.companies if company.preset_works]

    def add_company(self, company: 'Company') -> NoReturn:
        self.companies.append(company)
        self.companies.sort()

    def get_wam_raw_usage(self) -> Dict[str, Decimal]:
        frm = Decimal('0.00')
        wrm = Decimal('0.00')
        for company in self.wam_companies:
            if company.industry in [1, 7, 8, 9, 10, 11]:
                frm += company.raw_usage
            elif company.industry in [2, 12, 13, 14, 15, 16]:
                wrm += company.raw_usage
        return dict(frm=frm, wrm=wrm)

    def get_wam_companies(self, raw_factory: bool = None) -> List['Company']:
        raw = []
        factory = []
        for company in self.wam_companies:
            if not company.already_worked and not company.cannot_wam_reason == 'war':
                if company.is_raw:
                    raw.append(company)
                else:
                    factory.append(company)
        if raw_factory is None:
            return raw + factory
        else:
            return raw if raw_factory else factory

    def __str__(self) -> str:
        comp = len(self.companies)
        name = f"Holding (#{self.id}) with {comp} "
        if comp == 1:
            name += 'company'
        else:
            name += 'companies'
        return name

    def __repr__(self):
        return str(self)

    @property
    def as_dict(self) -> Dict[str, Union[str, int, List[Dict[str, Union[str, int, bool, float, Decimal]]]]]:
        return dict(name=self.name, id=self.id, region=self.region,
                    companies=[c.as_dict for c in self.companies], wam_count=self.wam_count)

    @property
    def citizen(self):
        return self._citizen()


class Company:
    _holding: weakref.ReferenceType
    holding: Holding
    id: int
    quality: int
    is_raw: bool
    raw_usage: Decimal
    products_made: Decimal
    wam_enabled: bool
    can_wam: bool
    cannot_wam_reason: str
    industry: int
    already_worked: bool
    preset_works: int

    def __init__(
        self, holding: Holding, _id: int, quality: int, is_raw: bool, effective_bonus: Decimal, raw_usage: Decimal,
        base_production: Decimal, wam_enabled: bool, can_wam: bool, cannot_wam_reason: str, industry: int,
        already_worked: bool, preset_works: int
    ):
        self._holding = weakref.ref(holding)
        self.id: int = _id
        self.industry: int = industry
        self.quality: int = self._get_real_quality(quality)
        self.is_raw: bool = is_raw
        self.wam_enabled: bool = wam_enabled
        self.can_wam: bool = can_wam
        self.cannot_wam_reason: str = cannot_wam_reason
        self.already_worked: bool = already_worked
        self.preset_works: int = preset_works

        self.products_made = self.raw_usage = Decimal(base_production) * Decimal(effective_bonus)
        if not self.is_raw:
            self.raw_usage = - self.products_made * raw_usage

    def _get_real_quality(self, quality) -> int:
        #  7: 'FRM q1',  8: 'FRM q2',  9: 'FRM q3', 10: 'FRM q4', 11: 'FRM q5',
        # 12: 'WRM q1', 13: 'WRM q2', 14: 'WRM q3', 15: 'WRM q4', 16: 'WRM q5',
        # 18: 'HRM q1', 19: 'HRM q2', 20: 'HRM q3', 21: 'HRM q4', 22: 'HRM q5',
        # 24: 'ARM q1', 25: 'ARM q2', 26: 'ARM q3', 27: 'ARM q4', 28: 'ARM q5',
        if 7 <= self.industry <= 11:
            return self.industry % 6
        elif 12 <= self.industry <= 16:
            return self.industry % 11
        elif 18 <= self.industry <= 22:
            return self.industry % 17
        elif 24 <= self.industry <= 28:
            return self.industry % 23
        else:
            return quality

    @property
    def _internal_industry(self) -> int:
        #  7: 'FRM q1',  8: 'FRM q2',  9: 'FRM q3', 10: 'FRM q4', 11: 'FRM q5',
        # 12: 'WRM q1', 13: 'WRM q2', 14: 'WRM q3', 15: 'WRM q4', 16: 'WRM q5',
        # 18: 'HRM q1', 19: 'HRM q2', 20: 'HRM q3', 21: 'HRM q4', 22: 'HRM q5',
        # 24: 'ARM q1', 25: 'ARM q2', 26: 'ARM q3', 27: 'ARM q4', 28: 'ARM q5',
        if 7 <= self.industry <= 11:
            return 7
        elif 12 <= self.industry <= 16:
            return 12
        elif 18 <= self.industry <= 22:
            return 18
        elif 24 <= self.industry <= 28:
            return 24
        else:
            return self.industry

    @property
    def _sort_keys(self):
        return not self.is_raw, self._internal_industry, self.quality, self.id

    def __hash__(self):
        return hash(self._sort_keys)

    def __lt__(self, other: 'Company'):
        return self._sort_keys < other._sort_keys

    def __le__(self, other: 'Company'):
        return self._sort_keys <= other._sort_keys

    def __gt__(self, other: 'Company'):
        return self._sort_keys > other._sort_keys

    def __ge__(self, other: 'Company'):
        return self._sort_keys >= other._sort_keys

    def __eq__(self, other: 'Company'):
        return self._sort_keys == other._sort_keys

    def __ne__(self, other: 'Company'):
        return self._sort_keys != other._sort_keys

    def __str__(self):
        name = f"(#{self.id:>9d}) {constants.INDUSTRIES[self.industry]}"
        if not self.is_raw:
            name += f" q{self.quality}"
        return name

    def __repr__(self):
        return str(self)

    @property
    def as_dict(self) -> Dict[str, Union[str, int, bool, float, Decimal]]:
        return dict(name=str(self), holding=self.holding.id, id=self.id, quality=self.quality, is_raw=self.is_raw,
                    raw_usage=self.raw_usage, products_made=self.products_made, wam_enabled=self.wam_enabled,
                    can_wam=self.can_wam, cannot_wam_reason=self.cannot_wam_reason, industry=self.industry,
                    already_worked=self.already_worked, preset_works=self.preset_works)

    def dissolve(self) -> Response:
        self.holding.citizen.write_log(f"{self} dissolved!")
        # noinspection PyProtectedMember
        return self.holding.citizen._post_economy_sell_company(self.id, self.holding.citizen.details.pin, sell=False)

    def upgrade(self, level: int) -> Response:
        # noinspection PyProtectedMember
        return self.holding.citizen._post_economy_upgrade_company(self.id, level, self.holding.citizen.details.pin)

    @property
    def holding(self) -> Holding:
        return self._holding()


class MyCompanies:
    work_units: int = 0
    next_ot_time: datetime.datetime
    ff_lockdown: int = 0

    holdings: Dict[int, Holding]
    _companies: weakref.WeakSet
    _citizen: weakref.ReferenceType
    companies: Generator[Company, None, None]

    def __init__(self, citizen):
        self._citizen = weakref.ref(citizen)
        self.holdings = dict()
        self._companies = weakref.WeakSet()
        self.next_ot_time = utils.now()

    def prepare_holdings(self, holdings: Dict[str, Dict[str, Any]]):
        """
        :param holdings: Parsed JSON to dict from en/economy/myCompanies
        """
        for holding in holdings.values():
            if holding.get('id') not in self.holdings:
                self.holdings.update({
                    int(holding.get('id')): Holding(holding['id'], holding['region_id'], self.citizen, holding['name'])
                })
        if not self.holdings.get(0):
            self.holdings.update({0: Holding(0, 0, self.citizen, 'Unassigned')})  # unassigned

    def prepare_companies(self, companies: Dict[str, Dict[str, Any]]):
        """
        :param companies: Parsed JSON to dict from en/economy/myCompanies
        """
        self.__clear_data()
        for company_dict in companies.values():
            holding = self.holdings.get(int(company_dict['holding_company_id']))
            quality = company_dict.get('quality')
            is_raw = company_dict.get('is_raw')
            if is_raw:
                raw_usage = Decimal('0.0')
            else:
                raw_usage = Decimal(str(company_dict.get('upgrades').get(str(quality)).get('raw_usage')))
            company = Company(
                holding, company_dict.get('id'), quality, is_raw,
                Decimal(str(company_dict.get('effective_bonus'))) / 100,
                raw_usage, Decimal(str(company_dict.get('base_production'))), company_dict.get('wam_enabled'),
                company_dict.get('can_work_as_manager'), company_dict.get('cannot_work_as_manager_reason'),
                company_dict.get('industry_id'), company_dict.get('already_worked'), company_dict.get('preset_works')
            )
            self._companies.add(company)
            holding.add_company(company)

    def get_employable_factories(self) -> Dict[int, int]:
        return {company.id: company.preset_works for company in self.companies if company.preset_works}

    def get_total_wam_count(self) -> int:
        return sum([holding.wam_count for holding in self.holdings.values()])

    @staticmethod
    def get_needed_inventory_usage(companies: Union[Company, Iterable[Company]]) -> Decimal:
        if isinstance(companies, list):
            return sum(company.products_made * 100 if company.is_raw else 1 for company in companies)
        else:
            return companies.products_made

    @property
    def companies(self) -> Generator[Company, None, None]:
        return (c for c in self._companies)

    def __str__(self):
        return f"MyCompanies: {sum(1 for _ in self.companies)} companies in {len(self.holdings)} holdings"

    def __repr__(self):
        return str(self)

    def __clear_data(self):
        for holding in self.holdings.values():
            for company in holding.companies:  # noqa
                del company
            holding.companies.clear()
        self._companies.clear()

    @property
    def as_dict(self) -> Dict[str, Union[str, int, datetime.datetime, Dict[str, Dict[str, Union[
        str, int, List[Dict[str, Union[str, int, bool, float, Decimal]]]]
    ]]]]:
        return dict(name=str(self), work_units=self.work_units, next_ot_time=self.next_ot_time,
                    ff_lockdown=self.ff_lockdown,
                    holdings={str(hi): h.as_dict for hi, h in self.holdings.items()},
                    company_count=sum(1 for _ in self.companies))

    @property
    def citizen(self):
        return self._citizen()


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
    maverick = False
    spin_wheel_of_fortune = False

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
        self.maverick = False
        self.spin_wheel_of_fortune = False

    @property
    def as_dict(self) -> Dict[str, Union[bool, int, str, List[str]]]:
        return dict(email=self.email, work=self.work, train=self.train, wam=self.wam, ot=self.ot,
                    auto_sell=self.auto_sell, auto_sell_all=self.auto_sell_all, employees=self.employees,
                    fight=self.fight, air=self.air, ground=self.ground, all_in=self.all_in,
                    next_energy=self.next_energy, travel_to_fight=self.travel_to_fight,
                    always_travel=self.always_travel, epic_hunt=self.epic_hunt, epic_hunt_ebs=self.epic_hunt_ebs,
                    rw_def_side=self.rw_def_side, interactive=self.interactive, maverick=self.maverick,
                    continuous_fighting=self.continuous_fighting, auto_buy_raw=self.auto_buy_raw,
                    force_wam=self.force_wam, sort_battles_time=self.sort_battles_time, force_travel=self.force_travel,
                    telegram=self.telegram, telegram_chat_id=self.telegram_chat_id, telegram_token=self.telegram_token,
                    spin_wheel_of_fortune=self.spin_wheel_of_fortune)


class Energy:
    limit = 500  # energyToRecover
    interval = 10  # energyPerInterval
    recoverable = 0  # energyFromFoodRemaining
    recovered = 0  # energy
    _recovery_time = None

    def __init__(self):
        self._recovery_time = utils.now()

    def __repr__(self):
        return f"{self.recovered:4}/{self.limit:4} + {self.recoverable:4}, {self.interval:3}hp/6min"

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

    @property
    def as_dict(self) -> Dict[str, Union[int, datetime.datetime, bool]]:
        return dict(limit=self.limit, interval=self.interval, recoverable=self.recoverable, recovered=self.recovered,
                    reference_time=self.reference_time, food_fights=self.food_fights,
                    is_recoverable_full=self.is_recoverable_full, is_recovered_full=self.is_recovered_full,
                    is_energy_full=self.is_energy_full, available=self.available)


class Details:
    xp: int = 0
    cc: float = 0
    pp: int = 0
    pin: str = None
    gold: float = 0
    level: int = 0
    next_pp: List[int] = None
    citizen_id: int = 0
    citizenship: constants.Country
    current_region: int = 0
    current_country: constants.Country
    residence_region: int = 0
    residence_country: constants.Country
    daily_task_done: bool = False
    daily_task_reward: bool = False
    mayhem_skills: Dict[int, int]

    def __init__(self):
        self.next_pp = []
        self.mayhem_skills = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0, 9: 0, 10: 0, 11: 0, 12: 0, 13: 0, 14: 0}

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

    @property
    def as_dict(self) -> Dict[str, Union[int, float, str, constants.Country, bool]]:
        return dict(xp=self.xp, cc=self.cc, pp=self.pp, pin=self.pin, gold=self.gold, next_pp=self.next_pp,
                    level=self.level, citizen_id=self.citizen_id, citizenship=self.citizenship,
                    current_region=self.current_region, current_country=self.current_country,
                    residence_region=self.residence_region, residence_country=self.residence_country,
                    daily_task_done=self.daily_task_done, daily_task_reward=self.daily_task_reward,
                    mayhem_skills=self.mayhem_skills, xp_till_level_up=self.xp_till_level_up)

    @property
    def is_elite(self):
        return self.level > 100


class Politics:
    is_party_member: bool = False

    party_id: int = 0
    party_slug: str = ""
    is_party_president: bool = False
    is_congressman: bool = False
    is_country_president: bool = False

    @property
    def as_dict(self) -> Dict[str, Union[bool, int, str]]:
        return dict(is_party_member=self.is_party_member, party_id=self.party_id, party_slug=self.party_slug,
                    is_party_president=self.is_party_president, is_congressman=self.is_congressman,
                    is_country_president=self.is_country_president)


class House:
    quality = None
    unactivated_count = 0
    active_until = utils.good_timedelta(utils.now(), -datetime.timedelta(days=1))

    def __init__(self, quality: int):
        if 0 < quality < 6:
            self.quality = quality

    @property
    def next_ot_point(self) -> datetime.datetime:
        return self.active_until


class Reporter:
    __to_update: List[Dict[Any, Any]] = None
    key: str = ""
    allowed: bool = False

    @property
    def name(self) -> str:
        return self.citizen.name

    @property
    def email(self) -> str:
        return self.citizen.config.email

    @property
    def citizen_id(self) -> int:
        return self.citizen.details.citizen_id

    @property
    def as_dict(self) -> Dict[str, Union[bool, int, str, List[Dict[Any, Any]]]]:
        return dict(name=self.name, email=self.email, citizen_id=self.citizen_id, key=self.key, allowed=self.allowed,
                    queue=self.__to_update)

    def __init__(self, citizen):
        self._citizen = weakref.ref(citizen)
        self._req = Session()
        self.url = "https://api.erep.lv"
        self._req.headers.update({"user-agent": 'eRepublik Script Reporter v3',
                                  'erep-version': utils.__version__,
                                  'erep-user-id': str(self.citizen_id),
                                  'erep-user-name': self.citizen.name})
        self.__to_update = []
        self.__registered: bool = False

    def do_init(self):
        self.key: str = ""
        self.__update_key()
        self.register_account()
        self.allowed = True

    @property
    def citizen(self):
        return self._citizen()

    def __update_key(self):
        self.key = hashlib.md5(bytes(f"{self.name}:{self.email}", encoding="UTF-8")).hexdigest()

    def __bot_update(self, data: dict) -> Response:
        if self.__to_update:
            for unreported_data in self.__to_update:
                unreported_data.update(player_id=self.citizen_id, key=self.key)
                unreported_data = utils.json.loads(utils.json.dumps(unreported_data, cls=ErepublikJSONEncoder))
                self._req.post(f"{self.url}/bot/update", json=unreported_data)
            self.__to_update.clear()
        data = utils.json.loads(utils.json.dumps(data, cls=ErepublikJSONEncoder))
        r = self._req.post(f"{self.url}/bot/update", json=data)
        return r

    def register_account(self):
        if not self.__registered:
            try:
                r = self.__bot_update(dict(key=self.key, check=True, player_id=self.citizen_id))
                if not r.json().get('status'):
                    self._req.post(f"{self.url}/bot/register", json=dict(name=self.name, email=self.email,
                                                                         player_id=self.citizen_id))
            finally:
                self.__registered = True
                self.allowed = True
                self.report_action('STARTED', value=utils.now().strftime("%F %T"))

    def send_state_update(self, xp: int, cc: float, gold: float, inv_total: int, inv: int,
                          hp_limit: int, hp_interval: int, hp_available: int, food: int, pp: int):

        data = dict(key=self.key, player_id=self.citizen_id, state=dict(
            xp=xp, cc=cc, gold=gold, inv_total=inv_total, inv_free=inv_total - inv, inv=inv, food=food,
            pp=pp, hp_limit=hp_limit, hp_interval=hp_interval, hp_available=hp_available,
        ))

        if self.allowed:
            self.__bot_update(data)

    def report_action(self, action: str, json_val: Dict[Any, Any] = None, value: str = None):
        json_data = dict(
            player_id=getattr(self, 'citizen_id', None), log={'action': action}, key=getattr(self, 'key', None)
        )
        if json_val:
            json_data['log'].update(dict(json=json_val))
        if value:
            json_data['log'].update(dict(value=value))
        if not any([self.key, self.email, self.name, self.citizen_id]):
            return
        if self.allowed:
            self.__bot_update(json_data)
        else:
            self.__to_update.append(json_data)

    def report_fighting(self, battle: 'Battle', invader: bool, division: 'BattleDivision', damage: float, hits: int):
        side = battle.invader if invader else battle.defender
        self.report_action('FIGHT', dict(battle_id=battle.id, side=side, dmg=damage,
                                         air=battle.has_air, hits=hits,
                                         round=battle.zone_id, extra=dict(battle=battle, side=side, division=division)))

    def report_money_donation(self, citizen_id: int, amount: float, is_currency: bool = True):
        cur = 'cc' if is_currency else 'gold'
        self.report_action('DONATE_MONEY', dict(citizen_id=citizen_id, amount=amount, currency=cur),
                           f"Successfully donated {amount}{cur} to citizen with id {citizen_id}!")

    def report_item_donation(self, citizen_id: int, amount: float, quality: int, industry: str):
        self.report_action('DONATE_ITEMS',
                           dict(citizen_id=citizen_id, amount=amount, quality=quality, industry=industry),
                           f"Successfully donated {amount} x {industry} q{quality} to citizen with id {citizen_id}!")

    def report_promo(self, kind: str, time_until: datetime.datetime):
        self._req.post(f"{self.url}/promos/add/", data=dict(kind=kind, time_untill=time_until))

    def fetch_battle_priorities(self, country: constants.Country) -> List['Battle']:
        try:
            battle_response = self._req.get(f'{self.url}/api/v1/battles/{country.id}')
            return [self.citizen.all_battles[bid] for bid in battle_response.json().get('battle_ids', []) if
                    bid in self.citizen.all_battles]
        except:  # noqa
            return []

    def fetch_tasks(self) -> List[Dict[str, Any]]:
        try:
            task_response = self._req.post(
                f'{self.url}/api/v1/command', data=dict(citizen=self.citizen_id, key=self.key)).json()
            if task_response.get('status'):
                return task_response.get('data')
            else:
                return []
        except:  # noqa
            return []


class ErepublikJSONEncoder(utils.json.JSONEncoder):
    def default(self, o):
        from erepublik.citizen import Citizen
        if isinstance(o, Decimal):
            return float(f"{o:.02f}")
        elif isinstance(o, datetime.datetime):
            return dict(__type__='datetime', date=o.strftime("%Y-%m-%d"), time=o.strftime("%H:%M:%S"),
                        tzinfo=str(o.tzinfo) if o.tzinfo else None)
        elif isinstance(o, datetime.date):
            return dict(__type__='date', date=o.strftime("%Y-%m-%d"))
        elif isinstance(o, datetime.timedelta):
            return dict(__type__='timedelta', days=o.days, seconds=o.seconds,
                        microseconds=o.microseconds, total_seconds=o.total_seconds())
        elif isinstance(o, Response):
            return dict(headers=dict(o.__dict__['headers']), url=o.url, text=o.text, status_code=o.status_code)
        elif hasattr(o, 'as_dict'):
            return o.as_dict
        elif isinstance(o, set):
            return list(o)
        elif isinstance(o, Citizen):
            return o.to_json()
        try:
            return super().default(o)
        except Exception as e:  # noqa
            return 'Object is not JSON serializable'


class BattleSide:
    points: int
    deployed: List[constants.Country]
    allies: List[constants.Country]
    battle: 'Battle'
    _battle: weakref.ReferenceType
    country: constants.Country
    is_defender: bool

    def __init__(self, battle: 'Battle', country: constants.Country, points: int, allies: List[constants.Country],
                 deployed: List[constants.Country], defender: bool):
        self._battle = weakref.ref(battle)
        self.country = country
        self.points = points
        self.allies = allies
        self.deployed = deployed
        self.is_defender = defender

    @property
    def id(self) -> int:
        return self.country.id

    def __repr__(self):
        side_text = 'Defender' if self.is_defender else 'Invader '
        return f"<BattleSide: {side_text} {self.country.name}|{self.points:>2d}p>"

    def __str__(self):
        side_text = 'Defender' if self.is_defender else 'Invader '
        return f"{side_text} {self.country.name} - {self.points:>2d} points"

    def __format__(self, format_spec):
        return self.country.iso

    @property
    def as_dict(self) -> Dict[str, Union[int, constants.Country, bool, List[constants.Country]]]:
        return dict(points=self.points, country=self.country, is_defender=self.is_defender, allies=self.allies,
                    deployed=self.deployed)

    @property
    def battle(self):
        return self._battle()


class BattleDivision:
    id: int
    end: datetime.datetime
    epic: bool
    dom_pts: Dict[str, int]
    wall: Dict[str, Union[int, float]]
    def_medal: Dict[str, int]
    inv_medal: Dict[str, int]
    terrain: int
    div: int
    battle: 'Battle'
    _battle: weakref.ReferenceType

    @property
    def as_dict(self):
        return dict(id=self.id, division=self.div, terrain=(self.terrain, self.terrain_display), wall=self.wall,
                    epic=self.epic, end=self.div_end)

    @property
    def is_air(self):
        return self.div == 11

    @property
    def div_end(self) -> bool:
        return utils.now() >= self.end

    def __init__(self, battle: 'Battle', div_id: int, end: datetime.datetime, epic: bool, div: int, wall_for: int,
                 wall_dom: float, terrain_id: int = 0):
        """Battle division helper class

        :type div_id: int
        :type end: datetime.datetime
        :type epic: bool
        :type div: int
        :type terrain_id: int
        :type wall_for: int
        :type wall_dom: float
        """
        self._battle = weakref.ref(battle)
        self.id = div_id
        self.end = end
        self.epic = epic
        self.wall = {'for': wall_for, 'dom': wall_dom}
        self.terrain = terrain_id
        self.div = div

    @property
    def terrain_display(self):
        return constants.TERRAINS[self.terrain]

    def __str__(self):
        base_name = f"D{self.div} #{self.id}"
        if self.terrain:
            base_name += f" ({self.terrain_display})"
        if self.div_end:
            base_name += ' Ended'
        return base_name

    def __repr__(self):
        return f"<BattleDivision #{self.id} (battle #{self.battle.id})>"

    @property
    def battle(self):
        return self._battle()


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
    region_id: int
    region_name: str

    @property
    def as_dict(self):
        return dict(id=self.id, war_id=self.war_id, divisions=self.div, zone=self.zone_id, rw=self.is_rw,
                    dict_lib=self.is_dict_lib, start=self.start, sides={'inv': self.invader, 'def': self.defender},
                    region=[self.region_id, self.region_name], link=self.link)

    @property
    def has_air(self) -> bool:
        for div in self.div.values():
            if div.div == 11:
                return True
        return not bool(self.zone_id % 4)

    @property
    def has_started(self) -> bool:
        return self.start <= utils.now()

    @property
    def has_ground(self) -> bool:
        for div in self.div.values():
            if div.div != 11:
                return True
        return bool(self.zone_id % 4)

    @property
    def link(self):
        return f"https://www.erepublik.com/en/military/battlefield/{self.id}"

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
        self.region_id = battle.get('region', {}).get('id')
        self.region_name = battle.get('region', {}).get('name')
        self.start = datetime.datetime.fromtimestamp(int(battle.get('start', 0)), tz=constants.erep_tz)

        self.invader = BattleSide(
            self, constants.COUNTRIES[battle.get('inv', {}).get('id')], battle.get('inv', {}).get('points'),
            [constants.COUNTRIES[row.get('id')] for row in battle.get('inv', {}).get('ally_list')],
            [constants.COUNTRIES[row.get('id')] for row in battle.get('inv', {}).get('ally_list') if row['deployed']],
            False
        )

        self.defender = BattleSide(
            self, constants.COUNTRIES[battle.get('def', {}).get('id')], battle.get('def', {}).get('points'),
            [constants.COUNTRIES[row.get('id')] for row in battle.get('def', {}).get('ally_list')],
            [constants.COUNTRIES[row.get('id')] for row in battle.get('def', {}).get('ally_list') if row['deployed']],
            True
        )

        self.div = {}
        for div, data in battle.get('div', {}).items():
            div = int(div)
            if data.get('end'):
                end = datetime.datetime.fromtimestamp(data.get('end'), tz=constants.erep_tz)
            else:
                end = constants.max_datetime

            battle_div = BattleDivision(self, div_id=data.get('id'), div=data.get('div'), end=end,
                                        epic=data.get('epic_type') in [1, 5],
                                        wall_for=data.get('wall').get('for'),
                                        wall_dom=data.get('wall').get('dom'),
                                        terrain_id=data.get('terrain', 0))

            self.div.update({div: battle_div})

    def __str__(self):
        time_now = utils.now()
        is_started = self.start < utils.now()
        if is_started:
            time_part = f" {time_now - self.start}"
        else:
            time_part = f"-{self.start - time_now}"

        return (f"Battle {self.id} for {self.region_name[:16]:16} | "
                f"{self.invader} : {self.defender} | Round time {time_part} | {'R'+str(self.zone_id):>3}")

    def __repr__(self):
        return f"<Battle #{self.id} {self.invader}:{self.defender} R{self.zone_id}>"


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


class TelegramReporter:
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
    def as_dict(self):
        return {'chat_id': self.chat_id, 'api_url': self.api_url, 'player': self.player_name,
                'last_time': self._last_time, 'next_time': self._next_time, 'queue': self.__queue,
                'initialized': self.__initialized, 'has_threads': not self._threads}

    def do_init(self, chat_id: int, token: str = None, player_name: str = None):
        if token is None:
            token = "864251270:AAFzZZdjspI-kIgJVk4gF3TViGFoHnf8H4o"
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.player_name = player_name or ""
        self.__initialized = True
        self._last_time = utils.good_timedelta(utils.now(), datetime.timedelta(minutes=-5))
        self._last_full_energy_report = utils.good_timedelta(utils.now(), datetime.timedelta(minutes=-30))
        if self.__queue:
            self.send_message('Telegram initialized')

    def send_message(self, message: str) -> bool:
        self.__queue.append(message)
        if not self.__initialized:
            if self._last_time < utils.now():
                self.__queue.clear()
            return True
        self._threads = [t for t in self._threads if t.is_alive()]
        self._next_time = utils.good_timedelta(utils.now(), datetime.timedelta(seconds=20))
        if not self._threads:
            name = f"telegram_{f'{self.player_name}_' if self.player_name else ''}send"
            send_thread = threading.Thread(target=self.__send_messages, name=name)
            send_thread.start()
            self._threads.append(send_thread)

        return True

    def report_full_energy(self, available: int, limit: int, interval: int):
        if (utils.now() - self._last_full_energy_report).total_seconds() >= 30 * 60:
            self._last_full_energy_report = utils.now()
            message = f"Full energy ({available}hp/{limit}hp +{interval}hp/6min)"
            self.send_message(message)

    def report_medal(self, msg, multiple: bool = True):
        new_line = '\n' if multiple else ''
        self.send_message(f"New award: {new_line}*{msg}*")

    def report_fight(self, battle: 'Battle', invader: bool, division: 'BattleDivision', damage: float, hits: int):
        side_txt = (battle.invader if invader else battle.defender).country.iso
        self.send_message(f"*Fight report*:\n{int(damage):,d} dmg ({hits} hits) in"
                          f" [battle {battle.id} for {battle.region_name[:16]}]({battle.link}) in d{division.div} on "
                          f"{side_txt} side")

    def report_item_donation(self, citizen_id: int, amount: float, product: str):
        self.send_message(f"*Donation*: {amount} x {product} to citizen "
                          f"[{citizen_id}](https://www.erepublik.com/en/citizen/profile/{citizen_id})")

    def report_money_donation(self, citizen_id: int, amount: float, is_currency: bool = True):
        self.send_message(f"*Donation*: {amount}{'cc' if is_currency else 'gold'} to citizen "
                          f"[{citizen_id}](https://www.erepublik.com/en/citizen/profile/{citizen_id})")

    def __send_messages(self):
        while self._next_time > utils.now():
            if self.__thread_stopper.is_set():
                break
            self.__thread_stopper.wait(utils.get_sleep_seconds(self._next_time))

        message = "\n\n".join(self.__queue)
        if self.player_name:
            message = f"Player *{self.player_name}*\n\n" + message
        response = post(self.api_url, json=dict(chat_id=self.chat_id, text=message, parse_mode='Markdown'))
        self._last_time = utils.now()
        if response.json().get('ok'):
            self.__queue.clear()
            return True
        return False


class OfferItem(NamedTuple):
    price: float = 999_999_999.
    country: constants.Country = constants.Country(0, "", "", "")
    amount: int = 0
    offer_id: int = 0
    citizen_id: int = 0


class Inventory:
    final: types.InvFinal
    active: types.InvFinal
    boosters: types.InvBooster
    raw: types.InvRaw
    market: types.InvRaw
    used: int
    total: int

    def __init__(self):
        self.active = {}
        self.final = {}
        self.boosters = {}
        self.raw = {}
        self.offers = {}
        self.used = 0
        self.total = 0

    @property
    def as_dict(self) -> Dict[str, Union[types.InvFinal, types.InvRaw, int]]:
        return dict(active=self.active, final=self.final, boosters=self.boosters, raw=self.raw, offers=self.offers,
                    total=self.total, used=self.used)
