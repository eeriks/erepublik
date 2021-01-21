import datetime
import random
import time
from typing import Any, Dict, List, Mapping, Union

from requests import Response, Session

from . import constants, utils

__all__ = ['SlowRequests', 'CitizenAPI']


class SlowRequests(Session):
    last_time: datetime.datetime
    timeout: datetime.timedelta = datetime.timedelta(milliseconds=500)
    _uas: List[str] = [
        # Chrome
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.141 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.183 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.125 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.138 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.141 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.183 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.125 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.138 Safari/537.36',

        # FireFox
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:84.0) Gecko/20100101 Firefox/84.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:83.0) Gecko/20100101 Firefox/83.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:82.0) Gecko/20100101 Firefox/82.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:81.0) Gecko/20100101 Firefox/81.0',
        'Mozilla/5.0 (X11; Linux x86_64; rv:84.0) Gecko/20100101 Firefox/84.0',
        'Mozilla/5.0 (X11; Linux x86_64; rv:83.0) Gecko/20100101 Firefox/83.0',
        'Mozilla/5.0 (X11; Linux x86_64; rv:82.0) Gecko/20100101 Firefox/82.0',
        'Mozilla/5.0 (X11; Linux x86_64; rv:81.0) Gecko/20100101 Firefox/81.0',
    ]
    debug: bool = False

    def __init__(self, proxies: Dict[str, str] = None, user_agent: str = None):
        super().__init__()
        if proxies:
            self.proxies = proxies
        if user_agent is None:
            user_agent = random.choice(self._uas)
        self.request_log_name = utils.get_file(utils.now().strftime("debug/requests_%Y-%m-%d.log"))
        self.last_time = utils.now()
        self.headers.update({'User-Agent': user_agent})

    @property
    def as_dict(self):
        return dict(last_time=self.last_time, timeout=self.timeout, cookies=self.cookies.get_dict(), debug=self.debug,
                    user_agent=self.headers['User-Agent'], request_log_name=self.request_log_name, proxies=self.proxies)

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
                args.update({'data': data})

            if json:
                args.update({'json': json})

            if params:
                args.update({'params': params})

            body = f"[{utils.now().strftime('%F %T')}]\tURL: '{url}'\tMETHOD: {method}\tARGS: {args}\n"
            with open(self.request_log_name, 'ab') as file:
                file.write(body.encode("UTF-8"))
            pass

    def _log_response(self, url, resp, redirect: bool = False):
        from erepublik import Citizen
        if self.debug:
            if resp.history and not redirect:
                for hist_resp in resp.history:
                    self._log_request(hist_resp.request.url, 'REDIRECT')
                    self._log_response(hist_resp.request.url, hist_resp, redirect=True)

            fd_path = 'debug/requests'
            fd_time = self.last_time.strftime('%Y/%m/%d/%H-%M-%S')
            fd_name = utils.slugify(url[len(Citizen.url):])
            fd_extra = '_REDIRECT' if redirect else ""

            try:
                utils.json.loads(resp.text)
                fd_ext = 'json'
            except utils.json.JSONDecodeError:
                fd_ext = 'html'

            filename = f'{fd_path}/{fd_time}_{fd_name}{fd_extra}.{fd_ext}'
            utils.write_file(filename, resp.text)
        pass


class CitizenBaseAPI:
    url: str = "https://www.erepublik.com/en"
    _req: SlowRequests
    token: str

    def __init__(self):
        """ Class for unifying eRepublik known endpoints and their required/optional parameters """
        self._req = SlowRequests()
        self.token = ""

    @property
    def as_dict(self):
        return dict(url=self.url, request=self._req.as_dict, token=self.token)

    def post(self, url: str, data=None, json=None, **kwargs) -> Response:
        return self._req.post(url, data, json, **kwargs)

    def get(self, url: str, **kwargs) -> Response:
        return self._req.get(url, **kwargs)

    def _get_main(self) -> Response:
        return self.get(self.url)

    def set_socks_proxy(self, host: str, port: int, username: str = None, password: str = None):
        url = f'socks5://{username}:{password}@{host}:{port}' if username and password else f'socks5://{host}:{port}'
        self._req.proxies = dict(http=url, https=url)

    def set_http_proxy(self, host: str, port: int, username: str = None, password: str = None):
        url = f'http://{username}:{password}@{host}:{port}' if username and password else f'socks5://{host}:{port}'
        self._req.proxies = dict(http=url)


