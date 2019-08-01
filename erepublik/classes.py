import datetime
import decimal
import hashlib
import random
import time
from collections import deque
from json import JSONDecodeError, loads, JSONEncoder
from typing import Any, Dict, List, Union, Mapping, Iterable

from requests import Response, Session

from erepublik import utils


class ErepublikException(Exception):
    def __init__(self, message):
        super().__init__(message)


class ErepublikNetworkException(Exception):
    def __init__(self, message, request):
        super().__init__(message)
        self.request = request


class MyCompanies:
    work_units: int = 0
    next_ot_time: datetime.datetime
    holdings: Dict[int, Dict] = dict()
    companies: Dict[int, Dict] = dict()
    ff_lockdown: int = 0

    def __init__(self):
        self.next_ot_time = utils.now()

    def prepare_holdings(self, holdings: dict):
        """
        :param holdings: Parsed JSON to dict from en/economy/myCompanies
        """
        self.holdings = {}
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
        self.companies = {}
        template = dict(id=None, quality=0, is_raw=False, resource_bonus=0, effective_bonus=0, raw_usage=0,
                        production=0, base_production=0, wam_enabled=False, can_work_as_manager=False,
                        preset_own_work=0, already_worked=False, can_assign_employees=False, preset_works=0,
                        todays_works=0, holding_company_id=None, is_assigned_to_holding=False,
                        cannot_work_as_manager_reason=False)

        for c_id, company in companies.items():
            tmp = {}
            for key in template.keys():
                if key in ['id', 'holding_company_id']:
                    company[key] = int(company[key])
                tmp.update({key: company[key]})
            self.companies.update({int(c_id): tmp})

    def update_holding_companies(self):
        for company_id, company_data in self.companies.items():
            if company_id not in self.holdings[company_data['holding_company_id']]['companies']:
                self.holdings[company_data['holding_company_id']]['companies'].append(company_id)
        else:
            for holding_id in self.holdings:
                self.holdings[holding_id]['companies'].sort()

    def get_employable_factories(self) -> Dict[int, int]:
        ret = {}
        for company_id, company in self.companies.items():
            if company.get('preset_works'):
                preset_works: int = int(company.get('preset_works', 0))
                ret.update({company_id: preset_works})
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
            for company_id in self.holdings.get(holding_id, {}).get('companies', []):
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


class SlowRequests(Session):
    last_time: datetime.datetime
    timeout = datetime.timedelta(milliseconds=500)
    uas = [
        # Chrome
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/73.0.3683.103 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/72.0.3626.13 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/71.0.3578.98 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/73.0.3683.103 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/72.0.3626.11 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/71.0.3578.98 Safari/537.36',
        # FireFox
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:66.0) Gecko/20100101 Firefox/66.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:65.0) Gecko/20100101 Firefox/65.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:64.0) Gecko/20100101 Firefox/64.0',
        'Mozilla/5.0 (X11; Linux x86_64; rv:66.0) Gecko/20100101 Firefox/66.0',
        'Mozilla/5.0 (X11; Linux x86_64; rv:65.0) Gecko/20100101 Firefox/65.0',
        'Mozilla/5.0 (X11; Linux x86_64; rv:64.0) Gecko/20100101 Firefox/64.0',
    ]
    debug = False

    def __init__(self):
        super().__init__()
        self.request_log_name = utils.get_file(utils.now().strftime("debug/requests_%Y-%m-%d.log"))
        self.last_time = utils.now()
        self.headers.update({
            'User-Agent': random.choice(self.uas)
        })

    @property
    def __dict__(self):
        return dict(last_time=self.last_time, timeout=self.timeout, user_agent=self.headers['User-Agent'],
                    request_log_name=self.request_log_name)

    def request(self, method, url, *args, **kwargs):
        self._slow_down_requests()
        self._log_request(url, method, **kwargs)
        resp = super().request(method, url, *args, **kwargs)
        self._log_response(url, resp)
        return resp

    def _slow_down_requests(self):
        ltt = utils.good_timedelta(self.last_time, self.timeout)
        if ltt > utils.now():
            seconds = (ltt - utils.now()).total_seconds()
            time.sleep(seconds if seconds > 0 else 0)
        self.last_time = utils.now()

    def _log_request(self, url, method, data=None, json=None, params=None, **kwargs):
        if self.debug:
            args = {}
            args.update({'kwargs': kwargs})
            if data:
                args.update({"data": data})

            if json:
                args.update({"json": json})

            if params:
                args.update({"params": params})

            body = "[{dt}]\tURL: '{url}'\tMETHOD: {met}\tARGS: {args}\n".format(dt=utils.now().strftime("%F %T"),
                                                                                url=url, met=method, args=args)
            utils.get_file(self.request_log_name)
            with open(self.request_log_name, 'ab') as file:
                file.write(body.encode("UTF-8"))

    def _log_response(self, url, resp, redirect: bool = False):
        from erepublik import Citizen
        if self.debug:
            if resp.history and not redirect:
                for hist_resp in resp.history:
                    self._log_request(hist_resp.request.url, "REDIRECT")
                    self._log_response(hist_resp.request.url, hist_resp, redirect=True)

            # TODO: Must thoroughly check response writing on windows systems
            file_data = {
                "path": 'debug/requests',
                "time": self.last_time.strftime('%Y-%m-%d_%H-%M-%S'),
                "name": utils.slugify(url[len(Citizen.url):]),
                "extra": "_REDIRECT" if redirect else ""
            }

            try:
                loads(resp.text)
                file_data.update({"ext": "json"})
            except JSONDecodeError:
                file_data.update({"ext": "html"})

            filename = 'debug/requests/{time}_{name}{extra}.{ext}'.format(**file_data)
            with open(utils.get_file(filename), 'wb') as f:
                f.write(resp.text.encode('utf-8'))


