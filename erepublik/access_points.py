import datetime
import random
import time
from typing import Any, Dict, List, Mapping, Union

from requests import Response, Session

from erepublik import utils

__all__ = ['SlowRequests', 'CitizenAPI']


class SlowRequests(Session):
    last_time: datetime.datetime
    timeout = datetime.timedelta(milliseconds=500)
    uas = [
        # Chrome
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.138 Safari/537.36',  # noqa
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.106 Safari/537.36',  # noqa
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.88 Safari/537.36',  # noqa
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/77.0.3865.90 Safari/537.36',  # noqa
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.138 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.106 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.88 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/77.0.3865.90 Safari/537.36',

        # FireFox
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:76.0) Gecko/20100101 Firefox/76.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:75.0) Gecko/20100101 Firefox/75.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:74.0) Gecko/20100101 Firefox/74.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:73.0) Gecko/20100101 Firefox/73.0',
        'Mozilla/5.0 (X11; Linux x86_64; rv:76.0) Gecko/20100101 Firefox/76.0',
        'Mozilla/5.0 (X11; Linux x86_64; rv:75.0) Gecko/20100101 Firefox/75.0',
        'Mozilla/5.0 (X11; Linux x86_64; rv:74.0) Gecko/20100101 Firefox/74.0',
        'Mozilla/5.0 (X11; Linux x86_64; rv:73.0) Gecko/20100101 Firefox/73.0',
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
                    request_log_name=self.request_log_name, debug=self.debug)

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
            kwargs.pop('allow_redirects', None)
            if kwargs:
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

            file_data = {
                "path": 'debug/requests',
                "time": self.last_time.strftime('%Y/%m/%d/%H-%M-%S'),
                "name": utils.slugify(url[len(Citizen.url):]),
                "extra": "_REDIRECT" if redirect else ""
            }

            try:
                utils.json.loads(resp.text)
                file_data.update({"ext": "json"})
            except utils.json.JSONDecodeError:
                file_data.update({"ext": "html"})

            filename = 'debug/requests/{time}_{name}{extra}.{ext}'.format(**file_data)
            with open(utils.get_file(filename), 'wb') as f:
                f.write(resp.text.encode('utf-8'))


class CitizenBaseAPI:
    url: str = "https://www.erepublik.com/en"
    _req: SlowRequests = None
    token: str = ""

    def __init__(self):
        """ Class for unifying eRepublik known endpoints and their required/optional parameters """
        self._req = SlowRequests()

    def post(self, url: str, data=None, json=None, **kwargs) -> Response:
        return self._req.post(url, data, json, **kwargs)

    def get(self, url: str, **kwargs) -> Response:
        return self._req.get(url, **kwargs)

    def _get_main(self) -> Response:
        return self.get(self.url)


class ErepublikAnniversaryAPI(CitizenBaseAPI):
    def _post_main_collect_anniversary_reward(self) -> Response:
        return self.post("{}/main/collect-anniversary-reward".format(self.url), data={"_token": self.token})

    # 12th anniversary endpoints
    def _get_anniversary_quest_data(self) -> Response:
        return self.get("{}/main/anniversaryQuestData".format(self.url))

    def _post_map_rewards_unlock(self, node_id: int) -> Response:
        data = {'nodeId': node_id, '_token': self.token}
        return self.post("{}/main/map-rewards-unlock".format(self.url), data=data)

    def _post_map_rewards_speedup(self, node_id: int, currency_amount: int) -> Response:
        data = {'nodeId': node_id, '_token': self.token, "currencyCost": currency_amount}
        return self.post("{}/main/map-rewards-speedup".format(self.url), data=data)

    def _post_map_rewards_claim(self, node_id: int) -> Response:
        data = {'nodeId': node_id, '_token': self.token}
        return self.post("{}/main/map-rewards-claim".format(self.url), data=data)

    def _post_main_wheel_of_fortune_spin(self, cost) -> Response:
        return self.post(f"{self.url}/wheeloffortune-spin", data={'_token': self.token, "cost": cost})

    def _post_main_wheel_of_fortune_build(self) -> Response:
        return self.post(f"{self.url}/wheeloffortune-build", data={'_token': self.token})