class ErepublikAnniversaryAPI(CitizenBaseAPI):
    def _post_main_collect_anniversary_reward(self) -> Response:
        return self.post(f"{self.url}/main/collect-anniversary-reward", data={'_token': self.token})

    # 12th anniversary endpoints
    def _get_anniversary_quest_data(self) -> Response:
        return self.get(f"{self.url}/main/anniversaryQuestData")

    def _post_map_rewards_unlock(self, node_id: int) -> Response:
        data = {'nodeId': node_id, '_token': self.token}
        return self.post(f"{self.url}/main/map-rewards-unlock", data=data)

    def _post_map_rewards_speedup(self, node_id: int, currency_amount: int) -> Response:
        data = {'nodeId': node_id, '_token': self.token, 'currencyCost': currency_amount}
        return self.post(f"{self.url}/main/map-rewards-speedup", data=data)

    def _post_map_rewards_claim(self, node_id: int, extra: bool = False) -> Response:
        data = {'nodeId': node_id, '_token': self.token}
        if extra:
            data['claimExtra'] = 1
        return self.post(f"{self.url}/main/map-rewards-claim", data=data)

    def _post_main_wheel_of_fortune_spin(self, cost) -> Response:
        return self.post(f"{self.url}/main/wheeloffortune-spin", data={'_token': self.token, '_currentCost': cost})

    def _post_main_wheel_of_fortune_build(self) -> Response:
        return self.post(f"{self.url}/main/wheeloffortune-build", data={'_token': self.token})


class ErepublikArticleAPI(CitizenBaseAPI):
    def _get_main_article_json(self, article_id: int) -> Response:
        return self.get(f"{self.url}/main/articleJson/{article_id}")

    def _get_main_delete_article(self, article_id: int) -> Response:
        return self.get(f"{self.url}/main/delete-article/{article_id}/1")

    def _post_main_article_comments(self, article_id: int, page: int = 1) -> Response:
        data = dict(_token=self.token, articleId=article_id, page=page)
        if page:
            data.update({'page': page})
        return self.post(f"{self.url}/main/articleComments", data=data)

    def _post_main_article_comments_create(self, message: str, article_id: int, parent: int = 0) -> Response:
        data = dict(_token=self.token, message=message, articleId=article_id)
        if parent:
            data.update({'parentId': parent})
        return self.post(f"{self.url}/main/articleComments/create", data=data)

    def _post_main_donate_article(self, article_id: int, amount: int) -> Response:
        data = dict(_token=self.token, articleId=article_id, amount=amount)
        return self.post(f"{self.url}/main/donate-article", data=data)

    def _post_main_write_article(self, title: str, content: str, country_id: int, kind_id: int) -> Response:
        data = dict(_token=self.token, article_name=title, article_body=content, article_location=country_id,
                    article_category=kind_id)
        return self.post(f"{self.url}/main/write-article", data=data)

    def _post_main_vote_article(self, article_id: int) -> Response:
        data = dict(_token=self.token, articleId=article_id)
        return self.post(f"{self.url}/main/vote-article", data=data)