class Config:
    email = ""
    password = ""
    work = True
    train = True
    wam = False
    auto_sell: List[str] = list()
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

    @property
    def wt(self):
        return self.work and self.train

    def __dict__(self) -> Dict[str, Union[bool, str, List[str]]]:
        return dict(
            email=self.email,
            password=self.password,
            work=self.work,
            train=self.train,
            wam=self.wam,
            auto_sell=self.auto_sell,
            auto_sell_all=self.auto_sell_all,
            employees=self.employees,
            fight=self.fight,
            air=self.air,
            ground=self.ground,
            all_in=self.all_in,
            next_energy=self.next_energy,
            boosters=self.boosters,
            travel_to_fight=self.travel_to_fight,
            epic_hunt=self.epic_hunt,
            epic_hunt_ebs=self.epic_hunt_ebs,
            rw_def_side=self.rw_def_side,
            interactive=self.interactive,
            continuous_fighting=self.continuous_fighting,
            auto_buy_raw=self.auto_buy_raw,
            force_wam=self.force_wam,
            sort_battles_time=self.sort_battles_time,
            force_travel=self.force_travel,
        )


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
        return (self.recoverable + self.recovered) // 10

    @property
    def reference_time(self):
        if self.is_recovered_full or self._recovery_time < utils.now():
            ret = utils.now()
        else:
            ret = self._recovery_time
        return ret

    @property
    def is_recoverable_full(self):
        return self.recoverable >= self.limit - self.interval

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
    def __dict__(self):
        return dict(
            limit=self.limit,
            interval=self.interval,
            recoverable=self.recoverable,
            recovered=self.recovered,
            reference_time=self.reference_time
        )


class Details(object):
    xp = 0
    cc = 0
    pp = 0
    pin = None
    gold = 0
    next_pp: List[int] = []
    citizen_id = 0
    citizenship = 0
    current_region = 0
    current_country = 0
    residence_region = 0
    residence_country = 0
    daily_task_done = False
    daily_task_reward = False
    mayhem_skills = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0, 9: 0, 10: 0, 11: 0, 12: 0, 13: 0, 14: 0, }

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


class House(object):
    quality = None
    unactivated_count = 0
    active_untill = utils.good_timedelta(utils.now(), -datetime.timedelta(days=1))

    def __init__(self, quality: int):
        if 0 < quality < 6:
            self.quality = quality

    @property
    def next_ot_point(self) -> datetime.datetime:
        return self.active_untill


