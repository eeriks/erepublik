import re
import sys
import warnings
import weakref
from datetime import datetime, time, timedelta
from decimal import Decimal
from itertools import product
from threading import Event
from time import sleep
from typing import Any, Dict, List, NoReturn, Optional, Set, Tuple, Union

from requests import HTTPError, RequestException, Response

from . import access_points, classes, constants, types, utils
from .classes import OfferItem


class BaseCitizen(access_points.CitizenAPI):
    _last_full_update: datetime = constants.min_datetime
    _last_inventory_update: datetime = constants.min_datetime

    promos: Dict[str, datetime] = None
    _inventory: classes.Inventory
    ot_points: int = 0

    food: Dict[str, int] = dict(q1=0, q2=0, q3=0, q4=0, q5=0, q6=0, q7=0, total=0)
    eb_normal: int = 0
    eb_double: int = 0
    eb_small: int = 0
    division: int = 0
    maverick: bool = False

    eday: int = 0
    wheel_of_fortune: bool

    debug: bool = False
    config: classes.Config = None
    energy: classes.Energy = None
    details: classes.Details = None
    politics: classes.Politics = None
    my_companies: classes.MyCompanies = None
    reporter: classes.Reporter = None
    stop_threads: Event = None
    telegram: classes.TelegramReporter = None

    r: Response = None
    name: str = 'Not logged in!'
    logged_in: bool = False
    restricted_ip: bool = False

    def __init__(self, email: str = "", password: str = ""):
        super().__init__()
        self.config = classes.Config()
        self.energy = classes.Energy()
        self.details = classes.Details()
        self.politics = classes.Politics()
        self.my_companies = classes.MyCompanies(self)
        self.reporter = classes.Reporter(self)
        self.stop_threads = Event()
        self.telegram = classes.TelegramReporter(stop_event=self.stop_threads)

        self.config.email = email
        self.config.password = password
        self._inventory = classes.Inventory()
        self.wheel_of_fortune = False

    def get_csrf_token(self):
        """
        get_csrf_token is the function which logs you in, and updates csrf tokens
        (after 15min time of inactivity opening page in eRepublik.com redirects to home page),
        by explicitly requesting homepage.
        """
        resp = self._req.get(self.url)
        self.r = resp
        if self._errors_in_response(resp):
            self.get_csrf_token()
            return

        html = resp.text
        self._check_response_for_medals(html)
        re_token = re.search(r'var csrfToken = \'(\w{32})\'', html)
        re_login_token = re.search(r'<input type="hidden" id="_token" name="_token" value="(\w{32})">', html)
        if re_token:
            self.token = re_token.group(1)
        elif re_login_token:
            self.token = re_login_token.group(1)
            self._login()
        else:
            raise classes.ErepublikException("Something went wrong! Can't find token in page! Exiting!")
        try:
            self.update_citizen_info(resp.text)
        except (AttributeError, utils.json.JSONDecodeError, ValueError, KeyError):
            pass

    def get(self, url: str, **kwargs) -> Response:
        if (self.now - self._req.last_time).seconds >= 15 * 60:
            self.get_csrf_token()
            if 'params' in kwargs:
                if '_token' in kwargs['params']:
                    kwargs['params']['_token'] = self.token
        if url == self.r.url and not url == self.url:  # Don't duplicate requests, except for homepage
            response = self.r
        else:
            try:
                response = super().get(url, **kwargs)
            except RequestException as e:
                self.write_log('Network error while issuing GET request', e)
                self.sleep(60)
                return self.get(url, **kwargs)

            try:
                self.update_citizen_info(response.text)
            except (AttributeError, utils.json.JSONDecodeError, ValueError, KeyError):
                pass

            if self._errors_in_response(response):
                self.get_csrf_token()
                self.get(url, **kwargs)
            else:
                self._check_response_for_medals(response.text)

            self.r = response
        return response

    def post(self, url: str, data: dict = None, json: dict = None, **kwargs) -> Response:
        if json is None:
            json = {}
        if data is None:
            data = {}
        if (self.now - self._req.last_time).seconds >= 14 * 60:
            self.get_csrf_token()
            if '_token' in data:
                data['_token'] = self.token
            if '_token' in json:
                json['_token'] = self.token

        try:
            response = super().post(url, data=data, json=json, **kwargs)
        except RequestException as e:
            self.write_log('Network error while issuing POST request', e)
            self.sleep(60)
            return self.post(url, data=data, json=json, **kwargs)

        try:
            r_json = response.json()
            if (r_json.get('error') or not r_json.get('status')) and r_json.get('message', '') == 'captcha':
                utils.send_email(self.name, [response.text, ], player=self, captcha=True)
        except (AttributeError, utils.json.JSONDecodeError, ValueError, KeyError):
            pass

        if self._errors_in_response(response):
            self.get_csrf_token()
            if data:
                data.update({'_token': self.token})
            elif json:
                json.update({'_token': self.token})
            response = self.post(url, data=data, json=json, **kwargs)
        else:
            self._check_response_for_medals(response.text)

        self.r = response
        return response

    def update_citizen_info(self, html: str = None):
        """
        Gets main page and updates most information about player
        """
        if html is None:
            self._get_main()
            return
        ugly_js = re.search(r'"promotions":\s*(\[{?.*?}?])', html).group(1)
        promos = utils.json.loads(utils.normalize_html_json(ugly_js))
        if self.promos is None:
            self.promos = {}
        else:
            self.promos = {k: v for k, v in self.promos.items() if v > self.now}
        send_mail = False
        for promo in promos:
            promo_name = promo.get('id')
            expire = utils.localize_timestamp(int(promo.get('expiresAt')))
            if promo_name not in self.promos:
                send_mail = True
                self.promos.update({promo_name: expire})
        if send_mail:
            active_promos = []
            for kind, time_until in self.promos.items():
                active_promos.append(f"{kind} active until {time_until}")
                self.reporter.report_promo(kind, time_until)
            utils.send_email(self.name, active_promos, player=self, promo=True)

        new_date = re.search(r"var new_date = '(\d*)';", html)
        if new_date:
            self.energy.set_reference_time(
                utils.good_timedelta(self.now, timedelta(seconds=int(new_date.group(1))))
            )

        ugly_js = re.search(r"var erepublik = ({.*}),\s+", html).group(1)
        citizen_js = utils.json.loads(ugly_js)
        citizen = citizen_js.get('citizen', {})

        self.eday = citizen_js.get('settings').get('eDay')
        self.division = int(citizen.get('division', 0))

        self.energy.interval = citizen.get('energyPerInterval', 0)
        self.energy.limit = citizen.get('energyToRecover', 0)
        self.energy.recovered = citizen.get('energy', 0)
        self.energy.recoverable = citizen.get('energyFromFoodRemaining', 0)

        self.details.current_region = citizen.get('regionLocationId', 0)
        self.details.current_country = constants.COUNTRIES.get(
            citizen.get('countryLocationId', 0))  # country where citizen is located
        self.details.residence_region = citizen.get('residence', {}).get('regionId', 0)
        self.details.residence_country = constants.COUNTRIES.get(citizen.get('residence', {}).get('countryId', 0))
        self.details.citizen_id = citizen.get('citizenId', 0)
        self.details.citizenship = constants.COUNTRIES.get(int(citizen.get('country', 0)))
        self.details.xp = citizen.get('currentExperiencePoints', 0)
        self.details.level = citizen.get('userLevel', 0)
        self.details.daily_task_done = citizen.get('dailyTasksDone', False)
        self.details.daily_task_reward = citizen.get('hasReward', False)
        self.maverick = citizen.get('canSwitchDivisions', False)
        if citizen.get('dailyOrderDone', False) and not citizen.get('hasDailyOrderReward', False):
            self._post_military_group_missions()

        self.details.next_pp.sort()
        for skill in citizen.get('terrainSkills', {}).values():
            self.details.mayhem_skills.update({int(skill['terrain_id']): int(skill['skill_points'])})

        if citizen.get('party', []):
            party = citizen.get('party')
            self.politics.is_party_member = True
            self.politics.party_id = party.get('party_id')
            self.politics.is_party_president = bool(party.get('is_party_president'))
            self.politics.party_slug = f"{party.get('stripped_title')}-{party.get('party_id')}"

        self.wheel_of_fortune = bool(
            re.search(r'<a id="launch_wof" class="powerspin_sidebar( show_free)?" href="javascript:">', html))

    def update_inventory(self):
        """
        Updates citizen inventory
        """
        self._update_inventory_data(self._get_economy_inventory_items().json())

    @property
    def inventory(self) -> classes.Inventory:
        return self.get_inventory()

    def get_inventory(self, force: bool = False) -> classes.Inventory:
        if utils.good_timedelta(self._last_inventory_update, timedelta(minutes=2)) < self.now or force:
            self.update_inventory()
        return self._inventory

    def _update_inventory_data(self, inv_data: Dict[str, Any]):
        if not isinstance(inv_data, dict):
            raise TypeError("Parameter `inv_data` must be dict not '{type(data)}'!")

        def _expire_value_to_python(_expire_value: str) -> Dict[str, Union[int, datetime]]:
            _data = re.search(
                r'((?P<amount>\d+) item\(s\) )?[eE]xpires? on Day (?P<eday>\d,\d{3}), (?P<time>\d\d:\d\d)',
                _expire_value).groupdict()
            eday = utils.date_from_eday(int(_data['eday'].replace(',', '')))
            dt = constants.erep_tz.localize(datetime.combine(eday, time(*[int(_) for _ in _data['time'].split(':')])))
            return {'amount': _data.get('amount'), 'expiration': dt}

        status = inv_data.get('inventoryStatus', {})
        if status:
            self._inventory.used = status.get('usedStorage')
            self._inventory.total = status.get('totalStorage')
        data = inv_data.get('inventoryItems', {})
        if not data:
            return
        self._last_inventory_update = self.now
        self.food.update(q1=0, q2=0, q3=0, q4=0, q5=0, q6=0, q7=0)
        self.eb_small = self.eb_double = self.eb_normal = 0
        active_items: types.InvFinal = {}
        if data.get('activeEnhancements', {}).get('items', {}):
            for item_data in data.get('activeEnhancements', {}).get('items', {}).values():
                if item_data.get('token'):
                    kind = re.sub(r'_q\d\d*', "", item_data.get('token'))
                else:
                    kind = item_data.get('type')
                if constants.INDUSTRIES[kind]:
                    kind = constants.INDUSTRIES[constants.INDUSTRIES[kind]]
                if kind not in active_items:
                    active_items[kind] = {}
                expiration_info = []
                if item_data.get('attributes').get('expirationInfo'):
                    expire_info = item_data.get('attributes').get('expirationInfo')
                    expiration_info = [_expire_value_to_python(v) for v in expire_info['value']]
                if not item_data.get('icon') and item_data.get('isPackBooster'):
                    item_data['icon'] = f"//www.erepublik.com/images/icons/boosters/52px/{item_data.get('type')}.png"
                icon = item_data['icon'] if item_data['icon'] else "//www.erepublik.net/images/modules/manager/tab_storage.png"
                inv_item: types.InvFinalItem = dict(
                    name=item_data.get('name'), time_left=item_data['active']['time_left'], icon=icon,
                    kind=kind, expiration=expiration_info, quality=item_data.get('quality', 0)
                )

                if item_data.get('isPackBooster'):
                    active_items[kind].update({0: inv_item})
                else:
                    active_items[kind].update({inv_item.get('quality'): inv_item})

        final_items: types.InvFinal = {}
        boosters: types.InvBooster = {}
        if data.get('finalProducts', {}).get('items', {}):
            for item_data in data.get('finalProducts', {}).get('items', {}).values():
                is_booster: bool = False
                name = item_data['name']

                if item_data.get('type'):
                    #  in ['damageBoosters', 'aircraftDamageBoosters', 'prestigePointsBoosters']
                    if item_data.get('isBooster'):
                        is_booster = True
                        kind = item_data['type']

                        delta = item_data['duration']
                        if delta // 3600:
                            name += f" {delta // 3600}h"
                        if delta // 60 % 60:
                            name += f" {delta // 60 % 60}m"
                        if delta % 60:
                            name += f" {delta % 60}s"
                    else:
                        kind = item_data.get('type')
                else:
                    if item_data['industryId'] == 1:
                        amount = item_data['amount']
                        q = item_data['quality']
                        if 1 <= q <= 7:
                            self.food.update({f"q{q}": amount})
                        else:
                            if q == 10:
                                self.eb_normal = amount
                            elif q == 11:
                                self.eb_double = amount
                            elif q == 13:
                                self.eb_small += amount
                            elif q == 14:
                                self.eb_small += amount
                            elif q == 15:
                                self.eb_small += amount
                                item_data.update(token='energy_bar')
                            elif q == 16:
                                self.eb_small += amount
                                item_data.update(token='energy_bar')
                    kind = re.sub(r'_q\d\d*', "", item_data.get('token'))

                if item_data.get('token', "") == 'house_q100':
                    self.ot_points = item_data['amount']

                if constants.INDUSTRIES[kind]:
                    kind = constants.INDUSTRIES[constants.INDUSTRIES[kind]]

                if is_booster:
                    if kind not in boosters:
                        boosters[kind] = {}
                    if item_data.get('quality', 0) not in boosters[kind]:
                        boosters[kind][item_data['quality']] = {}
                else:
                    if kind not in final_items:
                        final_items[kind] = {}

                if item_data['icon']:
                    icon = item_data['icon']
                else:
                    if item_data['type'] == 'damageBoosters':
                        icon = "/images/modules/pvp/damage_boosters/damage_booster.png"
                    elif item_data['type'] == 'aircraftDamageBoosters':
                        icon = "/images/modules/pvp/damage_boosters/air_damage_booster.png"
                    elif item_data['type'] == 'prestigePointsBoosters':
                        icon = "/images/modules/pvp/prestige_points_boosters/prestige_booster.png"
                    elif item_data['type'] == 'speedBoosters':
                        icon = "/images/modules/pvp/speed_boosters/speed_booster.png"
                    elif item_data['type'] == 'catchupBoosters':
                        icon = "/images/modules/pvp/ghost_boosters/icon_booster_30_60.png"
                    else:
                        icon = "//www.erepublik.net/images/modules/manager/tab_storage.png"

                expiration_info = []
                if item_data.get('attributes'):
                    if item_data.get('attributes').get('expirationInfo'):
                        expire_info = item_data.get('attributes').get('expirationInfo')
                        expiration_info = [_expire_value_to_python(v) for v in expire_info['value']]
                    elif item_data.get('attributes').get('expiration'):
                        _exp = item_data.get('attributes').get('expiration')
                        exp_dt = (utils.date_from_eday(int(_exp['value'].replace(',', ''))))
                        expiration_info = [{'amount': item_data.get('amount'), 'expiration': exp_dt}]
                _inv_item: Dict[int, types.InvFinalItem]
                inv_item: types.InvFinalItem = dict(
                    kind=kind, quality=item_data.get('quality', 0), icon=icon, expiration=expiration_info,
                    amount=item_data.get('amount'), durability=item_data.get('duration', 0), name=name
                )
                if is_booster:
                    _inv_item = {inv_item['durability']: inv_item}
                else:
                    if item_data.get('type') == 'bomb':
                        firepower = 0
                        try:
                            firepower = item_data.get('attributes').get('firePower').get('value', 0)
                        except AttributeError:
                            pass
                        finally:
                            inv_item.update(fire_power=firepower)
                    _inv_item = {inv_item['quality']: inv_item}
                if is_booster:
                    boosters[kind][inv_item['quality']].update(_inv_item)
                else:
                    final_items[kind].update(_inv_item)

        raw_materials: types.InvRaw = {}
        if data.get('rawMaterials', {}).get('items', {}):
            for item_data in data.get('rawMaterials', {}).get('items', {}).values():
                if item_data['isPartial']:
                    continue
                kind = constants.INDUSTRIES[item_data['industryId']]
                if kind not in raw_materials:
                    raw_materials[kind] = {}
                if item_data['icon'].startswith('//www.erepublik.net/'):
                    icon = item_data['icon']
                else:
                    icon = "//www.erepublik.net/" + item_data['icon']

                raw_materials[constants.INDUSTRIES[item_data.get('industryId')]].update({
                    0: dict(name=item_data.get('name'),
                            amount=item_data['amount'] + (item_data.get('underCostruction', 0) / 100),
                            icon=icon)
                })

        offers: Dict[str, Dict[int, Dict[str, Union[str, int]]]] = {}
        for offer in self._get_economy_my_market_offers().json():
            kind = constants.INDUSTRIES[offer['industryId']]
            offer_data = dict(quality=offer.get('quality', 0), amount=offer.get('amount', 0), icon=offer.get('icon'),
                              kind=kind, name=kind)
            offer_data = {offer_data['quality']: offer_data}

            if kind not in offers:
                offers[kind] = {}

            offers[kind].update(offer_data)
        self._inventory.active = active_items
        self._inventory.final = final_items
        self._inventory.boosters = boosters
        self._inventory.raw = raw_materials
        self._inventory.offers = offers
        self.food['total'] = sum([self.food[q] * constants.FOOD_ENERGY[q] for q in constants.FOOD_ENERGY])

    def write_log(self, *args, **kwargs):
        if self.config.interactive:
            utils.write_interactive_log(*args, **kwargs)
        else:
            utils.write_silent_log(*args, **kwargs)

    def report_error(self, msg: str = "", is_warning: bool = False):
        if is_warning:
            utils.process_warning(msg, self.name, sys.exc_info(), self)
        else:
            utils.process_error(msg, self.name, sys.exc_info(), self, None, None)

    def sleep(self, seconds: Union[int, float, Decimal]):
        if seconds < 0:
            seconds = 0
        if self.config.interactive:
            utils.interactive_sleep(seconds)
        else:
            sleep(seconds)

    def set_debug(self, debug: bool):
        self.debug = bool(debug)
        self._req.debug = bool(debug)

    def to_json(self, indent: bool = False) -> str:
        return utils.json.dumps(self, cls=classes.ErepublikJSONEncoder, indent=4 if indent else None, sort_keys=True)

    def get_countries_with_regions(self) -> Set[constants.Country]:
        r_json = self._post_main_travel_data().json()
        return_set = {*[]}
        for country_data in r_json['countries'].values():
            if country_data['currentRegions']:
                return_set.add(constants.COUNTRIES[country_data['id']])
        return return_set

    def dump_instance(self):
        filename = f"{self.__class__.__name__}__dump.json"
        with open(filename, 'w') as f:
            utils.json.dump(dict(config=self.config, cookies=self._req.cookies.get_dict(),
                                 user_agent=self._req.headers.get("User-Agent")), f, cls=classes.ErepublikJSONEncoder)
        self.write_log(f"Session saved to: '{filename}'")

    @classmethod
    def load_from_dump(cls, dump_name: str):
        with open(dump_name) as f:
            data = utils.json.load(f, object_hook=utils.json_decode_object_hook)
        player = cls(data['config']['email'], "")
        player._req.cookies.update(data['cookies'])
        player._req.headers.update({"User-Agent": data['user_agent']})
        for k, v in data.get('config', {}).items():
            if hasattr(player.config, k):
                setattr(player.config, k, v)
        player._resume_session()
        return player

    def _resume_session(self):
        resp = self._req.get(self.url)
        re_name_id = re.search(r'<a data-fblog="profile_avatar" href="/en/citizen/profile/(\d+)" '
                               r'class="user_avatar" title="(.*?)">', resp.text)
        if re_name_id:
            self.name = re_name_id.group(2)
            self.details.citizen_id = re_name_id.group(1)
            self.write_log(f"Resumed as: {self.name}")
            if re.search('<div id="accountSecurity" class="it-hurts-when-ip">', resp.text):
                self.restricted_ip = True
                # self.report_error("eRepublik has blacklisted IP. Limited functionality!", True)

            self.logged_in = True
            self.get_csrf_token()
        else:
            self._login()

    def __str__(self) -> str:
        return f'Citizen {self.name}'

    def __repr__(self):
        return self.__str__()

    @property
    def as_dict(self):
        ret = super().as_dict
        ret.update(
            name=self.name, __str__=self.__str__(),
            ebs=dict(normal=self.eb_normal, double=self.eb_double, small=self.eb_small),
            promos=self.promos, inventory=self._inventory.as_dict, ot_points=self.ot_points, food=self.food,
            division=self.division, maveric=self.maverick, eday=self.eday, wheel_of_fortune=self.wheel_of_fortune,
            debug=self.debug,
            logged_in=self.logged_in, restricted_ip=self.restricted_ip, _properties=dict(
                now=self.now, should_do_levelup=self.should_do_levelup, is_levelup_reachable=self.is_levelup_reachable,
                max_time_till_full_ff=self.max_time_till_full_ff, is_levelup_close=self.is_levelup_close,
                time_till_full_ff=self.time_till_full_ff, time_till_week_change=self.time_till_week_change,
                next_wc_start=self.next_wc_start, next_reachable_energy=self.next_reachable_energy,
                health_info=self.health_info),
            _last_full_update=self._last_full_update, _last_inventory_update=self._last_inventory_update,
            config=self.config.as_dict, energy=self.energy.as_dict, details=self.details.as_dict,
            politics=self.politics.as_dict, my_companies=self.my_companies.as_dict, reporter=self.reporter.as_dict,
            telegram=self.telegram.as_dict, stop_threads=self.stop_threads.is_set(), response=self.r,
        )
        return ret

    def set_locks(self):
        self.stop_threads.set()

    @property
    def health_info(self):
        ret = f"{self.energy.recovered}/{self.energy.limit} + {self.energy.recoverable}, " \
              f"{self.energy.interval}hp/6m. {self.details.xp_till_level_up}xp until level up"
        return ret

    @property
    def next_reachable_energy(self) -> int:
        # Return pps for furthest __reachable__ +1 energy else 0
        max_pp = 0
        for pp_milestone in self.details.next_pp:
            pp_milestone = int(pp_milestone)
            if self.details.pp + self.energy.food_fights > pp_milestone:  # if reachable set max pp
                max_pp = pp_milestone
            else:  # rest are only bigger no need
                break
        return max_pp - self.details.pp if max_pp else 0

    @property
    def next_wc_start(self) -> datetime:
        days = 1 - self.now.weekday() if 1 - self.now.weekday() > 0 else 1 - self.now.weekday() + 7
        return utils.good_timedelta(self.now.replace(hour=0, minute=0, second=0, microsecond=0), timedelta(days=days))

    @property
    def time_till_week_change(self) -> timedelta:
        return self.next_wc_start - self.now

    @property
    def time_till_full_ff(self) -> timedelta:
        energy = self.energy.recoverable + self.energy.recovered
        if energy >= self.energy.limit * 2:
            return timedelta(0)
        minutes_needed = round((self.energy.limit * 2 - energy) / self.energy.interval) * 6
        return (self.energy.reference_time - self.now) + timedelta(minutes=minutes_needed)

    @property
    def max_time_till_full_ff(self) -> timedelta:
        """
        Max required time for 0 to full energy (0/0 -> limit/limit) (last interval rounded up)
        :return:
        """
        return timedelta(minutes=round((self.energy.limit * 2 / self.energy.interval) + 0.49) * 6)

    @property
    def is_levelup_close(self) -> bool:
        """
        If Energy limit * 2 >= xp till levelup * 10
        :return: bool
        """
        return self.energy.limit * 2 >= self.details.xp_till_level_up * 10

    @property
    def is_levelup_reachable(self) -> bool:
        """
        If Energy limit >= xp till levelup * 10
        :return: bool
        """
        return self.energy.limit >= self.details.xp_till_level_up * 10

    @property
    def should_do_levelup(self) -> bool:
        """
        If Energy limit >= xp till levelup * 10
        :return: bool
        """
        can_reach_next_level = self.energy.recovered >= self.details.xp_till_level_up * 10
        can_do_max_amount_of_dmg = self.energy.recoverable + 2 * self.energy.interval >= self.energy.limit
        return can_reach_next_level and can_do_max_amount_of_dmg

    @property
    def now(self) -> datetime:
        """
        Returns aware datetime object localized to US/Pacific (eRepublik time)
        :return: datetime
        """
        return utils.now()

    def _check_response_for_medals(self, html: str):
        new_medals = re.findall(r'(<div class="home_reward reward achievement">.*?<div class="bottom"></div>\s*</div>)',
                                html, re.M | re.S | re.I)
        data: Dict[Tuple[str, Union[float, str]], Dict[str, Union[int, str, float]]] = {}
        for medal in new_medals:
            try:
                info = re.search(r"<h3>New Achievement</h3>.*?<p.*?>(.*?)</p>.*?"
                                 r"achievement_recieved.*?<strong>(.*?)</strong>.*?"
                                 r"<div title=\"(.*?)\">", medal, re.M | re.S)
                about = info.group(1).strip()
                title = info.group(2).strip()
                award_id = re.search(r'"wall_enable_alerts_(\d+)', medal)
                if award_id:
                    try:
                        award_id = int(award_id.group(1))
                        self._post_main_wall_post_automatic(message=title, achievement_id=award_id)
                    except ValueError:
                        pass
                reward, currency = info.group(3).strip().split(' ')
                while not isinstance(reward, float):
                    try:
                        reward = float(reward)
                    except ValueError:
                        reward = reward[:-1]

                if (title, reward) not in data:
                    data[(title, reward)] = dict(about=about, kind=title, reward=reward, count=1, currency=currency)
                else:
                    data[(title, reward)]['count'] += 1
            except AttributeError:
                continue
        if data:
            msgs = [f"{d['count']} x {d['kind']}, totaling {d['count'] * d['reward']} "
                    f"{d['currency']}" for d in data.values()]

            msgs = "\n".join(msgs)
            if self.config.telegram:
                self.telegram.report_medal(msgs)
            self.write_log(f"Found awards:\n{msgs}")
            for info in data.values():
                self.reporter.report_action('NEW_MEDAL', info)

        levelup = re.search(r"<p>Congratulations, you have reached experience <strong>level (\d+)</strong></p>", html)
        if levelup:
            level = levelup.group(1)
            msg = f"Level up! Current level {level}"
            self.write_log(msg)
            if self.config.telegram:
                self.telegram.report_medal(f"Level *{level}*")
            self.reporter.report_action('LEVEL_UP', value=level)

    def _travel(self, country: constants.Country, region_id: int = 0) -> Response:
        data = dict(toCountryId=country.id, inRegionId=region_id)
        return self._post_main_travel('moveAction', **data)

    def _get_main_party_members(self, party_id: int) -> Dict[int, str]:
        ret = {}
        r = super()._get_main_party_members(party_id)
        for id_, name in re.findall(r'<a href="//www.erepublik.com/en/main/messages-compose/(\d+)" '
                                    r'title="([\w\d_ .]+)">', r.text):
            ret.update({id_: name})
        return ret

    def _eat(self, colour: str = 'blue') -> Response:
        response = self._post_eat(colour)
        r_json = response.json()
        for q, amount in r_json.get('units_consumed').items():
            if f"q{q}" in self.food:
                self.food[f"q{q}"] -= amount
            elif q == '10':
                self.eb_normal -= amount
            elif q == '11':
                self.eb_double -= amount
            elif q == '12':
                self.eb_small -= amount
            elif q == '15':
                self.eb_small -= amount
            elif q == '16':
                self.eb_small -= amount
        next_recovery = r_json.get('food_remaining_reset').split(":")
        self.energy.set_reference_time(
            utils.good_timedelta(self.now, timedelta(seconds=int(next_recovery[1]) * 60 + int(next_recovery[2])))
        )
        self.energy.recovered = r_json.get('health')
        self.energy.recoverable = r_json.get('food_remaining')
        return response

    def _login(self):
        # MUST BE CALLED TROUGH self.get_csrf_token()
        r = self._post_login(self.config.email, self.config.password)
        self.r = r

        if r.url == f"{self.url}/login":
            self.write_log("Citizen email and/or password is incorrect!")
            raise KeyboardInterrupt
        else:
            re_name_id = re.search(r'<a data-fblog="profile_avatar" href="/en/citizen/profile/(\d+)" '
                                   r'class="user_avatar" title="(.*?)">', r.text)
            self.name = re_name_id.group(2)
            self.details.citizen_id = re_name_id.group(1)

            self.write_log(f"Logged in as: {self.name}")
            self.get_csrf_token()
            if re.search('<div id="accountSecurity" class="it-hurts-when-ip">', self.r.text):
                self.restricted_ip = True
                # self.report_error('eRepublik has blacklisted IP. Limited functionality!', True)

            self.logged_in = True

    def _errors_in_response(self, response: Response):
        try:
            j = response.json()
            if j['error'] and j['message'] == 'Too many requests':
                self.write_log('Made too many requests! Sleeping for 30 seconds.')
                self.sleep(30)
        except (utils.json.JSONDecodeError, KeyError, TypeError):
            pass
        if response.status_code >= 400:
            self.r = response
            if response.status_code >= 500:
                if self.restricted_ip:
                    self._req.cookies.clear()
                    return True
                self.write_log('eRepublik servers are having internal troubles. Sleeping for 5 minutes')
                self.sleep(5 * 60)
            else:
                raise classes.ErepublikException(f"HTTP {response.status_code} error!")

        if re.search(r'Occasionally there are a couple of things which we need to check or to implement in order make '
                     r'your experience in eRepublik more pleasant. <strong>Don\'t worry about ongoing battles, timer '
                     r'will be stopped during maintenance.</strong>', response.text):
            self.write_log('eRepublik is having maintenance. Sleeping for 5 minutes')
            self.sleep(5 * 60)
            return True

        if re.search('We are experiencing some tehnical dificulties', response.text):
            self.write_log('eRepublik is having technical difficulties. Sleeping for 5 minutes')
            self.sleep(5 * 60)
            return True

        return bool(re.search(r'body id="error"|Internal Server Error|'
                              r'CSRF attack detected|meta http-equiv="refresh"|'
                              r'not_authenticated', response.text))

    def _report_action(self, action: str, msg: str, **kwargs: Optional[Dict[str, Any]]):
        """ Report action to all available reporting channels

        :type action: str
        :type msg: str
        :type kwargs: Optional[Dict[str, Any]]
        :param action: Action taken
        :param msg: Message about the action
        :param kwargs: Extra information regarding action
        """
        kwargs = utils.json.loads(utils.json.dumps(kwargs or {}, cls=classes.ErepublikJSONEncoder))
        action = action[:32]
        self.write_log(msg)
        if self.reporter.allowed:
            self.reporter.report_action(action, kwargs, msg)
        if self.config.telegram:
            self.telegram.send_message(msg)


