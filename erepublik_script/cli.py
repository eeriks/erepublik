# -*- coding: utf-8 -*-

"""Console script for erepublik_script."""

import json
import os
import random
import sys
import threading
from collections import defaultdict
from datetime import timedelta
from typing import List, Tuple

import click

from erepublik_script import classes, utils
from erepublik_script.citizen import Citizen


__all__ = ["Citizen"]

CONFIG = defaultdict(bool)


@click.command()
@click.option('--silent', help='Run silently', type=bool, is_flag=True)
def main(silent):
    global CONFIG
    assert sys.version_info >= (3, 7, 1)
    if silent:
        write_log = utils.write_silent_log
    else:
        write_log = utils.write_interactive_log

    try:
        with open('config.json', 'r') as f:
            CONFIG = json.load(f)

        write_log('Config file found. Checking...')
        CONFIG = utils.parse_config(CONFIG)
    except:
        CONFIG = utils.parse_config()

    with open('config.json', 'w') as f:
        json.dump(CONFIG, f, indent=True, sort_keys=True)
    if CONFIG['interactive']:
        write_log = utils.write_interactive_log
    else:
        write_log = utils.write_silent_log
    write_log('\nTo quit press [ctrl] + [c]', False)
    os.chdir(os.path.dirname(os.path.realpath(__file__)))
    write_log('Version: ' + utils.VERSION)
    player = None
    try:  # If errors before player is initialized
        while True:
            player = Citizen(email=CONFIG['email'], password=CONFIG['password'])
            if player.logged_in:
                break
            utils.silent_sleep(2)
        player.config.work = CONFIG['work']
        player.config.train = CONFIG['train']
        player.config.ot = CONFIG['ot']
        player.config.wam = bool(CONFIG['wam'])
        player.config.employees = bool(CONFIG['employ'])
        player.config.auto_sell = CONFIG.get('auto_sell', [])
        player.config.auto_sell_all = CONFIG.get('auto_sell_all', False)
        player.config.auto_buy_raw = CONFIG.get('auto_buy_raw', False)
        player.config.force_wam = CONFIG.get('force_wam', False)
        player.config.fight = CONFIG['fight']
        player.config.air = CONFIG['air']
        player.config.ground = CONFIG['ground']
        player.config.all_in = CONFIG['all_in']
        player.config.next_energy = CONFIG['next_energy']
        player.config.boosters = CONFIG['boosters']
        player.config.travel_to_fight = CONFIG['travel_to_fight']
        player.config.always_travel = CONFIG.get('always_travel', False)
        player.config.epic_hunt = CONFIG['epic_hunt']
        player.config.epic_hunt_ebs = CONFIG['epic_hunt_ebs']
        player.config.rw_def_side = CONFIG['rw_def_side']
        player.config.random_sleep = CONFIG['random_sleep']
        player.config.continuous_fighting = CONFIG['continuous_fighting']
        player.config.interactive = CONFIG['interactive']
        player.reporter.allowed = not CONFIG.get('reporting_is_not_allowed')

        player.set_debug(CONFIG.get('debug', False))
        while True:
            try:
                player.update_all()
                break
            except:
                utils.silent_sleep(2)

        now = utils.now()
        dt_max = now.replace(year=9999)
        tasks = {
            'eat': now,
        }
        wam_hour = employ_hour = 14
        if player.config.work:
            tasks.update({'work': now})
        if player.config.train:
            tasks.update({'train': now})
        if player.config.ot:
            tasks.update({'ot': now})
        if player.config.fight:
            tasks.update({'fight': now})
        if player.config.wam:
            wam_hour = 14
            if not isinstance(CONFIG['wam'], bool):
                try:
                    wam_hour = abs(int(CONFIG['wam'])) % 24
                except ValueError:
                    pass
            tasks.update({'wam': now.replace(hour=wam_hour, minute=0, second=0, microsecond=0)})
        if player.config.employees:
            employ_hour = 8
            if not isinstance(CONFIG['employ'], bool):
                try:
                    employ_hour = abs(int(CONFIG['employ'])) % 24
                except ValueError:
                    pass
            tasks.update({'employ': now.replace(hour=employ_hour, minute=0, second=0, microsecond=0)})

        if player.config.epic_hunt:
            tasks['epic_hunt'] = now

        if CONFIG.get("renew_houses", True):
            tasks['renew_houses'] = now

        if CONFIG.get('start_battles'):
            """ {'start_battle': {war_id: {'regions': [region_id, ],
                                 'timing': ['at', 'hh:mm' | 'before', 'hh:mm' (before autoattack) |
                                         'auto' (after round for citizenship country's oldest battle or at 00:00)
                                         'rw', (after first round of RW if you are occupying)]}} """
            player.allowed_battles = CONFIG.get('start_battles', dict())
            raise classes.ErepublikException("Battle starting is not implemented")

        if player.reporter.allowed:
            report = dict(CONFIG)
            report.pop("email", None)
            report.pop("password", None)
            report.update(
                VERSION=utils.VERSION,
                COMMIT_ID=utils.COMMIT_ID
            )
            player.reporter.report_action("ACTIVE_CONFIG", json_val=report)
            # -1 because main thread is counted in
            name = "{}-state_updater-{}".format(player.name, threading.active_count() - 1)
            state_thread = threading.Thread(target=player.state_update_repeater, name=name)
            state_thread.start()

        if CONFIG.get("congress", True):
            tasks['congress'] = now.replace(hour=1, minute=30, second=0)

        if CONFIG.get("party_president", False):
            tasks['party_president'] = now.replace(hour=1, minute=30, second=0)

        contribute_cc = int(CONFIG.get("contribute_cc", 0))
        if contribute_cc:
            tasks['contribute_cc'] = now.replace(hour=2, minute=0, second=0)

        if CONFIG.get("gold_buy"):
            tasks['gold_buy'] = now.replace(hour=23, minute=57, second=0, microsecond=0)

        error_count = 0
        while error_count < 3:
            try:
                now = utils.now()
                player.update_all()
                if tasks.get('work', dt_max) <= now:
                    player.write_log("Doing task: work")
                    player.update_citizen_info()
                    player.work()
                    if player.config.ot:
                        tasks['ot'] = now
                    player.collect_daily_task()
                    next_time = now.replace(hour=0, minute=0, second=0) + timedelta(days=1)
                    tasks.update({'work': next_time})

                if tasks.get('train', dt_max) <= now:
                    player.write_log("Doing task: train")
                    player.update_citizen_info()
                    player.train()
                    player.collect_daily_task()
                    next_time = now.replace(hour=0, minute=0, second=0) + timedelta(days=1)
                    tasks.update({'train': next_time})

                if tasks.get('wam', dt_max) <= now:
                    player.write_log("Doing task: Work as manager")
                    success = player.work_wam()
                    player.eat()
                    if success:
                        next_time = now.replace(hour=wam_hour, minute=0, second=0, microsecond=0) + timedelta(days=1)
                    else:
                        next_time = now.replace(second=0, microsecond=0) + timedelta(minutes=30)

                    tasks.update({'wam': next_time})

                if tasks.get('eat', dt_max) <= now:
                    player.write_log("Doing task: eat")
                    player.eat()

                    if player.energy.food_fights > player.energy.limit // 10:
                        next_minutes = 12
                    else:
                        next_minutes = (player.energy.limit - 5 * player.energy.interval) // player.energy.interval * 6

                    next_time = player.energy.reference_time + timedelta(minutes=next_minutes)
                    tasks.update({'eat': next_time})

                if tasks.get('fight', dt_max) <= now or player.energy.is_energy_full:
                    fight_energy_debug_log: List[Tuple[int, str]] = []
                    player.write_log("Doing task: fight")
                    player.write_log(player.health_info)

                    if player.should_fight():
                        player.find_battle_and_fight()
                    else:
                        player.collect_weekly_reward()
                    energy = classes.EnergyToFight(player.details.xp_till_level_up * 10 - player.energy.limit + 50)
                    fight_energy_debug_log.append((
                        energy.i,
                        f"Levelup reachable {player.details.xp_till_level_up} * 10 - {player.energy.limit} + 50"
                    ))

                    # Do levelup
                    energy.check(player.details.xp_till_level_up * 10 + 50)
                    fight_energy_debug_log.append((
                        energy.i, f"Levelup {player.details.xp_till_level_up} * 10 + 50"
                    ))

                    # if levelup is close stop queueing other fighting
                    if not player.is_levelup_close:

                        # Obligatory need 75pp
                        if player.details.pp < 75:
                            energy.check(75 - player.details.pp)
                            fight_energy_debug_log.append((energy.i, f"Obligatory need 75pp: 75 - {player.details.pp}"))

                        if player.config.continuous_fighting and player.has_battle_contribution:
                            energy.check(player.energy.interval)
                            fight_energy_debug_log.append((energy.i, f"continuous_fighting: {player.energy.interval}"))

                        # All-in
                        if player.config.all_in:
                            energy.check(player.energy.limit * 2 - 3 * player.energy.interval)
                            fight_energy_debug_log.append((
                                energy.i, f"All-in: {player.energy.limit} * 2 - 3 * {player.energy.interval}"
                            ))
                        elif player.energy.limit * 2 - 3 * player.energy.interval >= player.energy.recovered:
                            # 1h worth of energy
                            energy.check(player.energy.limit * 2 - 3 * player.energy.interval)
                            fight_energy_debug_log.append(
                                (energy.i, f"1h worth of energy: {player.energy.interval} * 10"
                                 ))

                        # All-in for AIR battles
                        if all([player.config.air, player.config.all_in,
                                player.energy.available >= player.energy.limit]):
                            energy.check(player.energy.limit)
                            fight_energy_debug_log.append((
                                energy.i, f"All-in for AIR battles: {player.energy.limit}"
                            ))

                        # Get to next Energy +1
                        if player.next_reachable_energy and player.config.next_energy:
                            energy.check(player.next_reachable_energy * 10)
                            fight_energy_debug_log.append((
                                energy.i, f"Get to next Energy +1: {player.next_reachable_energy} * 10"
                            ))

                    energy = energy.i - player.energy.available
                    next_minutes = max([6, abs(energy) // player.energy.interval * 6])
                    # utils.write_silent_log("\n".join([f"{energy} {info}" for energy, info in fight_energy_debug_log]))
                    next_time = player.energy.reference_time + timedelta(minutes=next_minutes)
                    tasks.update({'fight': next_time})

                if tasks.get('ot', dt_max) <= now:
                    player.write_log("Doing task: ot")
                    if now > player.my_companies.next_ot_time:
                        player.work_ot()
                        next_time = now + timedelta(minutes=60)
                    else:
                        next_time = player.my_companies.next_ot_time
                    tasks.update({'ot': next_time})

                if tasks.get('employ', dt_max) <= now:
                    player.write_log("Doing task: Employee work")
                    next_time = utils.now().replace(hour=employ_hour, minute=0, second=0) + timedelta(days=1)
                    next_time = next_time if player.work_employees() else tasks.get('employ') + timedelta(minutes=30)
                    tasks.update({'employ': next_time})

                if tasks.get('epic_hunt', dt_max) <= now:
                    player.write_log("Doing task: EPIC check")
                    player.check_epic_battles()
                    if player.active_fs:
                        next_time = now + timedelta(minutes=1)
                    else:
                        next_time = tasks.get('eat')
                    tasks.update({'epic_hunt': next_time})

                if tasks.get('gold_buy', dt_max) <= now:
                    player.write_log("Doing task: auto buy 10g")
                    for offer in player.get_monetary_offers():
                        if offer['amount'] >= 10 and player.details.cc >= 20 * offer["price"]:
                            # TODO: check allowed amount to buy
                            if player.buy_monetary_market_offer(offer=offer['offer_id'], amount=10, currency=62):
                                break

                    next_time = tasks.get('gold_buy') + timedelta(days=1)
                    tasks.update({'gold_buy': next_time})

                if tasks.get('congress', dt_max) <= now:
                    if 1 <= now.day < 16:
                        next_time = now.replace(day=16)
                    elif 16 <= now.day < 24:
                        player.write_log("Doing task: candidate for congress")
                        player.candidate_for_congress()
                        if not now.month == 12:
                            next_time = now.replace(month=now.month + 1, day=16)
                        else:
                            next_time = now.replace(year=now.year + 1, month=1, day=16)
                    else:
                        if not now.month == 12:
                            next_time = now.replace(month=now.month + 1, day=16)
                        else:
                            next_time = now.replace(year=now.year + 1, month=1, day=16)
                    tasks.update({'congress': next_time.replace(hour=1, minute=30, second=0, microsecond=0)})

                if tasks.get('party_president', dt_max) <= now:
                    if not now.day == 15:
                        player.write_log("Doing task: candidate for party president")
                        player.candidate_for_party_presidency()
                        if not now.month == 12:
                            next_time = now.replace(month=now.month + 1)
                        else:
                            next_time = now.replace(year=now.year + 1, month=1)
                    else:
                        if not now.month == 12:
                            next_time = now.replace(month=now.month + 1)
                        else:
                            next_time = now.replace(year=now.year + 1, month=1)
                    tasks.update(party_president=next_time.replace(day=16, hour=0, minute=0, second=0, microsecond=0))

                if tasks.get('contribute_cc', dt_max) <= now:
                    if not now.weekday():
                        player.update_money()
                        cc = (player.details.cc // contribute_cc) * contribute_cc
                        player.write_log("Doing task: Contribute {}cc to Latvia".format(cc))
                        player.contribute_cc_to_country(cc)
                    next_time = now + timedelta(days=7 - now.weekday())
                    next_time = next_time.replace(hour=2, minute=0, second=0)
                    tasks.update({'contribute_cc': next_time})

                if tasks.get('renew_houses', dt_max) <= now:
                    player.write_log("Doing task: Renew houses")
                    end_times = player.renew_houses()
                    if end_times:
                        tasks.update(renew_houses=min(end_times.values()) - timedelta(hours=24))
                    else:
                        player.write_log("No houses found! Forcing q1 usage...")
                        end_times = player.buy_and_activate_house(1)
                        if not end_times:
                            tasks.update(renew_houses=now + timedelta(hours=6))
                        else:
                            tasks.update(renew_houses=min(end_times.values()) - timedelta(hours=24))

                closest_next_time = dt_max
                next_tasks = []
                for task, next_time in sorted(tasks.items(), key=lambda s: s[1]):
                    next_tasks.append("{}: {}".format(next_time.strftime('%F %T'), task))
                    if next_time < closest_next_time:
                        closest_next_time = next_time
                random_seconds = random.randint(0, 121) if player.config.random_sleep else 0
                sleep_seconds = int(utils.get_sleep_seconds(closest_next_time))
                if sleep_seconds <= 0:
                    raise classes.ErepublikException(f"Loop detected! Offending task: '{next_tasks[0]}'")
                closest_next_time += timedelta(seconds=random_seconds)
                player.write_log("My next Tasks and there time:\n" + "\n".join(sorted(next_tasks)))
                player.write_log("Sleeping until (eRep): {} (sleeping for {}s + random {}s)".format(
                    closest_next_time.strftime("%F %T"), sleep_seconds, random_seconds))
                seconds_to_sleep = sleep_seconds + random_seconds if sleep_seconds > 0 else 0
                player.sleep(seconds_to_sleep)

            except classes.ErepublikNetworkException:
                player.write_log('Network ERROR detected. Sleeping for 1min...')
                player.sleep(60)
            except (KeyboardInterrupt, SystemExit):
                sys.exit(1)
            except classes.ErepublikException as e:
                utils.process_error(f"Known error detected! {e}", player.name, sys.exc_info(), player, utils.COMMIT_ID)
            except:
                utils.process_error("Unknown error!", player.name, sys.exc_info(), player, utils.COMMIT_ID)
                error_count += 1
                if error_count < 3:
                    player.sleep(60)
            finally:
                if error_count >= 3:
                    player.stop_threads.set()
        player.stop_threads.set()
        player.write_log('Too many errors.')
    except (KeyboardInterrupt, SystemExit):
        sys.exit(1)
    except classes.ErepublikException:
        utils.process_error("[{}] To many errors.".format(utils.COMMIT_ID), player.name, sys.exc_info(), player,
                            utils.COMMIT_ID)
    except:
        if isinstance(player, Citizen):
            name = player.name
        elif CONFIG.get('email', None):
            name = CONFIG['email']
        else:
            name = "Uninitialized"
        utils.process_error("[{}] Fatal error.".format(utils.COMMIT_ID), name, sys.exc_info(), player, utils.COMMIT_ID)
        sys.exit(1)


if __name__ == "__main__":
    while True:
        main()
        utils.write_interactive_log("Restarting after 1h")
        utils.interactive_sleep(60 * 60)