class ErepublikArticleAPI(CitizenBaseAPI):
    def _get_main_article_json(self, article_id: int) -> Response:
        return self.get("{}/main/articleJson/{}".format(self.url, article_id))

    def _post_main_article_comments(self, article: int, page: int = 1) -> Response:
        data = dict(_token=self.token, articleId=article, page=page)
        if page:
            data.update({'page': page})
        return self.post("{}/main/articleComments".format(self.url), data=data)

    def _post_main_article_comments_create(self, message: str, article: int, parent: int = 0) -> Response:
        data = dict(_token=self.token, message=message, articleId=article)
        if parent:
            data.update({"parentId": parent})
        return self.post("{}/main/articleComments/create".format(self.url), data=data)

    def _post_main_donate_article(self, article_id: int, amount: int) -> Response:
        data = dict(_token=self.token, articleId=article_id, amount=amount)
        return self.post("{}/main/donate-article".format(self.url), data=data)

    def _post_main_write_article(self, title: str, content: str, country: int, kind: int) -> Response:
        data = dict(_token=self.token, article_name=title, article_body=content, article_location=country,
                    article_category=kind)
        return self.post("{}/main/write-article".format(self.url), data=data)

    def _post_main_vote_article(self, article_id: int) -> Response:
        data = dict(_token=self.token, articleId=article_id)
        return self.post("{}/main/vote-article".format(self.url), data=data)


class ErepublikCompanyAPI(CitizenBaseAPI):
    def _post_economy_assign_to_holding(self, factory: int, holding: int) -> Response:
        data = dict(_token=self.token, factoryId=factory, action="assign", holdingCompanyId=holding)
        return self.post("{}/economy/assign-to-holding".format(self.url), data=data)

    def _post_economy_create_company(self, industry: int, building_type: int = 1) -> Response:
        data = {"_token": self.token, "company[industry_id]": industry, "company[building_type]": building_type}
        return self.post("{}/economy/create-company".format(self.url), data=data,
                         headers={"Referer": "{}/economy/create-company".format(self.url)})

    def _get_economy_inventory_items(self) -> Response:
        return self.get("{}/economy/inventory-items/".format(self.url))

    def _get_economy_job_market_json(self, country: int) -> Response:
        return self.get("{}/economy/job-market-json/{}/1/desc".format(self.url, country))

    def _get_economy_my_companies(self) -> Response:
        return self.get("{}/economy/myCompanies".format(self.url))

    def _post_economy_train(self, tg_ids: List[int]) -> Response:
        data: Dict[str, Union[int, str]] = {}
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
        data: Dict[str, Union[int, str]] = dict(action_type=action_type, _token=self.token)
        if action_type == "production":
            if employ is None:
                employ = {}
            if wam is None:
                wam = []
            max_idx = 0
            for company_id in sorted(wam or []):
                data.update({
                    f"companies[{max_idx}][id]": company_id,
                    f"companies[{max_idx}][employee_works]": employ.pop(company_id, 0),
                    f"companies[{max_idx}][own_work]": 1
                })
                max_idx += 1
            for company_id in sorted(employ or []):
                data.update({
                    f"companies[{max_idx}][id]": company_id,
                    f"companies[{max_idx}][employee_works]": employ.pop(company_id, 0),
                    f"companies[{max_idx}][own_work]": 0
                })
                max_idx += 1
        return self.post("{}/economy/work".format(self.url), data=data)

    def _post_economy_work_overtime(self) -> Response:
        data = dict(action_type="workOvertime", _token=self.token)
        return self.post("{}/economy/workOvertime".format(self.url), data=data)

    def _post_economy_job_market_apply(self, citizen: int, salary: float) -> Response:
        data = dict(_token=self.token, citizenId=citizen, salary=salary)
        return self.post("{}/economy/job-market-apply".format(self.url), data=data)

    def _post_economy_resign(self) -> Response:
        return self.post("{}/economy/resign".format(self.url),
                         headers={"Content-Type": "application/x-www-form-urlencoded"},
                         data={"_token": self.token, "action_type": "resign"})

    def _post_economy_sell_company(self, factory: int, pin: int = None, sell: bool = True) -> Response:
        data = dict(_token=self.token, pin="" if pin is None else pin)
        if sell:
            data.update({"sell": "sell"})
        else:
            data.update({"dissolve": factory})
        return self.post("{}/economy/sell-company/{}".format(self.url, factory),
                         data=data, headers={"Referer": self.url})