class CitizenAnniversary(BaseCitizen):
    def collect_anniversary_reward(self) -> Response:
        return self._post_main_collect_anniversary_reward()

    def get_anniversary_quest_data(self):
        return self._get_anniversary_quest_data().json()

    def start_unlocking_map_quest_node(self, node_id: int):
        return self._post_map_rewards_unlock(node_id)

    def collect_map_quest_node(self, node_id: int, extra: bool = False):
        return self._post_map_rewards_claim(node_id, extra)

    def speedup_map_quest_node(self, node_id: int):
        node = self.get_anniversary_quest_data().get('cities', {}).get(str(node_id), {})
        return self._post_map_rewards_speedup(node_id, node.get('skipCost', 0))

    def spin_wheel_of_fortune(self, max_cost=0, spin_count=0):
        if not self.config.spin_wheel_of_fortune:
            self.write_log("Unable to spin wheel of fortune because 'config.spin_wheel_of_fortune' is False")
            return

        def _write_spin_data(cost: int, prize: str):
            self._report_action('WHEEL_SPIN', f"Cost: {cost:4d} | Currency left: {self.details.cc:,} | Prize: {prize}")

        if not self.wheel_of_fortune:
            self.update_citizen_info()
        base = self._post_main_wheel_of_fortune_build().json()
        current_cost = 0 if base.get('progress').get('free_spin') else base.get('cost')
        current_count = base.get('progress').get('spins')
        prizes = base.get('prizes')
        if not max_cost and not spin_count:
            r = self._post_main_wheel_of_fortune_spin(current_cost).json()
            _write_spin_data(current_cost, prizes.get('prizes').get(str(r.get('result'))).get('tooltip'))
        else:
            while max_cost >= current_cost if max_cost else spin_count >= current_count if spin_count else False:
                r = self._spin_wheel_of_loosing(current_cost)
                current_count += 1
                prize_name = prizes.get('prizes').get(str(r.get('result'))).get('tooltip')
                if r.get('result') == 7:
                    prize_name += f" - {prizes.get('jackpot').get(str(r.get('jackpot'))).get('tooltip')}"
                _write_spin_data(current_cost, prize_name)
                current_cost = r.get('cost')
                if r.get('jackpot', 0) == 3:
                    return

    def _spin_wheel_of_loosing(self, current_cost: int) -> Dict[str, Any]:
        r = self._post_main_wheel_of_fortune_spin(current_cost).json()
        self.details.cc = float(Decimal(r.get('account')))
        return r