class ErepublikCompanyAPI(CitizenBaseAPI):
    def _post_economy_assign_to_holding(self, factory_id: int, holding_id: int) -> Response:
        data = dict(_token=self.token, factoryId=factory_id, action='assign', holdingCompanyId=holding_id)
        return self.post(f"{self.url}/economy/assign-to-holding", data=data)

    def _post_economy_create_company(self, industry_id: int, building_type: int = 1) -> Response:
        data = {'_token': self.token, "company[industry_id]": industry_id, "company[building_type]": building_type}
        return self.post(f"{self.url}/economy/create-company", data=data,
                         headers={'Referer': f"{self.url}/economy/create-company"})

    def _get_economy_inventory_items(self) -> Response:
        return self.get(f"{self.url}/economy/inventory-items/")

    def _get_economy_job_market_json(self, country_id: int) -> Response:
        return self.get(f"{self.url}/economy/job-market-json/{country_id}/1/desc")

    def _get_economy_my_companies(self) -> Response:
        return self.get(f"{self.url}/economy/myCompanies")

    def _post_economy_train(self, tg_ids: List[int]) -> Response:
        data: Dict[str, Union[int, str]] = {}
        for idx, tg_id in enumerate(tg_ids):
            data["grounds[%i][id]" % idx] = tg_id
            data["grounds[%i][train]" % idx] = 1
        if data:
            data['_token'] = self.token
        return self.post(f"{self.url}/economy/train", data=data)

    def _post_economy_upgrade_company(self, factory: int, level: int, pin: str = None) -> Response:
        data = dict(_token=self.token, type='upgrade', companyId=factory, level=level, pin="" if pin is None else pin)
        return self.post(f"{self.url}/economy/upgrade-company", data=data)

    def _post_economy_work(self, action_type: str, wam: List[int] = None, employ: Dict[int, int] = None) -> Response:
        data: Dict[str, Union[int, str]] = dict(action_type=action_type, _token=self.token)
        if action_type == 'production':
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
        return self.post(f"{self.url}/economy/work", data=data)

    def _post_economy_work_overtime(self) -> Response:
        data = dict(action_type='workOvertime', _token=self.token)
        return self.post(f"{self.url}/economy/workOvertime", data=data)

    def _post_economy_job_market_apply(self, citizen_id: int, salary: float) -> Response:
        data = dict(_token=self.token, citizenId=citizen_id, salary=salary)
        return self.post(f"{self.url}/economy/job-market-apply", data=data)

    def _post_economy_resign(self) -> Response:
        return self.post(f"{self.url}/economy/resign",
                         headers={"Content-Type": "application/x-www-form-urlencoded"},
                         data={'_token': self.token, 'action_type': 'resign'})

    def _post_economy_sell_company(self, factory_id: int, pin: int = None, sell: bool = True) -> Response:
        data = dict(_token=self.token, pin="" if pin is None else pin)
        if sell:
            data.update({'sell': 'sell'})
        else:
            data.update({'dissolve': factory_id})
        return self.post(f"{self.url}/economy/sell-company/{factory_id}",
                         data=data, headers={'Referer': self.url})


class ErepublikCountryAPI(CitizenBaseAPI):
    def _get_country_military(self, country_name: str) -> Response:
        return self.get(f"{self.url}/country/military/{country_name}")

    def _post_main_country_donate(self, country_id: int, action: str, value: Union[int, float],
                                  quality: int = None) -> Response:
        data = dict(countryId=country_id, action=action, _token=self.token, value=value, quality=quality)
        return self.post(f"{self.url}/main/country-donate", data=data,
                         headers={'Referer': f"{self.url}/country/economy/Latvia"})