class ErepublikCountryAPI(CitizenBaseAPI):
    def _get_country_military(self, country: str) -> Response:
        return self.get("{}/country/military/{}".format(self.url, country))

    def _post_main_country_donate(self, country: int, action: str, value: Union[int, float],
                                  quality: int = None) -> Response:
        json = dict(countryId=country, action=action, _token=self.token, value=value, quality=quality)
        return self.post("{}/main/country-donate".format(self.url), data=json,
                         headers={"Referer": "{}/country/economy/Latvia".format(self.url)})


class ErepublikEconomyAPI(CitizenBaseAPI):
    def _get_economy_citizen_accounts(self, organisation_id: int) -> Response:
        return self.get("{}/economy/citizen-accounts/{}".format(self.url, organisation_id))

    def _get_economy_my_market_offers(self) -> Response:
        return self.get("{}/economy/myMarketOffers".format(self.url))

    def _get_main_job_data(self) -> Response:
        return self.get("{}/main/job-data".format(self.url))

    def _post_main_buy_gold_items(self, currency: str, item: str, amount: int) -> Response:
        data = dict(itemId=item, currency=currency, amount=amount, _token=self.token)
        return self.post("{}/main/buyGoldItems".format(self.url), data=data)

    def _post_economy_activate_booster(self, quality: int, duration: int, kind: str) -> Response:
        data = dict(type=kind, quality=quality, duration=duration, fromInventory=True)
        return self.post("{}/economy/activateBooster".format(self.url), data=data)

    def _post_economy_activate_house(self, quality: int) -> Response:
        data = {"action": "activate", "quality": quality, "type": "house", "_token": self.token}
        return self.post("{}/economy/activateHouse".format(self.url), data=data)

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

    def _post_economy_game_tokens_market(self, action: str) -> Response:
        assert action in ['retrieve', ]
        data = dict(_token=self.token, action=action)
        return self.post("{}/economy/gameTokensMarketAjax".format(self.url), data=data)

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


class ErepublikLeaderBoardAPI(CitizenBaseAPI):
    def _get_main_leaderboards_damage_aircraft_rankings(self, country: int, weeks: int = 0, mu: int = 0) -> Response:
        data = (country, weeks, mu)
        return self.get("{}/main/leaderboards-damage-aircraft-rankings/{}/{}/{}/0".format(self.url, *data))

    def _get_main_leaderboards_damage_rankings(self, country: int, weeks: int = 0, mu: int = 0,
                                               div: int = 0) -> Response:
        data = (country, weeks, mu, div)
        return self.get("{}/main/leaderboards-damage-rankings/{}/{}/{}/{}".format(self.url, *data))

    def _get_main_leaderboards_kills_aircraft_rankings(self, country: int, weeks: int = 0, mu: int = 0) -> Response:
        data = (country, weeks, mu)
        return self.get("{}/main/leaderboards-kills-aircraft-rankings/{}/{}/{}/0".format(self.url, *data))

    def _get_main_leaderboards_kills_rankings(self, country: int, weeks: int = 0, mu: int = 0,
                                              div: int = 0) -> Response:
        data = (country, weeks, mu, div)
        return self.get("{}/main/leaderboards-kills-rankings/{}/{}/{}/{}".format(self.url, *data))


class ErepublikLocationAPI(CitizenBaseAPI):
    def _get_main_city_data_residents(self, city: int, page: int = 1, params: Mapping[str, Any] = None) -> Response:
        if params is None:
            params = {}
        return self.get("{}/main/city-data/{}/residents".format(self.url, city), params={"currentPage": page, **params})