class CitizenAPI:
    url: str = "https://www.erepublik.com/en"
    _req: SlowRequests = None
    token: str = ""

    def __init__(self):
        """
Class for unifying eRepublik known endpoints and their required/optional parameters
        """
        self._req = SlowRequests()

    def post(self, url: str, *args, **kwargs) -> Response:
        return self._req.post(url, *args, **kwargs)

    def get(self, url: str, **kwargs) -> Response:
        return self._req.get(url, **kwargs)

    def _get_article_json(self, article_id: int) -> Response:
        return self.get("{}/main/articleJson/{}".format(self.url, article_id))

    def _get_battlefield_choose_side(self, battle: int, side: int) -> Response:
        return self.get("{}/military/battlefield-choose-side/{}/{}".format(self.url, battle, side))

    def _get_candidate_party(self, party_slug: str) -> Response:
        return self.post("{}/candidate/{}".format(self.url, party_slug))

    def _get_citizen_hovercard(self, citizen: int) -> Response:
        return self.get("{}/main/citizen-hovercard/{}".format(self.url, citizen))

    def _get_citizen_profile(self, player_id: int) -> Response:
        return self.get("{}/main/citizen-profile-json/{}".format(self.url, player_id))

    def _get_citizen_daily_assistant(self) -> Response:
        return self.get("{}/main/citizenDailyAssistant".format(self.url))

    def _get_city_data_residents(self, city: int, page: int = 1, params: Mapping[str, Any] = None) -> Response:
        if params is None:
            params = {}
        return self.get("{}/main/city-data/{}/residents".format(self.url, city), params={"currentPage": page, **params})

    def _get_country_military(self, country: str) -> Response:
        return self.get("{}/country/military/{}".format(self.url, country))

    def _get_economy_inventory_items(self) -> Response:
        return self.get("{}/economy/inventory-items/".format(self.url))

    def _get_economy_job_market_json(self, country: int) -> Response:
        return self.get("{}/economy/job-market-json/{}/1/desc".format(self.url, country))

    def _get_economy_my_companies(self) -> Response:
        return self.get("{}/economy/myCompanies".format(self.url))

    def _get_economy_my_market_offers(self) -> Response:
        return self.get("{}/economy/myMarketOffers".format(self.url))

    def _get_job_data(self) -> Response:
        return self.get("{}/main/job-data".format(self.url))

    def _get_leaderboards_damage_aircraft_rankings(self, country: int, weeks: int = 0, mu: int = 0) -> Response:
        data = (country, weeks, mu)
        return self.get("{}/main/leaderboards-damage-aircraft-rankings/{}/{}/{}/0".format(self.url, *data))

    def _get_leaderboards_damage_rankings(self, country: int, weeks: int = 0, mu: int = 0, div: int = 0) -> Response:
        data = (country, weeks, mu, div)
        return self.get("{}/main/leaderboards-damage-rankings/{}/{}/{}/{}".format(self.url, *data))

    def _get_leaderboards_kills_aircraft_rankings(self, country: int, weeks: int = 0, mu: int = 0) -> Response:
        data = (country, weeks, mu)
        return self.get("{}/main/leaderboards-kills-aircraft-rankings/{}/{}/{}/0".format(self.url, *data))

    def _get_leaderboards_kills_rankings(self, country: int, weeks: int = 0, mu: int = 0, div: int = 0) -> Response:
        data = (country, weeks, mu, div)
        return self.get("{}/main/leaderboards-kills-rankings/{}/{}/{}/{}".format(self.url, *data))

    def _get_main(self) -> Response:
        return self.get(self.url)

    def _get_messages(self, page: int = 1) -> Response:
        return self.get("{}/main/messages-paginated/{}".format(self.url, page))

    def _get_military_campaigns(self) -> Response:
        return self.get("{}/military/campaigns-new/".format(self.url))

    def _get_military_unit_data(self, unit_id: int, **kwargs) -> Response:
        params = {"groupId": unit_id, "panel": "members", **kwargs}
        return self.get("{}/military/military-unit-data/".format(self.url), params=params)

    def _get_money_donation_accept(self, donation_id: int) -> Response:
        return self.get("{}/main/money-donation/accept/{}".format(self.url, donation_id), params={"_token": self.token})

    def _get_money_donation_reject(self, donation_id: int) -> Response:
        return self.get("{}/main/money-donation/reject/{}".format(self.url, donation_id), params={"_token": self.token})

    def _get_notifications_ajax_community(self, page: int = 1) -> Response:
        return self.get("{}/main/notificationsAjax/community/{}".format(self.url, page))

    def _get_notifications_ajax_system(self, page: int = 1) -> Response:
        return self.get("{}/main/notificationsAjax/system/{}".format(self.url, page))

    def _get_notifications_ajax_report(self, page: int = 1) -> Response:
        return self.get("{}/main/notificationsAjax/report/{}".format(self.url, page))

    def _get_party_members(self, party: int) -> Response:
        return self.get("{}/main/party-members/{}".format(self.url, party))

    def _get_rankings_parties(self, country: int) -> Response:
        return self.get("{}/main/rankings-parties/1/{}".format(self.url, country))

    def _get_training_grounds_json(self) -> Response:
        return self.get("{}/main/training-grounds-json".format(self.url))

    def _get_weekly_challenge_data(self) -> Response:
        return self.get("{}/main/weekly-challenge-data".format(self.url))

    def _get_wars_show(self, war_id: int) -> Response:
        return self.get("{}/wars/show/{}".format(self.url, war_id))

    def _post_activate_battle_effect(self, battle: int, kind: str, citizen_id: int) -> Response:
        data = dict(battleId=battle, citizenId=citizen_id, type=kind, _token=self.token)
        return self.post("{}/main/fight-activateBattleEffect".format(self.url), data=data)

    def _post_article_comments(self, article: int, page: int = 1) -> Response:
        data = dict(_token=self.token, articleId=article, page=page)
        if page:
            data.update({'page': page})
        return self.post("{}/main/articleComments".format(self.url), data=data)

    def _post_article_comments_create(self, message: str, article: int, parent: int = 0) -> Response:
        data = dict(_token=self.token, message=message, articleId=article)
        if parent:
            data.update({"parentId": parent})
        return self.post("{}/main/articleComments/create".format(self.url), data=data)

    def _post_battle_console(self, battle: int, zone: int, round_id: int, division: int, page: int,
                             damage: bool) -> Response:
        data = dict(battleId=battle, zoneId=zone, action="battleStatistics", round=round_id, division=division,
                    leftPage=page, rightPage=page, _token=self.token)
        if damage:
            data.update({"type": "damage"})
        else:
            data.update({"type": "kills"})

        return self.post("{}/military/battle-console".format(self.url), data=data)

    def _post_buy_gold_items(self, currency: str, item: str, amount: int) -> Response:
        data = dict(itemId=item, currency=currency, amount=amount, _token=self.token)
        return self.post("{}/main/buyGoldItems".format(self.url), data=data)

    def _post_candidate_for_congress(self, presentation: str = "") -> Response:
        data = dict(_token=self.token, presentation=presentation)
        return self.post("{}/candidate-for-congress".format(self.url), data=data)

    def _post_citizen_add_remove_friend(self, citizen: int, add: bool) -> Response:
        data = dict(_token=self.token, citizenId=citizen, url="//www.erepublik.com/en/main/citizen-addRemoveFriend")
        if add:
            data.update({"action": "addFriend"})
        else:
            data.update({"action": "removeFriend"})
        return self.post("{}/main/citizen-addRemoveFriend".format(self.url), data=data)

    def _post_collect_anniversary_reward(self) -> Response:
        return self.post("{}/main/collect-anniversary-reward".format(self.url), data={"_token": self.token})

    def _post_country_donate(self, country: int, action: str, value: Union[int, float],
                             quality: int = None) -> Response:
        json = dict(countryId=country, action=action, _token=self.token, value=value, quality=quality)
        return self.post("{}/main/country-donate".format(self.url), data=json,
                         headers={"Referer": "{}/country/economy/Latvia".format(self.url)})

    def _post_daily_task_reward(self) -> Response:
        return self.post("{}/main/daily-tasks-reward".format(self.url), data=dict(_token=self.token))

    def _post_delete_message(self, msg_id: list) -> Response:
        data = {"_token": self.token, "delete_message[]": msg_id}
        return self.post("{}/main/messages-delete".format(self.url), data)

    def _post_eat(self, color: str) -> Response:
        data = dict(_token=self.token, buttonColor=color)
        return self.post("{}/main/eat".format(self.url), params=data)

    def _post_economy_activate_house(self, quality: int) -> Response:
        data = {"action": "activate", "quality": quality, "type": "house", "_token": self.token}
        return self.post("{}/economy/activateHouse".format(self.url), data=data)

    def _post_economy_assign_to_holding(self, factory: int, holding: int) -> Response:
        data = dict(_token=self.token, factoryId=factory, action="assign", holdingCompanyId=holding)
        return self.post("{}/economy/assign-to-holding".format(self.url), data=data)

    def _post_economy_create_company(self, industry: int, building_type: int = 1) -> Response:
        data = {"_token": self.token, "company[industry_id]": industry, "company[building_type]": building_type}
        return self.post("{}/economy/create-company".format(self.url), data=data,
                         headers={"Referer": "{}/economy/create-company".format(self.url)})

    def _post_economy_donate_items_action(self, citizen: int, amount: int, industry: int,
                                          quality: int) -> Response:
        data = dict(citizen_id=citizen, amount=amount, industry_id=industry, quality=quality, _token=self.token)
        return self.post("{}/economy/donate-items-action".format(self.url), data=data,
                         headers={"Referer": "{}/economy/donate-items/{}".format(self.url, citizen)})

    def _post_economy_donate_money_action(self, citizen: int, amount: float = 0.0,
                                          currency: int = 62) -> Response:
        data = dict(citizen_id=citizen, _token=self.token, currency_id=currency, amount=amount)
        return self.post("{}/economy/donate-money-action".format(self.url), data=data,
                         headers={"Referer": "{}/economy/donate-money/{}".format(self.url, citizen)})

    def _post_economy_exchange_purchase(self, amount: float, currency: int, offer: int) -> Response:
        data = dict(_token=self.token, amount=amount, currencyId=currency, offerId=offer)
        return self.post("{}/economy/exchange/purchase/".format(self.url), data=data)

    def _post_economy_exchange_retrieve(self, personal: bool, page: int, currency: int) -> Response:
        data = dict(_token=self.token, personalOffers=int(personal), page=page, currencyId=currency)
        return self.post("{}/economy/exchange/retrieve/".format(self.url), data=data)

    def _post_economy_job_market_apply(self, citizen: int, salary: int) -> Response:
        data = dict(_token=self.token, citizenId=citizen, salary=salary)
        return self.post("{}/economy/job-market-apply".format(self.url), data=data)

    def _post_economy_marketplace(self, country: int, industry: int, quality: int,
                                  order_asc: bool = True) -> Response:
        data = dict(countryId=country, industryId=industry, quality=quality, ajaxMarket=1,
                    orderBy="price_asc" if order_asc else "price_desc", _token=self.token)
        return self.post("{}/economy/marketplaceAjax".format(self.url), data=data)

    def _post_economy_marketplace_actions(self, amount: int, buy: bool = False, **kwargs) -> Response:
        if buy:
            data = dict(_token=self.token, offerId=kwargs['offer'], amount=amount, orderBy="price_asc", currentPage=1,
                        buyAction=1)
        else:
            data = dict(_token=self.token, countryId=kwargs["country"], price=kwargs["price"],
                        industryId=kwargs["industry"], quality=kwargs["quality"], amount=amount, sellAction='postOffer')
        return self.post("{}/economy/marketplaceActions".format(self.url), data=data)

    def _post_economy_resign(self) -> Response:
        return self.post("{}/economy/resign".format(self.url),
                         headers={"Content-Type": "application/x-www-form-urlencoded"},
                         data={"_token": self.token, "action_type": "resign"})

    def _post_economy_sell_company(self, factory: int, pin: int = None, sell: bool = True) -> Response:
        url = "{}/economy/sell-company/{}".format(self.url, factory)
        data = dict(_token=self.token, pin="" if pin is None else pin)
        if sell:
            data.update({"sell": "sell"})
        else:
            data.update({"dissolve": factory})
        return self.post(url, data=data, headers={"Referer": url})

    def _post_economy_train(self, tg_ids: List[int]) -> Response:
        data: Dict[str, Union[int, str]] = {}
        if not tg_ids:
            return self._get_training_grounds_json()
        else:
            for idx, tg_id in enumerate(tg_ids):
                data["grounds[%i][id]" % idx] = tg_id
                data["grounds[%i][train]" % idx] = 1
        if data:
            data['_token'] = self.token
        return self.post("{}/economy/train".format(self.url), data=data)

    def _post_economy_upgrade_company(self, factory: int, level: int, pin: str = None) -> Response:
        data = dict(_token=self.token, type="upgrade", companyId=factory, level=level, pin="" if pin is None else pin)
        return self.post("{}/economy/upgrade-company".format(self.url), data=data)

    def _post_economy_work(self, action_type: str, wam: List[int] = None, employ: Dict[int, int] = None) -> Response:
        """
        :return: requests.Response or None
        """
        if employ is None:
            employ = dict()
        if wam is None:
            wam = []
        data: Dict[str, Union[int, str]] = dict(action_type=action_type, _token=self.token)
        if action_type == "production":
            max_idx = 0
            for company_id in sorted(wam or []):
                data.update({
                    "companies[%i][id]" % max_idx: company_id,
                    "companies[%i][employee_works]" % max_idx: employ.pop(company_id, 0),
                    "companies[%i][own_work]" % max_idx: 1
                })
                max_idx += 1
            for company_id in sorted(employ or []):
                data.update({
                    "companies[%i][id]" % max_idx: company_id,
                    "companies[%i][employee_works]" % max_idx: employ.pop(company_id),
                    "companies[%i][own_work]" % max_idx: 0
                })
                max_idx += 1
        return self.post("{}/economy/work".format(self.url), data=data)

    def _post_economy_work_overtime(self) -> Response:
        data = dict(action_type="workOvertime", _token=self.token)
        return self.post("{}/economy/workOvertime".format(self.url), data=data)

    def _post_forgot_password(self, email: str) -> Response:
        data = dict(_token=self.token, email=email, commit="Reset password")
        return self.post("{}/forgot-password".format(self.url), data=data)

    def _post_fight_activate_booster(self, battle: int, quality: int, duration: int, kind: str) -> Response:
        data = dict(type=kind, quality=quality, duration=duration, battleId=battle, _token=self.token)
        return self.post("{}/military/fight-activateBooster".format(self.url), data=data)

    def _post_login(self, email: str, password: str) -> Response:
        data = dict(csrf_token=self.token, citizen_email=email, citizen_password=password, remember='on')
        return self.post("{}/login".format(self.url), data=data)

    def _post_messages_alert(self, notification_ids: List[int]) -> Response:
        data = {"_token": self.token, "delete_alerts[]": notification_ids, "deleteAllAlerts": "1", "delete": "Delete"}
        return self.post("{}/main/messages-alerts/1".format(self.url), data=data)

    def _post_messages_compose(self, subject: str, body: str, citizens: List[int]) -> Response:
        url_pk = 0 if len(citizens) > 1 else str(citizens[0])
        data = dict(citizen_name=",".join([str(x) for x in citizens]),
                    citizen_subject=subject, _token=self.token, citizen_message=body)
        return self.post("{}/main/messages-compose/{}}".format(self.url, url_pk), data=data)

    def _post_military_battle_console(self, battle_id: int, action: str, page: int = 1, **kwargs) -> Response:
        data = dict(battleId=battle_id, action=action, _token=self.token)
        if action == "battleStatistics":
            data.update(round=kwargs["round_id"], zoneId=kwargs["round_id"], leftPage=page, rightPage=page,
                        division=kwargs["division"], type=kwargs.get("type", 'damage'),)
        elif action == "warList":
            data.update(page=page)
        return self.post("{}/military/battle-console".format(self.url), data=data)

    def _post_military_deploy_bomb(self, battle_id: int, bomb_id: int) -> Response:
        data = dict(battleId=battle_id, bombId=bomb_id, _token=self.token)
        return self.post("{}/military/deploy-bomb".format(self.url), data=data)

    def _post_military_fight_air(self, battle_id: int, side_id: int) -> Response:
        data = dict(sideId=side_id, battleId=battle_id, _token=self.token)
        return self.post("{}/military/fight-shoooot/{}".format(self.url, battle_id), data=data)

    def _post_military_fight_ground(self, battle_id: int, side_id: int) -> Response:
        data = dict(sideId=side_id, battleId=battle_id, _token=self.token)
        return self.post("{}/military/fight-shooot/{}".format(self.url, battle_id), data=data)

    def _post_military_group_missions(self) -> Response:
        data = dict(action="check", _token=self.token)
        return self.post("{}/military/group-missions".format(self.url), data=data)

    def _post_travel(self, check: str, **kwargs) -> Response:
        data = dict(_token=self.token, check=check, **kwargs)
        return self.post("{}/main/travel".format(self.url), data=data)

    def _post_travel_data(self, **kwargs) -> Response:
        return self.post("{}/main/travelData".format(self.url), data=dict(_token=self.token, **kwargs))

    def _post_wars_attack_region(self, war_id: int, region_id: int, region_name: str) -> Response:
        data = {'_token': self.token, 'warId': war_id, 'regionName': region_name, 'regionNameConfirm': region_name}
        return self.post('{}/wars/attack-region/{}/{}'.format(self.url, war_id, region_id), data=data)

    def _post_weekly_challenge_reward(self, reward_id: int) -> Response:
        data = dict(_token=self.token, rewardId=reward_id)
        return self.post("{}/main/weekly-challenge-collect-reward".format(self.url), data=data)

    def _post_write_article(self, title: str, content: str, location: int, kind: int) -> Response:
        data = dict(_token=self.token, article_name=title, article_body=content, article_location=location,
                    article_category=kind)
        return self.post("{}/main/write-article".format(self.url), data=data)

    # Wall Posts
    # ## Country

    def _post_country_comment_retrieve(self, post_id: int) -> Response:
        data = {"_token": self.token, "postId": post_id}
        return self.post("{}/main/country-comment/retrieve/json".format(self.url), data=data)

    def _post_country_comment_create(self, post_id: int, comment_message: str) -> Response:
        data = {"_token": self.token, "postId": post_id, 'comment_message': comment_message}
        return self.post("{}/main/country-comment/create/json".format(self.url), data=data)

    def _post_country_post_create(self, body: str, post_as: int) -> Response:
        data = {"_token": self.token, "post_message": body, "post_as": post_as}
        return self.post("{}/main/country-post/create/json".format(self.url), data=data)

    def _post_country_post_retrieve(self) -> Response:
        data = {"_token": self.token, "page": 1, "switchedFrom": False}
        return self.post("{}/main/country-post/retrieve/json".format(self.url), data=data)

    # ## Military Unit

    def _post_military_unit_comment_retrieve(self, post_id: int) -> Response:
        data = {"_token": self.token, "postId": post_id}
        return self.post("{}/main/military-unit-comment/retrieve/json".format(self.url), data=data)

    def _post_military_unit_comment_create(self, post_id: int, comment_message: str) -> Response:
        data = {"_token": self.token, "postId": post_id, 'comment_message': comment_message}
        return self.post("{}/main/military-unit-comment/create/json".format(self.url), data=data)

    def _post_military_unit_post_create(self, body: str, post_as: int) -> Response:
        data = {"_token": self.token, "post_message": body, "post_as": post_as}
        return self.post("{}/main/military-unit-post/create/json".format(self.url), data=data)

    def _post_military_unit_post_retrieve(self) -> Response:
        data = {"_token": self.token, "page": 1, "switchedFrom": False}
        return self.post("{}/main/military-unit-post/retrieve/json".format(self.url), data=data)

    # ## Party

    def _post_party_comment_retrieve(self, post_id: int) -> Response:
        data = {"_token": self.token, "postId": post_id}
        return self.post("{}/main/party-comment/retrieve/json".format(self.url), data=data)

    def _post_party_comment_create(self, post_id: int, comment_message: str) -> Response:
        data = {"_token": self.token, "postId": post_id, 'comment_message': comment_message}
        return self.post("{}/main/party-comment/create/json".format(self.url), data=data)

    def _post_party_post_create(self, body: str) -> Response:
        data = {"_token": self.token, "post_message": body}
        return self.post("{}/main/party-post/create/json".format(self.url), data=data)

    def _post_party_post_retrieve(self) -> Response:
        data = {"_token": self.token, "page": 1, "switchedFrom": False}
        return self.post("{}/main/party-post/retrieve/json".format(self.url), data=data)

    # ## Friend's Wall

    def _post_wall_comment_retrieve(self, post_id: int) -> Response:
        data = {"_token": self.token, "postId": post_id}
        return self.post("{}/main/wall-comment/retrieve/json".format(self.url), data=data)

    def _post_wall_comment_create(self, post_id: int, comment_message: str) -> Response:
        data = {"_token": self.token, "postId": post_id, 'comment_message': comment_message}
        return self.post("{}/main/wall-comment/create/json".format(self.url), data=data)

    def _post_wall_post_create(self, body: str) -> Response:
        data = {"_token": self.token, "post_message": body}
        return self.post("{}/main/wall-post/create/json".format(self.url), data=data)

    def _post_wall_post_retrieve(self) -> Response:
        data = {"_token": self.token, "page": 1, "switchedFrom": False}
        return self.post("{}/main/wall-post/retrieve/json".format(self.url), data=data)