class CitizenTravel(BaseCitizen):
    def _update_citizen_location(self, country: constants.Country, region_id: int):
        self.details.current_region = region_id
        self.details.current_country = country

    def _travel(self, country: constants.Country, region_id: int = 0) -> bool:
        r_json = super()._travel(country, region_id).json()
        if not bool(r_json.get('error')):
            self._update_citizen_location(country, region_id)
            return True
        else:
            if 'Travelling too fast.' in r_json.get('message'):
                self.sleep(1)
                return self._travel(country, region_id)
        return False

    def get_country_travel_region(self, country: constants.Country) -> int:
        regions = self.get_travel_regions(country=country)
        regs = []
        if regions:
            for region in regions.values():
                if region['countryId'] == country.id:  # Is not occupied by other country
                    regs.append((region['id'], region['distanceInKm']))
        if regs:
            return min(regs, key=lambda _: int(_[1]))[0]
        else:
            return 0

    def travel_to_residence(self) -> bool:
        self.update_citizen_info()
        res_r = self.details.residence_region
        if self.details.residence_country and res_r and not res_r == self.details.current_region:
            if self._travel(self.details.residence_country, self.details.residence_region):
                self._report_action('TRAVEL', 'Traveled to residence')
                return True
            else:
                self._report_action('TRAVEL', 'Unable to travel to residence!')
                return False
        return True

    def travel_to_region(self, region_id: int) -> bool:
        data = self._post_main_travel_data(region_id=region_id).json()
        if data.get('alreadyInRegion'):
            return True
        else:
            country = None
            for country_data in data.get('countries').values():
                if region_id in country_data.get('regions'):
                    country = constants.COUNTRIES[country_data.get('id')]
                    break

            if country is None:
                raise classes.ErepublikException('Region not found!')

            if self._travel(country, region_id):
                self._report_action('TRAVEL', 'Traveled to region')
                return True
            else:
                self._report_action('TRAVEL', 'Unable to travel to region!')

        return False

    def travel_to_country(self, country: constants.Country) -> bool:
        data = self._post_main_travel_data(countryId=country.id, check='getCountryRegions').json()

        regs = []
        if data.get('regions'):
            for region in data.get('regions').values():
                if region['countryId'] == country:  # Is not occupied by other country
                    regs.append((region['id'], region['distanceInKm']))
        if regs:
            region_id = min(regs, key=lambda _: int(_[1]))[0]

            if self._travel(country, region_id):
                self._report_action('TRAVEL', f"Traveled to {country.name}")
                return True
            else:
                self._report_action('TRAVEL', f"Unable to travel to {country.name}!")

        return False

    def travel_to_holding(self, holding: classes.Holding) -> bool:
        data = self._post_main_travel_data(holdingId=holding.id).json()
        if data.get('alreadyInRegion'):
            return True
        else:
            country = constants.COUNTRIES[data.get('preselectCountryId')]
            region_id = data.get('preselectRegionId')

            if self._travel(country, region_id):
                self._report_action('TRAVEL', f"Traveled to {holding}")
                return True
            else:
                self._report_action('TRAVEL', f"Unable to travel to {holding}!")

    def travel_to_battle(self, battle: classes.Battle, allowed_countries: List[constants.Country]) -> bool:
        data = self.get_travel_regions(battle=battle)

        regs = []
        countries: Dict[int, constants.Country] = {c.id: c for c in allowed_countries}
        if data:
            for region in data.values():
                if region['countryId'] in countries:  # Is not occupied by other country
                    regs.append((region['distanceInKm'], region['id'], countries[region['countryId']]))
        if regs:
            reg = min(regs, key=lambda _: int(_[0]))
            region_id = reg[1]
            country = reg[2]
            if self._travel(country, region_id):
                self._report_action('TRAVEL', f"Traveled to {battle}")
                return True
            else:
                self._report_action('TRAVEL', f"Unable to travel to {battle}!")
        return False

    def get_travel_regions(
        self, holding: classes.Holding = None, battle: classes.Battle = None, country: constants.Country = None
    ) -> Union[List[Any], Dict[str, Dict[str, Any]]]:
        return self._post_main_travel_data(
            holdingId=holding.id if holding else 0,
            battleId=battle.id if battle else 0,
            countryId=country.id if country else 0
        ).json().get('regions', [])

    def get_travel_countries(self) -> Set[constants.Country]:
        warnings.simplefilter('always')
        warnings.warn('CitizenTravel.get_travel_countries() are being deprecated, '
                      'please use BaseCitizen.get_countries_with_regions()', DeprecationWarning)
        return self.get_countries_with_regions()


class CitizenCompanies(BaseCitizen):
    def employ_employees(self) -> bool:
        self.update_companies()
        ret = True
        employee_companies = self.my_companies.get_employable_factories()
        work_units_needed = sum(employee_companies.values())

        if work_units_needed:
            if work_units_needed <= self.my_companies.work_units:
                response = self._post_economy_work('production', employ=employee_companies).json()
                self.reporter.report_action('WORK_EMPLOYEES', response, response.get('status', False))
            self.update_companies()
            ret = bool(self.my_companies.get_employable_factories())

        return ret

    def work_as_manager_in_holding(self, holding: classes.Holding) -> Optional[Dict[str, Any]]:
        return self._work_as_manager(holding)

    def _work_as_manager(self, wam_holding: classes.Holding) -> Optional[Dict[str, Any]]:
        if self.restricted_ip:
            return None
        self.update_companies()
        data = {'action_type': 'production'}
        extra = {}
        raw_factories = wam_holding.get_wam_companies(raw_factory=True)
        fin_factories = wam_holding.get_wam_companies(raw_factory=False)

        free_inventory = self.inventory.total - self.inventory.used
        wam_list = raw_factories + fin_factories
        wam_list = wam_list[:self.energy.food_fights]

        if int(free_inventory * 0.75) < self.my_companies.get_needed_inventory_usage(wam_list):
            self.update_inventory()
            free_inventory = self.inventory.total - self.inventory.used

        while wam_list and free_inventory < self.my_companies.get_needed_inventory_usage(wam_list):
            wam_list.pop(-1)

        if wam_list:
            data.update(extra)
            if not self.details.current_region == wam_holding.region:
                self.write_log("Unable to work as manager because of location - please travel!")
                return

            employ_factories = self.my_companies.get_employable_factories()
            if sum(employ_factories.values()) > self.my_companies.work_units:
                employ_factories = {}

            response = self._post_economy_work('production', wam=[c.id for c in wam_list],
                                               employ=employ_factories).json()
            return response

    def update_companies(self):
        html = self._get_economy_my_companies().text
        page_details = utils.json.loads(re.search(r"var pageDetails\s+= ({.*});", html).group(1))
        self.my_companies.work_units = int(page_details.get('total_works', 0))

        have_holdings = re.search(r"var holdingCompanies\s+= ({.*}});", html)
        have_companies = re.search(r"var companies\s+= ({.*}});", html)
        if have_holdings and have_companies:
            self.my_companies.prepare_holdings(utils.json.loads(have_holdings.group(1)))
            self.my_companies.prepare_companies(utils.json.loads(have_companies.group(1)))

    def assign_company_to_holding(self, company: classes.Company, holding: classes.Holding) -> Response:
        """
        Assigns factory to new holding
        """
        self.write_log(f"{company} moved to {holding}")
        company._holding = weakref.ref(holding)
        return self._post_economy_assign_to_holding(company.id, holding.id)

    def create_factory(self, industry_id: int, building_type: int = 1) -> Response:
        """
        param industry_ids: FRM={q1:7, q2:8, q3:9, q4:10, q5:11} WRM={q1:12, q2:13, q3:14, q4:15, q5:16}
                            HRM={q1:18, q2:19, q3:20, q4:21, q5:22} ARM={q1:24, q2:25, q3:26, q4:27, q5:28}
                            Factories={Food:1, Weapons:2, House:4, Aircraft:23} <- Building_type 1

                            Storage={1000: 1, 2000: 2} <- Building_type 2
        """
        company_name = constants.INDUSTRIES[industry_id]
        if building_type == 2:
            company_name = 'Storage'
        self.write_log(f'{company_name} created!')
        return self._post_economy_create_company(industry_id, building_type)