class ErepublikMilitaryAPI(CitizenBaseAPI):
    def _get_military_battlefield_choose_side(self, battle: int, side: int) -> Response:
        return self.get("{}/military/battlefield-choose-side/{}/{}".format(self.url, battle, side))

    def _get_military_show_weapons(self, battle: int) -> Response:
        return self.get("{}/military/show-weapons".format(self.url), params={'_token': self.token, 'battleId': battle})

    def _get_military_campaigns(self) -> Response:
        return self.get("{}/military/campaigns-new/".format(self.url))

    def _get_military_campaigns_json_list(self) -> Response:
        return self.get("{}/military/campaignsJson/list".format(self.url))

    def _get_military_campaigns_json_citizen(self) -> Response:
        return self.get("{}/military/campaignsJson/citizen".format(self.url))

    def _get_military_unit_data(self, unit_id: int, **kwargs) -> Response:
        params = {"groupId": unit_id, "panel": "members", **kwargs}
        return self.get("{}/military/military-unit-data/".format(self.url), params=params)

    def _post_main_activate_battle_effect(self, battle: int, kind: str, citizen_id: int) -> Response:
        data = dict(battleId=battle, citizenId=citizen_id, type=kind, _token=self.token)
        return self.post("{}/main/fight-activateBattleEffect".format(self.url), data=data)

    def _post_main_battlefield_travel(self, side_id: int, battle_id: int) -> Response:
        data = dict(_token=self.token, sideCountryId=side_id, battleId=battle_id)
        return self.post("{}/main/battlefieldTravel".format(self.url), data=data)

    def _post_main_battlefield_change_division(self, battle_id: int, division_id: int) -> Response:
        data = dict(_token=self.token, battleZoneId=division_id, battleId=battle_id)
        return self.post("{}/main/battlefieldTravel".format(self.url), data=data)

    def _get_wars_show(self, war_id: int) -> Response:
        return self.get("{}/wars/show/{}".format(self.url, war_id))

    def _post_military_fight_activate_booster(self, battle: int, quality: int, duration: int, kind: str) -> Response:
        data = dict(type=kind, quality=quality, duration=duration, battleId=battle, _token=self.token)
        return self.post("{}/military/fight-activateBooster".format(self.url), data=data)

    def _post_military_change_weapon(self, battle: int, battle_zone: int, weapon_level: int, ) -> Response:
        data = dict(battleId=battle, _token=self.token, battleZoneId=battle_zone, customizationLevel=weapon_level)
        return self.post("{}/military/change-weapon".format(self.url), data=data)

    def _post_military_battle_console(self, battle_id: int, action: str, page: int = 1, **kwargs) -> Response:
        data = dict(battleId=battle_id, action=action, _token=self.token)
        if action == "battleStatistics":
            data.update(round=kwargs["round_id"], zoneId=kwargs["round_id"], leftPage=page, rightPage=page,
                        division=kwargs["division"], type=kwargs.get("type", 'damage'), )
        elif action == "warList":
            data.update(page=page)
        return self.post("{}/military/battle-console".format(self.url), data=data)

    def _post_military_deploy_bomb(self, battle_id: int, bomb_id: int) -> Response:
        data = dict(battleId=battle_id, bombId=bomb_id, _token=self.token)
        return self.post("{}/military/deploy-bomb".format(self.url), data=data)

    def _post_military_fight_air(self, battle_id: int, side_id: int, zone_id: int) -> Response:
        data = dict(sideId=side_id, battleId=battle_id, _token=self.token, battleZoneId=zone_id)
        return self.post("{}/military/fight-shoooot/{}".format(self.url, battle_id), data=data)

    def _post_military_fight_ground(self, battle_id: int, side_id: int, zone_id: int) -> Response:
        data = dict(sideId=side_id, battleId=battle_id, _token=self.token, battleZoneId=zone_id)
        return self.post("{}/military/fight-shooot/{}".format(self.url, battle_id), data=data)

    def _post_fight_deploy_deploy_report_data(self, deployment_id: int):
        data = dict(_token=self.token, deploymentId=deployment_id)
        return self.post(f"{self.url}/military/fightDeploy-deployReportData", json=data)


