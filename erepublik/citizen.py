import datetime
import itertools
import re
import sys
import threading
import time
from json import loads, dumps
from typing import Dict, List, Tuple, Any, Union, Mapping

import requests
from requests import Response, RequestException

from erepublik import classes, utils


class Citizen(classes.CitizenAPI):
    url: str = "https://www.erepublik.com/en"

    division = 0

    all_battles: Dict[int, classes.Battle] = dict()
    countries: Dict[int, Dict[str, Union[str, List[int]]]] = dict()
    __last_war_update_data = {}
    __last_full_update: datetime.datetime = utils.now().min

    active_fs: bool = False

    food = {"q1": 0, "q2": 0, "q3": 0, "q4": 0, "q5": 0, "q6": 0, "q7": 0, "total": 0}
    inventory = {"used": 0, "total": 0}
    boosters = {
        "100_damageBoosters_5_7200": 0,  # 2h × 60min × 60sec, +50%
        "100_damageBoosters_5_28800": 0,  # 8h × 60min × 60sec, +50%
        "100_damageBoosters_5_86400": 0,  # 1d × 24h × 60min × 60sec, +50%
        "100_speedBoosters_1_180": 0,  # 3min × 60sec, ×2 kills
        "100_speedBoosters_2_600": 0,  # 10min × 60sec, ×5 kills
        "100_catchupBoosters_30_60": 0,  # 60sec, +30%
    }

    candies_normal = 0
    candies_double = 0
    candies_small = 0
    tickets = 0

    work_units = 0
    ot_points = 0

    tg_contract = {}
    promos = {}

    eday = 0

    r: requests.Response
    reporter: classes.Reporter
    token = ""
    name = "Not logged in!"
    debug = False
    __registered = False
    logged_in = False

    def __init__(self, email: str = "", password: str = ""):
        super().__init__()
        self.commit_id = utils.COMMIT_ID
        self.config = classes.Config()
        self.config.email = email
        self.config.password = password
        self.energy = classes.Energy()
        self.details = classes.Details()
        self.politics = classes.Politics()
        self.my_companies = classes.MyCompanies()
        self.set_debug(True)
        self.reporter = classes.Reporter()
        self.get_csrf_token()
        self.update_citizen_info()
        self.reporter.do_init(self.name, email, self.details.citizen_id)
        self.stop_threads = threading.Event()
        self.__last_full_update = utils.good_timedelta(self.now, - datetime.timedelta(minutes=5))

    def write_log(self, *args, **kwargs):
        if self.config.interactive:
            utils.write_interactive_log(*args, **kwargs)
        else:
            utils.write_silent_log(*args, **kwargs)

    def sleep(self, seconds: int):
        if self.config.interactive:
            utils.interactive_sleep(seconds)
        else:
            time.sleep(seconds)

    def __str__(self) -> str:
        return "Citizen {}".format(self.name)

    @property
    def __dict__(self):
        ret = super().__dict__.copy()
        ret.pop('reporter', None)
        ret.pop('stop_threads', None)
        ret.pop('_Citizen__last_war_update_data', None)
        ret.update(all_battles=self.all_battles)

        return ret

    def set_debug(self, debug: bool):
        self.debug = debug
        self._req.debug = debug

    def set_pin(self, pin: int):
        self.details.pin = pin

    def get_csrf_token(self):
        """
        get_csrf_token is the function which logs you in, and updates csrf tokens
        (after 15min time of inactivity opening page in eRepublik.com redirects to home page),
        by explicitly requesting homepage.
        """
        resp = self._req.get(self.url)
        self.r = resp
        try:
            self.update_citizen_info(resp.text)
        except:
            pass
        if self._errors_in_response(resp):
            self.get_csrf_token()
            return

        html = resp.text
        self.check_for_new_medals(html)
        re_token = re.search(r'var csrfToken = \'(\w{32})\'', html)
        re_login_token = re.search(r'<input type="hidden" id="_token" name="_token" value="(\w{32})">', html)
        if re_token:
            self.token = re_token.group(1)
        elif re_login_token:
            self.token = re_login_token.group(1)
            self._login()
        else:
            raise classes.ErepublikException("Something went wrong! Can't find token in page! Exiting!")

    def _login(self):
        # MUST BE CALLED TROUGH self.get_csrf_token()
        r = self._post_login(self.config.email, self.config.password)
        self.r = r

        if r.url == "{}/login".format(self.url):
            self.write_log("Citizen email and/or password is incorrect!")
            raise KeyboardInterrupt
        else:
            re_name_id = re.search(r'<a data-fblog="profile_avatar" href="/en/citizen/profile/(\d+)" '
                                   r'class="user_avatar" title="(.*?)">', r.text)
            self.name = re_name_id.group(2)
            self.details.citizen_id = re_name_id.group(1)

            self.write_log("Logged in as: {}".format(self.name))
            self.get_csrf_token()
            self.logged_in = True

    def _errors_in_response(self, response: requests.Response):
        if response.status_code >= 400:
            self.r = response
            if response.status_code >= 500:
                self.write_log("eRepublik servers are having internal troubles. Sleeping for 5 minutes")
                self.sleep(5 * 60)
            else:
                raise classes.ErepublikException("HTTP {} error!".format(response.status_code))
        return bool(re.search(r'body id="error"|Internal Server Error|'
                              r'CSRF attack detected|meta http-equiv="refresh"|not_authenticated', response.text))

    def get(self, url: str, *args, **kwargs) -> Response:
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
                return self.get(url, *args, **kwargs)

            try:
                self.update_citizen_info(html=response.text)
            except:
                pass

            if self._errors_in_response(response):
                self.get_csrf_token()
                self.get(url, **kwargs)
            else:
                self.check_for_new_medals(response.text)

            self.r = response
        return response

    def post(self, url: str, data: dict = None, json: dict = None, **kwargs) -> Response:
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
            return self.post(url, data, json, **kwargs)

        # response = super().post(url, data=data, json=json, **kwargs)
        try:
            resp_data = response.json()
            if (resp_data.get("error") or not resp_data.get("status")) and resp_data.get("message", "") == "captcha":
                utils.send_email(self.name, [response.text, ], player=self, captcha=True)
        except:
            pass

        if self._errors_in_response(response):
            self.get_csrf_token()
            if data:
                data.update({"_token": self.token})
            elif json:
                json.update({"_token": self.token})
            response = self.post(url, data=data, json=json, **kwargs)
        else:
            self.check_for_new_medals(response.text)

        self.r = response
        return response

    def check_for_new_medals(self, html: str):
        new_medals = re.findall(r'(<div class="home_reward reward achievement">.*?<div class="bottom"></div>\s*</div>)',
                                html, re.M | re.S | re.I)
        data = {}
        for medal in new_medals:
            try:
                info = re.search(r"<h3>New Achievement</h3>.*?<p.*?>(.*?)</p>.*?"
                                 r"achievement_recieved.*?<strong>(.*?)</strong>.*?"
                                 r"<div title=\"(.*?)\">", medal, re.M | re.S)
                about = info.group(1).strip()
                title = info.group(2).strip()
                reward, currency = info.group(3).strip().split(" ")
                while not isinstance(reward, float):
                    try:
                        reward = float(reward)
                    except ValueError:
                        reward = reward[:-1]

                if title not in data:
                    data[title] = {'about': about, 'kind': title, 'reward': reward, "count": 1, "currency": currency}
                else:
                    data[title]['count'] += 1
            except AttributeError:
                continue
        if data:

            msgs = ["{count} ✕ {kind}, totaling {} {currency}\n"
                    "{about}".format(d["count"] * d["reward"], **d) for d in data.values()]

            self.write_log("Found awards: {}".format("\n".join(msgs)))
            for info in data.values():
                self.reporter.report_action("NEW_MEDAL", info)

        levelup = re.search(r"<p>Congratulations, you have reached experience <strong>level (\d+)</strong></p>", html)
        if levelup:
            level = levelup.group(1)
            msg = "Level up! Current level {}".format(level)
            self.write_log(msg)
            self.reporter.report_action("LEVEL_UP", value=level)

    def update_all(self, force_update=False):
        # Do full update max every 5 min
        if utils.good_timedelta(self.__last_full_update, datetime.timedelta(minutes=5)) > self.now and not force_update:
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

    def update_citizen_info(self, html: str = None):
        """
        Gets main page and updates most information about player
        """
        if html is None:
            self._get_main()
            html = self.r.text
        ugly_js = re.search(r"promotions: (\[{?.*}?]),\s+", html).group(1)
        promos = loads(utils.normalize_html_json(ugly_js))
        self.promos = {k: v for k, v in self.promos.items() if v > self.now}
        send_mail = False
        for promo in promos:
            promo_name = promo.get("id")
            expire = utils.localize_timestamp(int(promo.get("expiresAt")))
            if promo_name not in self.promos:
                send_mail = True
                self.promos.update({promo_name: expire})
            if promo_name == "trainingContract":
                if not self.tg_contract:
                    self.train()
                if not self.tg_contract["free_train"] and self.tg_contract.get("active", False):
                    if self.details.gold >= 54:
                        self.buy_tg_contract()
                    else:
                        self.write_log("Training ground contract active but don't have enough gold ({}g {}cc)".format(
                            self.details.gold, self.details.cc
                        ))
        if send_mail:
            active_promos = []
            for kind, time_until in self.promos.items():
                active_promos.append(f"{kind} active until {time_until}")
                utils.report_promo(kind, time_until)
            utils.send_email(self.name, active_promos, player=self, promo=True)

        new_date = re.search(r"var new_date = '(\d*)';", html)
        if new_date:
            self.energy.set_reference_time(
                utils.good_timedelta(self.now, datetime.timedelta(seconds=int(new_date.group(1))))
            )

        ugly_js = re.search(r"var erepublik = ({.*}),\s+", html).group(1)
        citizen_js = loads(ugly_js)
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
        # if citizen.get("dailyOrderDone", False) and not citizen.get("hasDailyOrderReward", False):
        #     self.post_military_group_missions(self.token)
        #     self.get_citizen_daily_assistant()

        self.details.next_pp.sort()
        for id_, skill in citizen.get("mySkills", {}).items():
            self.details.mayhem_skills.update({int(skill["terrain_id"]): int(skill["skill_points"])})

        if citizen.get('party', []):
            party = citizen.get('party')
            self.politics.is_party_member = True
            self.politics.party_id = party.get('party_id')
            self.politics.is_party_president = bool(party.get('is_party_president'))
            self.politics.party_slug = "{}-{}".format(party.get("stripped_title"), party.get('party_id'))

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

    def update_job_info(self):
        ot = self._get_job_data().json().get("overTime", {})
        if ot:
            self.my_companies.next_ot_time = utils.localize_timestamp(int(ot.get("nextOverTime", 0)))
            self.ot_points = ot.get("points", 0)

    def update_companies(self):
        html = self._get_economy_my_companies().text
        page_details = loads(re.search(r"var pageDetails\s+= ({.*});", html).group(1))
        self.my_companies.work_units = int(page_details.get("total_works", 0))

        have_holdings = re.search(r"var holdingCompanies\s+= ({.*}});", html)
        have_companies = re.search(r"var companies\s+= ({.*}});", html)
        if have_holdings and have_companies:
            self.my_companies.prepare_companies(loads(have_companies.group(1)))
            self.my_companies.prepare_holdings(loads(have_holdings.group(1)))
            self.my_companies.update_holding_companies()

    def update_inventory(self) -> dict:
        j = self._get_economy_inventory_items().json()

        self.inventory.update({"used": j.get("inventoryStatus").get("usedStorage"),
                               "total": j.get("inventoryStatus").get("totalStorage")})
        final = j.get("inventoryItems").get("finalProducts").get("items")
        self.food.update({
            "q1": final.get("1_1", {"amount": 0}).get("amount", 0),
            "q2": final.get("1_2", {"amount": 0}).get("amount", 0),
            "q3": final.get("1_3", {"amount": 0}).get("amount", 0),
            "q4": final.get("1_4", {"amount": 0}).get("amount", 0),
            "q5": final.get("1_5", {"amount": 0}).get("amount", 0),
            "q6": final.get("1_6", {"amount": 0}).get("amount", 0),
            "q7": final.get("1_7", {"amount": 0}).get("amount", 0),
        })
        self.boosters.update({
            "100_damageBoosters_5_7200": final.get("100_damageBoosters_5_7200", {"amount": 0}).get("amount", 0),
            "100_damageBoosters_5_28800": final.get("100_damageBoosters_5_28800", {"amount": 0}).get("amount", 0),
            "100_damageBoosters_5_86400": final.get("100_damageBoosters_5_86400", {"amount": 0}).get("amount", 0),
            "100_speedBoosters_1_180": final.get("100_speedBoosters_1_180", {"amount": 0}).get("amount", 0),
            "100_speedBoosters_2_600": final.get("100_speedBoosters_2_600", {"amount": 0}).get("amount", 0),
            "100_catchupBoosters_30_60": final.get("100_catchupBoosters_30_60", {"amount": 0}).get("amount", 0),
        })
        self.candies_normal = final.get("1_10", {"amount": 0}).get("amount", 0)
        self.candies_double = final.get("1_11", {"amount": 0}).get("amount", 0)
        self.candies_small = final.get("1_12", {"amount": 0}).get("amount", 0)
        self.ot_points = final.get("4_100", {"amount": 0}).get("amount", 0)
        self.tickets = final.get("3_5", {"amount": 0}).get("amount", 0)

        self.food["total"] = sum([self.food[q] * utils.FOOD_ENERGY[q] for q in utils.FOOD_ENERGY])
        return j

    def update_weekly_challenge(self):
        data = self._get_weekly_challenge_data().json()
        self.details.pp = data.get("player", {}).get("prestigePoints", 0)
        self.details.next_pp = []
        for reward in data.get("rewards", {}).get("normal", {}):
            status = reward.get("status", "")
            if status == "rewarded":
                continue
            elif status == "completed":
                self._post_weekly_challenge_reward(reward.get("id", 0))
            elif reward.get("icon", "") == "energy_booster":
                pps = re.search(r"Reach (\d+) Prestige Points to unlock the following reward: \+1 Energy",
                                reward.get("tooltip", ""))
                if pps:
                    self.details.next_pp.append(int(pps.group(1)))

    def update_war_info(self):
        if not self.details.current_country:
            self.update_citizen_info()

        resp_json = self._get_military_campaigns().json()
        self.all_battles = {}
        if resp_json.get("countries"):
            for c_id, c_data in resp_json.get("countries").items():
                if int(c_id) not in self.countries:
                    self.countries.update({
                        int(c_id): {"name": c_data.get("name"), "allies": c_data.get("allies")}
                    })
                else:
                    self.countries[int(c_id)].update(allies=c_data.get("allies"))
            self.__last_war_update_data = resp_json
            if resp_json.get("battles"):
                for battle_id, battle_data in resp_json.get("battles", {}).items():
                    self.all_battles.update({int(battle_id): classes.Battle(battle_data)})

    def eat(self):
        """
        Try to eat food
        """
        self.update_citizen_info()
        self.update_inventory()
        if self.details.xp_till_level_up > (self.energy.recovered - 50) // 10:
            if self.food["total"] > self.energy.interval:
                if self.energy.limit - self.energy.recovered > self.energy.interval or not self.energy.recoverable % 2:
                    self._eat("blue")
                else:
                    self.write_log("I don't want to eat right now!")
            else:
                self.write_log("I'm out of food! But I'll try to buy some!\n{}".format(self.food))
                self.buy_food()
                self.update_inventory()
                if self.food["total"] > self.energy.interval:
                    self.eat()
                else:
                    self.write_log("I failed to buy food")
        else:
            self.write_log("I'm not allowed to eat because I have levelup coming up!")
        self.write_log(self.health_info)

    def eat_ebs(self):
        self.write_log("Eating energy bar")
        self.update_citizen_info()
        if self.energy.recoverable:
            self._eat("blue")
        self._eat("orange")
        self.write_log(self.health_info)

    def _eat(self, colour: str = "blue") -> Response:
        response = self._post_eat(colour)
        r_json = response.json()
        next_recovery = r_json.get("food_remaining_reset").split(":")
        self.energy.set_reference_time(
            utils.good_timedelta(self.now,
                                 datetime.timedelta(seconds=int(next_recovery[1]) * 60 + int(next_recovery[2])))
        )
        self.energy.recovered = r_json.get("health")
        self.energy.recoverable = r_json.get("food_remaining")
        for q, amount in r_json.get("units_consumed").items():
            if "q{}".format(q) in self.food:
                self.food["q{}".format(q)] -= amount
            elif q == "10":
                self.candies_normal -= amount
            elif q == "11":
                self.candies_double -= amount
            elif q == "12":
                self.candies_small -= amount
        return response

    @property
    def health_info(self):
        self.update_citizen_info()
        ret = "{}/{} + {}, {}hp/6m. {}xp until level up".format(
            self.energy.recovered,
            self.energy.limit,
            self.energy.recoverable,
            self.energy.interval,
            self.details.xp_till_level_up
        )
        return ret

    @property
    def now(self) -> datetime.datetime:
        """
        Returns aware datetime object localized to US/Pacific (eRepublik time)
        :return: datetime.datetime
        """
        return utils.now()

    def check_epic_battles(self):
        active_fs = False
        for battle_id in self.sorted_battles(self.config.sort_battles_time):
            battle = self.all_battles.get(battle_id)
            if not battle.is_air:
                my_div: classes.BattleDivision = battle.div.get(self.division)
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
                                    "Country {} not in all allies list ({}) and also not in inv allies ({}) nor def "
                                    "allies ({})".format(self.details.current_country, all_allies,
                                                         inv_allies, def_allies))
                                break
                        error_count = 0
                        while self.energy.food_fights > 5 and error_count < 20:
                            errors = self.fight(battle_id, side_id=side, is_air=False,
                                                count=self.energy.food_fights - 5)
                            if errors:
                                error_count += errors
                            if self.config.epic_hunt_ebs:
                                self.eat_ebs()
                        self.travel_to_residence()
                        break
                elif bool(my_div.epic):
                    active_fs = True

        self.active_fs = active_fs

    def sorted_battles(self, sort_by_time: bool = False) -> List[int]:
        cs_battles_air: List[int] = []
        cs_battles_ground: List[int] = []
        deployed_battles_air: List[int] = []
        deployed_battles_ground: List[int] = []
        ally_battles_air: List[int] = []
        ally_battles_ground: List[int] = []
        other_battles_air: List[int] = []
        other_battles_ground: List[int] = []
        for bid, battle in sorted(self.all_battles.items(), key=lambda b: b[1].start if sort_by_time else b[0],
                                  reverse=sort_by_time):
            battle_sides = [battle.invader.id, battle.defender.id]

            # CS Battles
            if self.details.citizenship in battle_sides:
                if battle.is_air:
                    cs_battles_ground.append(battle.id)
                else:
                    cs_battles_air.append(battle.id)

            # Current location battles:
            elif self.details.current_country in battle_sides:
                if battle.is_air:
                    deployed_battles_ground.append(battle.id)
                else:
                    deployed_battles_air.append(battle.id)

            # Deployed battles and allied battles:
            elif self.details.current_country in battle.invader.allies + battle.defender.allies + battle_sides:
                if self.details.current_country in battle.invader.deployed + battle.defender.deployed:
                    if battle.is_air:
                        deployed_battles_ground.append(battle.id)
                    else:
                        deployed_battles_air.append(battle.id)
                # Allied battles:
                else:
                    if battle.is_air:
                        ally_battles_ground.append(battle.id)
                    else:
                        ally_battles_air.append(battle.id)
            else:
                if battle.is_air:
                    other_battles_ground.append(battle.id)
                else:
                    other_battles_air.append(battle.id)

        ret_battles = []
        if self.__last_war_update_data.get("citizen_contribution"):
            battle_id = self.__last_war_update_data.get("citizen_contribution")[0].get("battle_id", 0)
            ret_battles.append(battle_id)

        ret_battles += (cs_battles_air + cs_battles_ground +
                        deployed_battles_air + deployed_battles_ground +
                        ally_battles_air + ally_battles_ground +
                        other_battles_air + other_battles_ground)
        return ret_battles

    @property
    def has_battle_contribution(self):
        return bool(self.__last_war_update_data.get("citizen_contribution", []))

    def find_battle_and_fight(self):
        if self.should_fight(False):
            self.write_log("Checking for battles to fight in...")
            for battle_id in self.sorted_battles(self.config.sort_battles_time):
                battle = self.all_battles.get(battle_id)
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
                kwargs = {
                    "bid": battle.id,
                    "air": "air" if battle.is_air else "ground",
                    "rw": "True" if battle.is_rw else "False",
                    "def": def_points,
                    "inv": inv_points,
                    "travel": "(TRAVEL)" if travel_needed else "",
                }
                self.write_log("Battle {bid}, type: {air:6}, rw: {rw:5}, "
                               "points: {def:4}:{inv:<4} {travel}".format(**kwargs))

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
                self.fight(battle_id, side_id, battle.is_air)
                self.travel_to_residence()
                self.collect_weekly_reward()
                break

    def fight(self, battle_id: int, side_id: int, is_air: bool = False, count: int = None):
        data = dict(sideId=side_id, battleId=battle_id)
        error_count = 0
        ok_to_fight = True
        if count is None:
            count = self.should_fight(silent=False)

        total_damage = 0
        total_hits = 0

        while ok_to_fight and error_count < 10:
            while all((count > 0, error_count < 10, self.energy.recovered >= 50)):
                hits, error, damage = self._shoot(is_air, data)
                count -= hits
                total_hits += hits
                total_damage += damage
                error_count += error
            else:
                self.eat()
                if self.energy.recovered < 50 or error_count >= 10 or count <= 0:
                    self.write_log("Hits: {:>4} | Damage: {}".format(total_hits, total_damage))
                    ok_to_fight = False
                    if total_damage:
                        self.reporter.report_action(json_val=dict(battle=battle_id, side=side_id, dmg=total_damage,
                                                                  air=is_air, hits=total_hits), action="FIGHT")
        if error_count:
            return error_count

    def _shoot(self, air: bool, data: dict):
        if air:
            response = self._post_military_fight_air(data['battleId'], data['sideId'])
        else:
            response = self._post_military_fight_ground(data['battleId'], data['sideId'])

        if "Zone is not meant for " in response.text:
            self.sleep(5)
            return 0, 1, 0
        try:
            j_resp = response.json()
        except:
            return 0, 10, 0
        hits = 0
        damage = 0
        err = False
        if j_resp.get("error"):
            if j_resp.get("message") == "SHOOT_LOCKOUT":
                pass
            else:
                if j_resp.get("message") == "UNKNOWN_SIDE":
                    self._rw_choose_side(data["battleId"], data["sideId"])
                err = True
        elif j_resp.get("message") == "ENEMY_KILLED":
            hits = (self.energy.recovered - j_resp["details"]["wellness"]) // 10
            self.energy.recovered = j_resp["details"]["wellness"]
            damage = j_resp["user"]["givenDamage"] * (1.1 if j_resp["oldEnemy"]["isNatural"] else 1)
        else:
            err = True

        return hits, err, damage

    def deploy_bomb(self, battle_id: int, bomb_id: int):
        r = self._post_military_deploy_bomb(battle_id, bomb_id).json()
        return not r.get('error')

    def work_ot(self):
        # I"m not checking for 1h cooldown. Beware of nightshift work, if calling more than once every 60min
        self.update_job_info()
        if self.ot_points >= 24 and self.energy.food_fights > 1:
            r = self._post_economy_work_overtime()
            if not r.json().get("status") and r.json().get("message") == "money":
                self.resign()
                self.find_new_job()
            else:
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

    def work(self):
        if self.energy.food_fights >= 1:
            response = self._post_economy_work("work")
            js = response.json()
            good_msg = ["already_worked", "captcha"]
            if not js.get("status") and not js.get("message") in good_msg:
                self.update_citizen_info()
                self.work()
            else:
                self.reporter.report_action("WORK", json_val=js)
        else:
            self._eat("blue")
            if self.energy.food_fights < 1:
                large = max(self.energy.reference_time, self.now)
                small = min(self.energy.reference_time, self.now)
                self.write_log("I don't have energy to work. Will sleep for {}s".format((large - small).seconds))
                self.sleep(int((large - small).total_seconds()))
                self._eat("blue")
            self.work()

    def train(self):
        r = self._get_training_grounds_json()
        tg_json = r.json()
        self.details.gold = tg_json["page_details"]["gold"]
        self.tg_contract.update({"free_train": tg_json["hasFreeTrain"]})
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

    def work_employees(self) -> bool:
        self.update_companies()
        ret = True
        work_units_needed = 0
        employee_companies = self.my_companies.get_employable_factories()
        for c_id, preset_count in employee_companies.items():
            work_units_needed += preset_count

        if work_units_needed:
            if work_units_needed <= self.my_companies.work_units:
                self._do_wam_and_employee_work(employee_companies=employee_companies)
            self.update_companies()
            if self.my_companies.get_employable_factories():
                ret = False
            else:
                ret = True

        return ret

    def work_wam(self) -> bool:
        self.update_citizen_info()
        self.update_companies()
        # Prevent messing up levelup with wam
        if not (self.is_levelup_close and self.config.fight) or self.config.force_wam:
            # Check for current region
            regions = {}
            for holding_id, holding in self.my_companies.holdings.items():
                if self.my_companies.get_holding_wam_companies(holding_id):
                    regions.update({holding["region_id"]: holding_id})

            if self.details.current_region in regions:
                self._do_wam_and_employee_work(regions.pop(self.details.current_region, None))

            for holding_id in regions.values():
                self._do_wam_and_employee_work(holding_id)

            self.travel_to_residence()
        else:
            self.write_log("Did not wam because I would mess up levelup!")

        self.update_companies()
        return not self.my_companies.get_total_wam_count()

    def _do_wam_and_employee_work(self, wam_holding_id: int = 0, employee_companies: dict = None) -> bool:
        self.update_citizen_info()
        if employee_companies is None:
            employee_companies = {}
        data = {
            "action_type": "production",
        }
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
            wam_list = self.my_companies.get_holding_wam_companies(wam_holding_id,
                                                                   raw_factory=raw_factories)[:self.energy.food_fights]
            has_space = False
            while not has_space and wam_list:
                extra_needed = self.my_companies.get_needed_inventory_usage(companies=wam_list)
                has_space = extra_needed < free_inventory
                if not has_space:
                    inv_w = len(str(self.inventory["total"]))
                    self.write_log(
                        "Inv: {:{inv_w}}/{:{inv_w}} ({:4.2f}), Energy: {}/{} + {} (+{}hp/6min) WAM count {:3}".format(
                            self.inventory["used"], self.inventory["total"], extra_needed,
                            self.energy.recovered, self.energy.limit, self.energy.recoverable, self.energy.interval,
                            len(wam_list), inv_w=inv_w
                        ))
                    wam_list.pop(-1)

        if wam_list or employee_companies:
            data.update(extra)
            if wam_list:
                wam_holding = self.my_companies.holdings.get(wam_holding_id)
                if not self.details.current_region == wam_holding['region_id']:
                    if not self.travel_to_region(wam_holding['region_id']):
                        return False
            response = self._post_economy_work("production", wam=wam_list, employ=employee_companies).json()
            self.reporter.report_action("WORK_WAM_EMPLOYEES", response)
            if response.get("status"):
                if self.config.auto_sell:
                    for kind, data in response.get("result", {}).get("production", {}).items():
                        if kind in self.config.auto_sell and data:
                            if kind in ["food", "weapon", "house", "airplane"]:
                                for quality, amount in data.items():
                                    self.sell_produced_product(kind, quality)

                            elif kind.endswith("Raw"):
                                self.sell_produced_product(kind, 1)

                            else:
                                raise classes.ErepublikException("Unknown kind produced '{kind}'".format(kind=kind))
            elif self.config.auto_buy_raw and re.search(r"not_enough_[^_]*_raw", response.get("message")):
                raw_kind = re.search(r"not_enough_(\w+)_raw", response.get("message"))
                if raw_kind:
                    raw_kind = raw_kind.group(1)
                    result = response.get("result", {})
                    amount_remaining = round(result.get("consume") + 0.49) - round(result.get("stock") - 0.49)
                    industry = "{}Raw".format(raw_kind)
                    while amount_remaining > 0:
                        amount = amount_remaining
                        best_offer = self.get_market_offers(self.details.citizenship, industry, 1)
                        amount = best_offer['amount'] if amount >= best_offer['amount'] else amount
                        rj = self.buy_from_market(amount=best_offer['amount'], offer=best_offer['offer_id'])
                        if not rj.get('error'):
                            amount_remaining -= amount
                        else:
                            self.write_log(rj.get('message', ""))
                            break
                    else:
                        return self._do_wam_and_employee_work(wam_holding_id, employee_companies)

            else:
                self.write_log("I was not able to wam and or employ because:\n{}".format(response))
        wam_count = self.my_companies.get_total_wam_count()
        if wam_count:
            self.write_log("Wam ff lockdown is now {}, was {}".format(wam_count, self.my_companies.ff_lockdown))
        self.my_companies.ff_lockdown = wam_count
        return bool(wam_count)

    def sell_produced_product(self, kind: str, quality: int = 1, amount: int = 0):
        if not amount:
            inv_resp = self.update_inventory()
            category = "rawMaterials" if kind.endswith("Raw") else "finalProducts"
            item = "{}_{}".format(self.available_industries[kind], quality)
            amount = inv_resp.get("inventoryItems").get(category).get("items").get(item).get("amount", 0)

        if amount >= 1:
            lowest_price = self.get_market_offers(country_id=self.details.citizenship,
                                                  product=kind, quality=int(quality))

            if lowest_price["citizen_id"] == self.details.citizen_id:
                price = lowest_price["price"]
            else:
                price = lowest_price["price"] - 0.01

            self.post_market_offer(industry=self.available_industries[kind], amount=int(amount),
                                   quality=int(quality), price=price)

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

    def _update_citizen_location(self, country_id: int, region_id: int):
        self.details.current_region = region_id
        self.details.current_country = country_id

    def travel_to_residence(self) -> bool:
        self.update_citizen_info()
        res_r = self.details.residence_region
        if self.details.residence_country and res_r and not res_r == self.details.current_region:
            r = self._travel(self.details.residence_country, self.details.residence_region)
            if r.json().get('message', '') == 'success':
                self._update_citizen_location(self.details.residence_country, self.details.current_region)
                return True
            return False
        return True

    def travel_to_region(self, region_id: int) -> bool:
        data = self._post_travel_data(region_id=region_id).json()
        if data.get('alreadyInRegion'):
            return True
        else:
            r = self._travel(data.get('preselectCountryId'), region_id).json()
            if r.get('message', '') == 'success':
                self._update_citizen_location(data.get('preselectCountryId'), region_id)
                return True
            return False

    def travel_to_country(self, country_id: int) -> bool:
        data = self._post_travel_data(countryId=country_id, check="getCountryRegions").json()

        regs = []
        if data.get('regions'):
            for region in data.get('regions').values():
                if region['countryId'] == country_id:  # Is not occupied by other country
                    regs.append((region['id'], region['distanceInKm']))
        if regs:
            region_id = min(regs, key=lambda _: int(_[1]))[0]
            r = self._travel(country_id, region_id).json()
            if r.get('message', '') == 'success':
                self._update_citizen_location(country_id, region_id)
                return True
        return False

    def travel_to_holding(self, holding_id: int) -> bool:
        data = self._post_travel_data(holdingId=holding_id).json()
        if data.get('alreadyInRegion'):
            return True
        else:
            r = self._travel(data.get('preselectCountryId'), data.get('preselectRegionId')).json()
            if r.get('message', '') == 'success':
                self._update_citizen_location(data.get('preselectCountryId'), data.get('preselectRegionId'))
                return True
            return False

    def travel_to_battle(self, battle_id: int, *allowed_countries: List[int]) -> bool:
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

    def _travel(self, country_id: int, region_id: int = 0) -> Response:
        data = {
            "toCountryId": country_id,
            "inRegionId": region_id,
        }
        return self._post_travel("moveAction", **data)

    def get_travel_regions(self, holding_id: int = 0, battle_id: int = 0, country_id: int = 0
                           ) -> Union[List[Any], Dict[str, Dict[str, Any]]]:
        d = self._post_travel_data(holdingId=holding_id, battleId=battle_id, countryId=country_id).json()
        return d.get('regions', [])

    def get_travel_countries(self) -> List[int]:
        response_json = self._post_travel_data().json()
        return_list = []
        for country_data in response_json['countries'].values():
            if country_data['currentRegions']:
                return_list.append(country_data['id'])
        return return_list

    def parse_notifications(self, page: int = 1) -> list:
        community = self._get_notifications_ajax_community(page).json()
        system = self._get_notifications_ajax_system(page).json()
        return community['alertsList'] + system['alertsList']

    def delete_notifications(self):
        response = self._get_notifications_ajax_community().json()
        while response['totalAlerts']:
            self._post_messages_alert([_['id'] for _ in response['alertList']])
            response = self._get_notifications_ajax_community().json()

        response = self._get_notifications_ajax_system().json()
        while response['totalAlerts']:
            self._post_messages_alert([_['id'] for _ in response['alertList']])
            response = self._get_notifications_ajax_system().json()

    def collect_weekly_reward(self):
        self.update_weekly_challenge()

    def collect_daily_task(self) -> None:
        self.update_citizen_info()
        if self.details.daily_task_done and not self.details.daily_task_reward:
            self._post_daily_task_reward()

    def send_mail_to_owner(self) -> None:
        if not self.details.citizen_id == 1620414:
            self.send_mail("Started", "time {}".format(self.now.strftime("%Y-%m-%d %H-%M-%S")), [1620414, ])
            self.sleep(1)
            msg_id = re.search(r"<input type=\"hidden\" value=\"(\d+)\" "
                               r"id=\"delete_message_(\d+)\" name=\"delete_message\[]\">", self.r.text).group(1)
            self._post_delete_message([msg_id])

    def get_market_offers(self, country_id: int = None, product: str = None, quality: int = None) -> dict:
        raw_short_names = dict(frm="foodRaw", wrm="weaponRaw", hrm="houseRaw", arm="airplaneRaw")
        q1_industries = ["aircraft"] + list(raw_short_names.values())
        if product:
            if product not in self.available_industries and product not in raw_short_names:
                self.write_log("Industry '{}' not implemented".format(product))
                raise classes.ErepublikException("Industry '{}' not implemented".format(product))
            elif product in raw_short_names:
                quality = 1
                product = raw_short_names.get(product)
            product = [product]
        elif quality:
            raise classes.ErepublikException("Quality without product not allowed")

        item_data = dict(price=999999., country=0, amount=0, offer_id=0, citizen_id=0)

        items = {"food": dict(q1=item_data.copy(), q2=item_data.copy(), q3=item_data.copy(), q4=item_data.copy(),
                              q5=item_data.copy(), q6=item_data.copy(), q7=item_data.copy()),
                 "weapon": dict(q1=item_data.copy(), q2=item_data.copy(), q3=item_data.copy(), q4=item_data.copy(),
                                q5=item_data.copy(), q6=item_data.copy(), q7=item_data.copy()),
                 "house": dict(q1=item_data.copy(), q2=item_data.copy(), q3=item_data.copy(), q4=item_data.copy(),
                               q5=item_data.copy()), "aircraft": dict(q1=item_data.copy()),
                 "foodRaw": dict(q1=item_data.copy()), "weaponRaw": dict(q1=item_data.copy()),
                 "houseRaw": dict(q1=item_data.copy()), "airplaneRaw": dict(q1=item_data.copy())}

        if country_id:
            countries = [country_id]
        else:
            good_countries = self.get_travel_countries()
            countries = {cid for cid in self.countries.keys() if cid in good_countries}

        start_dt = self.now
        iterable = [countries, product or items, [quality] if quality else range(1, 8)]
        for country, industry, q in itertools.product(*iterable):
            if (q > 1 and industry in q1_industries) or (q > 5 and industry == "house"):
                continue

            str_q = "q%i" % q

            r = self._post_economy_marketplace(country, self.available_industries[industry], q).json()
            obj = items[industry][str_q]
            if not r.get("error", False):
                for offer in r["offers"]:
                    if obj["price"] > float(offer["priceWithTaxes"]):
                        obj["price"] = float(offer["priceWithTaxes"])
                        obj["country"] = int(offer["country_id"])
                        obj["amount"] = int(offer["amount"])
                        obj["offer_id"] = int(offer["id"])
                        obj["citizen_id"] = int(offer["citizen_id"])
                    elif obj["price"] == float(offer["priceWithTaxes"]) and obj["amount"] < int(offer["amount"]):
                        obj["country"] = int(offer["country_id"])
                        obj["amount"] = int(offer["amount"])
                        obj["offer_id"] = int(offer["id"])
        self.write_log("Scraped market in {}!".format(self.now - start_dt))

        if quality:
            ret = items[product[0]]["q%i" % quality]
        elif product:
            if product[0] in raw_short_names.values():
                ret = items[product[0]]["q1"]
            else:
                ret = items[product[0]]
        else:
            ret = items
        return ret

    def buy_food(self) -> None:
        self.update_money()
        hp_per_quality = {"q1": 2, "q2": 4, "q3": 6, "q4": 8, "q5": 10, "q6": 12, "q7": 20}
        hp_needed = 24 * self.energy.interval * 10 - self.food["total"]
        local_offers = self.get_market_offers(country_id=self.details.current_country, product="food")

        cheapest_q, cheapest = sorted(local_offers.items(), key=lambda v: v[1]["price"] / hp_per_quality[v[0]])[0]

        if cheapest["amount"] * hp_per_quality[cheapest_q] < hp_needed:
            amount = cheapest["amount"]
        else:
            amount = hp_needed // hp_per_quality[cheapest_q]

        if amount * cheapest["price"] < self.details.cc:
            data = dict(offer=cheapest["offer_id"], amount=amount, price=cheapest["price"],
                        cost=amount * cheapest["price"], quality=cheapest_q, energy=amount * hp_per_quality[cheapest_q])
            self.reporter.report_action("BUY_FOOD", json_val=data)
            self.buy_from_market(cheapest["offer_id"], amount)
        else:
            s = "Don't have enough money! Needed: {}cc, Have: {}cc".format(amount * cheapest["price"], self.details.cc)
            self.write_log(s)
            self.reporter.report_action("BUY_FOOD", value=s)

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

    def buy_monetary_market_offer(self, offer: int, amount: float, currency: int) -> bool:
        response = self._post_economy_exchange_purchase(amount, currency, offer)
        self.details.cc = float(response.json().get("ecash").get("value"))
        self.details.gold = float(response.json().get("gold").get("value"))
        self.reporter.report_action("BUY_GOLD", json_val=response.json(),
                                    value="New amount {o.cc}cc, {o.gold}g".format(o=self.details))
        return not response.json().get("error", False)

    def activate_dmg_booster(self, battle_id: int):
        if self.config.boosters:
            duration = 0
            if self.boosters.get("100_damageBoosters_5_600", 0) > 0:
                duration = 600
            elif self.boosters.get("100_damageBoosters_5_7200", 0) > 1:
                duration = 7200
            elif self.boosters.get("100_damageBoosters_5_28800", 0) > 2:
                duration = 28800
            elif self.boosters.get("100_damageBoosters_5_86400", 0) > 2:
                duration = 86400
            self._post_fight_activate_booster(battle_id, 5, duration, "damage")

    def activate_battle_effect(self, battle_id: int, kind: str) -> Response:
        return self._post_activate_battle_effect(battle_id, kind, self.details.citizen_id)

    def activate_pp_booster(self, battle_id: int) -> Response:
        return self._post_fight_activate_booster(battle_id, 1, 180, "prestige_points")

    def donate_money(self, citizen_id: int = 1620414, amount: float = 0.0, currency: int = 62) -> Response:
        """ currency: gold = 62, cc = 1 """
        return self._post_economy_donate_money_action(citizen_id, amount, currency)

    def donate_items(self, citizen_id: int = 1620414, amount: int = 0, industry_id: int = 1,
                     quality: int = 1) -> Response:
        ind = {v: k for k, v in self.available_industries.items()}
        self.write_log("D,{},q{},{},{}".format(amount, quality, ind[industry_id], citizen_id))
        return self._post_economy_donate_items_action(citizen_id, amount, industry_id, quality)

    def candidate_for_congress(self, presentation: str = "") -> Response:
        return self._post_candidate_for_congress(presentation)

    def candidate_for_party_presidency(self) -> Response:
        return self._get_candidate_party(self.politics.party_slug)

    def accept_money_donations(self):
        for notification in self.parse_notifications():
            don_id = re.search(r"erepublik.functions.acceptRejectDonation\(\"accept\", (\d+)\)", notification)
            if don_id:
                self._get_money_donation_accept(int(don_id.group(1)))
                self.sleep(5)

    def reject_money_donations(self) -> int:
        r = self._get_notifications_ajax_system()
        count = 0
        donation_ids = re.findall(r"erepublik.functions.acceptRejectDonation\(\"reject\", (\d+)\)", r.text)
        while donation_ids:
            for don_id in donation_ids:
                self._get_money_donation_reject(int(don_id))
                count += 1
                self.sleep(5)
            r = self._get_notifications_ajax_system()
            donation_ids = re.findall(r"erepublik.functions.acceptRejectDonation\(\"reject\", (\d+)\)", r.text)
        return count

    def _rw_choose_side(self, battle_id: int, side_id: int) -> Response:
        return self._get_battlefield_choose_side(battle_id, side_id)

    def should_travel_to_fight(self) -> bool:
        ret = False
        if self.config.always_travel:
            return True
        if self.should_do_levelup:  # Do levelup
            ret = True
        elif self.config.all_in and self.energy.available > self.energy.limit * 2 - self.energy.interval * 3:
            ret = True
        # Get to next Energy +1
        elif self.next_reachable_energy and self.config.next_energy:
            ret = True
        # 1h worth of energy
        elif self.energy.available + self.energy.interval * 3 >= self.energy.limit * 2:
            ret = True
        return ret

    def should_fight(self, silent: bool = True) -> int:
        if not self.config.fight:
            return 0
        count = 0
        log_msg = ""
        force_fight = False
        # Do levelup
        if self.is_levelup_reachable:
            log_msg = "Level up"
            if self.should_do_levelup:
                count = (self.energy.limit * 3) // 10
                force_fight = True
            else:
                self.write_log("Waiting for fully recovered energy before leveling up.", False)

        # Levelup reachable
        elif self.is_levelup_close:
            count = self.details.xp_till_level_up - (self.energy.limit // 10) + 5
            log_msg = "Fighting for close Levelup. Doing %i hits" % count
            force_fight = True

        elif self.details.pp < 75:
            count = 75 - self.details.pp
            log_msg = "Obligatory fighting for at least 75pp"
            force_fight = True

        elif self.config.continuous_fighting and self.has_battle_contribution:
            count = self.energy.food_fights
            log_msg = "Continuing to fight in previous battle"

        # All-in (type = all-in and full ff)
        elif self.config.all_in and self.energy.available + self.energy.interval * 3 >= self.energy.limit * 2:
            count = self.energy.food_fights
            log_msg = "Fighting all-in. Doing %i hits" % count

        # All-in for AIR battles
        elif all([self.config.air, self.config.all_in,
                  self.energy.available >= self.energy.limit]):
            count = self.energy.food_fights
            log_msg = "Fighting all-in in AIR. Doing %i hits" % count

        # Get to next Energy +1
        elif self.next_reachable_energy and self.config.next_energy:
            count = self.next_reachable_energy
            log_msg = "Fighting for +1 energy. Doing %i hits" % count

        # 1h worth of energy
        elif self.energy.available + self.energy.interval * 3 >= self.energy.limit * 2:
            count = self.energy.interval
            log_msg = "Fighting for 1h energy. Doing %i hits" % count

        if count > 0 and not force_fight:
            if self.my_companies.ff_lockdown and self.details.pp > 75:
                if count - self.my_companies.ff_lockdown > 0:
                    log_msg = ("Fight count modified (old count: {} | FF: {} | "
                               "WAM ff_lockdown: {} | New count: {})").format(
                        count, self.energy.food_fights, self.my_companies.ff_lockdown,
                        count - self.my_companies.ff_lockdown)
                    count -= self.my_companies.ff_lockdown
                else:
                    count = 0
                if count <= 0:
                    log_msg = "Not fighting because WAM needs {} food fights".format(self.my_companies.ff_lockdown)

            if self.max_time_till_full_ff > self.time_till_week_change:
                max_count = int((self.time_till_week_change - self.time_till_full_ff).total_seconds()) // 60
                log_msg = "End for Weekly challenge is near ({} | {})".format(max_count, count)
                count = count if max_count > count else max_count

        if not silent:
            self.write_log(log_msg, False)

        return count if count > 0 else 0

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
    def next_wc_start(self) -> datetime.datetime:
        days = 1 - self.now.weekday() if 1 - self.now.weekday() > 0 else 1 - self.now.weekday() + 7
        return utils.good_timedelta(self.now.replace(hour=0, minute=0, second=0, microsecond=0),
                                    datetime.timedelta(days=days))

    @property
    def time_till_week_change(self) -> datetime.timedelta:
        return self.next_wc_start - self.now

    @property
    def time_till_full_ff(self) -> datetime.timedelta:
        energy = self.energy.recoverable + self.energy.recovered
        if energy >= self.energy.limit * 2:
            return datetime.timedelta(0)
        minutes_needed = round((self.energy.limit * 2 - energy) / self.energy.interval) * 6
        return (self.energy.reference_time - self.now) + datetime.timedelta(minutes=minutes_needed)

    @property
    def max_time_till_full_ff(self) -> datetime.timedelta:
        """
        Max required time for 0 to full energy (0/0 -> limit/limit) (last interval rounded up)
        :return:
        """
        return datetime.timedelta(minutes=round((self.energy.limit * 2 / self.energy.interval) + 0.49) * 6)

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
        if self.energy.limit - self.energy.interval <= self.energy.recoverable:
            if self.is_levelup_reachable:
                # 45xp till levelup, 50hp/6min, 500+500/500 energy = 500+450 >= 1000
                # 40xp till levelup, 50hp/6min, 450+500/500 energy = 500+400 >= 950
                # 25xp till levelup, 50hp/6min, 300+500/500 energy = 500+250 >= 800
                # 25xp till levelup, 50hp/6min, 300+200/500 energy = 500+250 >= 500
                return self.energy.limit + self.details.xp_till_level_up * 10 <= self.energy.available
        return False

    def get_article_comments(self, article_id: int = 2645676, page_id: int = 1) -> Response:
        return self._post_article_comments(article_id, page_id)

    def comment_article(self, article_id: int = 2645676, msg: str = None) -> Response:
        if msg is None:
            msg = self.eday
        r = self.get_article_comments(article_id, 2)
        r = self.get_article_comments(article_id, r.json()["pages"])
        comments = r.json()["comments"]
        if not comments[max(comments.keys())]["isMyComment"]:
            r = self.write_article_comment(msg, article_id)
        return r

    def write_article_comment(self, message: str, article_id: int, parent_id: int = None) -> Response:
        return self._post_article_comments_create(message, article_id, parent_id)

    def publish_article(self, title: str, content: str, kind: int) -> Response:
        kinds = {1: "First steps in eRepublik", 2: "Battle orders", 3: "Warfare analysis",
                 4: "Political debates and analysis", 5: "Financial business",
                 6: "Social interactions and entertainment"}
        if kind in kinds:
            return self._post_write_article(title, content, self.details.citizenship, kind)
        else:
            raise classes.ErepublikException(
                "Article kind must be one of:\n{}\n'{}' is not supported".format(
                    "\n".join(["{}: {}".format(k, v) for k, v in kinds.items()]),
                    kind
                )
            )

    def post_market_offer(self, industry: int, quality: int, amount: int, price: float) -> Response:
        if industry not in self.available_industries.values():
            self.write_log("Trying to sell unsupported industry {}".format(industry))

        data = {
            "country": self.details.citizenship,
            "industry": industry,
            "quality": quality,
            "amount": amount,
            "price": price,
            "buy": False,
        }
        ret = self._post_economy_marketplace_actions(**data)
        self.reporter.report_action("SELL_PRODUCT", ret.json())
        return ret

    def buy_from_market(self, offer: int, amount: int) -> dict:
        ret = self._post_economy_marketplace_actions(amount, True, offer=offer)
        json_ret = ret.json()
        if json_ret.get('error'):
            return json_ret
        else:
            self.details.cc = ret.json()['currency']
            self.details.gold = ret.json()['gold']
            r_json = ret.json()
            r_json.pop("offerUpdate", None)
            self.reporter.report_action("BUY_PRODUCT", ret.json())
        return json_ret

    def get_raw_surplus(self) -> (float, float):
        frm = 0.00
        wrm = 0.00
        self.update_companies()
        for cdata in sorted(self.my_companies.companies.values()):
            if cdata["industry_token"] == "FOOD":
                raw = frm
            elif cdata["industry_token"] == "WEAPON":
                raw = wrm
            else:
                continue
            effective_bonus = cdata["effective_bonus"]
            base_prod = float(cdata["base_production"])
            if cdata["is_raw"]:
                raw += base_prod * effective_bonus / 100
            else:
                raw -= effective_bonus / 100 * base_prod * cdata["upgrades"][str(cdata["quality"])]["raw_usage"]
            if cdata["industry_token"] == "FOOD":
                frm = raw
            elif cdata["industry_token"] == "WEAPON":
                wrm = raw
        return frm, wrm

    def assign_factory_to_holding(self, factory_id: int, holding_id: int) -> Response:
        """
        Assigns factory to new holding
        """
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
        return self._post_economy_create_company(industry_id, building_type)

    def dissolve_factory(self, factory_id: int) -> Response:
        return self._post_economy_sell_company(factory_id, self.details.pin, sell=False)

    @property
    def available_industries(self) -> Dict[str, int]:
        """
        Returns currently available industries as dict(name: id)
        :return: dict
        """
        return {"food": 1, "weapon": 2, "house": 4, "aircraft": 23,
                "foodRaw": 7, "weaponRaw": 12, "houseRaw": 17, "airplaneRaw": 24}

    def get_industry_id(self, industry_name: str) -> int:
        """
        Returns industry id
        :type industry_name: str
        :return: int
        """
        return self.available_industries.get(industry_name, 0)

    def buy_tg_contract(self) -> Response:
        ret = self._post_buy_gold_items('gold', "TrainingContract2", 1)
        self.reporter.report_action("BUY_TG_CONTRACT", ret.json())
        return ret

    def resign(self) -> bool:
        self.update_job_info()
        if self.r.json().get("isEmployee"):
            self.reporter.report_action("RESIGN", self.r.json())
            self._post_economy_resign()
            return True
        return False

    def find_new_job(self) -> Response:
        r = self._get_economy_job_market_json(self.details.current_country)
        jobs = r.json().get("jobs")
        data = dict(citizen=0, salary=10)
        for posting in jobs:
            salary = posting.get("netSalary")
            limit = posting.get("salaryLimit", 0)
            userid = posting.get("citizen").get("id")

            if (not limit or salary * 3 < limit) and salary > data["salary"]:
                data.update({"citizen": userid, "salary": salary})
        self.reporter.report_action("APPLYING_FOR_JOB", jobs, str(data['citizen']))
        return self._post_economy_job_market_apply(**data)

    def add_friend(self, player_id: int) -> Response:
        resp = self._get_citizen_hovercard(player_id)
        rjson = resp.json()
        if not any([rjson["isBanned"], rjson["isDead"], rjson["isFriend"], rjson["isOrg"], rjson["isSelf"]]):
            r = self._post_citizen_add_remove_friend(int(player_id), True)
            self.write_log("{:<64} (id:{:>11}) added as friend".format(rjson["name"], player_id))
            return r
        return resp

    def get_country_parties(self, country_id: int = None) -> dict:
        if country_id is None:
            country_id = self.details.citizenship
        r = self._get_rankings_parties(country_id)
        ret = {}
        for name, id_ in re.findall(r'<a class="dotted" title="([^"]+)" href="/en/party/[\w\d-]+-(\d+)/1">', r.text):
            ret.update({int(id_): name})
        return ret

    def _get_party_members(self, party_id: int) -> Dict[int, str]:
        ret = {}
        r = super()._get_party_members(party_id)
        for id_, name in re.findall(r'<a href="//www.erepublik.com/en/main/messages-compose/(\d+)" '
                                    r'title="([\w\d_ .]+)">', r.text):
            ret.update({id_: name})
        return ret

    def get_country_mus(self, country_id: int) -> Dict[int, str]:
        ret = {}
        r = self._get_leaderboards_damage_rankings(country_id)
        for data in r.json()["mu_filter"]:
            if data["id"]:
                ret.update({data["id"]: data["name"]})
        r = self._get_leaderboards_damage_aircraft_rankings(country_id)
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

    def send_mail(self, subject: str, msg: str, ids: List[int] = None):
        if ids is None:
            ids = [1620414, ]
        for player_id in ids:
            self._post_messages_compose(subject, msg, [player_id])

    def add_every_player_as_friend(self):
        cities = []
        cities_dict = {}
        self.write_log("WARNING! This will take a lot of time.")
        rj = self._post_travel_data(regionId=662, check="getCountryRegions").json()
        for region_data in rj.get("regions", {}).values():
            cities.append(region_data['cityId'])
            cities_dict.update({region_data['cityId']: region_data['cityName']})

        cities.sort(key=int)
        for city_id in cities:
            self.write_log("Adding friends from {} (id: {})".format(cities_dict[city_id], city_id))
            resp = self._get_city_data_residents(city_id).json()
            for resident in resp["widgets"]["residents"]["residents"]:
                self.add_friend(resident["citizenId"])
            for page in range(2, resp["widgets"]["residents"]["numResults"] // 10 + 2):
                r = self._get_city_data_residents(city_id, page)
                resp = r.json()
                for resident in resp["widgets"]["residents"]["residents"]:
                    self.add_friend(resident["citizenId"])

    def schedule_attack(self, war_id: int, region_id: int, region_name: str, at_time: datetime) -> None:
        if at_time:
            self.sleep(utils.get_sleep_seconds(at_time))
        self.get_csrf_token()
        self.launch_attack(war_id, region_id, region_name)

    def get_active_wars(self, country_id: int = None) -> List[int]:
        r = self._get_country_military(utils.COUNTRY_LINK.get(country_id or self.details.citizenship))
        all_war_ids = re.findall(r'//www\.erepublik\.com/en/wars/show/(\d+)"', r.text)
        return [int(wid) for wid in all_war_ids]

    def get_war_status(self, war_id: int) -> Dict[str, Union[bool, Dict[int, str]]]:
        r = self._get_wars_show(war_id)
        html = r.text
        ret = {}
        reg_re = re.compile(fr'data-war-id="{war_id}" data-region-id="(\d+)" data-region-name="([- \w]+)"')
        if reg_re.findall(html):
            ret.update(regions={}, can_attack=True)
            for reg in reg_re.findall(html):
                ret["regions"].update({str(reg[0]): reg[1]})
        elif re.search(r'<a href="//www.erepublik.com/en/military/battlefield/(\d+)" '
                       r'class="join" title="Join"><span>Join</span></a>', html):
            battle_id = re.search(r'<a href="//www.erepublik.com/en/military/battlefield/(\d+)" '
                                  r'class="join" title="Join"><span>Join</span></a>', html).group(1)
            ret.update(can_attack=False, battle_id=battle_id)
        else:
            ret.update(can_attack=False)
        return ret

    def get_last_battle_of_war_end_time(self, war_id: int) -> datetime:
        r = self._get_wars_show(war_id)
        html = r.text
        last_battle_id = int(re.search(r'<a href="//www.erepublik.com/en/military/battlefield/(\d+)">', html).group(1))
        console = self._post_military_battle_console(last_battle_id, 'warList', 1).json()
        battle = console.get('list')[0]
        return utils.localize_dt(datetime.datetime.strptime(battle.get('result').get('end'), "%Y-%m-%d %H:%M:%S"))

    def launch_attack(self, war_id: int, region_id: int, region_name: str):
        self._post_wars_attack_region(war_id, region_id, region_name)

    def state_update_repeater(self):
        try:
            start_time = self.now.replace(second=0, microsecond=0)
            if start_time.minute <= 30:
                start_time = start_time.replace(minute=30)
            else:
                start_time = start_time.replace(minute=0)
            while not self.stop_threads.is_set():
                self.update_citizen_info()
                start_time = utils.good_timedelta(start_time, datetime.timedelta(minutes=30))
                self.send_state_update()
                self.send_inventory_update()
                sleep_seconds = (start_time - self.now).total_seconds()
                self.stop_threads.wait(sleep_seconds if sleep_seconds > 0 else 0)
        except:
            self.report_error()

    def send_state_update(self):
        data = dict(xp=self.details.xp, cc=self.details.cc, gold=self.details.gold, pp=self.details.pp,
                    inv_total=self.inventory['total'], inv=self.inventory['used'], hp_limit=self.energy.limit,
                    hp_interval=self.energy.interval, hp_available=self.energy.available, food=self.food['total'], )
        self.reporter.send_state_update(**data)

    def send_inventory_update(self):
        j = self.update_inventory()
        active_items = {}
        for item in j.get("inventoryItems", {}).get("activeEnhancements", {}).get("items", {}).values():
            active_items.update({item['name']: item['active']['time_left']})
        final_items = {}

        for item in j.get("inventoryItems", {}).get("finalProducts", {}).get("items", {}).values():
            name = item['name']
            if item.get('type') == 'damageBoosters':
                delta = item['duration']
                if delta // 3600:
                    name += f" {delta // 3600}h"
                if delta // 60 % 60:
                    name += f" {delta // 60 % 60}m"
                if delta % 60:
                    name += f" {delta % 60}s"
            if item['amount']:
                final_items.update({name: item['amount']})

        raw_materials = {}
        for item in j.get("inventoryItems", {}).get("rawMaterials", {}).get("items", {}).values():
            name = item['name']
            if item['isPartial']:
                continue
            if item['amount']:
                raw_materials.update({name: item['amount']})

        to_report = dict(items=dict(active=active_items, final=final_items, raw=raw_materials), status=self.inventory)
        self.reporter.report_action("INVENTORY", json_val=to_report)

    def check_house_durability(self) -> Dict[int, datetime.datetime]:
        ret = {}
        inv = self.update_inventory()
        if "activeEnhancements" in inv.get("inventoryItems", {}):
            active = inv.get("inventoryItems", {}).get("activeEnhancements", {}).get("items", {})
            for q in range(1, 6):
                if "4_%i_active" % q in active:
                    till = utils.good_timedelta(self.now, datetime.timedelta(
                        seconds=active["4_%i_active" % q]["active"]["time_left"]))
                    ret.update({q: till})
        return ret

    def buy_and_activate_house(self, q: int) -> Dict[int, datetime.datetime]:
        inventory = self.update_inventory()
        ok_to_activate = False
        if not inventory.get("inventoryItems").get("finalProducts", {}).get("items", {}).get("4_{}".format(q)):
            offers = []
            countries = [self.details.citizenship, ]
            if self.details.current_country != self.details.citizenship:
                countries.append(self.details.current_country)
            for country in countries:
                offers += [self.get_market_offers(country, "house", q)]
            global_cheapest = self.get_market_offers(product="house", quality=q)
            cheapest_offer = sorted(offers, key=lambda o: o["price"])[0]
            region = self.get_country_travel_region(global_cheapest['country'])
            if global_cheapest['price'] + 200 < cheapest_offer['price'] and region:
                self._travel(global_cheapest['country'], region)
                buy = self.buy_from_market(global_cheapest['offer_id'], 1)
            else:
                buy = self.buy_from_market(cheapest_offer['offer_id'], 1)
            if buy["error"]:
                msg = "Unable to buy q{} house! \n{}".format(q, buy['message'])
                self.write_log(msg)
            else:
                ok_to_activate = True
        else:
            ok_to_activate = True
        if ok_to_activate:
            self.activate_house(q)
        return self.check_house_durability()

    def renew_houses(self, forced: bool = False) -> Dict[int, datetime.datetime]:
        """
        Renew all houses which endtime is in next 48h
        :param forced: if true - renew all houses
        :return:
        """
        house_durability = self.check_house_durability()
        for q, active_till in house_durability.items():
            if utils.good_timedelta(active_till, - datetime.timedelta(hours=48)) <= self.now or forced:
                house_durability = self.buy_and_activate_house(q)
        self.travel_to_residence()
        return house_durability

    def activate_house(self, quality: int) -> datetime.datetime:
        active_until = self.now
        r = self._post_economy_activate_house(quality)
        if r.json().get("status") and not r.json().get("error"):
            house = r.json()["inventoryItems"]["activeEnhancements"]["items"]["4_%i_active" % quality]
            active_until = utils.good_timedelta(active_until, datetime.timedelta(seconds=house["active"]["time_left"]))
        return active_until

    def collect_anniversary_reward(self) -> Response:
        return self._post_collect_anniversary_reward()

    def get_battle_round_data(self, battle_id: int, round_id: int, division: int = None) -> dict:
        battle = self.all_battles.get(battle_id)
        if not battle:
            return {}
        r = self._post_battle_console(battle_id, battle.zone_id, round_id, division, 1, True)
        return {battle.invader.id: r.json().get(str(battle.invader.id)).get("fighterData"),
                battle.defender.id: r.json().get(str(battle.defender.id)).get("fighterData")}

    def contribute_cc_to_country(self, amount=0.) -> bool:
        self.update_money()
        amount = int(amount)
        if self.details.cc < amount or amount < 20:
            return False
        data = dict(country=71, action='currency', value=amount)
        self.reporter.report_action("CONTRIBUTE_CC", data)
        r = self._post_country_donate(**data)
        return r.json().get('status') or not r.json().get('error')

    def contribute_food_to_country(self, amount: int = 0, quality: int = 1) -> bool:
        self.update_inventory()
        amount = amount // 1
        if self.food["q" + str(quality)] < amount or amount < 10:
            return False
        data = dict(country=71, action='food', value=amount, quality=quality)
        self.reporter.report_action("CONTRIBUTE_FOOD", data)
        r = self._post_country_donate(**data)
        return r.json().get('status') or not r.json().get('error')

    def contribute_gold_to_country(self, amount: int) -> bool:
        self.update_money()

        if self.details.cc < amount:
            return False
        data = dict(country=71, action='gold', value=amount)
        self.reporter.report_action("CONTRIBUTE_GOLD", data)
        r = self._post_country_donate(**data)
        return r.json().get('status') or not r.json().get('error')

    def write_on_country_wall(self, message: str) -> bool:
        self._get_main()
        post_to_wall_as = re.findall(r"""id="post_to_country_as".*?<option value="(\d?)">.*?</option>.*</select>""",
                                     self.r.text, re.S | re.M)
        r = self._post_country_post_create(message, max(post_to_wall_as, key=int) if post_to_wall_as else 0)
        return r.json()

    def report_error(self, msg: str = ""):
        utils.process_error(msg, self.name, sys.exc_info(), self, self.commit_id, False)

    def get_battle_top_10(self, battle_id: int) -> Dict[int, List[Tuple[int, int]]]:
        battle = self.all_battles.get(battle_id)
        round_id = battle.get('zone_id')
        division = self.division if round_id % 4 else 11

        resp = self._post_military_battle_console(battle_id, round_id, division).json()
        resp.pop('rounds', None)
        ret = dict()
        for country_id, data in resp.items():
            ret.update({int(country_id): []})
            for place in sorted(data.get("fighterData", {}).values(), key=lambda _: -_['raw_value']):
                ret[int(country_id)].append((place['citizenId'], place['raw_value']))

        return ret

    def to_json(self, indent: bool = False) -> str:
        return dumps(self.__dict__, cls=utils.MyJSONEncoder, indent=4 if indent else None, sort_keys=True)