class CitizenEconomy(CitizenTravel):
    def update_money(self, page: int = 0, currency: int = 62):
        """
        Gets monetary market offers to get exact amount of CC and Gold available
        """
        if currency not in [1, 62]:
            currency = 62
        resp = self._post_economy_exchange_retrieve(False, page, currency)
        resp_data = resp.json()
        self.details.cc = float(resp_data.get('ecash').get('value'))
        self.details.gold = float(resp_data.get('gold').get('value'))

    def check_house_durability(self) -> Dict[int, datetime]:
        ret = {}
        inv = self.inventory
        for house_quality, active_house in inv.active.get('House', {}).items():
            till = utils.good_timedelta(self.now, timedelta(seconds=active_house['time_left']))
            ret.update({house_quality: till})
        return ret

    def buy_and_activate_house(self, q: int) -> Optional[Dict[int, datetime]]:
        original_region = self.details.current_country, self.details.current_region
        ok_to_activate = False
        inv = self.inventory
        if not inv.final.get('House', {}).get(q, {}):
            countries = [self.details.citizenship, ]
            if self.details.current_country != self.details.citizenship:
                countries.append(self.details.current_country)
            offers = [self.get_market_offers('House', q, country)[f"q{q}"] for country in countries]
            local_cheapest = sorted(offers, key=lambda o: o.price)[0]

            global_cheapest = self.get_market_offers('House', q)[f"q{q}"]
            if global_cheapest.price + 2000 < local_cheapest.price:
                if global_cheapest.price + 2000 < self.details.cc:
                    if self.travel_to_country(global_cheapest.country):
                        buy = self.buy_market_offer(global_cheapest, 1)
                    else:
                        buy = dict(error=True, message='Unable to travel!')
                else:
                    buy = dict(error=True, message='Not enough money to buy house!')
            else:
                if local_cheapest.price < self.details.cc:
                    buy = self.buy_market_offer(local_cheapest, 1)
                else:
                    buy = dict(error=True, message='Not enough money to buy house!')
            if buy is None:
                pass
            elif buy['error']:
                msg = f'Unable to buy q{q} house! \n{buy["message"]}'
                self.write_log(msg)
            else:
                ok_to_activate = True
        else:
            ok_to_activate = True
        if ok_to_activate:
            self.activate_house(q)
        if original_region[1] != self.details.current_region:
            self._travel(*original_region)
        return self.check_house_durability()

    def renew_houses(self, forced: bool = False) -> Dict[int, datetime]:
        """
        Renew all houses which end time is in next 48h
        :param forced: if true - renew all houses
        :return:
        """
        house_durability = self.check_house_durability()
        for q, active_till in house_durability.items():
            if utils.good_timedelta(active_till, - timedelta(hours=48)) <= self.now or forced:
                durability = self.buy_and_activate_house(q)
                if durability:
                    house_durability = durability
        return house_durability

    def activate_house(self, quality: int) -> bool:
        r: Dict[str, Any] = self._post_economy_activate_house(quality).json()
        self._update_inventory_data(r)
        if r.get('status') and not r.get('error'):
            house = self.inventory.active.get('House', {}).get(quality)
            time_left = timedelta(seconds=house['time_left'])
            active_until = utils.good_timedelta(self.now, time_left)
            self._report_action(
                'ACTIVATE_HOUSE',
                f"Activated {house['name']}. Expires at {active_until.strftime('%F %T')} (after {time_left})"
            )
            return True
        return False

    def get_game_token_offers(self):
        r = self._post_economy_game_tokens_market('retrieve').json()
        return {v.get('id'): dict(amount=v.get('amount'), price=v.get('price')) for v in r.get('topOffers')}

    def fetch_organisation_account(self, org_id: int):
        r = self._get_economy_citizen_accounts(org_id)
        table = re.search(r'(<table class="holder racc" .*</table>)', r.text, re.I | re.M | re.S)
        if table:
            account = re.findall(r'>\s*(\d+.\d+)\s*</td>', table.group(1))
            if account:
                return dict(gold=account[0], cc=account[1], ok=True)

        return dict(gold=0, cc=0, ok=False)

    def accept_money_donations(self):
        for notification in self._get_main_notifications_ajax_system().json():
            don_id = re.search(r"erepublik.functions.acceptRejectDonation\(\"accept\", (\d+)\)", notification)
            if don_id:
                self._get_main_money_donation_accept(int(don_id.group(1)))
                self.sleep(5)

    def reject_money_donations(self) -> int:
        r = self._get_main_notifications_ajax_system()
        count = 0
        donation_ids = re.findall(r"erepublik.functions.acceptRejectDonation\(\"reject\", (\d+)\)", r.text)
        while donation_ids:
            for don_id in donation_ids:
                self._get_main_money_donation_reject(int(don_id))
                count += 1
                self.sleep(5)
            r = self._get_main_notifications_ajax_system()
            donation_ids = re.findall(r"erepublik.functions.acceptRejectDonation\(\"reject\", (\d+)\)", r.text)
        return count

    def get_my_market_offers(self) -> List[Dict[str, Union[int, float, str]]]:
        ret = []
        for offer in self._get_economy_my_market_offers().json():
            line = offer.copy()
            line.pop('icon', None)
            ret.append(line)
        return ret

    def delete_my_market_offer(self, offer_id: int) -> bool:
        offers = self.get_my_market_offers()
        for offer in offers:
            if offer['id'] == offer_id:
                industry = constants.INDUSTRIES[offer['industryId']]
                amount = offer['amount']
                q = offer['quality']
                price = offer['price']
                ret = self._post_economy_marketplace_actions('delete', offer_id=offer_id).json()
                if ret.get('error'):
                    self._report_action('ECONOMY_DELETE_OFFER', f"Unable to delete offer: '{ret.get('message')}'",
                                        kwargs=offer)
                else:
                    self._report_action('ECONOMY_DELETE_OFFER',
                                        f"Removed offer for {amount} x {industry} q{q} for {price}cc/each",
                                        kwargs=offer)
                return not ret.get('error')
        else:
            self._report_action('ECONOMY_DELETE_OFFER', f"Unable to find offer id{offer_id}", kwargs={'offers': offers})
        return False

    def post_market_offer(self, industry: int, quality: int, amount: int, price: float) -> bool:
        if isinstance(industry, str):
            industry = constants.INDUSTRIES[industry]
        if not constants.INDUSTRIES[industry]:
            self.write_log(f"Trying to sell unsupported industry {industry}")

        _inv_qlt = quality if industry in [1, 2, 3, 4, 23] else 0
        final_kind = industry in [1, 2, 4, 23]
        items = (self.inventory.final if final_kind else self.inventory.raw).get(constants.INDUSTRIES[industry],
                                                                                 {_inv_qlt: {'amount': 0}})
        if items[_inv_qlt]['amount'] < amount:
            self.update_inventory()
            items = (self.inventory.final if final_kind else self.inventory.raw).get(constants.INDUSTRIES[industry],
                                                                                     {_inv_qlt: {'amount': 0}})
            if items[_inv_qlt]['amount'] < amount:
                self._report_action('ECONOMY_SELL_PRODUCTS', 'Unable to sell! Not enough items in storage!',
                                    kwargs=dict(inventory=items[_inv_qlt], amount=amount))
                return False

        data = dict(country_id=self.details.citizenship.id, industry=industry, quality=quality, amount=amount,
                    price=price, buy=False)
        ret = self._post_economy_marketplace_actions('sell', **data).json()
        message = (f"Posted market offer for {amount}q{quality} "
                   f"{constants.INDUSTRIES[industry]} for price {price}cc")
        self._report_action('ECONOMY_SELL_PRODUCTS', message, kwargs=ret)
        return not bool(ret.get('error', True))

    def buy_from_market(self, offer: int, amount: int) -> Dict[str, Any]:
        ret = self._post_economy_marketplace_actions('buy', offer=offer, amount=amount)
        json_ret = ret.json()
        if not json_ret.get('error', True):
            self.details.cc = ret.json()['currency']
            self.details.gold = ret.json()['gold']
            json_ret.pop('offerUpdate', None)
            self._report_action('BOUGHT_PRODUCTS', json_ret.get('message'), kwargs=json_ret)
        return json_ret

    def buy_market_offer(self, offer: OfferItem, amount: int = None) -> Optional[Dict[str, Any]]:
        if amount is None or amount > offer.amount:
            amount = offer.amount
        traveled = False
        if not self.details.current_country == offer.country:
            traveled = True
            self.travel_to_country(offer.country)
        json_ret = self.buy_from_market(offer.offer_id, amount)
        if traveled:
            self.travel_to_residence()
        return json_ret

    def get_market_offers(
        self, product_name: str, quality: int = None, country: constants.Country = None
    ) -> Dict[str, classes.OfferItem]:
        raw_short_names = dict(frm='foodRaw', wrm='weaponRaw', hrm='houseRaw', arm='airplaneRaw')
        q1_industries = list(raw_short_names.values())
        q5_industries = ['house', 'aircraft', 'ticket']
        if product_name in raw_short_names:
            quality = 1
            product_name = raw_short_names[product_name]
        elif not constants.INDUSTRIES[product_name]:
            self.write_log(f"Industry '{product_name}' not implemented")
            raise classes.ErepublikException(f"Industry '{product_name}' not implemented")

        offers: Dict[str, classes.OfferItem] = {}

        max_quality = 0
        if quality:
            offers[f"q{quality}"] = classes.OfferItem()
        else:
            max_quality = 1 if product_name in q1_industries else 5 if product_name.lower() in q5_industries else 7
            for q in range(max_quality):
                offers[f"q{q + 1}"] = classes.OfferItem()

        if country:
            countries: Set[constants.Country] = {country}
        else:
            countries: Set[constants.Country] = self.get_countries_with_regions()

        start_dt = self.now
        iterable = [countries, [quality] if quality else range(1, max_quality + 1)]
        for country, q in product(*iterable):
            r = self._post_economy_marketplace(country.id, constants.INDUSTRIES[product_name], q).json()
            obj = offers[f"q{q}"]
            if not r.get('error', False):
                for offer in r['offers']:
                    if (obj.price > float(offer['priceWithTaxes']) or (
                        obj.price == float(offer['priceWithTaxes']) and obj.amount < int(offer['amount'])
                    )):
                        offers[f"q{q}"] = obj = classes.OfferItem(
                            float(offer['priceWithTaxes']),
                            constants.COUNTRIES[int(offer['country_id'])], int(offer['amount']),
                            int(offer['id']), int(offer['citizen_id'])
                        )
        self.write_log(f"Scraped market in {self.now - start_dt}!")

        return offers

    def buy_food(self, energy_amount: int = 0):
        hp_needed = energy_amount if energy_amount else 48 * self.energy.interval * 10 - self.food['total']
        local_offers = self.get_market_offers('food', country=self.details.current_country)

        cheapest_q, cheapest = sorted(local_offers.items(), key=lambda v: v[1].price / constants.FOOD_ENERGY[v[0]])[0]

        if cheapest.amount * constants.FOOD_ENERGY[cheapest_q] < hp_needed:
            amount = cheapest.amount
        else:
            amount = hp_needed // constants.FOOD_ENERGY[cheapest_q]

        if amount * cheapest.price < self.details.cc:
            data = dict(offer=cheapest.offer_id, amount=amount, price=cheapest.price,
                        cost=amount * cheapest.price, quality=cheapest_q,
                        energy=amount * constants.FOOD_ENERGY[cheapest_q])
            self._report_action('BUY_FOOD', "", kwargs=data)
            self.buy_from_market(cheapest.offer_id, amount)
            self.update_inventory()
        else:
            s = f"Don't have enough money! Needed: {amount * cheapest.price}cc, Have: {self.details.cc}cc"
            self.write_log(s)
            self._report_action('BUY_FOOD', s)

    def get_monetary_offers(self, currency: int = 62) -> List[Dict[str, Union[int, float]]]:
        if currency not in [1, 62]:
            currency = 62
        resp = self._post_economy_exchange_retrieve(False, 0, currency).json()
        ret = []
        offers = re.findall(r"id='purchase_(\d+)' data-i18n='Buy for' data-currency='GOLD' "
                            r"data-price='(\d+\.\d+)' data-max='(\d+\.\d+)' trigger='purchase'",
                            resp['buy_mode'], re.M | re.I | re.S)

        for offer_id, price, amount in offers:
            ret.append(dict(offer_id=int(offer_id), price=float(price), amount=float(amount)))

        return sorted(ret, key=lambda o: (o['price'], -o['amount']))

    def buy_monetary_market_offer(self, offer: int, amount: float, currency: int) -> int:
        """ Buy from monetary market

        :param offer: offer id which should be bought
        :type offer: int
        :param amount: amount to buy
        :amount amount: float
        :param currency: currency kind - gold = 62, cc = 1
        :type currency: int
        :return:
        """
        response = self._post_economy_exchange_purchase(amount, currency, offer)
        self.details.cc = float(response.json().get('ecash').get('value'))
        self.details.gold = float(response.json().get('gold').get('value'))
        if response.json().get('error'):
            self._report_action('BUY_GOLD', 'Unable to buy gold!', kwargs=response.json())
            return False
        else:
            self._report_action('BUY_GOLD', f'New amount {self.details.cc}cc, {self.details.gold}g',
                                kwargs=response.json())
            return True

    def donate_money(self, citizen_id: int = 1620414, amount: float = 0.0, currency: int = 62) -> bool:
        """ currency: gold = 62, cc = 1 """
        resp = self._post_economy_donate_money_action(citizen_id, amount, currency)
        r = re.search('You do not have enough money in your account to make this donation', resp.text)
        success = not bool(r)
        self.update_money()
        cur = 'g' if currency == 62 else 'cc'
        if success:
            self.report_money_donation(citizen_id, amount, currency == 1)
        else:
            self._report_action('DONATE_MONEY', f"Unable to donate {amount}{cur}!")
        return success

    def donate_items(self, citizen_id: int = 1620414, amount: int = 0, industry_id: int = 1, quality: int = 1) -> int:
        if amount < 1:
            return 0
        industry = constants.INDUSTRIES[industry_id]
        self.write_log(f"Donate: {amount:4d}q{quality} {industry} to {citizen_id}")
        response = self._post_economy_donate_items_action(citizen_id, amount, industry_id, quality)
        if re.search(rf"Successfully transferred {amount} item\(s\) to", response.text):
            msg = (f"Successfully donated {amount}q{quality} {industry} "
                   f"to citizen with id {citizen_id}!")
            self._report_action('DONATE_ITEMS', msg)
            return amount
        elif re.search('You must wait 5 seconds before donating again', response.text):
            self.write_log('Previous donation failed! Must wait at least 5 seconds before next donation!')
            self.sleep(5)
            return self.donate_items(citizen_id, int(amount), industry_id, quality)
        else:
            if re.search(r'You do not have enough items in your inventory to make this donation', response.text):
                self._report_action('DONATE_ITEMS',
                                    f"Unable to donate {amount}q{quality} "
                                    f"{industry}, not enough left!")
                return 0
            available = re.search(
                r'Cannot transfer the items because the user has only (\d+) free slots in (his|her) storage.',
                response.text
            ).group(1)
            self._report_action('DONATE_ITEMS',
                                f'Unable to donate {amount}q{quality}{industry}'
                                f', receiver has only {available} storage left!')
            self.sleep(5)
            return self.donate_items(citizen_id, int(available), industry_id, quality)

    def contribute_cc_to_country(self, amount, country: constants.Country) -> bool:
        self.update_money()
        amount = int(amount)
        if self.details.cc < amount or amount < 20:
            return False
        data = dict(country=country.id, action='currency', value=amount)
        r = self._post_main_country_donate(country.id, 'currency', amount)
        if r.json().get('status') or not r.json().get('error'):
            self._report_action('CONTRIBUTE_CC', f'Contributed {amount}cc to {country}\'s treasury', kwargs=data)
            return True
        else:
            self._report_action('CONTRIBUTE_CC', f"Unable to contribute {amount}cc to {country}'s"
                                                 f' treasury', kwargs=r.json())
            return False

    def contribute_food_to_country(self, amount, quality, country: constants.Country) -> bool:
        self.update_inventory()
        amount = amount // 1
        if self.food['q' + str(quality)] < amount or amount < 10:
            return False
        data = dict(country=country.id, action='food', value=amount, quality=quality)
        r = self._post_main_country_donate(country.id, 'currency', amount, quality)

        if r.json().get('status') or not r.json().get('error'):
            self._report_action('CONTRIBUTE_FOOD', f"Contributed {amount}q{quality} food to "
                                                   f"{country}'s treasury", kwargs=data)
            return True
        else:
            self._report_action('CONTRIBUTE_FOOD', f"Unable to contribute {amount}q{quality} food to "
                                                   f"{country}'s treasury", kwargs=r.json())
            return False

    def contribute_gold_to_country(self, amount: int, country: constants.Country) -> bool:
        self.update_money()

        if self.details.cc < amount:
            return False
        data = dict(country=country.id, action='gold', value=amount)
        r = self._post_main_country_donate(country.id, 'gold', amount)

        if r.json().get('status') or not r.json().get('error'):
            self._report_action('CONTRIBUTE_GOLD', f"Contributed {amount}g to {country}'s treasury", kwargs=data)
            return True
        else:
            self._report_action('CONTRIBUTE_GOLD', f"Unable to contribute {amount}g to {country}'s treasury",
                                kwargs=r.json())
            return False

    def report_money_donation(self, citizen_id: int, amount: float, is_currency: bool = True):
        self.reporter.report_money_donation(citizen_id, amount, is_currency)
        if self.config.telegram:
            self.telegram.report_money_donation(citizen_id, amount, is_currency)

    def report_item_donation(self, citizen_id: int, amount: float, quality: int, industry: str):
        self.reporter.report_item_donation(citizen_id, amount, quality, industry)
        if self.config.telegram:
            self.telegram.report_item_donation(citizen_id, amount, f"{industry} q{quality}")


class CitizenLeaderBoard(BaseCitizen):
    def get_aircraft_damage_rankings(self, country: int, weeks: int = 0, mu: int = 0) -> Dict[str, any]:
        return self._get_main_leaderboards_damage_aircraft_rankings(country, weeks, mu).json()

    def get_ground_damage_rankings(self, country: int, weeks: int = 0, mu: int = 0, div: int = 4) -> Dict[str, any]:
        return self._get_main_leaderboards_damage_rankings(country, weeks, mu, div).json()

    def get_aircraft_kill_rankings(self, country: int, weeks: int = 0, mu: int = 0) -> Dict[str, any]:
        return self._get_main_leaderboards_kills_aircraft_rankings(country, weeks, mu).json()

    def get_ground_kill_rankings(self, country: int, weeks: int = 0, mu: int = 0, div: int = 4) -> Dict[str, any]:
        return self._get_main_leaderboards_kills_rankings(country, weeks, mu, div).json()