class ErepublikPoliticsAPI(CitizenBaseAPI):
    def _get_candidate_party(self, party_slug: str) -> Response:
        return self.post("{}/candidate/{}".format(self.url, party_slug))

    def _get_main_party_members(self, party: int) -> Response:
        return self.get("{}/main/party-members/{}".format(self.url, party))

    def _get_main_rankings_parties(self, country: int) -> Response:
        return self.get("{}/main/rankings-parties/1/{}".format(self.url, country))

    def _post_candidate_for_congress(self, presentation: str = "") -> Response:
        data = dict(_token=self.token, presentation=presentation)
        return self.post("{}/candidate-for-congress".format(self.url), data=data)


class ErepublikPresidentAPI(CitizenBaseAPI):
    def _post_wars_attack_region(self, war_id: int, region_id: int, region_name: str) -> Response:
        data = {'_token': self.token, 'warId': war_id, 'regionName': region_name, 'regionNameConfirm': region_name}
        return self.post('{}/wars/attack-region/{}/{}'.format(self.url, war_id, region_id), data=data)

    def _post_new_war(self, self_country_id: int, attack_country_id: int, debate: str = "") -> Response:
        data = dict(requirments=1, _token=self.token, debate=debate,
                    countryNameConfirm=utils.COUNTRY_LINK[attack_country_id])
        return self.post("{}/{}/new-war".format(self.url, utils.COUNTRY_LINK[self_country_id]), data=data)

    def _post_new_donation(self, country_id: int, amount: int, org_name: str, debate: str = "") -> Response:
        data = dict(requirments=1, _token=self.token, debate=debate, currency=1, value=amount, commit='Propose',
                    type_name=org_name)
        return self.post("{}/{}/new-donation".format(self.url, utils.COUNTRY_LINK[country_id]), data=data)