class ErepublikEconomyAPI(CitizenBaseAPI):
    def _get_economy_citizen_accounts(self, organisation_id: int) -> Response:
        return self.get(f"{self.url}/economy/citizen-accounts/{organisation_id}")

    def _get_economy_my_market_offers(self) -> Response:
        return self.get(f"{self.url}/economy/myMarketOffers")

    def _get_main_job_data(self) -> Response:
        return self.get(f"{self.url}/main/job-data")

    def _post_main_buy_gold_items(self, currency: str, item: str, amount: int) -> Response:
        data = dict(itemId=item, currency=currency, amount=amount, _token=self.token)
        return self.post(f"{self.url}/main/buyGoldItems", data=data)

    def _post_economy_activate_booster(self, quality: int, duration: int, kind: str) -> Response:
        data = dict(type=kind, quality=quality, duration=duration, fromInventory=True, _token=self.token)
        return self.post(f"{self.url}/economy/activateBooster", data=data)

    def _post_economy_activate_house(self, quality: int) -> Response:
        data = dict(action='activate', quality=quality, type='house', _token=self.token)
        return self.post(f"{self.url}/economy/activateHouse", data=data)

    def _post_economy_donate_items_action(self, citizen_id: int, amount: int, industry: int,
                                          quality: int) -> Response:
        data = dict(citizen_id=citizen_id, amount=amount, industry_id=industry, quality=quality, _token=self.token)
        return self.post(f"{self.url}/economy/donate-items-action", data=data,
                         headers={'Referer': f"{self.url}/economy/donate-items/{citizen_id}"})

    def _post_economy_donate_money_action(self, citizen_id: int, amount: float = 0.0,
                                          currency: int = 62) -> Response:
        data = dict(citizen_id=citizen_id, _token=self.token, currency_id=currency, amount=amount)
        return self.post(f"{self.url}/economy/donate-money-action", data=data,
                         headers={'Referer': f"{self.url}/economy/donate-money/{citizen_id}"})

    def _post_economy_exchange_purchase(self, amount: float, currency: int, offer: int) -> Response:
        data = dict(_token=self.token, amount=amount, currencyId=currency, offerId=offer)
        return self.post(f"{self.url}/economy/exchange/purchase/", data=data)

    def _post_economy_exchange_retrieve(self, personal: bool, page: int, currency: int) -> Response:
        data = dict(_token=self.token, personalOffers=int(personal), page=page, currencyId=currency)
        return self.post(f"{self.url}/economy/exchange/retrieve/", data=data)

    def _post_economy_game_tokens_market(self, action: str) -> Response:
        assert action in ['retrieve', ]
        data = dict(_token=self.token, action=action)
        return self.post(f"{self.url}/economy/gameTokensMarketAjax", data=data)

    def _post_economy_marketplace(self, country: int, industry: int, quality: int,
                                  order_asc: bool = True) -> Response:
        data = dict(countryId=country, industryId=industry, quality=quality, ajaxMarket=1,
                    orderBy='price_asc' if order_asc else 'price_desc', _token=self.token)
        return self.post(f"{self.url}/economy/marketplaceAjax", data=data)

    def _post_economy_marketplace_actions(self, action: str, **kwargs) -> Response:
        if action == 'buy':
            data = dict(_token=self.token, offerId=kwargs['offer'], amount=kwargs['amount'],
                        orderBy='price_asc', currentPage=1, buyAction=1)
        elif action == 'sell':
            data = dict(_token=self.token, countryId=kwargs['country_id'], price=kwargs['price'],
                        industryId=kwargs['industry'], quality=kwargs['quality'], amount=kwargs['amount'],
                        sellAction='postOffer')
        elif action == 'delete':
            data = dict(_token=self.token, offerId=kwargs['offer_id'], sellAction='deleteOffer')
        else:
            raise ValueError(f"Action '{action}' is not supported! Only 'buy/sell/delete' actions are available")
        return self.post(f"{self.url}/economy/marketplaceActions", data=data)


class ErepublikLeaderBoardAPI(CitizenBaseAPI):
    def _get_main_leaderboards_damage_aircraft_rankings(self, country_id: int, weeks: int = 0,
                                                        mu_id: int = 0) -> Response:  # noqa
        return self.get(f"{self.url}/main/leaderboards-damage-aircraft-rankings/{country_id}/{weeks}/{mu_id}/0")

    def _get_main_leaderboards_damage_rankings(self, country_id: int, weeks: int = 0, mu_id: int = 0,
                                               div: int = 0) -> Response:  # noqa
        return self.get(f"{self.url}/main/leaderboards-damage-rankings/{country_id}/{weeks}/{mu_id}/{div}")

    def _get_main_leaderboards_kills_aircraft_rankings(self, country_id: int, weeks: int = 0,
                                                       mu_id: int = 0) -> Response:  # noqa
        return self.get(f"{self.url}/main/leaderboards-kills-aircraft-rankings/{country_id}/{weeks}/{mu_id}/0")

    def _get_main_leaderboards_kills_rankings(self, country_id: int, weeks: int = 0, mu_id: int = 0,
                                              div: int = 0) -> Response:  # noqa
        return self.get(f"{self.url}/main/leaderboards-kills-rankings/{country_id}/{weeks}/{mu_id}/{div}")


class ErepublikLocationAPI(CitizenBaseAPI):
    def _get_main_city_data_residents(self, city_id: int, page: int = 1, params: Mapping[str, Any] = None) -> Response:
        if params is None:
            params = {}
        return self.get(f"{self.url}/main/city-data/{city_id}/residents", params={'currentPage': page, **params})