class Reporter:
    __to_update: List[Dict[Any, Any]] = []
    name: str = ""
    email: str = ""
    citizen_id: int = 0
    key: str = ""
    allowed: bool = False

    def __init__(self):
        self._req = Session()
        self.url = "https://api.erep.lv"
        self._req.headers.update({"user-agent": "Bot reporter v2"})
        self.__registered: bool = False

    @property
    def __dict__(self):
        return dict(allowed=self.allowed, __to_update=self.__to_update)

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
        if not self.key:
            if not all([self.email, self.name, self.citizen_id]):
                pass
        json_data = {'player_id': self.citizen_id, 'key': self.key, 'log': dict(action=action)}
        if json_val:
            json_data['log'].update(dict(json=json_val))
        if value:
            json_data['log'].update(dict(value=value))
        if self.allowed:
            self.__bot_update(json_data)
        else:
            self.__to_update.append(json_data)


class MyJSONEncoder(JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
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


class BattleSide:
    id: int
    points: int
    deployed: List[int] = list()
    allies: List[int] = list()

    def __init__(self, country_id: int, points: int, allies: List[int], deployed: List[int]):
        self.id = country_id
        self.points = points
        self.allies = [int(ally) for ally in allies]
        self.deployed = [int(ally) for ally in deployed]


class BattleDivision:
    end: datetime.datetime
    epic: bool
    dom_pts: Dict[str, int] = dict()
    wall: Dict[str, Union[int, float]] = dict()

    @property
    def div_end(self) -> bool:
        return utils.now() >= self.end

    def __init__(self, end: datetime.datetime, epic: bool, inv_pts: int, def_pts: int, wall_for: int, wall_dom: float):
        self.end = end
        self.epic = epic
        self.dom_pts.update({"inv": inv_pts, "def": def_pts})
        self.wall.update({"for": wall_for, "dom": wall_dom})


class Battle(object):
    id: int = 0
    war_id: int = 0
    zone_id: int = 0
    is_rw: bool = False
    is_dict_lib: bool = False
    start: datetime.datetime = None
    invader: BattleSide = None
    defender: BattleSide = None
    div: Dict[int, BattleDivision] = dict()

    @property
    def is_air(self) -> bool:
        return not bool(self.zone_id % 4)

    def __init__(self, battle: dict):
        self.id = int(battle.get('id', 0))
        self.war_id = int(battle.get('war_id', 0))
        self.zone_id = int(battle.get('zone_id', 0))
        self.is_rw = bool(battle.get('is_rw'))
        self.is_as = bool(battle.get('is_as'))
        self.is_dict_lib = bool(battle.get('is_dict')) or bool(battle.get('is_lib'))
        self.start = datetime.datetime.fromtimestamp(int(battle.get('start', 0)), tz=utils.erep_tz)

        self.invader = BattleSide(battle.get('inv', {}).get('id'), battle.get('inv', {}).get('points'),
                                  [row.get('id') for row in battle.get('inv', {}).get('ally_list')],
                                  [row.get('id') for row in battle.get('inv', {}).get('ally_list') if row['deployed']])

        self.defender = BattleSide(battle.get('def', {}).get('id'), battle.get('def', {}).get('points'),
                                   [row.get('id') for row in battle.get('def', {}).get('ally_list')],
                                   [row.get('id') for row in battle.get('def', {}).get('ally_list') if row['deployed']])

        for div, data in battle.get('div', {}).items():
            div = int(div)
            if data.get('end'):
                end = datetime.datetime.fromtimestamp(data.get('end'), tz=utils.erep_tz)
            else:
                end = datetime.datetime.max

            battle_div = BattleDivision(
                end=end, epic=data.get('epic_type') in [1, 5],
                inv_pts=data.get('dom_pts').get("inv"), def_pts=data.get('dom_pts').get("def"),
                wall_for=data.get('wall').get("for"), wall_dom=data.get('wall').get("dom")
            )

            self.div.update({div: battle_div})

    def __repr__(self):
        now = utils.now()
        is_started = self.start < utils.now()
        if is_started:
            time_part = "{}".format(now - self.start)
        else:
            time_part = "- {}".format(self.start - now)
        return "Battle {} | {:>21.21}:{:<21.21} | Round {:2} | Start {}".format(
            self.id, utils.COUNTRIES[self.invader.id], utils.COUNTRIES[self.defender.id], self.zone_id, time_part
        )


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
