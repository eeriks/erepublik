import re
import sys
import warnings
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import product
from threading import Event
from time import sleep
from typing import Any, Callable, Dict, List, NoReturn, Optional, Set, Tuple, Union

from requests import HTTPError, RequestException, Response

from erepublik import utils
from erepublik.access_points import CitizenAPI
from erepublik.classes import Battle, BattleDivision, Config, Details, Energy, \
    ErepublikException, MyCompanies, MyJSONEncoder, OfferItem, Politics, Reporter, TelegramBot


class BaseCitizen(CitizenAPI):
    __last_full_update: datetime = utils.now().min

    promos: Dict[str, datetime] = None
    inventory: Dict[str, int] = {'used': 0, 'total': 0}
    boosters: Dict[int, Dict[int, int]] = {50: {}, 100: {}}
    ot_points: int = 0

    food: Dict[str, int] = {"q1": 0, "q2": 0, "q3": 0, "q4": 0, "q5": 0, "q6": 0, "q7": 0, "total": 0}
    eb_normal = 0
    eb_double = 0
    eb_small = 0
    division = 0

    eday = 0

    config: Config = None
    energy: Energy = None
    details: Details = None
    politics: Politics = None
    reporter: Reporter = None
    stop_threads: Event = None
    telegram: TelegramBot = None

    r: Response = None
    name: str = "Not logged in!"
    logged_in: bool = False
    commit_id: str = ""
    restricted_ip: bool = False

    def __init__(self, email: str = "", password: str = ""):
        super().__init__()
        self.commit_id = utils.COMMIT_ID
        self.config = Config()
        self.energy = Energy()
        self.details = Details()
        self.politics = Politics()
        self.my_companies = MyCompanies()
        self.reporter = Reporter()
        self.stop_threads = Event()
        self.telegram = TelegramBot(stop_event=self.stop_threads)

        self.config.email = email
        self.config.password = password

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
            raise ErepublikException("Something went wrong! Can't find token in page! Exiting!")
        try:
            self.update_citizen_info(resp.text)
        except (AttributeError, utils.json.JSONDecodeError, ValueError, KeyError):
            pass

    def get(self, url: str, **kwargs) -> Response:
        if (self.now - self._req.last_time).seconds >= 15 * 60:
            self.get_csrf_token()
            if "params" in kwargs:
                if "_token" in kwargs["params"]:
                    kwargs["params"]["_token"] = self.token
        if url == self.r.url and not url == self.url:  # Don't duplicate requests, except for homepage
            response = self.r
        else:
            try:
                response = super().get(url, **kwargs)
            except RequestException as e:
                self.write_log("Network error while issuing GET request", e)
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
            if "_token" in data:
                data["_token"] = self.token
            if "_token" in json:
                json["_token"] = self.token

        try:
            response = super().post(url, data=data, json=json, **kwargs)
        except RequestException as e:
            self.write_log("Network error while issuing POST request", e)
            self.sleep(60)
            return self.post(url, data=data, json=json, **kwargs)

        try:
            r_json = response.json()
            if (r_json.get("error") or not r_json.get("status")) and r_json.get("message", "") == "captcha":
                utils.send_email(self.name, [response.text, ], player=self, captcha=True)
        except (AttributeError, utils.json.JSONDecodeError, ValueError, KeyError):
            pass

        if self._errors_in_response(response):
            self.get_csrf_token()
            if data:
                data.update({"_token": self.token})
            elif json:
                json.update({"_token": self.token})
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
            promo_name = promo.get("id")
            expire = utils.localize_timestamp(int(promo.get("expiresAt")))
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
        citizen = citizen_js.get("citizen", {})

        self.eday = citizen_js.get("settings").get("eDay")
        self.division = int(citizen.get("division", 0))

        self.energy.interval = citizen.get("energyPerInterval", 0)
        self.energy.limit = citizen.get("energyToRecover", 0)
        self.energy.recovered = citizen.get("energy", 0)
        self.energy.recoverable = citizen.get("energyFromFoodRemaining", 0)

        self.details.current_region = citizen.get("regionLocationId", 0)
        self.details.current_country = citizen.get("countryLocationId", 0)  # country where citizen is located
        self.details.residence_region = citizen.get("residence", {}).get("regionId", 0)
        self.details.residence_country = citizen.get("residence", {}).get("countryId", 0)
        self.details.citizen_id = citizen.get("citizenId", 0)
        self.details.citizenship = int(citizen.get("country", 0))
        self.details.xp = citizen.get("currentExperiencePoints", 0)
        self.details.daily_task_done = citizen.get("dailyTasksDone", False)
        self.details.daily_task_reward = citizen.get("hasReward", False)
        if citizen.get("dailyOrderDone", False) and not citizen.get("hasDailyOrderReward", False):
            self._post_military_group_missions()

        self.details.next_pp.sort()
        for skill in citizen.get("mySkills", {}).values():
            self.details.mayhem_skills.update({int(skill["terrain_id"]): int(skill["skill_points"])})

        if citizen.get('party', []):
            party = citizen.get('party')
            self.politics.is_party_member = True
            self.politics.party_id = party.get('party_id')
            self.politics.is_party_president = bool(party.get('is_party_president'))
            self.politics.party_slug = f"{party.get('stripped_title')}-{party.get('party_id')}"

    def update_inventory(self) -> Dict[str, Any]:
        """
        Updates class properties and returns structured inventory.
        Return structure: {status: {used: int, total: int}, items: {active/final/raw: {item_token:{quality: data}}}
        If item kind is damageBoosters or aircraftDamageBoosters then kind is renamed to kind+quality and duration is
        used as quality.
        :return: dict
        """
        self.food.update({"q1": 0, "q2": 0, "q3": 0, "q4": 0, "q5": 0, "q6": 0, "q7": 0})
        self.eb_small = self.eb_double = self.eb_normal = 0

        j = self._get_economy_inventory_items().json()
        active_items = {}
        if j.get("inventoryItems", {}).get("activeEnhancements", {}).get("items", {}):
            for item in j.get("inventoryItems", {}).get("activeEnhancements", {}).get("items", {}).values():
                if item.get('token'):
                    kind = re.sub(r'_q\d\d*', "", item.get('token'))
                else:
                    kind = item.get('type')
                if kind not in active_items:
                    active_items[kind] = {}
                icon = item['icon'] if item['icon'] else "//www.erepublik.net/images/modules/manager/tab_storage.png"
                item_data = dict(name=item.get("name"), time_left=item['active']['time_left'], icon=icon, kind=kind,
                                 quality=item.get("quality", 0))

                if item.get('isPackBooster'):
                    active_items[kind].update({0: item_data})
                else:
                    active_items[kind].update({item.get("quality"): item_data})

        final_items = {}
        for item in j.get("inventoryItems", {}).get("finalProducts", {}).get("items", {}).values():
            name = item['name']

            if item.get('type'):
                if item.get('type') in ['damageBoosters', "aircraftDamageBoosters"]:
                    kind = f"{item['type']}{item['quality']}"
                    if item['quality'] == 5:
                        self.boosters[50].update({item['duration']: item['amount']})
                    elif item['quality'] == 10:
                        self.boosters[100].update({item['duration']: item['amount']})

                    delta = item['duration']
                    if delta // 3600:
                        name += f" {delta // 3600}h"
                    if delta // 60 % 60:
                        name += f" {delta // 60 % 60}m"
                    if delta % 60:
                        name += f" {delta % 60}s"
                else:
                    kind = item.get('type')
            else:
                if item['industryId'] == 1:
                    amount = item['amount']
                    q = item['quality']
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
                kind = re.sub(r'_q\d\d*', "", item.get('token'))

            if item.get('token', "") == "house_q100":
                self.ot_points = item['amount']

            if kind not in final_items:
                final_items[kind] = {}

            if item['icon']:
                icon = item['icon']
            else:
                if item['type'] == 'damageBoosters':
                    icon = "/images/modules/pvp/damage_boosters/damage_booster.png"
                elif item['type'] == 'aircraftDamageBoosters':
                    icon = "/images/modules/pvp/damage_boosters/air_damage_booster.png"
                elif item['type'] == 'prestigePointsBoosters':
                    icon = "/images/modules/pvp/prestige_points_boosters/prestige_booster.png"
                elif item['type'] == 'speedBoosters':
                    icon = "/images/modules/pvp/speed_boosters/speed_booster.png"
                elif item['type'] == 'catchupBoosters':
                    icon = "/images/modules/pvp/ghost_boosters/icon_booster_30_60.png"
                else:
                    icon = "//www.erepublik.net/images/modules/manager/tab_storage.png"
            data = dict(kind=kind, quality=item.get('quality', 0), amount=item.get('amount', 0),
                        durability=item.get('duration', 0), icon=icon, name=name)
            if item.get('type') in ('damageBoosters', "aircraftDamageBoosters"):
                data = {data['durability']: data}
            else:
                if item.get('type') == 'bomb':
                    firepower = 0
                    try:
                        firepower = item.get('attributes').get('firePower').get('value', 0)
                    except AttributeError:
                        pass
                    finally:
                        data.update(fire_power=firepower)
                data = {data['quality']: data}
            final_items[kind].update(data)

        raw_materials = {}
        if j.get("inventoryItems", {}).get("rawMaterials", {}).get("items", {}):
            for item in j.get("inventoryItems", {}).get("rawMaterials", {}).get("items", {}).values():
                if item['isPartial']:
                    continue
                kind = re.sub(r'_q\d\d*', "", item.get('token'))
                if kind == "magnesium":
                    kind = "raw_aircraft"
                elif kind == "sand":
                    kind = "raw_house"
                if kind not in raw_materials:
                    raw_materials[kind] = []
                if item['icon'].startswith('//www.erepublik.net/'):
                    icon = item['icon']
                else:
                    icon = "//www.erepublik.net/" + item['icon']

                raw_materials[kind].append(
                    dict(name=item.get("name"), amount=item['amount'] + (item.get('underCostruction', 0) / 100),
                         icon=icon)
                )

        offers = {}
        for offer in self._get_economy_my_market_offers().json():
            kind = self.get_industry_name(offer['industryId'])
            data = dict(quality=offer.get('quality', 0), amount=offer.get('amount', 0), icon=offer.get('icon'),
                        kind=kind, name=kind)
            data = {data['quality']: data}

            if kind not in offers:
                offers[kind] = {}

            offers[kind].update(data)

        self.inventory.update({"used": j.get("inventoryStatus").get("usedStorage"),
                               "total": j.get("inventoryStatus").get("totalStorage")})
        inventory = dict(items=dict(active=active_items, final=final_items,
                                    raw=raw_materials, offers=offers), status=self.inventory)
        self.food["total"] = sum([self.food[q] * utils.FOOD_ENERGY[q] for q in utils.FOOD_ENERGY])
        return inventory

    def write_log(self, *args, **kwargs):
        if self.config.interactive:
            utils.write_interactive_log(*args, **kwargs)
        else:
            utils.write_silent_log(*args, **kwargs)

    def report_error(self, msg: str = "", is_warning: bool = False):
        if is_warning:
            utils.process_warning(msg, self.name, sys.exc_info(), self, self.commit_id)
        else:
            utils.process_error(msg, self.name, sys.exc_info(), self, self.commit_id, None)

    def sleep(self, seconds: int):
        if seconds < 0:
            seconds = 0
        if self.config.interactive:
            utils.interactive_sleep(seconds)
        else:
            sleep(seconds)

    def to_json(self, indent: bool = False) -> str:
        return utils.json.dumps(self.__dict__, cls=MyJSONEncoder, indent=4 if indent else None, sort_keys=True)

    def get_industry_id(self, industry_name: str) -> int:
        """Returns industry id

        :type industry_name: str
        :return: int
        """
        return self.available_industries.get(industry_name, 0)

    def get_industry_name(self, industry_id: int) -> str:
        """Returns industry name from industry ID

        :type industry_id: int
        :return: industry name
        :rtype: str
        """
        for industry_name, ind_id in self.available_industries.items():
            if ind_id == industry_id:
                return industry_name
        return ""

    def get_countries_with_regions(self) -> Set[int]:
        r_json = self._post_main_travel_data().json()
        return_set = {*[]}
        for country_data in r_json['countries'].values():
            if country_data['currentRegions']:
                return_set.add(country_data['id'])
        return return_set

    def __str__(self) -> str:
        return f"Citizen {self.name}"

    def __repr__(self):
        return self.__str__()

    @property
    def __dict__(self):
        ret = super().__dict__.copy()
        ret.pop('stop_threads', None)
        ret.pop('_CitizenMilitary__last_war_update_data', None)

        return ret

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
    def available_industries(self) -> Dict[str, int]:
        """
        Returns currently available industries as dict(name: id)
        :return: Dict[str, int]
        """
        return {"food": 1, "weapon": 2, "house": 4, "aircraft": 23,
                "foodRaw": 7, "weaponRaw": 12, "houseRaw": 17, "airplaneRaw": 24}

    @property
    def factories(self) -> Dict[int, str]:
        """Returns factory industries as dict(id: name)
        :return: Factory id:name dict
        :rtype: Dict[int, str]
        """
        return {1: "Food", 2: "Weapons", 4: "House", 23: "Aircraft",
                7: "FRM q1", 8: "FRM q2", 9: "FRM q3", 10: "FRM q4", 11: "FRM q5",
                12: "WRM q1", 13: "WRM q2", 14: "WRM q3", 15: "WRM q4", 16: "WRM q5",
                18: "HRM q1", 19: "HRM q2", 20: "HRM q3", 21: "HRM q4", 22: "HRM q5",
                24: "ARM q1", 25: "ARM q2", 26: "ARM q3", 27: "ARM q4", 28: "ARM q5", }

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
                reward, currency = info.group(3).strip().split(" ")
                while not isinstance(reward, float):
                    try:
                        reward = float(reward)
                    except ValueError:
                        reward = reward[:-1]

                if (title, reward) not in data:
                    data[(title, reward)] = {'about': about, 'kind': title, 'reward': reward, "count": 1,
                                             "currency": currency}
                else:
                    data[(title, reward)]['count'] += 1
            except AttributeError:
                continue
        if data:
            msgs = ["{count} x {kind}, totaling {} {currency}\n"
                    "{about}".format(d["count"] * d["reward"], **d) for d in data.values()]

            msgs = "\n".join(msgs)
            if self.config.telegram:
                self.telegram.report_medal(msgs)
            self.write_log(f"Found awards:\n{msgs}")
            for info in data.values():
                self.reporter.report_action("NEW_MEDAL", info)

        levelup = re.search(r"<p>Congratulations, you have reached experience <strong>level (\d+)</strong></p>", html)
        if levelup:
            level = levelup.group(1)
            msg = f"Level up! Current level {level}"
            self.write_log(msg)
            if self.config.telegram:
                self.telegram.report_medal(f"Level *{level}*")
            self.reporter.report_action("LEVEL_UP", value=level)

    def _travel(self, country_id: int, region_id: int = 0) -> Response:
        data = {
            "toCountryId": country_id,
            "inRegionId": region_id,
        }
        return self._post_main_travel("moveAction", **data)

    def _get_main_party_members(self, party_id: int) -> Dict[int, str]:
        ret = {}
        r = super()._get_main_party_members(party_id)
        for id_, name in re.findall(r'<a href="//www.erepublik.com/en/main/messages-compose/(\d+)" '
                                    r'title="([\w\d_ .]+)">', r.text):
            ret.update({id_: name})
        return ret

    def _eat(self, colour: str = "blue") -> Response:
        response = self._post_eat(colour)
        r_json = response.json()
        for q, amount in r_json.get("units_consumed").items():
            if f"q{q}" in self.food:
                self.food[f"q{q}"] -= amount
            elif q == "10":
                self.eb_normal -= amount
            elif q == "11":
                self.eb_double -= amount
            elif q == "12":
                self.eb_small -= amount
        next_recovery = r_json.get("food_remaining_reset").split(":")
        self.energy.set_reference_time(
            utils.good_timedelta(self.now, timedelta(seconds=int(next_recovery[1]) * 60 + int(next_recovery[2])))
        )
        self.energy.recovered = r_json.get("health")
        self.energy.recoverable = r_json.get("food_remaining")
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
                self.report_error("eRepublik has blacklisted IP. Limited functionality!", True)

            self.logged_in = True

    def _errors_in_response(self, response: Response):
        try:
            j = response.json()
            if j['error'] and j["message"] == 'Too many requests':
                self.write_log("Made too many requests! Sleeping for 30 seconds.")
                self.sleep(30)
        except (utils.json.JSONDecodeError, KeyError, TypeError):
            pass
        if response.status_code >= 400:
            self.r = response
            if response.status_code >= 500:
                self.write_log("eRepublik servers are having internal troubles. Sleeping for 5 minutes")
                self.sleep(5 * 60)
            else:
                raise ErepublikException(f"HTTP {response.status_code} error!")
        return bool(re.search(r'body id="error"|Internal Server Error|'
                              r'CSRF attack detected|meta http-equiv="refresh"|not_authenticated', response.text))

    def _report_action(self, action: str, msg: str, **kwargs: Optional[Dict[str, Any]]):
        """ Report action to all available reporting channels

        :type action: str
        :type msg: str
        :type kwargs: Optional[Dict[str, Any]]
        :param action: Action taken
        :param msg: Message about the action
        :param kwargs: Extra information regarding action
        """
        kwargs = utils.json.loads(utils.json.dumps(kwargs or {}, cls=MyJSONEncoder))
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

    def collect_map_quest_node(self, node_id: int):
        return self._post_map_rewards_claim(node_id)

    def speedup_map_quest_node(self, node_id: int):
        node = self.get_anniversary_quest_data().get('cities', {}).get(str(node_id), {})
        return self._post_map_rewards_speedup(node_id, node.get("skipCost", 0))

    def spin_wheel_of_fortune(self, max_cost=0, spin_count=0):
        def _write_spin_data(cost, cc, prize):
            self._report_action("WHEEL_SPIN", f"Cost: {cost:4d} | Currency left: {cc:,} | Prize: {prize}")

        base = self._post_main_wheel_of_fortune_build().json()
        current_cost = 0 if base.get('progress').get('free_spin') else base.get('cost')
        current_count = base.get('progress').get('spins')
        if not max_cost and not spin_count:
            r = self._post_main_wheel_of_fortune_spin(current_cost).json()
            _write_spin_data(current_cost, r.get('account'),
                             base.get('prizes').get('prizes').get(str(r.get('result'))).get('tooltip'))
        else:
            is_cost: Callable[[], bool] = lambda: (max_cost != current_cost if max_cost else True)
            is_count: Callable[[], bool] = lambda: (spin_count != current_count if spin_count else True)
            while is_cost() or is_count():
                r = self._spin_wheel_of_loosing(current_cost)
                current_count += 1
                current_cost = r.get('cost')
                _write_spin_data(current_cost, r.get('account'),
                                 base.get('prizes').get('prizes').get(str(r.get('result'))).get('tooltip'))

    def _spin_wheel_of_loosing(self, current_cost: int) -> Dict[str, Any]:
        r = self._post_main_wheel_of_fortune_spin(current_cost).json()
        self.details.cc = r.get('account')
        return r.get('result')