class ErepublikMilitaryAPI(CitizenBaseAPI):
    def _get_military_battle_stats(self, battle_id: int, division: int, division_id: int):
        return self.get(f"{self.url}/military/battle-stats/{battle_id}/{division}/{division_id}")

    def _get_military_battlefield_choose_side(self, battle_id: int, side_id: int) -> Response:
        return self.get(f"{self.url}/military/battlefield-choose-side/{battle_id}/{side_id}")

    def _get_military_show_weapons(self, battle_id: int) -> Response:
        return self.get(f"{self.url}/military/show-weapons", params={'_token': self.token, 'battleId': battle_id})

    def _get_military_campaigns(self) -> Response:
        return self.get(f"{self.url}/military/campaigns-new/")

    def _get_military_campaigns_json_list(self) -> Response:
        return self.get(f"{self.url}/military/campaignsJson/list")

    def _get_military_campaigns_json_citizen(self) -> Response:
        return self.get(f"{self.url}/military/campaignsJson/citizen")

    def _get_military_unit_data(self, unit_id: int, **kwargs) -> Response:
        params = {'groupId': unit_id, 'panel': 'members', **kwargs}
        return self.get(f"{self.url}/military/military-unit-data/", params=params)

    def _post_main_activate_battle_effect(self, battle_id: int, kind: str, citizen_id: int) -> Response:
        data = dict(battleId=battle_id, citizenId=citizen_id, type=kind, _token=self.token)
        return self.post(f"{self.url}/main/fight-activateBattleEffect", data=data)

    def _post_main_battlefield_travel(self, side_id: int, battle_id: int) -> Response:
        data = dict(_token=self.token, sideCountryId=side_id, battleId=battle_id)
        return self.post(f"{self.url}/main/battlefieldTravel", data=data)

    def _post_main_battlefield_change_division(self, battle_id: int, division_id: int) -> Response:
        data = dict(_token=self.token, battleZoneId=division_id, battleId=battle_id)
        return self.post(f"{self.url}/main/battlefieldTravel", data=data)

    def _get_wars_show(self, war_id: int) -> Response:
        return self.get(f"{self.url}/wars/show/{war_id}")

    def _post_military_fight_activate_booster(self, battle_id: int, quality: int, duration: int, kind: str) -> Response:
        data = dict(type=kind, quality=quality, duration=duration, battleId=battle_id, _token=self.token)
        return self.post(f"{self.url}/military/fight-activateBooster", data=data)

    def _post_military_change_weapon(self, battle_id: int, battle_zone: int, weapon_level: int, ) -> Response:
        data = dict(battleId=battle_id, _token=self.token, battleZoneId=battle_zone, customizationLevel=weapon_level)
        return self.post(f"{self.url}/military/change-weapon", data=data)

    def _post_military_battle_console(self, battle_id: int, action: str, page: int = 1, **kwargs) -> Response:
        data = dict(battleId=battle_id, action=action, _token=self.token)
        if action == 'battleStatistics':
            data.update(round=kwargs['round_id'], zoneId=kwargs['round_id'], leftPage=page, rightPage=page,
                        division=kwargs['division'], type=kwargs.get('type', 'damage'), )
        elif action == 'warList':
            data.update(page=page)
        return self.post(f"{self.url}/military/battle-console", data=data)

    def _post_military_deploy_bomb(self, battle_id: int, division_id: int, side_id: int, bomb_id: int) -> Response:
        data = dict(battleId=battle_id, battleZoneId=division_id, sideId=side_id, sideCountryId=side_id,
                    bombId=bomb_id, _token=self.token)
        return self.post(f"{self.url}/military/deploy-bomb", data=data)

    def _post_military_fight_air(self, battle_id: int, side_id: int, zone_id: int) -> Response:
        data = dict(sideId=side_id, battleId=battle_id, _token=self.token, battleZoneId=zone_id)
        return self.post(f"{self.url}/military/fight-shoooot/{battle_id}", data=data)

    def _post_military_fight_ground(self, battle_id: int, side_id: int, zone_id: int) -> Response:
        data = dict(sideId=side_id, battleId=battle_id, _token=self.token, battleZoneId=zone_id)
        return self.post(f"{self.url}/military/fight-shooot/{battle_id}", data=data)

    def _post_fight_deploy_deploy_report_data(self, deployment_id: int):
        data = dict(_token=self.token, deploymentId=deployment_id)
        return self.post(f"{self.url}/military/fightDeploy-deployReportData", json=data)