class ErepublikProfileAPI(CitizenBaseAPI):
    def _get_main_citizen_hovercard(self, citizen: int) -> Response:
        return self.get("{}/main/citizen-hovercard/{}".format(self.url, citizen))

    def _get_main_citizen_profile_json(self, player_id: int) -> Response:
        return self.get("{}/main/citizen-profile-json/{}".format(self.url, player_id))

    def _get_main_citizen_notifications(self) -> Response:
        return self.get("{}/main/citizenDailyAssistant".format(self.url))

    def _get_main_citizen_daily_assistant(self) -> Response:
        return self.get("{}/main/citizenNotifications".format(self.url))

    def _get_main_messages_paginated(self, page: int = 1) -> Response:
        return self.get("{}/main/messages-paginated/{}".format(self.url, page))

    def _get_main_money_donation_accept(self, donation_id: int) -> Response:
        return self.get("{}/main/money-donation/accept/{}".format(self.url, donation_id), params={"_token": self.token})

    def _get_main_money_donation_reject(self, donation_id: int) -> Response:
        return self.get("{}/main/money-donation/reject/{}".format(self.url, donation_id), params={"_token": self.token})

    def _get_main_notifications_ajax_community(self, page: int = 1) -> Response:
        return self.get("{}/main/notificationsAjax/community/{}".format(self.url, page))

    def _get_main_notifications_ajax_system(self, page: int = 1) -> Response:
        return self.get("{}/main/notificationsAjax/system/{}".format(self.url, page))

    def _get_main_notifications_ajax_report(self, page: int = 1) -> Response:
        return self.get("{}/main/notificationsAjax/report/{}".format(self.url, page))

    def _get_main_training_grounds_json(self) -> Response:
        return self.get("{}/main/training-grounds-json".format(self.url))

    def _get_main_weekly_challenge_data(self) -> Response:
        return self.get("{}/main/weekly-challenge-data".format(self.url))

    def _post_main_citizen_add_remove_friend(self, citizen: int, add: bool) -> Response:
        data = dict(_token=self.token, citizenId=citizen, url="//www.erepublik.com/en/main/citizen-addRemoveFriend")
        if add:
            data.update({"action": "addFriend"})
        else:
            data.update({"action": "removeFriend"})
        return self.post("{}/main/citizen-addRemoveFriend".format(self.url), data=data)

    def _post_main_daily_task_reward(self) -> Response:
        return self.post("{}/main/daily-tasks-reward".format(self.url), data=dict(_token=self.token))

    def _post_delete_message(self, msg_id: list) -> Response:
        data = {"_token": self.token, "delete_message[]": msg_id}
        return self.post("{}/main/messages-delete".format(self.url), data)

    def _post_eat(self, color: str) -> Response:
        data = dict(_token=self.token, buttonColor=color)
        return self.post("{}/main/eat".format(self.url), params=data)

    def _post_main_global_alerts_close(self, alert_id: int) -> Response:
        data = dict(_token=self.token, alert_id=alert_id)
        return self.post("{}/main/global-alerts/close".format(self.url), data=data)

    def _post_forgot_password(self, email: str) -> Response:
        data = dict(_token=self.token, email=email, commit="Reset password")
        return self.post("{}/forgot-password".format(self.url), data=data)

    def _post_login(self, email: str, password: str) -> Response:
        data = dict(csrf_token=self.token, citizen_email=email, citizen_password=password, remember='on')
        return self.post("{}/login".format(self.url), data=data)

    def _post_main_messages_alert(self, notification_ids: List[int]) -> Response:
        data = {"_token": self.token, "delete_alerts[]": notification_ids, "deleteAllAlerts": "1", "delete": "Delete"}
        return self.post("{}/main/messages-alerts/1".format(self.url), data=data)

    def _post_main_notifications_ajax_community(self, notification_ids: List[int], page: int = 1) -> Response:
        data = {"_token": self.token, "delete_alerts[]": notification_ids}
        return self.post("{}/main/notificationsAjax/community/{}".format(self.url, page), data=data)

    def _post_main_notifications_ajax_system(self, notification_ids: List[int], page: int = 1) -> Response:
        data = {"_token": self.token, "delete_alerts[]": notification_ids}
        return self.post("{}/main/notificationsAjax/system/{}".format(self.url, page), data=data)

    def _post_main_notifications_ajax_report(self, notification_ids: List[int], page: int = 1) -> Response:
        data = {"_token": self.token, "delete_alerts[]": notification_ids}
        return self.post("{}/main/notificationsAjax/report/{}".format(self.url, page), data=data)

    def _post_main_messages_compose(self, subject: str, body: str, citizens: List[int]) -> Response:
        url_pk = 0 if len(citizens) > 1 else str(citizens[0])
        data = dict(citizen_name=",".join([str(x) for x in citizens]),
                    citizen_subject=subject, _token=self.token, citizen_message=body)
        return self.post("{}/main/messages-compose/{}".format(self.url, url_pk), data=data)

    def _post_military_group_missions(self) -> Response:
        data = dict(action="check", _token=self.token)
        return self.post("{}/military/group-missions".format(self.url), data=data)

    def _post_main_weekly_challenge_reward(self, reward_id: int) -> Response:
        data = dict(_token=self.token, rewardId=reward_id)
        return self.post("{}/main/weekly-challenge-collect-reward".format(self.url), data=data)


class ErepublikTravelAPI(CitizenBaseAPI):
    def _post_main_travel(self, check: str, **kwargs) -> Response:
        data = dict(_token=self.token, check=check, **kwargs)
        return self.post("{}/main/travel".format(self.url), data=data)

    def _post_main_travel_data(self, **kwargs) -> Response:
        return self.post("{}/main/travelData".format(self.url), data=dict(_token=self.token, **kwargs))