class CitizenTravel(BaseCitizen):
    def _update_citizen_location(self, country_id: int, region_id: int):
        self.details.current_region = region_id
        self.details.current_country = country_id

    def get_country_travel_region(self, country_id: int) -> int:
        regions = self.get_travel_regions(country_id=country_id)
        regs = []
        if regions:
            for region in regions.values():
                if region['countryId'] == country_id:  # Is not occupied by other country
                    regs.append((region['id'], region['distanceInKm']))
        if regs:
            return min(regs, key=lambda _: int(_[1]))[0]
        else:
            return 0

    def travel_to_residence(self) -> bool:
        self.update_citizen_info()
        res_r = self.details.residence_region
        if self.details.residence_country and res_r and not res_r == self.details.current_region:
            r_json = self._travel(self.details.residence_country, self.details.residence_region).json()
            if r_json.get('message', '') == 'success':
                self._update_citizen_location(self.details.residence_country, self.details.current_region)
                self._report_action("TRAVEL", "Traveled to residence", response=r_json)
                return True
            return False
        return True

    def travel_to_region(self, region_id: int) -> bool:
        data = self._post_main_travel_data(region_id=region_id).json()
        if data.get('alreadyInRegion'):
            return True
        else:
            r_json = self._travel(data.get('preselectCountryId'), region_id).json()
            if r_json.get('message', '') == 'success':
                self._update_citizen_location(data.get('preselectCountryId'), region_id)
                self._report_action("TRAVEL", "Traveled to region", response=r_json)
                return True
            return False

    def travel_to_country(self, country_id: int) -> bool:
        data = self._post_main_travel_data(countryId=country_id, check="getCountryRegions").json()

        regs = []
        if data.get('regions'):
            for region in data.get('regions').values():
                if region['countryId'] == country_id:  # Is not occupied by other country
                    regs.append((region['id'], region['distanceInKm']))
        if regs:
            region_id = min(regs, key=lambda _: int(_[1]))[0]
            r_json = self._travel(country_id, region_id).json()
            if r_json.get('message', '') == 'success':
                self._update_citizen_location(country_id, region_id)
                self._report_action("TRAVEL", f"Traveled to {utils.COUNTRIES[country_id]}", response=r_json)
                return True
        return False

    def travel_to_holding(self, holding_id: int) -> bool:
        data = self._post_main_travel_data(holdingId=holding_id).json()
        if data.get('alreadyInRegion'):
            return True
        else:
            r_json = self._travel(data.get('preselectCountryId'), data.get('preselectRegionId')).json()
            if r_json.get('message', '') == 'success':
                self._update_citizen_location(data.get('preselectCountryId'), data.get('preselectRegionId'))
                self._report_action("TRAVEL", f"Traveled to holding {holding_id}", response=r_json)
                return True
            return False

    def get_travel_regions(self, holding_id: int = 0, battle_id: int = 0, country_id: int = 0
                           ) -> Union[List[Any], Dict[str, Dict[str, Any]]]:
        d = self._post_main_travel_data(holdingId=holding_id, battleId=battle_id, countryId=country_id).json()
        return d.get('regions', [])

    def get_travel_countries(self) -> Set[int]:
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
                response = self._post_economy_work("production", employ=employee_companies).json()
                self.reporter.report_action("WORK_EMPLOYEES", response, response.get('status', False))
            self.update_companies()
            ret = bool(self.my_companies.get_employable_factories())

        return ret

    def work_as_manager_in_holding(self, holding_id: int) -> Optional[Dict[str, Any]]:
        return self._work_as_manager(holding_id)

    def _work_as_manager(self, wam_holding_id: int = 0) -> Optional[Dict[str, Any]]:
        if self.restricted_ip:
            return None
        self.update_companies()
        self.update_inventory()
        data = {"action_type": "production"}
        extra = {}
        wam_list = []
        if wam_holding_id:
            raw_count = self.my_companies.get_holding_wam_count(wam_holding_id, raw_factory=True)
            fab_count = self.my_companies.get_holding_wam_count(wam_holding_id, raw_factory=False)
            if raw_count + fab_count <= self.energy.food_fights:
                raw_factories = None
            elif not raw_count and fab_count <= self.energy.food_fights:
                raw_factories = False
            else:
                raw_factories = True

            free_inventory = self.inventory["total"] - self.inventory["used"]
            wam_list = self.my_companies.get_holding_wam_companies(
                wam_holding_id, raw_factory=raw_factories)[:self.energy.food_fights]
            has_space = False
            while not has_space and wam_list:
                extra_needed = self.my_companies.get_needed_inventory_usage(companies=wam_list)
                has_space = extra_needed < free_inventory
                if not has_space:
                    wam_list.pop(-1)

        if wam_list:
            data.update(extra)
            if wam_list:
                wam_holding = self.my_companies.holdings.get(wam_holding_id)
                if not self.details.current_region == wam_holding.region:
                    self.write_log("Unable to work as manager because of location - please travel!")
                    return

            employ_factories = self.my_companies.get_employable_factories()
            if sum(employ_factories.values()) > self.my_companies.work_units:
                employ_factories = {}

            response = self._post_economy_work("production", wam=[c.id for c in wam_list],
                                               employ=employ_factories).json()
            return response

    def update_companies(self):
        html = self._get_economy_my_companies().text
        page_details = utils.json.loads(re.search(r"var pageDetails\s+= ({.*});", html).group(1))
        self.my_companies.work_units = int(page_details.get("total_works", 0))

        have_holdings = re.search(r"var holdingCompanies\s+= ({.*}});", html)
        have_companies = re.search(r"var companies\s+= ({.*}});", html)
        if have_holdings and have_companies:
            self.my_companies.prepare_holdings(utils.json.loads(have_holdings.group(1)))
            self.my_companies.prepare_companies(utils.json.loads(have_companies.group(1)))

    def assign_factory_to_holding(self, factory_id: int, holding_id: int) -> Response:
        """
        Assigns factory to new holding
        """
        company = self.my_companies.companies[factory_id]
        self.write_log(f"{company} moved to {holding_id}")
        return self._post_economy_assign_to_holding(factory_id, holding_id)

    def upgrade_factory(self, factory_id: int, level: int) -> Response:
        return self._post_economy_upgrade_company(factory_id, level, self.details.pin)

    def create_factory(self, industry_id: int, building_type: int = 1) -> Response:
        """
        param industry_ids: FRM={q1:7, q2:8, q3:9, q4:10, q5:11} WRM={q1:12, q2:13, q3:14, q4:15, q5:16}
                            HRM={q1:18, q2:19, q3:20, q4:21, q5:22} ARM={q1:24, q2:25, q3:26, q4:27, q5:28}
                            Factories={Food:1, Weapons:2, House:4, Aircraft:23} <- Building_type 1

                            Storage={1000: 1, 2000: 2} <- Building_type 2
        """
        company_name = {1: "Food", 2: "Weapons", 4: "House", 23: "Aircraft",
                        7: "FRM q1", 8: "FRM q2", 9: "FRM q3", 10: "FRM q4", 11: "FRM q5",
                        12: "WRM q1", 13: "WRM q2", 14: "WRM q3", 15: "WRM q4", 16: "WRM q5",
                        18: "HRM q1", 19: "HRM q2", 20: "HRM q3", 21: "HRM q4", 22: "HRM q5",
                        24: "ARM q1", 25: "ARM q2", 26: "ARM q3", 27: "ARM q4", 28: "ARM q5", }[industry_id]
        if building_type == 2:
            company_name = "Storage"
        self.write_log(f'{company_name} created!')
        return self._post_economy_create_company(industry_id, building_type)

    def dissolve_factory(self, factory_id: int) -> Response:
        company = self.my_companies.companies[factory_id]
        self.write_log(f"{company} dissolved!")
        return self._post_economy_sell_company(factory_id, self.details.pin, sell=False)