class CitizenMedia(BaseCitizen):
    def endorse_article(self, article_id: int, amount: int) -> bool:
        if amount in (5, 50, 100):
            resp = self._post_main_donate_article(article_id, amount).json()
            if not bool(resp.get('error')):
                self._report_action('ARTICLE_ENDORSE', f"Endorsed article ({article_id}) with {amount}cc")
                return True
            else:
                self._report_action('ARTICLE_ENDORSE', f"Unable to endorse article ({article_id}) with {amount}cc",
                                    kwargs=resp)
                return False
        else:
            return False

    def vote_article(self, article_id: int) -> bool:
        resp = self._post_main_vote_article(article_id).json()

        if not bool(resp.get('error')):
            self._report_action('ARTICLE_VOTE', f"Voted article {article_id}")
            return True
        else:
            self._report_action('ARTICLE_VOTE', f"Unable to vote for article {article_id}", kwargs=resp)
            return False

    def get_article_comments(self, article_id: int, page_id: int = 1) -> Dict[str, Any]:
        return self._post_main_article_comments(article_id, page_id).json()

    def write_article_comment(self, message: str, article_id: int, parent_id: int = None) -> Response:
        self._report_action('ARTICLE_COMMENT', f"Wrote a comment to article ({article_id})",
                            kwargs=dict(msg=message, article_id=article_id, parent_id=parent_id))
        return self._post_main_article_comments_create(message, article_id, parent_id)

    def publish_article(self, title: str, content: str, kind: int) -> int:
        kinds = {1: 'First steps in eRepublik', 2: 'Battle orders', 3: 'Warfare analysis',
                 4: 'Political debates and analysis', 5: 'Financial business',
                 6: 'Social interactions and entertainment'}
        if kind in kinds:
            data = {'title': title, 'content': content, 'country': self.details.citizenship.id, 'kind': kind}
            resp = self._post_main_write_article(title, content, self.details.citizenship.id, kind)
            try:
                article_id = int(resp.history[1].url.split("/")[-3])
                self._report_action('ARTICLE_PUBLISH', f"Published new article \"{title}\" ({article_id})", kwargs=data)
            except:  # noqa
                article_id = 0
            return article_id
        else:
            kinds = "\n".join([f"{k}: {v}" for k, v in kinds.items()])
            raise classes.ErepublikException(f"Article kind must be one of:\n{kinds}\n'{kind}' is not supported")

    def get_article(self, article_id: int) -> Dict[str, Any]:
        return self._get_main_article_json(article_id).json()

    def delete_article(self, article_id: int) -> NoReturn:
        article_data = self.get_article(article_id)
        if article_data and article_data['articleData']['canDelete']:
            self._report_action('ARTICLE_DELETE',
                                f"Attempting to delete article '{article_data['article']['title']}' (#{article_id})",
                                kwargs=article_data)
            self._get_main_delete_article(article_id)
        else:
            self.write_log(f"Unable to delete article (#{article_id})!")