class ErepublikPoliticsAPI(CitizenBaseAPI):
    def _get_candidate_party(self, party_slug: str) -> Response:
        return self.get(f"{self.url}/candidate/{party_slug}")

    def _get_main_party_members(self, party_id: int) -> Response:
        return self.get(f"{self.url}/main/party-members/{party_id}")

    def _get_main_rankings_parties(self, country_id: int) -> Response:
        return self.get(f"{self.url}/main/rankings-parties/1/{country_id}")

    def _post_candidate_for_congress(self, presentation: str = "") -> Response:
        data = dict(_token=self.token, presentation=presentation)
        return self.post(f"{self.url}/candidate-for-congress", data=data)

    def _get_presidential_elections(self, country_id: int, timestamp: int) -> Response:
        return self.get(f"{self.url}/main/presidential-elections/{country_id}/{timestamp}")

    def _post_propose_president_candidate(self, party_slug: str, citizen_id: int) -> Response:
        return self.post(f"{self.url}/propose-president-candidate/{party_slug}",
                         data=dict(_token=self.token, citizen=citizen_id))

    def _get_auto_propose_president_candidate(self, party_slug: str) -> Response:
        return self.get(f"{self.url}/auto-propose-president-candidate/{party_slug}")


class ErepublikPresidentAPI(CitizenBaseAPI):
    def _post_wars_attack_region(self, war_id: int, region_id: int, region_name: str) -> Response:
        data = {'_token': self.token, 'warId': war_id, 'regionName': region_name, 'regionNameConfirm': region_name}
        return self.post(f'{self.url}/wars/attack-region/{war_id}/{region_id}', data=data)

    def _post_new_war(self, self_country_id: int, attack_country_id: int, debate: str = "") -> Response:
        data = dict(requirments=1, _token=self.token, debate=debate,
                    countryNameConfirm=constants.COUNTRIES[attack_country_id].link)
        return self.post(f"{self.url}/{constants.COUNTRIES[self_country_id].link}/new-war", data=data)

    def _post_new_donation(self, country_id: int, amount: int, org_name: str, debate: str = "") -> Response:
        data = dict(requirments=1, _token=self.token, debate=debate, currency=1, value=amount, commit='Propose',
                    type_name=org_name)
        return self.post(f"{self.url}/{constants.COUNTRIES[country_id].link}/new-donation", data=data)