class CitizenEconomy(CitizenTravel):
    def update_money(self, page: int = 0, currency: int = 62) -> Dict[str, Any]:
        """
        Gets monetary market offers to get exact amount of CC and Gold available
        """
        if currency not in [1, 62]:
            currency = 62
        resp = self._post_economy_exchange_retrieve(False, page, currency)
        resp_data = resp.json()
        self.details.cc = float(resp_data.get("ecash").get("value"))
        self.details.gold = float(resp_data.get("gold").get("value"))
        return resp_data

    def check_house_durability(self) -> Dict[int, datetime]:
        ret = {}
        inv = self.update_inventory()
        for house_quality, active_house in inv['items']['active'].get('house', {}).items():
            till = utils.good_timedelta(self.now, timedelta(seconds=active_house['time_left']))
            ret.update({house_quality: till})
        return ret

    def buy_and_activate_house(self, q: int) -> Dict[int, datetime]:
        inventory = self.update_inventory()
        original_region = self.details.current_country, self.details.current_region
        ok_to_activate = False
        if not inventory['items']['final'].get('house', {}).get(q, {}):
            countries = [self.details.citizenship, ]
            if self.details.current_country != self.details.citizenship:
                countries.append(self.details.current_country)
            offers = [self.get_market_offers("house", q, country)[f"q{q}"] for country in countries]
            local_cheapest = sorted(offers, key=lambda o: o.price)[0]

            global_cheapest = self.get_market_offers("house", q)[f"q{q}"]
            if global_cheapest.price + 200 < local_cheapest.price:
                self._travel(global_cheapest.country)
                buy = self.buy_from_market(global_cheapest.offer_id, 1)
            else:
                buy = self.buy_from_market(local_cheapest.offer_id, 1)
            if buy["error"]:
                msg = f"Unable to buy q{q} house! \n{buy['message']}"
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
                house_durability = self.buy_and_activate_house(q)
        return house_durability

    def activate_house(self, quality: int) -> datetime:
        active_until = self.now
        r = self._post_economy_activate_house(quality)
        if r.json().get("status") and not r.json().get("error"):
            house = r.json()["inventoryItems"]["activeEnhancements"]["items"]["4_%i_active" % quality]
            active_until = utils.good_timedelta(active_until, timedelta(seconds=house["active"]["time_left"]))
        return active_until

    def get_game_token_offers(self):
        r = self._post_economy_game_tokens_market('retrieve').json()
        return {v.get('id'): dict(amount=v.get('amount'), price=v.get('price')) for v in r.get("topOffers")}

    def fetch_organisation_account(self, org_id: int):
        r = self._get_economy_citizen_accounts(org_id)
        table = re.search(r'(<table class="holder racc" .*</table>)', r.text, re.I | re.M | re.S)
        if table:
            account = re.findall(r'>\s*(\d+.\d+)\s*</td>', table.group(1))
            if account:
                return {"gold": account[0], "cc": account[1], 'ok': True}

        return {"gold": 0, "cc": 0, 'ok': False}

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

    def post_market_offer(self, industry: int, quality: int, amount: int, price: float) -> Response:
        if industry not in self.available_industries.values():
            self.write_log(f"Trying to sell unsupported industry {industry}")

        data = {
            "country": self.details.citizenship,
            "industry": industry,
            "quality": quality,
            "amount": amount,
            "price": price,
            "buy": False,
        }
        ret = self._post_economy_marketplace_actions(**data)
        message = (f"Posted market offer for {amount}q{quality} "
                   f"{self.get_industry_name(industry)} for price {price}cc")
        self._report_action("ECONOMY_SELL_PRODUCTS", message, kwargs=ret.json())
        return ret

    def buy_from_market(self, offer: int, amount: int) -> dict:
        ret = self._post_economy_marketplace_actions(amount, True, offer=offer)
        json_ret = ret.json()
        if json_ret.get('error'):
            return json_ret
        else:
            self.details.cc = ret.json()['currency']
            self.details.gold = ret.json()['gold']
            json_ret.pop("offerUpdate", None)
            self._report_action("BOUGHT_PRODUCTS", "", kwargs=json_ret)
        return json_ret

    def get_market_offers(self, product_name: str, quality: int = None, country_id: int = None) -> Dict[str, OfferItem]:
        raw_short_names = dict(frm="foodRaw", wrm="weaponRaw", hrm="houseRaw", arm="airplaneRaw")
        q1_industries = ["aircraft"] + list(raw_short_names.values())
        if product_name not in self.available_industries and product_name not in raw_short_names:
            self.write_log(f"Industry '{product_name}' not implemented")
            raise ErepublikException(f"Industry '{product_name}' not implemented")
        elif product_name in raw_short_names:
            quality = 1
            product_name = raw_short_names[product_name]

        offers: Dict[str, OfferItem] = {}

        max_quality = 0
        if quality:
            offers[f"q{quality}"] = OfferItem()
        else:
            max_quality = 1 if product_name in q1_industries else 5 if product_name == 'house' else 7
            for q in range(max_quality):
                offers[f"q{q + 1}"] = OfferItem()

        if country_id:
            countries = [country_id]
        else:
            countries = self.get_countries_with_regions()

        start_dt = self.now
        iterable = [countries, [quality] if quality else range(1, max_quality + 1)]
        for country, q in product(*iterable):
            r = self._post_economy_marketplace(country, self.available_industries[product_name], q).json()
            obj = offers[f"q{q}"]
            if not r.get("error", False):
                for offer in r["offers"]:
                    if (obj.price > float(offer["priceWithTaxes"]) or (
                        obj.price == float(offer["priceWithTaxes"]) and obj.amount < int(offer["amount"])
                    )):
                        offers[f"q{q}"] = obj = OfferItem(
                            float(offer["priceWithTaxes"]), int(offer["country_id"]), int(offer["amount"]),
                            int(offer["id"]), int(offer["citizen_id"])
                        )
        self.write_log(f"Scraped market in {self.now - start_dt}!")

        return offers

    def buy_food(self, energy_amount: int = 0):
        hp_needed = energy_amount if energy_amount else 48 * self.energy.interval * 10 - self.food["total"]
        local_offers = self.get_market_offers("food", country_id=self.details.current_country)

        cheapest_q, cheapest = sorted(local_offers.items(), key=lambda v: v[1].price / utils.FOOD_ENERGY[v[0]])[0]

        if cheapest.amount * utils.FOOD_ENERGY[cheapest_q] < hp_needed:
            amount = cheapest.amount
        else:
            amount = hp_needed // utils.FOOD_ENERGY[cheapest_q]

        if amount * cheapest.price < self.details.cc:
            data = dict(offer=cheapest.offer_id, amount=amount, price=cheapest.price,
                        cost=amount * cheapest.price, quality=cheapest_q, energy=amount * utils.FOOD_ENERGY[cheapest_q])
            self._report_action("BUY_FOOD", "", kwargs=data)
            self.buy_from_market(cheapest.offer_id, amount)
            self.update_inventory()
        else:
            s = f"Don't have enough money! Needed: {amount * cheapest.price}cc, Have: {self.details.cc}cc"
            self.write_log(s)
            self._report_action("BUY_FOOD", s)

    def get_monetary_offers(self, currency: int = 62) -> List[Dict[str, Union[int, float]]]:
        if currency not in [1, 62]:
            currency = 62
        resp = self._post_economy_exchange_retrieve(False, 0, currency).json()
        ret = []
        offers = re.findall(r"id='purchase_(\d+)' data-i18n='Buy for' data-currency='GOLD' "
                            r"data-price='(\d+\.\d+)' data-max='(\d+\.\d+)' trigger='purchase'",
                            resp["buy_mode"], re.M | re.I | re.S)

        for offer_id, price, amount in offers:
            ret.append({"offer_id": int(offer_id), "price": float(price), "amount": float(amount)})

        return sorted(ret, key=lambda o: (o["price"], -o["amount"]))

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
        self.details.cc = float(response.json().get("ecash").get("value"))
        self.details.gold = float(response.json().get("gold").get("value"))
        if response.json().get('error'):
            self._report_action("BUY_GOLD", "Unable to buy gold!", kwargs=response.json())
            self.stop_threads.wait()
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
        cur = "g" if currency == 62 else "cc"
        if success:
            self._report_action("DONATE_MONEY", f"Successfully donated {amount}{cur} to citizen with id {citizen_id}!")
        else:
            self._report_action("DONATE_MONEY", f"Unable to donate {amount}{cur}!")
        return success

    def donate_items(self, citizen_id: int = 1620414, amount: int = 0, industry_id: int = 1, quality: int = 1) -> int:
        if amount < 1:
            return 0
        ind = {v: k for k, v in self.available_industries.items()}
        self.write_log(f"Donate: {amount:4d}q{quality} {ind[industry_id]} to {citizen_id}")
        response = self._post_economy_donate_items_action(citizen_id, amount, industry_id, quality)
        if re.search(rf"Successfully transferred {amount} item\(s\) to", response.text):
            msg = (f"Successfully donated {amount}q{quality} {self.get_industry_name(industry_id)} "
                   f"to citizen with id {citizen_id}!")
            self._report_action("DONATE_ITEMS", msg)
            return amount
        elif re.search('You must wait 5 seconds before donating again', response.text):
            self.write_log('Previous donation failed! Must wait at least 5 seconds before next donation!')
            self.sleep(5)
            return self.donate_items(citizen_id, int(amount), industry_id, quality)
        else:
            if re.search(r'You do not have enough items in your inventory to make this donation', response.text):
                self._report_action("DONATE_ITEMS",
                                    f"Unable to donate {amount}q{quality} "
                                    f"{self.get_industry_name(industry_id)}, not enough left!")
                return 0
            available = re.search(
                r'Cannot transfer the items because the user has only (\d+) free slots in (his|her) storage.',
                response.text
            ).group(1)
            self._report_action('DONATE_ITEMS',
                                f'Unable to donate {amount}q{quality}{self.get_industry_name(industry_id)}'
                                f', receiver has only {available} storage left!')
            self.sleep(5)
            return self.donate_items(citizen_id, int(available), industry_id, quality)

    def contribute_cc_to_country(self, amount=0., country_id: int = 71) -> bool:
        self.update_money()
        amount = int(amount)
        if self.details.cc < amount or amount < 20:
            return False
        data = dict(country=country_id, action='currency', value=amount)
        r = self._post_main_country_donate(**data)
        if r.json().get('status') or not r.json().get('error'):
            self._report_action("CONTRIBUTE_CC", f'Contributed {amount}cc to {utils.COUNTRIES[country_id]}\'s treasury')
            return True
        else:
            self._report_action("CONTRIBUTE_CC", f"Unable to contribute {amount}cc to {utils.COUNTRIES[country_id]}'s"
                                                 f" treasury", kwargs=r.json())
            return False

    def contribute_food_to_country(self, amount: int = 0, quality: int = 1, country_id: int = 71) -> bool:
        self.update_inventory()
        amount = amount // 1
        if self.food["q" + str(quality)] < amount or amount < 10:
            return False
        data = dict(country=country_id, action='food', value=amount, quality=quality)
        r = self._post_main_country_donate(**data)

        if r.json().get('status') or not r.json().get('error'):
            self._report_action("CONTRIBUTE_FOOD", f"Contributed {amount}q{quality} food to "
                                                   f"{utils.COUNTRIES[country_id]}'s treasury")
            return True
        else:
            self._report_action("CONTRIBUTE_FOOD", f"Unable to contribute {amount}q{quality} food to "
                                                   f"{utils.COUNTRIES[country_id]}'s treasury", kwargs=r.json())
            return False

    def contribute_gold_to_country(self, amount: int, country_id: int = 71) -> bool:
        self.update_money()

        if self.details.cc < amount:
            return False
        data = dict(country=country_id, action='gold', value=amount)
        self.reporter.report_action("CONTRIBUTE_GOLD", data, str(amount))
        r = self._post_main_country_donate(**data)

        if r.json().get('status') or not r.json().get('error'):
            self._report_action("CONTRIBUTE_GOLD", f"Contributed {amount}g to {utils.COUNTRIES[country_id]}'s treasury")
            return True
        else:
            self._report_action("CONTRIBUTE_GOLD", f"Unable to contribute {amount}g to {utils.COUNTRIES[country_id]}'s"
                                                   f" treasury", kwargs=r.json())
            return False


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
                self._report_action("ARTICLE_ENDORSE", f"Endorsed article ({article_id}) with {amount}cc")
                return True
            else:
                self._report_action("ARTICLE_ENDORSE", f"Unable to endorse article ({article_id}) with {amount}cc",
                                    kwargs=resp)
                return False
        else:
            return False

    def vote_article(self, article_id: int) -> bool:
        resp = self._post_main_vote_article(article_id).json()

        if not bool(resp.get('error')):
            self._report_action("ARTICLE_VOTE", f"Voted article {article_id}")
            return True
        else:
            self._report_action("ARTICLE_VOTE", f"Unable to vote for article {article_id}", kwargs=resp)
            return False

    def get_article_comments(self, article_id: int, page_id: int = 1) -> Dict[str, Any]:
        return self._post_main_article_comments(article_id, page_id).json()

    def write_article_comment(self, message: str, article_id: int, parent_id: int = None) -> Response:
        self._report_action("ARTICLE_COMMENT", f"Wrote a comment to article ({article_id})",
                            kwargs=dict(msg=message, article_id=article_id, parent_id=parent_id))
        return self._post_main_article_comments_create(message, article_id, parent_id)

    def publish_article(self, title: str, content: str, kind: int) -> int:
        kinds = {1: "First steps in eRepublik", 2: "Battle orders", 3: "Warfare analysis",
                 4: "Political debates and analysis", 5: "Financial business",
                 6: "Social interactions and entertainment"}
        if kind in kinds:
            data = {'title': title, 'content': content, 'country': self.details.citizenship, 'kind': kind}
            resp = self._post_main_write_article(**data)
            try:
                article_id = int(resp.history[1].url.split("/")[-3])
                self._report_action("ARTICLE_PUBLISH", f"Published new article \"{title}\" ({article_id})", kwargs=data)
            except:  # noqa
                article_id = 0
            return article_id
        else:
            raise ErepublikException("Article kind must be one of:\n{}\n'{}' is not supported".format(
                "\n".join(["{}: {}".format(k, v) for k, v in kinds.items()]), kind
            ))