class CitizenMilitary(CitizenTravel):
    all_battles: Dict[int, classes.Battle] = None
    __last_war_update_data = None

    active_fs: bool = False

    @property
    def as_dict(self):
        d = super().as_dict
        d.update(active_fs=self.active_fs, all_battles=self.all_battles)
        return d

    def update_war_info(self):
        if self.__last_war_update_data and self.__last_war_update_data.get('last_updated',
                                                                           0) + 30 > self.now.timestamp():
            r_json = self.__last_war_update_data
        else:
            r_json = self._get_military_campaigns_json_list().json()
        if r_json.get('countries'):
            if self.all_battles is None:
                self.all_battles = {}
            self.__last_war_update_data = r_json
            if r_json.get('battles'):
                all_battles = {}
                for battle_data in r_json.get('battles', {}).values():
                    all_battles[battle_data.get('id')] = classes.Battle(battle_data)
                # old_all_battles = self.all_battles
                self.all_battles = all_battles
                # for battle in old_all_battles.values():
                #     utils._clear_up_battle_memory(battle)

    def get_battle_for_war(self, war_id: int) -> Optional[classes.Battle]:
        self.update_war_info()
        war_info = self.get_war_status(war_id)
        return self.all_battles.get(war_info.get('battle_id'), None)

    def get_war_status(self, war_id: int) -> Dict[str, Union[bool, Dict[int, str]]]:
        r = self._get_wars_show(war_id)
        html = r.text
        ret = {}
        reg_re = re.compile(fr'data-war-id="{war_id}" data-region-id="(\d+)" data-region-name="([- \w]+)"')
        if reg_re.findall(html):
            ret.update(regions={}, can_attack=True)
            for reg in reg_re.findall(html):
                ret['regions'].update({int(reg[0]): reg[1]})
        elif re.search(r'<a href="//www.erepublik.com/en/military/battlefield/(\d+)" '
                       r'class="join" title="Join"><span>Join</span></a>', html):
            battle_id = re.search(r'<a href="//www.erepublik.com/en/military/battlefield/(\d+)" '
                                  r'class="join" title="Join"><span>Join</span></a>', html).group(1)
            ret.update(can_attack=False, battle_id=int(battle_id))
        elif re.search(r'This war is no longer active.', html):
            ret.update(can_attack=False, ended=True)
        else:
            ret.update(can_attack=False)
        return ret

    def get_available_weapons(self, battle_id: int):
        return self._get_military_show_weapons(battle_id).json()

    def set_default_weapon(self, battle: classes.Battle, division: classes.BattleDivision) -> int:
        available_weapons = self._get_military_show_weapons(battle.id).json()
        while not isinstance(available_weapons, list):
            available_weapons = self._get_military_show_weapons(battle.id).json()
        weapon_quality = -1
        weapon_damage = 0
        if not division.is_air:
            for weapon in available_weapons:
                try:
                    if weapon['weaponQuantity'] > 30 and weapon['weaponInfluence'] > weapon_damage:
                        weapon_quality = int(weapon['weaponId'])
                        weapon_damage = weapon['weaponInfluence']
                except ValueError:
                    pass
        return self.change_weapon(battle, weapon_quality, division)

    def change_weapon(self, battle: classes.Battle, quality: int, battle_zone: classes.BattleDivision) -> int:
        r = self._post_military_change_weapon(battle.id, battle_zone.id, quality)
        influence = r.json().get('weaponInfluence')
        self._report_action('MILITARY_WEAPON', f"Switched to q{quality} weapon,"
                                               f" new influence {influence}", kwargs=r.json())
        return influence

    def sorted_battles(self, sort_by_time: bool = True, only_tp=False) -> List[classes.Battle]:
        cs_battles_priority_air: List[classes.Battle] = []
        cs_battles_priority_ground: List[classes.Battle] = []
        cs_battles_air: List[classes.Battle] = []
        cs_battles_ground: List[classes.Battle] = []
        deployed_battles_air: List[classes.Battle] = []
        deployed_battles_ground: List[classes.Battle] = []
        ally_battles_air: List[classes.Battle] = []
        ally_battles_ground: List[classes.Battle] = []
        other_battles_air: List[classes.Battle] = []
        other_battles_ground: List[classes.Battle] = []

        ret_battles: List[classes.Battle] = []
        if sort_by_time:
            battle_list = sorted(self.all_battles.values(), key=lambda b: b.start)
            battle_list.reverse()
        else:
            battle_list = sorted(self.all_battles.values(), key=lambda b: b.id)

        contribution_json = self._get_military_campaigns_json_citizen().json()
        contributions: List[Dict[str, int]] = contribution_json.get('contributions') or []
        contributions.sort(key=lambda b: -b.get('damage'))

        for contribution_battle in contributions:
            if contribution_battle.get('battle_id') and contribution_battle.get('battle_id') in self.all_battles:
                ret_battles.append(self.all_battles[contribution_battle.get('battle_id')])

        for battle in battle_list:
            battle_sides = [battle.invader.country, battle.defender.country]
            if battle.id in ret_battles:
                continue
            # CS Battles
            elif self.details.citizenship in battle_sides:
                if battle.has_air:
                    if battle.defender.id == self.details.citizenship:
                        cs_battles_priority_air.append(battle)
                    else:
                        cs_battles_air.append(battle)
                else:
                    if battle.defender.id == self.details.citizenship:
                        cs_battles_priority_ground.append(battle)
                    else:
                        cs_battles_ground.append(battle)

            # Current location battles:
            elif self.details.current_country in battle_sides:
                if battle.has_air:
                    deployed_battles_air.append(battle)
                else:
                    deployed_battles_ground.append(battle)

            # Deployed battles and allied battles:
            elif self.details.current_country in battle.invader.allies + battle.defender.allies + battle_sides:
                if self.details.current_country in battle.invader.deployed + battle.defender.deployed:
                    if battle.has_air:
                        deployed_battles_air.append(battle)
                    else:
                        deployed_battles_ground.append(battle)
                # Allied battles:
                else:
                    if battle.has_air:
                        ally_battles_air.append(battle)
                    else:
                        ally_battles_ground.append(battle)
            else:
                if battle.has_air:
                    other_battles_air.append(battle)
                else:
                    other_battles_ground.append(battle)

        cs_battles = cs_battles_priority_air + cs_battles_priority_ground + cs_battles_air + cs_battles_ground
        if only_tp:
            return cs_battles
        deployed_battles = deployed_battles_air + deployed_battles_ground
        other_battles = ally_battles_air + ally_battles_ground + other_battles_air + other_battles_ground
        ret_battles = ret_battles + cs_battles + deployed_battles + other_battles
        return ret_battles

    def get_cheap_tp_divisions(self) -> Dict[str, List[Tuple[int, classes.BattleDivision]]]:
        air_divs: List[Tuple[int, classes.BattleDivision]] = []
        ground_divs: List[Tuple[int, classes.BattleDivision]] = []
        check_maverick = self.maverick and self.config.maverick
        for battle in reversed(self.sorted_battles(True, True)):
            for division in battle.div.values():
                is_start_ok = utils.good_timedelta(division.battle.start, timedelta(minutes=-1)) < self.now
                if not division.terrain and is_start_ok and not division.div_end:
                    if division.is_air and self.config.air:
                        division_medals = self.get_battle_round_data(division)
                        medal = division_medals[self.details.citizenship == division.battle.defender.country]
                        if not medal:
                            air_divs.append((0, division))
                        else:
                            air_divs.append((medal.get('1').get('raw_value'), division))
                    elif not division.is_air and self.config.ground:
                        if not division.div == self.division and not check_maverick:
                            continue
                        division_medals = self.get_battle_round_data(division)
                        medal = division_medals[self.details.citizenship == division.battle.defender.country]
                        if not medal:
                            ground_divs.append((0, division))
                        else:
                            ground_divs.append((medal.get('1').get('raw_value'), division))

        air_divs.sort(key=lambda z: (z[0], z[1].battle.start))
        ground_divs.sort(key=lambda z: (z[0], z[1].battle.start))
        return {'air': air_divs, 'ground': ground_divs}

    @property
    def has_battle_contribution(self):
        return bool(self.__last_war_update_data.get('citizen_contribution', []))

    def find_battle_to_fight(self, silent: bool = False) -> Tuple[
        classes.Battle, classes.BattleDivision, classes.BattleSide
    ]:
        self.update_war_info()
        for battle in self.sorted_battles(self.config.sort_battles_time):
            if not isinstance(battle, classes.Battle):
                continue
            if battle.is_dict_lib:
                continue
            battle_zone: Optional[classes.BattleDivision] = None
            for div in battle.div.values():
                if div.terrain == 0:
                    if div.div_end:
                        continue
                    maverick_ok = self.maverick and self.config.maverick
                    if self.config.air and div.is_air:
                        battle_zone = div
                        break
                    elif self.config.ground and not div.is_air and (div.div == self.division or maverick_ok):
                        battle_zone = div
                        break
                    else:
                        continue
            if not battle_zone:
                continue
            allies = battle.invader.deployed + battle.defender.deployed + [battle.invader.country,
                                                                           battle.defender.country]

            travel_needed = self.details.current_country not in allies

            if battle.is_rw:
                side = battle.defender if self.config.rw_def_side else battle.invader
            else:
                defender_side = self.details.current_country in battle.defender.allies + [battle.defender.country, ]
                side = battle.defender if defender_side else battle.invader

            if not silent:
                self.write_log(battle)

            travel = (self.config.travel_to_fight and self.should_travel_to_fight() or self.config.force_travel) \
                if travel_needed else True

            if not travel:
                continue
            yield battle, battle_zone, side

    def find_battle_and_fight(self):
        count = self.should_fight()[0]
        if count:
            self.write_log('Checking for battles to fight in...')
            for battle, division, side in self.find_battle_to_fight():

                allies = battle.invader.deployed + battle.defender.deployed + [battle.invader.country,
                                                                               battle.defender.country]

                travel_needed = self.details.current_country not in allies

                if battle.start > self.now:
                    self.sleep(utils.get_sleep_seconds(battle.start))

                if travel_needed:
                    if battle.is_rw:
                        countries_to_travel = [battle.defender.country]
                    elif self.details.current_country in battle.invader.allies:
                        countries_to_travel = battle.invader.deployed + [battle.invader.country]
                        side = battle.invader
                    else:
                        countries_to_travel = battle.defender.deployed + [battle.defender.country]
                        side = battle.defender

                    if not self.travel_to_battle(battle, countries_to_travel):
                        break

                if self.change_division(battle, division):
                    self.set_default_weapon(battle, division)
                    self.fight(battle, division, side, count)
                    self.travel_to_residence()
                    break

    def fight(self, battle: classes.Battle, division: classes.BattleDivision, side: classes.BattleSide = None,
              count: int = None, use_ebs: bool = False) -> Optional[int]:
        """Fight in a battle.

        Will auto activate booster and travel if allowed to do it.
        :param battle: Battle battle to fight in
        :type battle: Battle
        :param division: Division number to fight in available choices
        :type division: BattleDivision
        :param side: BattleSide or None. Battle side to fight in, If side not == invader id or not in invader deployed
        allies list, then defender's side is chosen
        :type side: BattleSide
        :param count: How many hits to do, if not specified self.should_fight() is called.
        :type count: int
        :param use_ebs: Should use energy bars if count > 0 and not enough food_fights
        :type use_ebs: bool
        :return: None if no errors while fighting, otherwise error count.
        :rtype: int
        """
        if self.restricted_ip:
            self._report_action('IP_BLACKLISTED', 'Fighting is not allowed from restricted IP!')
            return 1
        if not division.is_air and self.config.boosters:
            self.activate_damage_booster(not division.is_air)
        if side is None:
            side = battle.defender if self.details.citizenship in battle.defender.allies + [
                battle.defender.country] else battle.invader
        error_count = 0
        ok_to_fight = True
        if count is None:
            count = self.should_fight()[0]

        self.write_log(f"Fighting in battle for {battle.region_name} on {side} side\n{battle}\n{str(division)}")

        total_damage = 0
        total_hits = 0
        while ok_to_fight and error_count < 10 and count > 0:
            while all((count > 0, error_count < 10, self.energy.recovered >= 50)):
                hits, error, damage = self._shoot(battle, division, side)
                count -= hits
                total_hits += hits
                total_damage += damage
                error_count += error
            else:
                self._eat('blue')
                if count > 0 and self.energy.recovered < 50 and use_ebs:
                    self._eat('orange')
                if self.energy.recovered < 50 or error_count >= 10 or count <= 0:
                    self.write_log(f"Hits: {total_hits:>4} | Damage: {total_damage}")
                    ok_to_fight = False
                    if total_damage:
                        self.report_fighting(battle, not side.is_defender, division, total_damage, total_hits)
        return error_count

    def _shoot(self, battle: classes.Battle, division: classes.BattleDivision, side: classes.BattleSide):
        if division.is_air:
            response = self._post_military_fight_air(battle.id, side.id, division.id)
        else:
            response = self._post_military_fight_ground(battle.id, side.id, division.id)

        if 'Zone is not meant for ' in response.text:
            self.sleep(5)
            return 0, 1, 0
        try:
            r_json = response.json()
        except (ValueError, HTTPError, RequestException):
            return 0, 10, 0
        hits = 0
        damage = 0
        err = False
        if r_json.get('error'):
            if r_json.get('message') == 'SHOOT_LOCKOUT':
                pass
            elif r_json.get('message') == 'NOT_ENOUGH_WEAPONS':
                self.set_default_weapon(battle, division)
            elif r_json.get('message') == "Cannot activate a zone with a non-native division":
                self.write_log('Wrong division!!')
                return 0, 10, 0
            elif r_json.get('message') == 'ZONE_INACTIVE':
                self.write_log('Wrong division!!')
                return 0, 10, 0
            elif r_json.get('message') == 'NON_BELLIGERENT':
                self.write_log("Dictatorship/Liberation wars are not supported!")
                return 0, 10, 0
            elif r_json.get('message') in ['FIGHT_DISABLED', 'DEPLOYMENT_MODE']:
                self._post_main_profile_update('options',
                                               params='{"optionName":"enable_web_deploy","optionValue":"off"}')
                self.set_default_weapon(battle, division)
            else:
                if r_json.get('message') == 'UNKNOWN_SIDE':
                    self._rw_choose_side(battle, side)
                elif r_json.get('message') == 'CHANGE_LOCATION':
                    countries = [side.country] + side.deployed
                    self.travel_to_battle(battle, countries)
                err = True
        elif r_json.get('message') == 'ENEMY_KILLED':
            # Non-InfantryKit players
            if r_json['user']['earnedXp']:
                hits = r_json['user']['earnedXp']
            # InfantryKit player
            # The almost always safe way (breaks on levelup hit)
            elif self.energy.recovered >= r_json['details']['wellness']:  # Haven't reached levelup
                hits = (self.energy.recovered - r_json['details']['wellness']) // 10
            else:
                hits = r_json['hits']
                if r_json['user']['epicBattle']:
                    hits /= 1 + r_json['user']['epicBattle']

            self.energy.recovered = r_json['details']['wellness']
            self.details.xp = int(r_json['details']['points'])
            damage = r_json['user']['givenDamage'] * (1.1 if r_json['oldEnemy']['isNatural'] else 1)
        else:
            err = True

        return hits, err, damage

    def deploy_bomb(self, battle: classes.Battle, division: classes.BattleDivision, bomb_id: int, inv_side: bool,
                    count: int = 1) -> Optional[int]:
        """Deploy bombs in a battle for given side.

        :param battle: Battle
        :type battle: classes.Battle
        :param division: BattleDivision
        :type division: classes.BattleDivision
        :param bomb_id: int bomb id
        :type bomb_id: int
        :param inv_side: should deploy on invader side
        :type inv_side: bool
        :param count: how many bombs to deploy
        :type count: int
        :return: Deployed count
        :rtype: int
        """

        if not isinstance(count, int) or count < 1:
            count = 1
        has_traveled = False
        if battle.is_rw:
            has_traveled = self.travel_to_battle(battle, [battle.defender.country])
            self._rw_choose_side(battle, battle.invader if inv_side else battle.defender)
        if inv_side:
            good_countries = [battle.invader.country] + battle.invader.deployed
            if self.details.current_country not in good_countries:
                has_traveled = self.travel_to_battle(battle, good_countries)
        else:
            involved = [battle.invader.country,
                        battle.defender.country] + battle.invader.deployed + battle.defender.deployed
            if self.details.current_country not in involved:
                count = 0
        side = battle.invader if inv_side else battle.defender
        errors = deployed_count = 0
        while (not deployed_count == count) and errors < 10:
            r = self._post_military_deploy_bomb(battle.id, division.id, side.id, bomb_id).json()
            if not r.get('error'):
                deployed_count += 1
                self.sleep(0.5)
            elif r.get('message') == 'LOCKED':
                self.sleep(0.5)
            elif r.get('message') == 'INVALID_BOMB':
                errors = 10
            else:
                errors += 1

        if has_traveled:
            self.travel_to_residence()

        self._report_action('MILITARY_BOMB', f"Deployed {deployed_count} bombs in battle {battle.id}")
        return deployed_count

    def change_division(self, battle: classes.Battle, division: classes.BattleDivision) -> bool:
        """Change division.

        :param battle: Battle
        :type battle: Battle
        :param division: int target division to switch to
        :type division: BattleDivision
        :return:
        """
        resp = self._post_main_battlefield_change_division(battle.id, division.id)
        if resp.json().get('error'):
            self.write_log(resp.json().get('message'))
            return False
        self._report_action('MILITARY_DIV_SWITCH', f"Switched to d{division.div} in battle {battle.id}",
                            kwargs=resp.json())
        return True

    def get_ground_hit_dmg_value(self, rang: int = None, strength: float = None, elite: bool = None, ne: bool = False,
                                 booster_50: bool = False, booster_100: bool = False, tp: bool = True) -> Decimal:
        if not rang or not strength or elite is None:
            r = self._get_main_citizen_profile_json(self.details.citizen_id).json()
            if not rang:
                rang = r['military']['militaryData']['ground']['rankNumber']
            if not strength:
                strength = r['military']['militaryData']['ground']['strength']
            if elite is None:
                elite = r['citizenAttributes']['level'] > 100
        if ne:
            tp = True

        return utils.calculate_hit(strength, rang, tp, elite, ne, 50 if booster_50 else 100 if booster_100 else 0)

    def get_air_hit_dmg_value(self, rang: int = None, elite: bool = None, ne: bool = False,
                              weapon: bool = False) -> Decimal:
        if not rang or elite is None:
            r = self._get_main_citizen_profile_json(self.details.citizen_id).json()
            if not rang:
                rang = r['military']['militaryData']['aircraft']['rankNumber']
            if elite is None:
                elite = r['citizenAttributes']['level'] > 100

        return utils.calculate_hit(0, rang, True, elite, ne, 0, 20 if weapon else 0)

    def activate_damage_booster(self, ground: bool = True) -> int:
        kind = 'damage' if ground else 'aircraftDamage'
        if self.config.boosters and not self.get_active_damage_booster(ground):
            booster: Optional[types.InvFinalItem] = None
            for quality, data in sorted(self.inventory.boosters.get(kind, {}).items(), key=lambda x: x[0]):
                for _duration, _booster in sorted(data.items(), key=lambda y: y[0]):
                    critical_amount = 2 if quality < 10 and ground else 10
                    if _booster.get('amount') > critical_amount:
                        booster = _booster
                        break
                break
            if booster:
                kind = 'damage' if ground else 'air_damage'
                self._report_action('MILITARY_BOOSTER', f"Activated {booster['name']}")
                resp = self._post_economy_activate_booster(booster['quality'], booster['durability'], kind).json()
                self._update_inventory_data(resp)
        return self.get_active_damage_booster(ground)

    def get_active_damage_booster(self, ground: bool = True) -> int:
        kind = 'damage' if ground else 'aircraftDamage'
        boosters = self.inventory.active.get(kind, {})
        quality = 0
        for q, boost in boosters.items():
            if boost['quality'] * 10 > quality:
                quality = boost['quality'] * 10
        return quality

    def get_active_ground_damage_booster(self) -> int:
        return self.get_active_damage_booster(True)

    def get_active_air_damage_booster(self) -> int:
        return self.get_active_damage_booster(False)

    def activate_battle_effect(self, battle_id: int, kind: str) -> bool:
        self._report_action('MILITARY_BOOSTER', f'Activated {kind} booster')
        resp = self._post_main_activate_battle_effect(battle_id, kind, self.details.citizen_id).json()
        return not resp.get('error')

    def activate_pp_booster(self, pp_item: types.InvFinalItem) -> bool:
        self._report_action('MILITARY_BOOSTER', f'Activated {pp_item["name"]}')
        resp = self._post_economy_activate_booster(pp_item['quality'], pp_item['durability'], 'prestige_points').json()
        self._update_inventory_data(resp)
        return pp_item.get('kind') in self.inventory.active

    def _rw_choose_side(self, battle: classes.Battle, side: classes.BattleSide) -> Response:
        return self._post_main_battlefield_travel(side.id, battle.id)

    def should_travel_to_fight(self) -> bool:
        ret = False
        if self.config.always_travel:
            ret = True
        elif self.should_do_levelup:  # Do levelup
            ret = True
        # Get to next Energy +1
        elif self.next_reachable_energy and self.config.next_energy:
            ret = True
        # 1h worth of energy
        elif self.energy.available + self.energy.interval * 3 >= self.energy.limit * 2:
            ret = True
        return ret

    def should_fight(self) -> Tuple[int, str, bool]:
        """ Checks if citizen should fight at this moment
        :rtype: Tuple[int, str, bool]
        """
        count = 0
        force_fight = False
        msg = 'Fighting not allowed!'
        if not self.config.fight:
            return count, msg, force_fight

        # Do levelup
        if self.is_levelup_reachable:
            msg = 'Level up'
            if self.should_do_levelup:
                count = (self.energy.limit * 3) // 10
                force_fight = True
            else:
                self.write_log('Waiting for fully recovered energy before leveling up.', False)

        # Levelup reachable
        elif self.is_levelup_close:
            count = self.details.xp_till_level_up - (self.energy.limit // 10) + 5
            msg = "Fighting for close Levelup. Doing %i hits" % count
            force_fight = True

        elif self.details.pp < 75:
            count = 75 - self.details.pp
            msg = 'Obligatory fighting for at least 75pp'
            force_fight = True

        elif self.config.continuous_fighting and self.has_battle_contribution:
            count = self.energy.food_fights
            msg = 'Continuing to fight in previous battle'

        # All-in (type = all-in and full ff)
        elif self.config.all_in and self.energy.available + self.energy.interval * 3 >= self.energy.limit * 2:
            count = self.energy.food_fights
            msg = "Fighting all-in. Doing %i hits" % count

        # Get to next Energy +1
        elif self.config.next_energy and self.next_reachable_energy:
            count = self.next_reachable_energy
            msg = "Fighting for +1 energy. Doing %i hits" % count

        # 1h worth of energy
        elif self.energy.available + self.energy.interval * 3 >= self.energy.limit * 2:
            count = self.energy.interval
            msg = "Fighting for 1h energy. Doing %i hits" % count
            force_fight = True

        return (count if count > 0 else 0), msg, force_fight

    def get_battle_round_data(self, division: classes.BattleDivision) -> Tuple[Any, Any]:
        battle = division.battle

        r = self._post_military_battle_console(battle.id, 'battleStatistics', 1,
                                               zoneId=battle.zone_id, round_id=battle.zone_id, division=division.div,
                                               battleZoneId=division.id, type='damage')
        r_json = r.json()
        return (r_json.get(str(battle.invader.id)).get('fighterData'),
                r_json.get(str(battle.defender.id)).get('fighterData'))

    def get_battle_division_stats(self, division: classes.BattleDivision) -> Dict[str, Any]:
        battle = division.battle
        r = self._get_military_battle_stats(battle.id, division.div, division.id)
        return r.json()

    def get_division_max_hit(self, division: classes.BattleDivision) -> int:
        """ Returns max hit in division for current side (if not on either side returns 0)

        :param division: BattleDivision for which to get max hit value
        :type division: classes.BattleDivision
        :return: max hit value
        :rtype: int
        """
        return self.get_battle_division_stats(division).get('maxHit', -1)

    def schedule_attack(self, war_id: int, region_id: int, region_name: str, at_time: datetime):
        if at_time:
            self.sleep(utils.get_sleep_seconds(at_time))
        self.get_csrf_token()
        self.launch_attack(war_id, region_id, region_name)

    def get_active_wars(self, country: constants.Country = None) -> List[int]:
        r = self._get_country_military(country.link if country else self.details.citizenship.link)
        all_war_ids = re.findall(r'//www\.erepublik\.com/en/wars/show/(\d+)"', r.text)
        return [int(wid) for wid in all_war_ids]

    def get_last_battle_of_war_end_time(self, war_id: int) -> datetime:
        r = self._get_wars_show(war_id)
        html = r.text
        last_battle_id = int(re.search(r'<a href="//www.erepublik.com/en/military/battlefield/(\d+)">', html).group(1))
        console = self._post_military_battle_console(last_battle_id, 'warList', 1).json()
        battle = console.get('list')[0]
        return utils.localize_dt(datetime.strptime(battle.get('result').get('end'), "%Y-%m-%d %H:%M:%S"))

    def launch_attack(self, war_id: int, region_id: int, region_name: str):
        self._post_wars_attack_region(war_id, region_id, region_name)
        self._report_action('MILITARY_QUEUE_ATTACK', f"Battle for *{region_name}* queued")

    def get_country_mus(self, country: constants.Country) -> Dict[int, str]:
        ret = {}
        r = self._get_main_leaderboards_damage_rankings(country.id)
        for data in r.json()['mu_filter']:
            if data['id']:
                ret.update({data['id']: data['name']})
        r = self._get_main_leaderboards_damage_aircraft_rankings(country.id)
        for data in r.json()['mu_filter']:
            if data['id']:
                ret.update({data['id']: data['name']})
        return ret

    def get_mu_members(self, mu_id: int) -> Dict[int, str]:
        ret = {}
        r = self._get_military_unit_data(mu_id)

        for page in range(int(r.json()['panelContents']['pages'])):
            r = self._get_military_unit_data(mu_id, currentPage=page + 1)
            for user in r.json()['panelContents']['members']:
                if not user['isDead']:
                    ret.update({user['citizenId']: user['name']})
        return ret

    def get_citizen_weekly_daily_orders_done(self, citizen_id: int = None, weeks_ago: int = 0) -> int:
        if citizen_id is None:
            citizen_id = self.details.citizen_id
        profile = self._get_main_citizen_profile_json(citizen_id).json()
        mu_id = profile.get('military', {}).get('militaryUnit', {}).get('id', 0)
        if mu_id:
            name = profile.get('citizen', {}).get('name')
            member = self._get_military_unit_data(mu_id, currentPage=1, panel='members', sortBy='dailyOrdersCompleted',
                                                  weekFilter=f"week{weeks_ago}", search=name).json()
            return member.get('panelContents', {}).get('members', [{}])[0].get('dailyOrdersCompleted')
        return 0

    def get_possibly_empty_medals(self):
        self.update_war_info()
        for battle in self.all_battles.values():
            for division in battle.div.values():
                if division.wall['dom'] == 50 or division.wall['dom'] > 98:
                    yield division, division.wall['for'] == battle.invader.country.id

    def report_fighting(self, battle: classes.Battle, invader: bool, division: classes.BattleDivision, damage: float, hits: int):
        self.reporter.report_fighting(battle, invader, division, damage, hits)
        if self.config.telegram:
            self.telegram.report_fight(battle, invader, division, damage, hits)


class CitizenPolitics(BaseCitizen):
    def get_country_parties(self, country: constants.Country = None) -> dict:
        r = self._get_main_rankings_parties(country.id if country else self.details.citizenship.id)
        ret = {}
        for name, id_ in re.findall(r'<a class="dotted" title="([^"]+)" href="/en/party/[\w\d-]+-(\d+)/1">', r.text):
            ret.update({int(id_): name})
        return ret

    def candidate_for_party_presidency(self) -> Optional[Response]:
        if self.politics.is_party_member:
            self._report_action('POLITIC_PARTY_PRESIDENT', 'Applied for party president elections')
            return self._get_candidate_party(self.politics.party_slug)
        else:
            self._report_action('POLITIC_CONGRESS',
                                'Unable to apply for party president elections - not a party member')
            return None

    def candidate_for_congress(self, presentation: str = "") -> Optional[Response]:
        if self.politics.is_party_member:
            self._report_action('POLITIC_CONGRESS', 'Applied for congress elections')
            return self._post_candidate_for_congress(presentation)
        else:
            self._report_action('POLITIC_CONGRESS', 'Unable to apply for congress elections - not a party member')
            return None

    def get_country_president_election_result(
        self, country: constants.Country, year: int, month: int
    ) -> Dict[str, int]:
        timestamp = int(constants.erep_tz.localize(datetime(year, month, 5)).timestamp())
        resp = self._get_presidential_elections(country.id, timestamp)
        candidates = re.findall(r'class="candidate_info">(.*?)</li>', resp.text, re.S | re.M)
        ret = {}
        for candidate in candidates:
            name = re.search(r'<a hovercard=1 class="candidate_name" href="//www.erepublik.com/en/citizen/profile/\d+"'
                             r' title="(.*)">', candidate)
            name = name.group(1)
            votes = re.search(r'<span class="votes">(\d+) votes</span>', candidate).group(1)
            ret.update({name: int(votes)})
        return ret


class CitizenSocial(BaseCitizen):
    def send_mail(self, subject: str, msg: str, ids: List[int]):
        for player_id in ids:
            self._report_action('SOCIAL_MESSAGE', f'Sent a message to {player_id}',
                                kwargs=dict(subject=subject, msg=msg, id=player_id))
            self._post_main_messages_compose(subject, msg, [player_id])

    def write_on_country_wall(self, message: str) -> bool:
        self._get_main()
        post_to_wall_as = re.findall(r'id="post_to_country_as".*?<option value="(\d?)">.*?</option>.*</select>',
                                     self.r.text, re.S | re.M)
        r = self._post_main_country_post_create(message, max(post_to_wall_as, key=int) if post_to_wall_as else 0)

        self._report_action('SOCIAL_WRITE_WALL_COUNTRY', 'Wrote a message to the country wall')
        return r.json()

    def add_friend(self, player_id: int) -> Response:
        resp = self._get_main_citizen_hovercard(player_id)
        r_json = resp.json()
        if not any([r_json['isBanned'], r_json['isDead'], r_json['isFriend'], r_json['isOrg'], r_json['isSelf']]):
            r = self._post_main_citizen_add_remove_friend(int(player_id), True)
            self.write_log(f"{r_json['name']:<64} (id:{player_id:>11}) added as friend")
            self._report_action('SOCIAL_ADD_FRIEND', f"{r_json['name']:<64} (id:{player_id:>11}) added as friend")
            return r
        return resp

    def add_every_player_as_friend(self):
        cities = []
        cities_dict = {}
        self.write_log('WARNING! This will take a lot of time.')
        rj = self._post_main_travel_data(regionId=662, check='getCountryRegions').json()
        for region_data in rj.get('regions', {}).values():
            cities.append(region_data['cityId'])
            cities_dict.update({region_data['cityId']: region_data['cityName']})

        cities.sort(key=int)
        for city_id in cities:
            self.write_log(f"Adding friends from {cities_dict[city_id]} (id: {city_id})")
            resp = self._get_main_city_data_residents(city_id).json()
            for resident in resp['widgets']['residents']['residents']:
                self.add_friend(resident['citizenId'])
            for page in range(2, resp['widgets']['residents']['numResults'] // 10 + 2):
                r = self._get_main_city_data_residents(city_id, page)
                resp = r.json()
                for resident in resp['widgets']['residents']['residents']:
                    self.add_friend(resident['citizenId'])

    def get_community_notifications(self, page: int = 1) -> List[Dict[str, Any]]:
        return self._get_main_notifications_ajax_community(page).json().get('alertsList', [])

    def get_system_notifications(self, page: int = 1) -> List[Dict[str, Any]]:
        return self._get_main_notifications_ajax_system(page).json().get('alertsList', [])

    def get_report_notifications(self, page: int = 1) -> List[Dict[str, Any]]:
        return self._get_main_notifications_ajax_report(page).json().get('alertsList', [])

    def delete_community_notification(self, *notification_ids: int):
        ids = []
        for _id in sorted(notification_ids):
            ids.append(int(_id))
        self._post_main_notifications_ajax_community(ids)

    def delete_system_notification(self, *notification_ids: int):
        ids = []
        for _id in sorted(notification_ids):
            ids.append(int(_id))
        self._post_main_notifications_ajax_system(ids)

    def delete_report_notification(self, *notification_ids: int):
        ids = []
        for _id in sorted(notification_ids):
            ids.append(int(_id))
        self._post_main_notifications_ajax_report(ids)

    def get_all_notifications(self, page: int = 1) -> Dict[str, List[Dict[str, Any]]]:
        return dict(community=self.get_community_notifications(),
                    system=self.get_system_notifications(page),
                    report=self.get_report_notifications(page))

    def delete_all_notifications(self):
        for kind, notifications in self.get_all_notifications():
            if notifications:
                if kind == 'community':
                    self.delete_community_notification(*[n['id'] for n in notifications])
                elif kind == 'report':
                    self.delete_report_notification(*[n['id'] for n in notifications])
                elif kind == 'system':
                    self.delete_system_notification(*[n['id'] for n in notifications])
                else:
                    self.report_error(f'Unsupported notification kind: "{kind}"!')

    def get_citizen_profile(self, player_id: int = None):
        if player_id is None:
            player_id = self.details.citizen_id
        return self._get_main_citizen_profile_json(player_id).json()

    def get_citizen_residency_data(self, citizen_id: int = None) -> Optional[Dict[str, Any]]:
        if citizen_id is None:
            citizen_id = self.details.citizen_id
        profile = self.get_citizen_profile(citizen_id)
        name = profile.get('citizen', {}).get('name', '')
        city_id = profile.get('citizen', {}).get('residenceCityId')
        if city_id:
            return self._get_main_city_data_residents(city_id, params={'search': name}).json()


class CitizenTasks(CitizenEconomy):
    tg_contract: dict = {}
    ot_points: int = 0
    next_ot_time: datetime = None

    @property
    def as_dict(self):
        d = super().as_dict
        d.update(tg_contract=self.tg_contract, ot_points=self.ot_points, next_ot_time=self.next_ot_time)
        return d

    def eat(self):
        """ Eat food """
        self._eat('blue')

    def work(self):
        if self.energy.food_fights >= 1:
            response = self._post_economy_work('work')
            js = response.json()
            good_msg = ['already_worked', 'captcha']
            if not js.get('status') and not js.get('message') in good_msg:
                if js.get('message') in ['employee', 'money']:
                    self.resign_from_employer()
                    self.find_new_job()
                elif js.get('message') in ['not_enough_health_food']:
                    self.buy_food(120)
                self.update_citizen_info()
                self.work()
            else:
                self.reporter.report_action('WORK', json_val=js)
        else:
            self._eat('blue')
            if self.energy.food_fights < 1:
                seconds = (self.energy.reference_time - self.now).total_seconds()
                self.write_log(f"I don't have energy to work. Will sleep for {seconds}s")
                self.sleep(seconds)
                self._eat('blue')
            self.work()

    def train(self):
        r = self._get_main_training_grounds_json()
        tg_json = r.json()
        self.details.gold = tg_json['page_details']['gold']
        self.tg_contract.update(free_train=tg_json['hasFreeTrain'])
        if tg_json['contracts']:
            self.tg_contract.update(**tg_json['contracts'][0])

        tgs = []
        for data in sorted(tg_json['grounds'], key=lambda k: k['cost']):
            if data['default'] and not data['trained']:
                tgs.append(data['id'])
        if tgs:
            if self.energy.food_fights >= len(tgs):
                response = self._post_economy_train(tgs)
                if not response.json().get('status'):
                    self.update_citizen_info()
                    self.train()
                else:
                    self.reporter.report_action('TRAIN', response.json())
            else:
                self._eat('blue')
                if self.energy.food_fights < len(tgs):
                    large = max(self.energy.reference_time, self.now)
                    sleep_seconds = utils.get_sleep_seconds(large)
                    self.write_log(f"I don't have energy to train. Will sleep for {sleep_seconds} seconds")
                    self.sleep(sleep_seconds)
                    self._eat('blue')
                self.train()

    def work_ot(self):
        # I"m not checking for 1h cooldown. Beware of nightshift work, if calling more than once every 60min
        self.update_job_info()
        if self.ot_points >= 24 and self.energy.food_fights > 1:
            r = self._post_economy_work_overtime()
            if not r.json().get('status') and r.json().get('message') == 'money':
                self.resign_from_employer()
                self.find_new_job()
            else:
                if r.json().get('message') == 'employee':
                    self.find_new_job()
                elif r.json().get('message') == 'not_enough_health_food':
                    self.buy_food(120)
                self.reporter.report_action('WORK_OT', r.json())
        elif self.energy.food_fights < 1 and self.ot_points >= 24:
            self._eat('blue')
            if self.energy.food_fights < 1:
                large = max(self.energy.reference_time, self.now)
                sleep_seconds = utils.get_sleep_seconds(large)
                self.write_log(f"I don't have energy to work OT. Will sleep for {sleep_seconds}s")
                self.sleep(sleep_seconds)
                self._eat('blue')
            self.work_ot()

    def resign_from_employer(self) -> bool:
        r = self._get_main_job_data()
        if r.json().get('isEmployee'):
            self._report_action('ECONOMY_RESIGN', 'Resigned from employer!', kwargs=r.json())
            self._post_economy_resign()
            return True
        return False

    def buy_tg_contract(self) -> Response:
        ret = self._post_main_buy_gold_items('gold', 'TrainingContract2', 1)
        try:
            extra = ret.json()
        except:  # noqa
            extra = {}
        self._report_action('ECONOMY_TG_CONTRACT', 'Bought TG Contract', kwargs=extra)
        return ret

    def find_new_job(self) -> bool:
        r = self._get_economy_job_market_json(self.details.current_country.id)
        jobs = r.json().get('jobs')
        data = dict(citizen_id=0, salary=10)
        for posting in jobs:
            salary = posting.get('salary')
            limit = posting.get('salaryLimit', 0)
            citizen_id = posting.get('citizen').get('id')

            if (not limit or salary * 3 < limit) and salary > data['salary']:
                data.update(citizen_id=citizen_id, salary=salary)

        return self.apply_to_employer(data['citizen_id'], data['salary'])

    def apply_to_employer(self, employer_id: int, salary: float) -> bool:
        data = dict(citizenId=employer_id, salary=salary)
        self._report_action('ECONOMY_APPLY_FOR_JOB', f"I'm working now for #{employer_id}", kwargs=data)
        r = self._post_economy_job_market_apply(employer_id, salary)
        return bool(r.json().get('status'))

    def update_job_info(self):
        resp = self._get_main_job_data()
        ot = resp.json().get('overTime', {})
        if ot:
            self.next_ot_time = utils.localize_timestamp(int(ot.get('nextOverTime', 0)))
            self.ot_points = ot.get('points', 0)


class _Citizen(CitizenAnniversary, CitizenCompanies, CitizenLeaderBoard,
               CitizenMedia, CitizenPolitics, CitizenSocial, CitizenMilitary, CitizenTasks):
    def __init__(self, email: str = "", password: str = "", auto_login: bool = False):
        super().__init__(email, password)
        self._last_full_update = constants.min_datetime
        self.set_debug(True)
        if auto_login:
            self.login()

    @classmethod
    def load_from_dump(cls, dump_name: str = ""):
        filename = dump_name if dump_name else f"{cls.__name__}__dump.json"
        player: _Citizen = super().load_from_dump(filename)  # noqa
        player.login()
        return player

    def _eat(self, colour: str = 'blue') -> Response:
        resp = super()._eat(colour)
        if not any([resp.json().get('units_consumed').values()]):
            if colour == 'orange' and resp.json().get('food_remaining'):
                self.eat()
            return self._eat(colour)
        return resp

    def config_setup(self, **kwargs):
        self.config.reset()
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
            else:
                self.write_log(f"Unknown config parameter! ({key}={value})")

    def login(self):
        self.get_csrf_token()

        self.update_citizen_info()
        self.reporter.do_init()
        if self.config.telegram and self.config.telegram_chat_id:
            self.telegram.do_init(self.config.telegram_chat_id,
                                  self.config.telegram_token,
                                  self.name)
            self.telegram.send_message(f"*Started* {utils.now():%F %T}")

        self.update_all(True)

    def update_citizen_info(self, html: str = None):
        """
        Gets main page and updates most information about player
        """
        if html is None:
            self._get_main()
            return
        super().update_citizen_info(html)

        if self.promos.get('trainingContract'):
            if not self.tg_contract:
                self.train()
            if not self.tg_contract['free_train'] and self.tg_contract.get('active', False):
                if self.details.gold >= 54:
                    self.buy_tg_contract()
                else:
                    self.write_log(f'Training ground contract active but '
                                   f"don't have enough gold ({self.details.gold}g {self.details.cc}cc)")
        if self.energy.is_energy_full and self.config.telegram:
            self.telegram.report_full_energy(self.energy.available, self.energy.limit, self.energy.interval)

    def check_for_notification_medals(self):
        notifications = self._get_main_citizen_daily_assistant().json()
        data: Dict[Tuple[str, Union[float, str]], Dict[str, Union[int, str, float]]] = {}
        for medal in notifications.get('notifications', []):
            if medal.get('details', {}).get('type') == 'citizenAchievement':
                params: dict = medal.get('details', {}).get('achievement')
                about: str = medal.get('body')
                title: str = medal.get('title')
                count: int = medal.get('details', {}).get('achievementAmount', 1)

                award_id: int = medal.get('id')
                if award_id and title and medal.get('details').get('isWallMaterial'):
                    self._post_main_wall_post_automatic(title.lower(), award_id)

                if params.get('ccValue'):
                    reward = params.get('ccValue')
                    currency = 'Currency'
                elif params.get('goldValue'):
                    reward = params.get('goldValue')
                    currency = 'Gold'
                else:
                    reward = params.get('energyValue')
                    currency = 'Energy'

                if (title, reward) not in data:
                    data[(title, reward)] = {'about': about, 'kind': title, 'reward': reward, 'count': count,
                                             'currency': currency, 'params': medal.get('details', {})}
                else:
                    data[(title, reward)]['count'] += count
            self._post_main_global_alerts_close(medal.get('id'))
        if data:
            msgs = [f"{d['count']} x {d['kind']}, totaling {d['count'] * d['reward']} "
                    f"{d['currency']}" for d in data.values()]

            msgs = "\n".join(msgs)
            if self.config.telegram:
                self.telegram.report_medal(msgs, len(data) > 1)
            self.write_log(f"Found awards:\n{msgs}")
            for info in data.values():
                self.reporter.report_action('NEW_MEDAL', info)

    def set_pin(self, pin: str):
        self.details.pin = str(pin[:4])

    def update_all(self, force_update=False):
        # Do full update max every 5 min
        if utils.good_timedelta(self._last_full_update, timedelta(minutes=5)) < self.now or force_update:
            self._last_full_update = self.now
            self.update_citizen_info()
            self.update_war_info()
            self.update_inventory()
            self.update_companies()
            self.update_money()
            self.update_weekly_challenge()
            self.send_state_update()
            self.check_for_notification_medals()

    def update_weekly_challenge(self):
        data = self._get_main_weekly_challenge_data().json()
        self.details.pp = data.get('player', {}).get('prestigePoints', 0)
        self.details.next_pp.clear()
        max_collectable_id = data.get('maxRewardId')
        should_collect = False
        for reward in data.get('rewards', {}).get('normal', {}):
            status = reward.get('status', "")
            if status == 'rewarded':
                continue
            elif status == 'completed':
                should_collect = True
            elif reward.get('icon', "") == 'energy_booster':
                pps = re.search(r"Reach (\d+) Prestige Points to unlock the following reward: \+1 Energy",
                                reward.get('tooltip', ""))
                if pps:
                    self.details.next_pp.append(int(pps.group(1)))
        if should_collect:
            self._post_main_weekly_challenge_collect_all(max_collectable_id)

    def should_fight(self, silent: bool = True) -> Tuple[int, str, bool]:
        count, log_msg, force_fight = super().should_fight()

        if count > 0 and not force_fight:
            if self.energy.food_fights - self.my_companies.ff_lockdown < count:
                log_msg = (f"Fight count modified (old count: {count} | FF: {self.energy.food_fights} | "
                           f"WAM ff_lockdown: {self.my_companies.ff_lockdown} |"
                           f" New count: {count - self.my_companies.ff_lockdown})")
                count -= self.my_companies.ff_lockdown
                if count <= 0:
                    count = 0
                    log_msg = f"Not fighting because WAM needs {self.my_companies.ff_lockdown} food fights"

        if self.max_time_till_full_ff > self.time_till_week_change:
            max_count = (int(self.time_till_week_change.total_seconds()) // 360 * self.energy.interval) // 10
            log_msg = ('End for Weekly challenge is near '
                       f"(Recoverable until WC end {max_count}hp | want to do {count}hits)")
            count = count if max_count > count else max_count

        if not silent:
            self.write_log(log_msg, False)

        return count, log_msg, force_fight

    def collect_weekly_reward(self):
        utils.deprecation(f"Logic moved to {self.__class__.__name__}.update_weekly_challenge()!")
        self.update_weekly_challenge()

    def collect_daily_task(self):
        self.update_citizen_info()
        if self.details.daily_task_done and not self.details.daily_task_reward:
            self._post_main_daily_task_reward()

    def state_update_repeater(self):
        try:
            start_time = self.now.replace(minute=(self.now.minute // 10) * 10, second=0, microsecond=0)
            if not self.restricted_ip:
                if start_time.minute <= 30:
                    start_time = start_time.replace(minute=30)
                else:
                    start_time = utils.good_timedelta(start_time.replace(minute=0), timedelta(hours=1))
            while not self.stop_threads.is_set():
                start_time = utils.good_timedelta(start_time, timedelta(minutes=10 if self.restricted_ip else 30))
                self.update_citizen_info()
                self.update_weekly_challenge()
                self.send_state_update()
                self.send_inventory_update()
                self.update_companies()
                self.send_my_companies_update()
                sleep_seconds = (start_time - self.now).total_seconds()
                self.stop_threads.wait(sleep_seconds if sleep_seconds > 0 else 0)
        except:  # noqa
            self.report_error('State updater crashed')

    def send_state_update(self):
        data = dict(xp=self.details.xp, cc=self.details.cc, gold=self.details.gold, pp=self.details.pp,
                    inv_total=self.inventory.total, inv=self.inventory.used,
                    hp_limit=self.energy.limit,
                    hp_interval=self.energy.interval, hp_available=self.energy.available, food=self.food['total'], )
        self.reporter.send_state_update(**data)

    def send_inventory_update(self):
        self.reporter.report_action('INVENTORY', json_val=self.inventory.as_dict)

    def send_my_companies_update(self):
        self.reporter.report_action('COMPANIES', json_val=self.my_companies.as_dict)

    def eat(self):
        """
        Try to eat food
        """
        self._eat('blue')
        if self.food['total'] > self.energy.interval:
            if self.energy.limit - self.energy.recovered > self.energy.interval or not self.energy.recoverable % 2:
                super().eat()
            else:
                self.write_log("I don't want to eat right now!")
        else:
            self.write_log(f"I'm out of food! But I'll try to buy some!\n{self.food}")
            self.buy_food()
            if self.food['total'] > self.energy.interval:
                super().eat()
            else:
                self.write_log('I failed to buy food')

    def eat_eb(self):
        self.write_log('Eating energy bar')
        if self.energy.recoverable:
            self._eat('blue')
        self._eat('orange')
        self.write_log(self.health_info)

    def sell_produced_product(self, kind: str, quality: int = 1, amount: int = 0):
        if not amount:
            inv_resp = self._get_economy_inventory_items().json()
            category = 'rawMaterials' if kind.endswith('Raw') else 'finalProducts'
            item = f"{constants.INDUSTRIES[kind]}_{quality}"
            amount = inv_resp.get('inventoryItems').get(category).get('items').get(item).get('amount', 0)

        if amount >= 1:
            lowest_price = self.get_market_offers(kind, int(quality), self.details.citizenship)[f'q{int(quality)}']

            if lowest_price.citizen_id == self.details.citizen_id:
                price = lowest_price.price
            else:
                price = lowest_price.price - 0.01

            self.post_market_offer(industry=constants.INDUSTRIES[kind], amount=int(amount),
                                   quality=int(quality), price=price)

    def _wam(self, holding: classes.Holding) -> NoReturn:
        response = self.work_as_manager_in_holding(holding)
        if response is None:
            return
        if response.get('status'):
            self._report_action('WORK_AS_MANAGER', 'Worked as manager', kwargs=response)
            if self.config.auto_sell:
                for kind, data in response.get('result', {}).get('production', {}).items():
                    if data and kind in self.config.auto_sell:
                        if kind in ['food', 'weapon', 'house', 'airplane']:
                            for quality, amount in data.items():
                                self.sell_produced_product(kind, quality)
                        elif kind.endswith('Raw'):
                            self.sell_produced_product(kind, 1)
                        else:
                            raise classes.ErepublikException(f"Unknown kind produced '{kind}'")
        elif self.config.auto_buy_raw and re.search(r"not_enough_[^_]*_raw", response.get('message')):
            raw_kind = re.search(r"not_enough_(\w+)_raw", response.get('message'))
            if raw_kind:
                raw_kind = raw_kind.group(1)
                result = response.get('result', {})
                amount_needed = round(result.get('consume', 0) - result.get('stock', 0) + 0.5)
                self._report_action(
                    'WORK_AS_MANAGER', f"Unable to wam! Missing {amount_needed} {raw_kind}, will try to buy.",
                    kwargs=response
                )
                start_place = (self.details.current_country, self.details.current_region)
                while amount_needed > 0:
                    amount = amount_needed
                    best_offer = self.get_market_offers(f"{raw_kind}Raw")['q1']
                    amount = best_offer.amount if amount >= best_offer.amount else amount

                    if not best_offer.country == self.details.current_country:
                        self.travel_to_country(best_offer.country)
                    self._report_action('ECONOMY_BUY',
                                        f"Attempting to buy {amount} {raw_kind} for {best_offer.price * amount}cc")
                    rj = self.buy_from_market(amount=amount, offer=best_offer.offer_id)
                    if not rj.get('error'):
                        amount_needed -= amount
                    else:
                        self.write_log(rj.get('message', ""))
                        self._report_action(
                            'ECONOMY_BUY', f"Unable to buy products! Reason: {rj.get('message')}", kwargs=rj
                        )
                        break
                else:
                    if not start_place == (self.details.current_country, self.details.current_region):
                        self.travel_to_holding(holding)
                    self._wam(holding)
                    return

                if not start_place == (self.details.current_country, self.details.current_region):
                    self.travel_to_residence()
                    return
        elif response.get('message') == 'not_enough_health_food':
            self.buy_food()
            self._wam(holding)
        elif response.get('message') == 'tax_money':
            self._report_action('WORK_AS_MANAGER', 'Not enough money to work as manager!', kwargs=response)
            self.write_log('Not enough money to work as manager!')
        else:
            msg = f'I was not able to wam and or employ because:\n{response}'
            self._report_action('WORK_AS_MANAGER', f'Worked as manager failed: {msg}', kwargs=response)
            self.write_log(msg)

    def work_as_manager(self) -> bool:
        """ Does Work as Manager in all holdings with wam. If employees assigned - work them also

        :return: if has more wam work to do
        :rtype: bool
        """
        if self.restricted_ip:
            self._report_action('IP_BLACKLISTED', 'Work as manager is not allowed from restricted IP!')
            return False
        self.update_citizen_info()
        self.update_companies()
        # Prevent messing up levelup with wam
        if not (self.is_levelup_close and self.config.fight) or self.config.force_wam:
            regions: Dict[int, classes.Holding] = {}
            for holding in self.my_companies.holdings.values():
                if holding.wam_count:
                    regions.update({holding.region: holding})

            # Check for current region
            if self.details.current_region in regions:
                self._wam(regions.pop(self.details.current_region))
                self.update_companies()

            for holding in regions.values():
                raw_usage = holding.get_wam_raw_usage()
                free_storage = self.inventory.total - self.inventory.used
                if (raw_usage['frm'] + raw_usage['wrm']) * 100 > free_storage:
                    self._report_action('WAM_UNAVAILABLE', 'Not enough storage!')
                    continue
                self.travel_to_holding(holding)
                self._wam(holding)
                self.update_companies()

            wam_count = self.my_companies.get_total_wam_count()
            if wam_count:
                self.write_log(f"Wam ff lockdown is now {wam_count}, was {self.my_companies.ff_lockdown}")
            self.my_companies.ff_lockdown = wam_count
            self.travel_to_residence()
            return bool(wam_count)
        else:
            self.write_log('Did not WAM because I would mess up levelup!')
            self.my_companies.ff_lockdown = 0

        self.update_companies()
        return bool(self.my_companies.get_total_wam_count())

    def sorted_battles(self, sort_by_time: bool = True, only_tp=False) -> List[classes.Battle]:
        battles: List[classes.Battle] = self.reporter.fetch_battle_priorities(self.details.current_country)
        return battles + super().sorted_battles(sort_by_time, only_tp)

    def command_central(self):
        while not self.stop_threads.is_set():
            try:
                tasks = self.reporter.fetch_tasks()
                for task, args in tasks:
                    try:
                        fn = getattr(self, task)
                        if callable(fn):
                            fn(*args)
                    except AttributeError:
                        continue
                self.stop_threads.wait(90)
            except:  # noqa
                self.report_error('Command central is broken')


class Citizen(_Citizen):
    _concurrency_lock: Event
    _update_lock: Event
    _update_timeout: int = 10
    _concurrency_timeout: int = 600

    def __init__(self, *args, **kwargs):
        self._concurrency_lock = Event()
        self._concurrency_lock.set()
        self._update_lock = Event()
        self._update_lock.set()
        super().__init__(*args, **kwargs)

    def update_weekly_challenge(self):
        if not self._update_lock.wait(self._update_timeout):
            e = f'Update concurrency not freed in {self._update_timeout}sec!'
            self.write_log(e)
            if self.debug:
                self.report_error(e)
            return None
        try:
            self._update_lock.clear()
            super().update_weekly_challenge()
        finally:
            self._update_lock.set()

    def update_companies(self):
        if not self._update_lock.wait(self._update_timeout):
            e = f'Update concurrency not freed in {self._update_timeout}sec!'
            self.write_log(e)
            if self.debug:
                self.report_error(e)
            return None
        try:
            self._update_lock.clear()
            super().update_companies()
        finally:
            self._update_lock.set()

    def update_war_info(self):
        if not self._update_lock.wait(self._update_timeout):
            e = f'Update concurrency not freed in {self._update_timeout}sec!'
            self.write_log(e)
            if self.debug:
                self.report_error(e)
            return None
        try:
            self._update_lock.clear()
            super().update_war_info()
        finally:
            self._update_lock.set()

    def update_job_info(self):
        if not self._update_lock.wait(self._update_timeout):
            e = f'Update concurrency not freed in {self._update_timeout}sec!'
            self.write_log(e)
            if self.debug:
                self.report_error(e)
            return None
        try:
            self._update_lock.clear()
            super().update_job_info()
        finally:
            self._update_lock.set()

    def update_money(self, page: int = 0, currency: int = 62):
        if not self._update_lock.wait(self._update_timeout):
            e = f'Update concurrency not freed in {self._update_timeout}sec!'
            self.write_log(e)
            if self.debug:
                self.report_error(e)
            return None
        try:
            self._update_lock.clear()
            super().update_money(page, currency)
        finally:
            self._update_lock.set()

    def update_inventory(self):
        if not self._update_lock.wait(self._update_timeout):
            e = f'Update concurrency not freed in {self._update_timeout}sec!'
            self.write_log(e)
            if self.debug:
                self.report_error(e)
            return None
        try:
            self._update_lock.clear()
            super().update_inventory()
        finally:
            self._update_lock.set()

    def _work_as_manager(self, wam_holding: classes.Holding) -> Optional[Dict[str, Any]]:
        if not self._concurrency_lock.wait(self._concurrency_timeout):
            e = f'Concurrency not freed in {self._concurrency_timeout}sec!'
            self.write_log(e)
            if self.debug:
                self.report_error(e)
            return None
        try:
            self._concurrency_lock.clear()
            return super()._work_as_manager(wam_holding)
        finally:
            self._concurrency_lock.set()

    def fight(self, battle: classes.Battle, division: classes.BattleDivision, side: classes.BattleSide = None,
              count: int = None, use_ebs: bool = False) -> Optional[int]:
        if not self._concurrency_lock.wait(self._concurrency_timeout):
            e = f'Concurrency not freed in {self._concurrency_timeout}sec!'
            self.write_log(e)
            if self.debug:
                self.report_error(e)
            return None
        try:
            self._concurrency_lock.clear()
            return super().fight(battle, division, side, count, use_ebs)
        finally:
            self._concurrency_lock.set()

    def deploy_bomb(self, battle: classes.Battle, division: classes.BattleDivision, bomb_id: int, inv_side: bool,
                    count: int = 1) -> Optional[int]:
        if not self._concurrency_lock.wait(self._concurrency_timeout):
            e = f'Concurrency not freed in {self._concurrency_timeout}sec!'
            self.write_log(e)
            if self.debug:
                self.report_error(e)
            return None
        try:
            self._concurrency_lock.clear()
            return super().deploy_bomb(battle, division, bomb_id, inv_side, count)
        finally:
            self._concurrency_lock.set()

    def buy_market_offer(self, offer: OfferItem, amount: int = None) -> Optional[Dict[str, Any]]:
        if not self._concurrency_lock.wait(self._concurrency_timeout):
            e = f'Concurrency not freed in {self._concurrency_timeout}sec!'
            self.write_log(e)
            if self.debug:
                self.report_error(e)
            return None
        try:
            self._concurrency_lock.clear()
            return super().buy_market_offer(offer, amount)
        finally:
            self._concurrency_lock.set()

    @property
    def as_dict(self):
        d = super().as_dict
        d.update(locks=dict(concurrency_lock=self._concurrency_lock.is_set(), update_lock=self._update_lock.is_set(),
                            concurrency_timeout=self._concurrency_timeout, update_timeout=self._update_timeout))
        return d

    def set_locks(self):
        super().set_locks()
        self._concurrency_lock.set()
        self._update_lock.set()