class ErepublikProfileAPI(CitizenBaseAPI):
    def _get_main_citizen_hovercard(self, citizen_id: int) -> Response:
        return self.get(f"{self.url}/main/citizen-hovercard/{citizen_id}")

    def _get_main_citizen_profile_json(self, citizen_id: int) -> Response:
        return self.get(f"{self.url}/main/citizen-profile-json/{citizen_id}")

    def _get_main_citizen_notifications(self) -> Response:
        return self.get(f"{self.url}/main/citizenDailyAssistant")

    def _get_main_citizen_daily_assistant(self) -> Response:
        return self.get(f"{self.url}/main/citizenNotifications")

    def _get_main_messages_paginated(self, page: int = 1) -> Response:
        return self.get(f"{self.url}/main/messages-paginated/{page}")

    def _get_main_money_donation_accept(self, donation_id: int) -> Response:
        return self.get(f"{self.url}/main/money-donation/accept/{donation_id}", params={'_token': self.token})

    def _get_main_money_donation_reject(self, donation_id: int) -> Response:
        return self.get(f"{self.url}/main/money-donation/reject/{donation_id}", params={'_token': self.token})

    def _get_main_notifications_ajax_community(self, page: int = 1) -> Response:
        return self.get(f"{self.url}/main/notificationsAjax/community/{page}")

    def _get_main_notifications_ajax_system(self, page: int = 1) -> Response:
        return self.get(f"{self.url}/main/notificationsAjax/system/{page}")

    def _get_main_notifications_ajax_report(self, page: int = 1) -> Response:
        return self.get(f"{self.url}/main/notificationsAjax/report/{page}")

    def _get_main_training_grounds_json(self) -> Response:
        return self.get(f"{self.url}/main/training-grounds-json")

    def _get_main_weekly_challenge_data(self) -> Response:
        return self.get(f"{self.url}/main/weekly-challenge-data")

    def _post_main_citizen_add_remove_friend(self, citizen: int, add: bool) -> Response:
        data = dict(_token=self.token, citizenId=citizen, url="//www.erepublik.com/en/main/citizen-addRemoveFriend")
        if add:
            data.update({'action': 'addFriend'})
        else:
            data.update({'action': 'removeFriend'})
        return self.post(f"{self.url}/main/citizen-addRemoveFriend", data=data)

    def _post_main_daily_task_reward(self) -> Response:
        return self.post(f"{self.url}/main/daily-tasks-reward", data=dict(_token=self.token))

    def _post_delete_message(self, msg_id: list) -> Response:
        data = {'_token': self.token, "delete_message[]": msg_id}
        return self.post(f"{self.url}/main/messages-delete", data)

    def _post_eat(self, color: str) -> Response:
        data = dict(_token=self.token, buttonColor=color)
        return self.post(f"{self.url}/main/eat", params=data)

    def _post_main_global_alerts_close(self, alert_id: int) -> Response:
        data = dict(_token=self.token, alert_id=alert_id)
        return self.post(f"{self.url}/main/global-alerts/close", data=data)

    def _post_forgot_password(self, email: str) -> Response:
        data = dict(_token=self.token, email=email, commit='Reset password')
        return self.post(f"{self.url}/forgot-password", data=data)

    def _post_login(self, email: str, password: str) -> Response:
        data = dict(csrf_token=self.token, citizen_email=email, citizen_password=password, remember='on')
        return self.post(f"{self.url}/login", data=data)

    def _post_main_messages_alert(self, notification_ids: List[int]) -> Response:
        data = {'_token': self.token, "delete_alerts[]": notification_ids, 'deleteAllAlerts': '1', 'delete': 'Delete'}
        return self.post(f"{self.url}/main/messages-alerts/1", data=data)

    def _post_main_notifications_ajax_community(self, notification_ids: List[int], page: int = 1) -> Response:
        data = {'_token': self.token, "delete_alerts[]": notification_ids}
        return self.post(f"{self.url}/main/notificationsAjax/community/{page}", data=data)

    def _post_main_notifications_ajax_system(self, notification_ids: List[int], page: int = 1) -> Response:
        data = {'_token': self.token, "delete_alerts[]": notification_ids}
        return self.post(f"{self.url}/main/notificationsAjax/system/{page}", data=data)

    def _post_main_notifications_ajax_report(self, notification_ids: List[int], page: int = 1) -> Response:
        data = {'_token': self.token, "delete_alerts[]": notification_ids}
        return self.post(f"{self.url}/main/notificationsAjax/report/{page}", data=data)

    def _post_main_messages_compose(self, subject: str, body: str, citizens: List[int]) -> Response:
        url_pk = 0 if len(citizens) > 1 else str(citizens[0])
        data = dict(citizen_name=",".join([str(x) for x in citizens]),
                    citizen_subject=subject, _token=self.token, citizen_message=body)
        return self.post(f"{self.url}/main/messages-compose/{url_pk}", data=data)

    def _post_military_group_missions(self) -> Response:
        data = dict(action='check', _token=self.token)
        return self.post(f"{self.url}/military/group-missions", data=data)

    def _post_main_weekly_challenge_reward(self, reward_id: int) -> Response:
        data = dict(_token=self.token, rewardId=reward_id)
        return self.post(f"{self.url}/main/weekly-challenge-collect-reward", data=data)

    def _post_main_weekly_challenge_collect_all(self, max_reward_id: int) -> Response:
        data = dict(_token=self.token, maxRewardId=max_reward_id)
        return self.post(f"{self.url}/main/weekly-challenge-collect-all", data=data)

    def _post_main_profile_update(self, action: str, params: str):
        data = {'action': action, 'params': params, '_token': self.token}
        return self.post(f"{self.url}/main/profile-update", data=data)


class ErepublikTravelAPI(CitizenBaseAPI):
    def _post_main_travel(self, check: str, **kwargs) -> Response:
        data = dict(_token=self.token, check=check, **kwargs)
        return self.post(f"{self.url}/main/travel", data=data)

    def _post_main_travel_data(self, **kwargs) -> Response:
        return self.post(f"{self.url}/main/travelData", data=dict(_token=self.token, **kwargs))