class ErepublikWallPostAPI(CitizenBaseAPI):
    # ## Country

    def _post_main_country_comment_retrieve(self, post_id: int) -> Response:
        data = {"_token": self.token, "postId": post_id}
        return self.post("{}/main/country-comment/retrieve/json".format(self.url), data=data)

    def _post_main_country_comment_create(self, post_id: int, comment_message: str) -> Response:
        data = {"_token": self.token, "postId": post_id, 'comment_message': comment_message}
        return self.post("{}/main/country-comment/create/json".format(self.url), data=data)

    def _post_main_country_post_create(self, body: str, post_as: int) -> Response:
        data = {"_token": self.token, "post_message": body, "post_as": post_as}
        return self.post("{}/main/country-post/create/json".format(self.url), data=data)

    def _post_main_country_post_retrieve(self) -> Response:
        data = {"_token": self.token, "page": 1, "switchedFrom": False}
        return self.post("{}/main/country-post/retrieve/json".format(self.url), data=data)

    # ## Military Unit

    def _post_main_military_unit_comment_retrieve(self, post_id: int) -> Response:
        data = {"_token": self.token, "postId": post_id}
        return self.post("{}/main/military-unit-comment/retrieve/json".format(self.url), data=data)

    def _post_main_military_unit_comment_create(self, post_id: int, comment_message: str) -> Response:
        data = {"_token": self.token, "postId": post_id, 'comment_message': comment_message}
        return self.post("{}/main/military-unit-comment/create/json".format(self.url), data=data)

    def _post_main_military_unit_post_create(self, body: str, post_as: int) -> Response:
        data = {"_token": self.token, "post_message": body, "post_as": post_as}
        return self.post("{}/main/military-unit-post/create/json".format(self.url), data=data)

    def _post_main_military_unit_post_retrieve(self) -> Response:
        data = {"_token": self.token, "page": 1, "switchedFrom": False}
        return self.post("{}/main/military-unit-post/retrieve/json".format(self.url), data=data)

    # ## Party

    def _post_main_party_comment_retrieve(self, post_id: int) -> Response:
        data = {"_token": self.token, "postId": post_id}
        return self.post("{}/main/party-comment/retrieve/json".format(self.url), data=data)

    def _post_main_party_comment_create(self, post_id: int, comment_message: str) -> Response:
        data = {"_token": self.token, "postId": post_id, 'comment_message': comment_message}
        return self.post("{}/main/party-comment/create/json".format(self.url), data=data)

    def _post_main_party_post_create(self, body: str) -> Response:
        data = {"_token": self.token, "post_message": body}
        return self.post("{}/main/party-post/create/json".format(self.url), data=data)

    def _post_main_party_post_retrieve(self) -> Response:
        data = {"_token": self.token, "page": 1, "switchedFrom": False}
        return self.post("{}/main/party-post/retrieve/json".format(self.url), data=data)

    # ## Friend's Wall

    def _post_main_wall_comment_retrieve(self, post_id: int) -> Response:
        data = {"_token": self.token, "postId": post_id}
        return self.post("{}/main/wall-comment/retrieve/json".format(self.url), data=data)

    def _post_main_wall_comment_create(self, post_id: int, comment_message: str) -> Response:
        data = {"_token": self.token, "postId": post_id, 'comment_message': comment_message}
        return self.post("{}/main/wall-comment/create/json".format(self.url), data=data)

    def _post_main_wall_post_create(self, body: str) -> Response:
        data = {"_token": self.token, "post_message": body}
        return self.post("{}/main/wall-post/create/json".format(self.url), data=data)

    def _post_main_wall_post_retrieve(self) -> Response:
        data = {"_token": self.token, "page": 1, "switchedFrom": False}
        return self.post("{}/main/wall-post/retrieve/json".format(self.url), data=data)

    # ## Medal posting
    def _post_main_wall_post_automatic(self, message: str, achievement_id: int) -> Response:
        return self.post("{}/main/wall-post/automatic".format(self.url), data=dict(_token=self.token, message=message,
                                                                                   achievementId=achievement_id))


class CitizenAPI(
    ErepublikArticleAPI, ErepublikCountryAPI, ErepublikCompanyAPI, ErepublikEconomyAPI,
    ErepublikLeaderBoardAPI, ErepublikLocationAPI, ErepublikMilitaryAPI, ErepublikProfileAPI,
    ErepublikPresidentAPI, ErepublikPoliticsAPI, ErepublikAnniversaryAPI, ErepublikWallPostAPI,
    ErepublikTravelAPI
):
    pass