class CitizenMilitary(CitizenTravel):
    all_battles: Dict[int, Battle] = None
    countries: Dict[int, Dict[str, Union[str, List[int]]]] = None
    __last_war_update_data = None

    active_fs: bool = False
    boosters: Dict[int, Dict[int, int]] = {100: {}, 50: {}}

    def update_war_info(self):
        if not self.details.current_country:
            self.update_citizen_info()

        if self.__last_war_update_data and self.__last_war_update_data.get('last_updated',
                                                                           0) + 30 > self.now.timestamp():
            r_json = self.__last_war_update_data
        else:
            r_json = self._get_military_campaigns_json_list().json()
        if r_json.get("countries"):
            if self.all_battles is None:
                self.all_battles = {}
            if self.countries is None:
                self.countries = {}
            countries = {}
            for c_id, c_data in r_json.get("countries").items():
                if int(c_id) not in countries:
                    countries.update({
                        int(c_id): {"name": c_data.get("name"), "allies": c_data.get("allies")}
                    })
                else:
                    countries[int(c_id)].update(allies=c_data.get("allies"))
            self.countries = countries
            self.__last_war_update_data = r_json
            if r_json.get("battles"):
                all_battles = {}
                for battle_data in r_json.get("battles", {}).values():
                    all_battles[battle_data.get('id')] = Battle(battle_data)
                self.all_battles = all_battles

    def get_battle_for_war(self, war_id: int) -> Optional[Battle]:
        self.update_war_info()
        war_info = self.get_war_status(war_id)
        return self.all_battles.get(war_info.get("battle_id"), None)

    def get_war_status(self, war_id: int) -> Dict[str, Union[bool, Dict[int, str]]]:
        r = self._get_wars_show(war_id)
        html = r.text
        ret = {}
        reg_re = re.compile(fr'data-war-id="{war_id}" data-region-id="(\d+)" data-region-name="([- \w]+)"')
        if reg_re.findall(html):
            ret.update(regions={}, can_attack=True)
            for reg in reg_re.findall(html):
                ret["regions"].update({int(reg[0]): reg[1]})
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

    def set_default_weapon(self, battle_id: int) -> int:
        battle = self.all_battles.get(battle_id)
        available_weapons = self._get_military_show_weapons(battle_id).json()
        while not isinstance(available_weapons, list):
            available_weapons = self._get_military_show_weapons(battle_id).json()
        weapon_quality = -1
        weapon_damage = 0
        if not battle.is_air:
            for weapon in available_weapons:
                try:
                    if weapon['weaponQuantity'] > 30 and weapon['weaponInfluence'] > weapon_damage:
                        weapon_quality = int(weapon['weaponId'])
                except ValueError:
                    pass
        return self.change_weapon(battle_id, weapon_quality)

    def change_weapon(self, battle_id: int, quality: int) -> int:
        battle = self.all_battles.get(battle_id)
        battle_zone = battle.div[11 if battle.is_air else self.division].battle_zone_id
        r = self._post_military_change_weapon(battle_id, battle_zone, quality)
        influence = r.json().get('weaponInfluence')
        self._report_action("MILITARY_WEAPON", f"Switched to q{quality} weapon,"
                                               f" new influence {influence}", kwargs=r.json())
        return influence

    def check_epic_battles(self):
        active_fs = False
        for battle_id in self.sorted_battles(self.config.sort_battles_time):
            battle = self.all_battles.get(battle_id)
            if not battle.is_air:
                my_div: BattleDivision = battle.div.get(self.division)
                if my_div.epic and my_div.end > self.now:
                    if self.energy.food_fights > 50:
                        inv_allies = battle.invader.deployed + [battle.invader.id]
                        def_allies = battle.defender.deployed + [battle.defender.id]
                        all_allies = inv_allies + def_allies
                        if self.details.current_country not in all_allies:
                            if self.details.current_country in battle.invader.allies:
                                allies = battle.invader.deployed
                                side = battle.invader.id
                            else:
                                allies = battle.defender.deployed
                                side = battle.defender.id

                            self.travel_to_battle(battle.id, allies)

                        else:
                            if self.details.current_country in inv_allies:
                                side = battle.invader.id
                            elif self.details.current_country in def_allies:
                                side = battle.defender.id
                            else:
                                self.write_log(
                                    f"Country {self.details.current_country} not in all allies list ({all_allies}) and "
                                    f"also not in inv allies ({inv_allies}) nor def allies ({def_allies})")
                                break
                        error_count = 0
                        while self.energy.food_fights > 5 and error_count < 20:
                            errors = self.fight(battle_id, side_id=side, count=self.energy.food_fights - 5)
                            if errors:
                                error_count += errors
                            if self.config.epic_hunt_ebs:
                                self._eat('orange')
                        self.travel_to_residence()
                        break
                elif bool(my_div.epic):
                    active_fs = True

        self.active_fs = active_fs

    def sorted_battles(self, sort_by_time: bool = True) -> List[int]:
        cs_battles_priority_air: List[int] = []
        cs_battles_priority_ground: List[int] = []
        cs_battles_air: List[int] = []
        cs_battles_ground: List[int] = []
        deployed_battles_air: List[int] = []
        deployed_battles_ground: List[int] = []
        ally_battles_air: List[int] = []
        ally_battles_ground: List[int] = []
        other_battles_air: List[int] = []
        other_battles_ground: List[int] = []

        ret_battles: List[int] = []
        if sort_by_time:
            battle_list = sorted(self.all_battles.values(), key=lambda b: b.start)
            battle_list.reverse()
        else:
            battle_list = sorted(self.all_battles.values(), key=lambda b: b.id)

        contribution_json: Response = self._get_military_campaigns_json_citizen()
        contributions: List[Dict[str, int]] = contribution_json.json().get('contributions') or []
        contributions.sort(key=lambda b: -b.get('damage'))
        ret_battles += [int(b.get('battle_id', 0)) for b in contributions if b.get('battle_id')]

        for battle in battle_list:
            battle_sides = [battle.invader.id, battle.defender.id]
            if battle.id in ret_battles:
                continue
            # CS Battles
            elif self.details.citizenship in battle_sides:
                if battle.is_air:
                    if battle.defender.id == self.details.citizenship:
                        cs_battles_priority_air.append(battle.id)
                    else:
                        cs_battles_air.append(battle.id)
                else:
                    if battle.defender.id == self.details.citizenship:
                        cs_battles_priority_ground.append(battle.id)
                    else:
                        cs_battles_ground.append(battle.id)

            # Current location battles:
            elif self.details.current_country in battle_sides:
                if battle.is_air:
                    deployed_battles_air.append(battle.id)
                else:
                    deployed_battles_ground.append(battle.id)

            # Deployed battles and allied battles:
            elif self.details.current_country in battle.invader.allies + battle.defender.allies + battle_sides:
                if self.details.current_country in battle.invader.deployed + battle.defender.deployed:
                    if battle.is_air:
                        deployed_battles_air.append(battle.id)
                    else:
                        deployed_battles_ground.append(battle.id)
                # Allied battles:
                else:
                    if battle.is_air:
                        ally_battles_air.append(battle.id)
                    else:
                        ally_battles_ground.append(battle.id)
            else:
                if battle.is_air:
                    other_battles_air.append(battle.id)
                else:
                    other_battles_ground.append(battle.id)

        cs_battles = cs_battles_priority_air + cs_battles_priority_ground + cs_battles_air + cs_battles_ground
        deployed_battles = deployed_battles_air + deployed_battles_ground
        other_battles = ally_battles_air + ally_battles_ground + other_battles_air + other_battles_ground
        ret_battles = ret_battles + cs_battles + deployed_battles + other_battles
        return ret_battles

    @property
    def has_battle_contribution(self):
        return bool(self.__last_war_update_data.get("citizen_contribution", []))

    def find_battle_and_fight(self):
        if self.should_fight()[0]:
            self.write_log("Checking for battles to fight in...")
            for battle_id in self.sorted_battles(self.config.sort_battles_time):
                battle = self.all_battles.get(battle_id)
                if not isinstance(battle, Battle):
                    continue
                div = 11 if battle.is_air else self.division

                allies = battle.invader.deployed + battle.defender.deployed + [battle.invader.id, battle.defender.id]

                travel_needed = self.details.current_country not in allies

                if battle.is_rw:
                    side_id = battle.defender.id if self.config.rw_def_side else battle.invader.id
                else:
                    side = self.details.current_country in battle.defender.allies + [battle.defender.id, ]
                    side_id = battle.defender.id if side else battle.invader.id
                try:
                    def_points = battle.div.get(div).dom_pts.get('def')
                    inv_points = battle.div.get(div).dom_pts.get('inv')
                except KeyError:
                    self.report_error(f"Division {div} not available for battle {battle.id}!")
                    def_points = inv_points = 3600
                self.write_log(battle)

                points = def_points <= 1700 and inv_points <= 1700
                b_type = battle.is_air and self.config.air or not battle.is_air and self.config.ground
                travel = (self.config.travel_to_fight and self.should_travel_to_fight() or self.config.force_travel) \
                    if travel_needed else True

                if not (points and b_type and travel):
                    continue

                if battle.start > self.now:
                    self.sleep(utils.get_sleep_seconds(battle.start))

                if travel_needed:
                    if battle.is_rw:
                        country_ids_to_travel = [battle.defender.id]
                    elif self.details.current_country in battle.invader.allies:
                        country_ids_to_travel = battle.invader.deployed + [battle.invader.id]
                        side_id = battle.invader.id
                    else:
                        country_ids_to_travel = battle.defender.deployed + [battle.defender.id]
                        side_id = battle.defender.id

                    if not self.travel_to_battle(battle_id, country_ids_to_travel):
                        break
                self.set_default_weapon(battle_id)
                self.fight(battle_id, side_id)
                self.travel_to_residence()
                break

    def fight(self, battle_id: int, side_id: int = None, count: int = None, division: int = None) -> int:
        """Fight in a battle.

        Will auto activate booster and travel if allowed to do it.
        :param battle_id: int BattleId - battle to fight in
        :type battle_id: int
        :param side_id: int or None. Battle side to fight in, If side_id not == invader id or not in invader deployed
                                     allies list, then defender's side is chosen
        :type side_id: int
        :param count: How many hits to do, if not specified self.should_fight() is called.
        :type count: int
        :param division: int Division number to fight in available choices 1,2,3,4,11
        :type division: int
        :return: None if no errors while fighting, otherwise error count.
        :rtype: int
        """
        if self.restricted_ip:
            self._report_action("IP_BLACKLISTED", "Fighting is not allowed from restricted IP!")
            return 1
        if not isinstance(battle_id, int):
            self.report_error(f"WARNING! Parameter battle_id should be 'int', but it is '{type(battle_id).__name__}'")
            battle_id = int(battle_id)
        if battle_id not in self.all_battles:
            self.update_war_info()
        battle = self.all_battles.get(battle_id)
        division = self.division if division is None else division
        zone_id = battle.div[11 if battle.is_air else division].battle_zone_id
        if not battle.is_air and self.config.boosters:
            self.activate_dmg_booster()
        error_count = 0
        ok_to_fight = True
        if count is None:
            count = self.should_fight()[0]

        total_damage = 0
        total_hits = 0
        side = battle.invader.id == side_id or side_id in battle.invader.deployed
        while ok_to_fight and error_count < 10 and count > 0:
            while all((count > 0, error_count < 10, self.energy.recovered >= 50)):
                hits, error, damage = self._shoot(battle_id, side, zone_id)
                count -= hits
                total_hits += hits
                total_damage += damage
                error_count += error
            else:
                self._eat('blue')
                if self.energy.recovered < 50 or error_count >= 10 or count <= 0:
                    self.write_log("Hits: {:>4} | Damage: {}".format(total_hits, total_damage))
                    ok_to_fight = False
                    if total_damage:
                        self.reporter.report_action("FIGHT", dict(battle=battle_id, side=side_id, dmg=total_damage,
                                                                  air=battle.is_air, hits=total_hits))
        return error_count

    def _shoot(self, battle_id: int, inv_side: bool, zone_id: int):
        battle = self.all_battles.get(battle_id)
        side_id = battle.invader.id if inv_side else battle.defender.id
        if battle.is_air:
            response = self._post_military_fight_air(battle_id, side_id, zone_id)
        else:
            response = self._post_military_fight_ground(battle_id, side_id, zone_id)

        if "Zone is not meant for " in response.text:
            self.sleep(5)
            return 0, 1, 0
        try:
            r_json = response.json()
        except (ValueError, HTTPError, RequestException):
            return 0, 10, 0
        hits = 0
        damage = 0
        err = False
        if r_json.get("error"):
            if r_json.get("message") == "SHOOT_LOCKOUT" or r_json.get("message") == "ZONE_INACTIVE":
                pass
            elif r_json.get("message") == "NOT_ENOUGH_WEAPONS":
                self.set_default_weapon(battle_id)
            else:
                if r_json.get("message") == "UNKNOWN_SIDE":
                    self._rw_choose_side(battle_id, side_id)
                elif r_json.get("message") == "CHANGE_LOCATION":
                    countries = [side_id] + battle.invader.deployed if inv_side else battle.defender.deployed
                    self.travel_to_battle(battle_id, countries)
                err = True
        elif r_json.get("message") == "ENEMY_KILLED":
            hits = (self.energy.recovered - r_json["details"]["wellness"]) // 10
            self.energy.recovered = r_json["details"]["wellness"]
            self.details.xp = int(r_json["details"]["points"])
            damage = r_json["user"]["givenDamage"] * (1.1 if r_json["oldEnemy"]["isNatural"] else 1)
        else:
            err = True

        return hits, err, damage

    def deploy_bomb(self, battle_id: int, bomb_id: int, inv_side: bool = None, count: int = 1) -> int:
        """Deploy bombs in a battle for given side.

        :param battle_id: int battle id
        :param bomb_id: int bomb id
        :param inv_side: should deploy on invader side, if None then will deploy in currently available side
        :param count: int how many bombs to deploy
        :return: Deployed count
        :rtype: int
        """
        if not isinstance(count, int) or count < 1:
            count = 1
        has_traveled = False
        battle = self.all_battles.get(battle_id)
        if battle.is_rw:
            has_traveled = self.travel_to_battle(battle_id, [battle.defender.id])
            self._rw_choose_side(battle.id, battle.invader.id if inv_side else battle.defender.id)
        if inv_side:
            good_countries = [battle.invader.id] + battle.invader.deployed
            if self.details.current_country not in good_countries:
                has_traveled = self.travel_to_battle(battle_id, good_countries)
        elif inv_side is not None:
            good_countries = [battle.defender.id] + battle.defender.deployed
            if self.details.current_country not in good_countries:
                has_traveled = self.travel_to_battle(battle_id, good_countries)
        else:
            involved = [battle.invader.id, battle.defender.id] + battle.invader.deployed + battle.defender.deployed
            if self.details.current_country not in involved:
                count = 0
        errors = deployed_count = 0
        while (not deployed_count == count) and errors < 10:
            r = self._post_military_deploy_bomb(battle_id, bomb_id).json()
            if not r.get('error'):
                deployed_count += 1
            elif r.get('message') == 'LOCKED':
                sleep(0.5)
            else:
                errors += 1

        if has_traveled:
            self.travel_to_residence()

        self._report_action("MILITARY_BOMB", f"Deployed {deployed_count} bombs in battle {battle.id}")
        return deployed_count

    def change_division(self, battle_id: int, division_to: int):
        """Change division.

        :param battle_id: int battle id
        :param division_to: int target division to switch to
        :return:
        """
        battle = self.all_battles.get(battle_id)
        self._post_main_battlefield_change_division(battle_id, battle.div[division_to].battle_zone_id)
        self._report_action("MILITARY_DIV_SWITCH", f"Switched to d{division_to} in battle {battle_id}")

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
                rang = r['military']['militaryData']['air']['rankNumber']
            if elite is None:
                elite = r['citizenAttributes']['level'] > 100

        return utils.calculate_hit(0, rang, True, elite, ne, 0, 20 if weapon else 0)

    def activate_dmg_booster(self):
        if self.config.boosters:
            if not self.get_active_ground_damage_booster():
                duration = 0
                for length, amount in self.boosters[50].items():
                    if amount > 2:
                        duration = length
                        break
                if duration:
                    self._report_action("MILITARY_BOOSTER", f"Activated 50% {duration/60}h damage booster")
                    self._post_economy_activate_booster(5, duration, "damage")

    def get_active_ground_damage_booster(self):
        inventory = self.update_inventory()
        quality = 0
        if inventory['items']['active'].get('damageBoosters', {}).get(10):
            quality = 100
        elif inventory['items']['active'].get('damageBoosters', {}).get(5):
            quality = 50
        return quality

    def activate_battle_effect(self, battle_id: int, kind: str) -> Response:
        self._report_action('MILITARY_BOOSTER', f'Activated {kind} booster')
        return self._post_main_activate_battle_effect(battle_id, kind, self.details.citizen_id)

    def activate_pp_booster(self, battle_id: int) -> Response:
        self._report_action('MILITARY_BOOSTER', 'Activated PrestigePoint booster')
        return self._post_military_fight_activate_booster(battle_id, 1, 180, "prestige_points")

    def _rw_choose_side(self, battle_id: int, side_id: int) -> Response:
        return self._post_main_battlefield_travel(side_id, battle_id)

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
        msg = "Fighting not allowed!"
        if not self.config.fight:
            return count, msg, force_fight

        # Do levelup
        if self.is_levelup_reachable:
            msg = "Level up"
            if self.should_do_levelup:
                count = (self.energy.limit * 3) // 10
                force_fight = True
            else:
                self.write_log("Waiting for fully recovered energy before leveling up.", False)

        # Levelup reachable
        elif self.is_levelup_close:
            count = self.details.xp_till_level_up - (self.energy.limit // 10) + 5
            msg = "Fighting for close Levelup. Doing %i hits" % count
            force_fight = True

        elif self.details.pp < 75:
            count = 75 - self.details.pp
            msg = "Obligatory fighting for at least 75pp"
            force_fight = True

        elif self.config.continuous_fighting and self.has_battle_contribution:
            count = self.energy.food_fights
            msg = "Continuing to fight in previous battle"

        # All-in (type = all-in and full ff)
        elif self.config.all_in and self.energy.available + self.energy.interval * 3 >= self.energy.limit * 2:
            count = self.energy.food_fights
            msg = "Fighting all-in. Doing %i hits" % count

        # All-in for AIR battles
        elif all([self.config.air, self.config.all_in, self.energy.available >= self.energy.limit]):
            count = self.energy.food_fights
            msg = "Fighting all-in in AIR. Doing %i hits" % count

        # Get to next Energy +1
        elif self.next_reachable_energy and self.config.next_energy:
            count = self.next_reachable_energy
            msg = "Fighting for +1 energy. Doing %i hits" % count

        # 1h worth of energy
        elif self.energy.available + self.energy.interval * 3 >= self.energy.limit * 2:
            count = self.energy.interval
            msg = "Fighting for 1h energy. Doing %i hits" % count
            force_fight = True

        return (count if count > 0 else 0), msg, force_fight

    def get_battle_round_data(self, battle_id: int, round_id: int, division: int = None) -> dict:
        battle = self.all_battles.get(battle_id)
        if not battle:
            return {}

        data = dict(zoneId=round_id, round=round_id, division=division, leftPage=1, rightPage=1, type="damage")

        r = self._post_military_battle_console(battle_id, "battleStatistics", 1, **data)
        return {battle.invader.id: r.json().get(str(battle.invader.id)).get("fighterData"),
                battle.defender.id: r.json().get(str(battle.defender.id)).get("fighterData")}

    def schedule_attack(self, war_id: int, region_id: int, region_name: str, at_time: datetime):
        if at_time:
            self.sleep(utils.get_sleep_seconds(at_time))
        self.get_csrf_token()
        self.launch_attack(war_id, region_id, region_name)

    def get_active_wars(self, country_id: int = None) -> List[int]:
        r = self._get_country_military(utils.COUNTRY_LINK.get(country_id or self.details.citizenship))
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
        self._report_action("MILITARY_QUEUE_ATTACK", f"Battle for *{region_name}* queued")

    def travel_to_battle(self, battle_id: int, allowed_countries: List[int]) -> bool:
        data = self.get_travel_regions(battle_id=battle_id)

        regs = []
        if data:
            for region in data.values():
                if region['countryId'] in allowed_countries:  # Is not occupied by other country
                    regs.append((region['distanceInKm'], region['id'], region['countryId']))
        if regs:
            reg = min(regs, key=lambda _: int(_[0]))
            region_id = reg[1]
            country_id = reg[2]
            r = self._travel(country_id, region_id).json()
            if r.get('message', '') == 'success':
                self._update_citizen_location(country_id, region_id)
                return True
        return False

    def get_country_mus(self, country_id: int) -> Dict[int, str]:
        ret = {}
        r = self._get_main_leaderboards_damage_rankings(country_id)
        for data in r.json()["mu_filter"]:
            if data["id"]:
                ret.update({data["id"]: data["name"]})
        r = self._get_main_leaderboards_damage_aircraft_rankings(country_id)
        for data in r.json()["mu_filter"]:
            if data["id"]:
                ret.update({data["id"]: data["name"]})
        return ret

    def get_mu_members(self, mu_id: int) -> Dict[int, str]:
        ret = {}
        r = self._get_military_unit_data(mu_id)

        for page in range(int(r.json()["panelContents"]["pages"])):
            r = self._get_military_unit_data(mu_id, currentPage=page + 1)
            for user in r.json()["panelContents"]["members"]:
                if not user["isDead"]:
                    ret.update({user["citizenId"]: user["name"]})
        return ret

    def get_citizen_weekly_daily_orders_done(self, citizen_id: int = None, weeks_ago: int = 0) -> int:
        if citizen_id is None:
            citizen_id = self.details.citizen_id
        profile = self._get_main_citizen_profile_json(citizen_id).json()
        mu_id = profile.get('military', {}).get('militaryUnit', {}).get('id', 0)
        if mu_id:
            name = profile.get('citizen', {}).get('name')
            params = dict(currentPage=1, panel="members", sortBy="dailyOrdersCompleted",
                          weekFilter=f"week{weeks_ago}", search=name)
            member = self._get_military_unit_data(mu_id, **params).json()
            return member.get('panelContents', {}).get('members', [{}])[0].get('dailyOrdersCompleted')
        return 0


class CitizenPolitics(BaseCitizen):
    def get_country_parties(self, country_id: int = None) -> dict:
        if country_id is None:
            country_id = self.details.citizenship
        r = self._get_main_rankings_parties(country_id)
        ret = {}
        for name, id_ in re.findall(r'<a class="dotted" title="([^"]+)" href="/en/party/[\w\d-]+-(\d+)/1">', r.text):
            ret.update({int(id_): name})
        return ret

    def candidate_for_congress(self, presentation: str = "") -> Response:
        self._report_action('POLITIC_CONGRESS', 'Applied for congress elections')
        return self._post_candidate_for_congress(presentation)

    def candidate_for_party_presidency(self) -> Response:
        self._report_action('POLITIC_PARTY_PRESIDENT', 'Applied for party president elections')
        return self._get_candidate_party(self.politics.party_slug)


class CitizenSocial(BaseCitizen):
    def send_mail_to_owner(self):
        if not self.details.citizen_id == 1620414:
            self.send_mail('Started', f'time {self.now.strftime("%Y-%m-%d %H-%M-%S")}', [1620414, ])
            self.sleep(1)
            msg_id = re.search(r'<input type="hidden" value="(\d+)" '
                               r'id="delete_message_(\d+)" name="delete_message\[]">', self.r.text).group(1)
            self._post_delete_message([msg_id])

    def send_mail(self, subject: str, msg: str, ids: List[int] = None):
        if ids is None:
            ids = [1620414, ]
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
        self.write_log("WARNING! This will take a lot of time.")
        rj = self._post_main_travel_data(regionId=662, check="getCountryRegions").json()
        for region_data in rj.get("regions", {}).values():
            cities.append(region_data['cityId'])
            cities_dict.update({region_data['cityId']: region_data['cityName']})

        cities.sort(key=int)
        for city_id in cities:
            self.write_log(f"Adding friends from {cities_dict[city_id]} (id: {city_id})")
            resp = self._get_main_city_data_residents(city_id).json()
            for resident in resp["widgets"]["residents"]["residents"]:
                self.add_friend(resident["citizenId"])
            for page in range(2, resp["widgets"]["residents"]["numResults"] // 10 + 2):
                r = self._get_main_city_data_residents(city_id, page)
                resp = r.json()
                for resident in resp["widgets"]["residents"]["residents"]:
                    self.add_friend(resident["citizenId"])

    def get_community_notifications(self, page: int = 1) -> List[Dict[str, Any]]:
        return self._get_main_notifications_ajax_community(page).json().get('alertsList', [])

    def get_system_notifications(self, page: int = 1) -> List[Dict[str, Any]]:
        return self._get_main_notifications_ajax_system(page).json().get('alertsList', [])

    def get_report_notifications(self, page: int = 1) -> List[Dict[str, Any]]:
        return self._get_main_notifications_ajax_report(page).json().get('alertsList', [])

    def delete_community_notification(self, notification_id: Union[int, List[int]]):
        if not isinstance(notification_id, list):
            notification_id = [notification_id]
        self._post_main_notifications_ajax_community(notification_id)

    def delete_system_notification(self, notification_id: Union[int, List[int]]):
        if not isinstance(notification_id, list):
            notification_id = [notification_id]
        self._post_main_notifications_ajax_system(notification_id)

    def delete_report_notification(self, notification_id: Union[int, List[int]]):
        if not isinstance(notification_id, list):
            notification_id = [notification_id]
        self._post_main_notifications_ajax_report(notification_id)

    def get_all_notifications(self, page: int = 1) -> Dict[str, List[Dict[str, Any]]]:
        return dict(community=self.get_community_notifications(),
                    system=self.get_system_notifications(page),
                    report=self.get_report_notifications(page))

    def delete_all_notifications(self):
        for kind, notifications in self.get_all_notifications():
            if notifications:
                if kind == "community":
                    self.delete_community_notification([n['id'] for n in notifications])
                elif kind == "report":
                    self.delete_report_notification([n['id'] for n in notifications])
                elif kind == "system":
                    self.delete_system_notification([n['id'] for n in notifications])
                else:
                    self.report_error(f"Unsupported notification kind: \"{kind}\"!")

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
            return self._get_main_city_data_residents(city_id, params={"search": name}).json()


class CitizenTasks(BaseCitizen):
    tg_contract: dict = {}
    ot_points: int = 0
    next_ot_time: datetime = None

    def eat(self):
        """ Eat food """
        self._eat("blue")

    def work(self):
        if self.energy.food_fights >= 1:
            response = self._post_economy_work("work")
            js = response.json()
            good_msg = ["already_worked", "captcha"]
            if not js.get("status") and not js.get("message") in good_msg:
                if js.get('message') == 'employee':
                    self.find_new_job()
                self.update_citizen_info()
                self.work()
            else:
                self.reporter.report_action("WORK", json_val=js)
        else:
            self._eat("blue")
            if self.energy.food_fights < 1:
                seconds = (self.energy.reference_time - self.now).total_seconds()
                self.write_log("I don't have energy to work. Will sleep for {}s".format(seconds))
                self.sleep(seconds)
                self._eat("blue")
            self.work()

    def train(self):
        r = self._get_main_training_grounds_json()
        tg_json = r.json()
        self.details.gold = tg_json["page_details"]["gold"]
        self.tg_contract.update(free_train=tg_json["hasFreeTrain"])
        if tg_json["contracts"]:
            self.tg_contract.update(**tg_json["contracts"][0])

        tgs = []
        for data in sorted(tg_json["grounds"], key=lambda k: k["cost"]):
            if data["default"] and not data["trained"]:
                tgs.append(data["id"])
        if tgs:
            if self.energy.food_fights >= len(tgs):
                response = self._post_economy_train(tgs)
                if not response.json().get("status"):
                    self.update_citizen_info()
                    self.train()
                else:
                    self.reporter.report_action("TRAIN", response.json())
            else:
                self._eat("blue")
                if self.energy.food_fights < len(tgs):
                    large = max(self.energy.reference_time, self.now)
                    small = min(self.energy.reference_time, self.now)
                    self.write_log("I don't have energy to train. Will sleep for {} seconds".format(
                        (large - small).seconds))
                    self.sleep(int((large - small).total_seconds()))
                    self._eat("blue")
                self.train()

    def work_ot(self):
        # I"m not checking for 1h cooldown. Beware of nightshift work, if calling more than once every 60min
        self.update_job_info()
        if self.ot_points >= 24 and self.energy.food_fights > 1:
            r = self._post_economy_work_overtime()
            if not r.json().get("status") and r.json().get("message") == "money":
                self.resign_from_employer()
                self.find_new_job()
            else:
                if r.json().get('message') == 'employee':
                    self.find_new_job()
                self.reporter.report_action("WORK_OT", r.json())
        elif self.energy.food_fights < 1 and self.ot_points >= 24:
            self._eat("blue")
            if self.energy.food_fights < 1:
                large = max(self.energy.reference_time, self.now)
                small = min(self.energy.reference_time, self.now)
                self.write_log("I don't have energy to work OT. Will sleep for {}s".format((large - small).seconds))
                self.sleep(int((large - small).total_seconds()))
                self._eat("blue")
            self.work_ot()

    def resign_from_employer(self) -> bool:
        r = self.update_job_info()
        if r.json().get("isEmployee"):
            self._report_action('ECONOMY_RESIGN', 'Resigned from employer!', kwargs=r.json())
            self._post_economy_resign()
            return True
        return False

    def buy_tg_contract(self) -> Response:
        ret = self._post_main_buy_gold_items('gold', "TrainingContract2", 1)
        try:
            extra = ret.json()
        except:  # noqa
            extra = {}
        self._report_action('ECONOMY_TG_CONTRACT', 'Bought TG Contract', kwargs=extra)
        return ret

    def find_new_job(self) -> Response:
        r = self._get_economy_job_market_json(self.details.current_country)
        jobs = r.json().get("jobs")
        data = dict(citizen=0, salary=10)
        for posting in jobs:
            salary = posting.get("salary")
            limit = posting.get("salaryLimit", 0)
            citizen_id = posting.get("citizen").get("id")

            if (not limit or salary * 3 < limit) and salary > data["salary"]:
                data.update({"citizen": citizen_id, "salary": salary})

        self._report_action("ECONOMY_APPLY_FOR_JOB", f"I'm working now for {str(data['citizen'])}", kwargs=r.json())
        return self._post_economy_job_market_apply(**data)

    def apply_to_employer(self, employer_id: int, salary: float) -> bool:
        data = dict(citizenId=employer_id, salary=salary)
        self._report_action("ECONOMY_APPLY_FOR_JOB", f"I'm working now for #{employer_id}", kwargs=data)
        r = self._post_economy_job_market_apply(employer_id, salary)
        return bool(r.json().get('status'))

    def update_job_info(self):
        resp = self._get_main_job_data()
        ot = resp.json().get("overTime", {})
        if ot:
            self.next_ot_time = utils.localize_timestamp(int(ot.get("nextOverTime", 0)))
            self.ot_points = ot.get("points", 0)
        return resp


class Citizen(CitizenAnniversary, CitizenCompanies, CitizenEconomy, CitizenLeaderBoard,
              CitizenMedia, CitizenMilitary, CitizenPolitics, CitizenSocial, CitizenTasks):
    debug: bool = False

    def __init__(self, email: str = "", password: str = "", auto_login: bool = True):
        super().__init__(email, password)
        self.__last_full_update = utils.good_timedelta(self.now, - timedelta(minutes=5))
        self.set_debug(True)
        if auto_login:
            self.login()

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
        self.reporter.do_init(self.name, self.config.email, self.details.citizen_id)
        if self.config.telegram:
            # noinspection SpellCheckingInspection
            self.telegram.do_init(self.config.telegram_chat_id or 620981703,
                                  self.config.telegram_token or "864251270:AAFzZZdjspI-kIgJVk4gF3TViGFoHnf8H4o",
                                  "" if self.config.telegram_chat_id or self.config.telegram_token else self.name)
            self.telegram.send_message(f"*Started* {utils.now():%F %T}")

        self.__last_full_update = utils.good_timedelta(self.now, - timedelta(minutes=5))
        self.update_all(True)

    def update_citizen_info(self, html: str = None):
        """
        Gets main page and updates most information about player
        """
        if html is None:
            self._get_main()
            return
        super().update_citizen_info(html)

        if self.promos.get("trainingContract"):
            if not self.tg_contract:
                self.train()
            if not self.tg_contract["free_train"] and self.tg_contract.get("active", False):
                if self.details.gold >= 54:
                    self.buy_tg_contract()
                else:

                    self.write_log(f"Training ground contract active but "
                                   f"don't have enough gold ({self.details.gold}g {self.details.cc}cc)")
        if self.energy.is_energy_full and self.config.telegram:
            self.telegram.report_full_energy(self.energy.available, self.energy.limit, self.energy.interval)

    def check_for_notification_medals(self):
        notifications = self._get_main_citizen_daily_assistant().json()
        data: Dict[Tuple[str, Union[float, str]], Dict[str, Union[int, str, float]]] = {}
        for medal in notifications.get('notifications', []):
            if medal.get('details', {}).get('type') == "citizenAchievement":
                params: dict = medal.get('details', {}).get('achievement')
                about: str = medal.get('body')
                title: str = medal.get('title')
                count: int = medal.get('details', {}).get('achievementAmount', 1)

                award_id: int = medal.get('id')
                if award_id and title and medal.get('details').get('isWallMaterial'):
                    self._post_main_wall_post_automatic(title.lower(), award_id)

                if params.get('ccValue'):
                    reward = params.get('ccValue')
                    currency = "Currency"
                elif params.get('goldValue'):
                    reward = params.get('goldValue')
                    currency = "Gold"
                else:
                    reward = params.get('energyValue')
                    currency = "Energy"

                if (title, reward) not in data:
                    data[(title, reward)] = {'about': about, 'kind': title, 'reward': reward, "count": count,
                                             "currency": currency, "params": medal.get('details', {})}
                else:
                    data[(title, reward)]['count'] += count
            self._post_main_global_alerts_close(medal.get('id'))
        if data:
            msgs = ["{count} x {kind},"
                    " totaling {} {currency}".format(d["count"] * d["reward"], **d) for d in data.values()]

            msgs = "\n".join(msgs)
            if self.config.telegram:
                self.telegram.report_medal(msgs, len(data) > 1)
            self.write_log(f"Found awards:\n{msgs}")
            for info in data.values():
                self.reporter.report_action("NEW_MEDAL", info)

    def set_debug(self, debug: bool):
        self.debug = debug
        self._req.debug = debug

    def set_pin(self, pin: int):
        self.details.pin = pin

    def update_all(self, force_update=False):
        # Do full update max every 5 min
        if utils.good_timedelta(self.__last_full_update, timedelta(minutes=5)) > self.now and not force_update:
            return
        else:
            self.__last_full_update = self.now
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
        self.details.pp = data.get("player", {}).get("prestigePoints", 0)
        self.details.next_pp.clear()
        for reward in data.get("rewards", {}).get("normal", {}):
            status = reward.get("status", "")
            if status == "rewarded":
                continue
            elif status == "completed":
                self._post_main_weekly_challenge_reward(reward.get("id", 0))
            elif reward.get("icon", "") == "energy_booster":
                pps = re.search(r"Reach (\d+) Prestige Points to unlock the following reward: \+1 Energy",
                                reward.get("tooltip", ""))
                if pps:
                    self.details.next_pp.append(int(pps.group(1)))

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
            log_msg = ("End for Weekly challenge is near "
                       f"(Recoverable until WC end {max_count}hp | want to do {count}hits)")
            count = count if max_count > count else max_count

        self.write_log(log_msg, False)

        return count, log_msg, force_fight

    def collect_weekly_reward(self):
        self.update_weekly_challenge()

    def collect_daily_task(self):
        self.update_citizen_info()
        if self.details.daily_task_done and not self.details.daily_task_reward:
            self._post_main_daily_task_reward()

    def state_update_repeater(self):
        try:
            start_time = self.now.replace(second=0, microsecond=0)
            if start_time.minute <= 30:
                start_time = start_time.replace(minute=30)
            else:
                start_time = utils.good_timedelta(start_time.replace(minute=0), timedelta(hours=1))
            while not self.stop_threads.is_set():
                self.update_citizen_info()
                start_time = utils.good_timedelta(start_time, timedelta(minutes=30))
                self.send_state_update()
                self.send_inventory_update()
                sleep_seconds = (start_time - self.now).total_seconds()
                self.stop_threads.wait(sleep_seconds if sleep_seconds > 0 else 0)
        except:  # noqa
            self.report_error("State updater crashed")

    def send_state_update(self):
        data = dict(xp=self.details.xp, cc=self.details.cc, gold=self.details.gold, pp=self.details.pp,
                    inv_total=self.inventory['total'], inv=self.inventory['used'], hp_limit=self.energy.limit,
                    hp_interval=self.energy.interval, hp_available=self.energy.available, food=self.food['total'], )
        self.reporter.send_state_update(**data)

    def send_inventory_update(self):
        to_report = self.update_inventory()
        self.reporter.report_action("INVENTORY", json_val=to_report)

    def eat(self):
        """
        Try to eat food
        """
        self._eat("blue")
        if self.food["total"] > self.energy.interval:
            if self.energy.limit - self.energy.recovered > self.energy.interval or not self.energy.recoverable % 2:
                super().eat()
            else:
                self.write_log("I don't want to eat right now!")
        else:
            self.write_log(f"I'm out of food! But I'll try to buy some!\n{self.food}")
            self.buy_food()
            if self.food["total"] > self.energy.interval:
                super().eat()
            else:
                self.write_log("I failed to buy food")

    def eat_eb(self):
        self.write_log("Eating energy bar")
        if self.energy.recoverable:
            self._eat("blue")
        self._eat("orange")
        self.write_log(self.health_info)

    def sell_produced_product(self, kind: str, quality: int = 1, amount: int = 0):
        if not amount:
            inv_resp = self._get_economy_inventory_items().json()
            category = "rawMaterials" if kind.endswith("Raw") else "finalProducts"
            item = "{}_{}".format(self.available_industries[kind], quality)
            amount = inv_resp.get("inventoryItems").get(category).get("items").get(item).get("amount", 0)

        if amount >= 1:
            lowest_price = self.get_market_offers(kind, int(quality), self.details.citizenship)[f'q{int(quality)}']

            if lowest_price.citizen_id == self.details.citizen_id:
                price = lowest_price.price
            else:
                price = lowest_price.price - 0.01

            self.post_market_offer(industry=self.available_industries[kind], amount=int(amount),
                                   quality=int(quality), price=price)

    def _wam(self, holding_id: int) -> NoReturn:
        response = self.work_as_manager_in_holding(holding_id)
        if response is None:
            return
        if response.get("status"):
            self._report_action('WORK_AS_MANAGER', 'Worked as manager', kwargs=response)
            if self.config.auto_sell:
                for kind, data in response.get("result", {}).get("production", {}).items():
                    if data and kind in self.config.auto_sell:
                        if kind in ["food", "weapon", "house", "airplane"]:
                            for quality, amount in data.items():
                                self.sell_produced_product(kind, quality)
                        elif kind.endswith("Raw"):
                            self.sell_produced_product(kind, 1)
                        else:
                            raise ErepublikException("Unknown kind produced '{kind}'".format(kind=kind))
        elif self.config.auto_buy_raw and re.search(r"not_enough_[^_]*_raw", response.get("message")):
            raw_kind = re.search(r"not_enough_(\w+)_raw", response.get("message"))
            if raw_kind:
                raw_kind = raw_kind.group(1)
                result = response.get("result", {})
                amount_needed = round(result.get("consume", 0) - result.get("stock", 0) + 0.49)
                start_place = (self.details.current_country, self.details.current_region)
                while amount_needed > 0:
                    amount = amount_needed
                    best_offer = self.get_market_offers(f"{raw_kind}Raw")['q1']
                    amount = best_offer.amount if amount >= best_offer.amount else amount

                    if not best_offer.country == self.details.current_country:
                        self.travel_to_country(best_offer.country)
                    rj = self.buy_from_market(amount=amount, offer=best_offer.offer_id)
                    if not rj.get('error'):
                        amount_needed -= amount
                    else:
                        self.write_log(rj.get('message', ""))
                        break
                else:
                    if not start_place == (self.details.current_country, self.details.current_region):
                        self.travel_to_holding(holding_id)
                    return self._wam(holding_id)
        elif response.get("message") == "not_enough_health_food":
            self.buy_food()
            self._wam(holding_id)
        else:
            msg = "I was not able to wam and or employ because:\n{}".format(response)
            self._report_action("WORK_AS_MANAGER", f"Worked as manager failed: {msg}", kwargs=response)
            self.write_log(msg)

    def work_as_manager(self) -> bool:
        """ Does Work as Manager in all holdings with wam. If employees assigned - work them also

        :return: if has more wam work to do
        :rtype: bool
        """
        if self.restricted_ip:
            self._report_action("IP_BLACKLISTED", "Fighting is not allowed from restricted IP!")
            return False
        self.update_citizen_info()
        self.update_companies()
        # Prevent messing up levelup with wam
        if not (self.is_levelup_close and self.config.fight) or self.config.force_wam:
            regions = {}
            for holding_id, holding in self.my_companies.holdings.items():
                if self.my_companies.get_holding_wam_companies(holding_id):
                    regions.update({holding.region: holding_id})

            # Check for current region
            if self.details.current_region in regions:
                self._wam(regions.pop(self.details.current_region))
                self.update_companies()

            for holding_id in regions.values():
                self.travel_to_holding(holding_id)
                self._wam(holding_id)
                self.update_companies()

            wam_count = self.my_companies.get_total_wam_count()
            if wam_count:
                self.write_log("Wam ff lockdown is now {}, was {}".format(wam_count, self.my_companies.ff_lockdown))
            self.my_companies.ff_lockdown = wam_count
            self.travel_to_residence()
            return bool(wam_count)
        else:
            self.write_log('Did not WAM because I would mess up levelup!')
            self.my_companies.ff_lockdown = 0

        self.update_companies()
        return bool(self.my_companies.get_total_wam_count())

    def sorted_battles(self, sort_by_time: bool = True) -> List[int]:
        battles = self.reporter.fetch_battle_priorities(self.details.current_country)
        return battles + super().sorted_battles(sort_by_time)

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