class ErepublikWallPostAPI(CitizenBaseAPI):
    # ## Country

    def _post_main_country_comment_retrieve(self, post_id: int) -> Response:
        data = {'_token': self.token, 'postId': post_id}
        return self.post(f"{self.url}/main/country-comment/retrieve/json", data=data)

    def _post_main_country_comment_create(self, post_id: int, comment_message: str) -> Response:
        data = {'_token': self.token, 'postId': post_id, 'comment_message': comment_message}
        return self.post(f"{self.url}/main/country-comment/create/json", data=data)

    def _post_main_country_post_create(self, body: str, post_as: int) -> Response:
        data = {'_token': self.token, 'post_message': body, 'post_as': post_as}
        return self.post(f"{self.url}/main/country-post/create/json", data=data)

    def _post_main_country_post_retrieve(self) -> Response:
        data = {'_token': self.token, 'page': 1, 'switchedFrom': False}
        return self.post(f"{self.url}/main/country-post/retrieve/json", data=data)

    # ## Military Unit

    def _post_main_military_unit_comment_retrieve(self, post_id: int) -> Response:
        data = {'_token': self.token, 'postId': post_id}
        return self.post(f"{self.url}/main/military-unit-comment/retrieve/json", data=data)

    def _post_main_military_unit_comment_create(self, post_id: int, comment_message: str) -> Response:
        data = {'_token': self.token, 'postId': post_id, 'comment_message': comment_message}
        return self.post(f"{self.url}/main/military-unit-comment/create/json", data=data)

    def _post_main_military_unit_post_create(self, body: str, post_as: int) -> Response:
        data = {'_token': self.token, 'post_message': body, 'post_as': post_as}
        return self.post(f"{self.url}/main/military-unit-post/create/json", data=data)

    def _post_main_military_unit_post_retrieve(self) -> Response:
        data = {'_token': self.token, 'page': 1, 'switchedFrom': False}
        return self.post(f"{self.url}/main/military-unit-post/retrieve/json", data=data)

    # ## Party

    def _post_main_party_comment_retrieve(self, post_id: int) -> Response:
        data = {'_token': self.token, 'postId': post_id}
        return self.post(f"{self.url}/main/party-comment/retrieve/json", data=data)

    def _post_main_party_comment_create(self, post_id: int, comment_message: str) -> Response:
        data = {'_token': self.token, 'postId': post_id, 'comment_message': comment_message}
        return self.post(f"{self.url}/main/party-comment/create/json", data=data)

    def _post_main_party_post_create(self, body: str) -> Response:
        data = {'_token': self.token, 'post_message': body}
        return self.post(f"{self.url}/main/party-post/create/json", data=data)

    def _post_main_party_post_retrieve(self) -> Response:
        data = {'_token': self.token, 'page': 1, 'switchedFrom': False}
        return self.post(f"{self.url}/main/party-post/retrieve/json", data=data)

    # ## Friend's Wall

    def _post_main_wall_comment_retrieve(self, post_id: int) -> Response:
        data = {'_token': self.token, 'postId': post_id}
        return self.post(f"{self.url}/main/wall-comment/retrieve/json", data=data)

    def _post_main_wall_comment_create(self, post_id: int, comment_message: str) -> Response:
        data = {'_token': self.token, 'postId': post_id, 'comment_message': comment_message}
        return self.post(f"{self.url}/main/wall-comment/create/json", data=data)

    def _post_main_wall_post_create(self, body: str) -> Response:
        data = {'_token': self.token, 'post_message': body}
        return self.post(f"{self.url}/main/wall-post/create/json", data=data)

    def _post_main_wall_post_retrieve(self) -> Response:
        data = {'_token': self.token, 'page': 1, 'switchedFrom': False}
        return self.post(f"{self.url}/main/wall-post/retrieve/json", data=data)

    # ## Medal posting
    def _post_main_wall_post_automatic(self, message: str, achievement_id: int) -> Response:
        return self.post(f"{self.url}/main/wall-post/automatic", data=dict(_token=self.token, message=message,
                                                                           achievementId=achievement_id))


class CitizenAPI(
    ErepublikArticleAPI, ErepublikCountryAPI, ErepublikCompanyAPI, ErepublikEconomyAPI,
    ErepublikLeaderBoardAPI, ErepublikLocationAPI, ErepublikMilitaryAPI, ErepublikProfileAPI,
    ErepublikPresidentAPI, ErepublikPoliticsAPI, ErepublikAnniversaryAPI, ErepublikWallPostAPI,
    ErepublikTravelAPI
):
    pass
