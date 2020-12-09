import threading
from datetime import timedelta

from erepublik import Citizen, utils

CONFIG = {
    'email': 'player@email.com',
    'password': 'Pa$5w0rd!',
    'interactive': True,
    'fight': True,
    'debug': True,
    'battle_launcher': {
        # War id: {auto_attack: bool (attack asap when region is available), regions: [region_ids allowed to attack]}
        121672: {"auto_attack": False, "regions": [661]},
        125530: {"auto_attack": False, "regions": [259]},
        125226: {"auto_attack": True, "regions": [549]},
        124559: {"auto_attack": True, "regions": [176]}
    }
}


def _battle_launcher(player: Citizen):
    """Launch battles. Check every 5th minute (0,5,10...45,50,55) if any battle could be started on specified regions
    and after launching wait for 90 minutes before starting next attack so that all battles aren't launched at the same
    time. If player is allowed to fight, do 100 hits on the first round in players division.

    :param player: Logged in Citizen instance
    :type player: Citizen
    """
    global CONFIG
    finished_war_ids = {*[]}
    war_data = CONFIG.get('battle_launcher', {})
    war_ids = {int(war_id) for war_id in war_data.keys()}
    next_attack_time = player.now
    next_attack_time = next_attack_time.replace(minute=next_attack_time.minute // 5 * 5, second=0)
    while not player.stop_threads.is_set():
        try:
            attacked = False
            player.update_war_info()
            running_wars = {b.war_id for b in player.all_battles.values()}
            for war_id in war_ids - finished_war_ids - running_wars:
                war = war_data[war_id]
                war_regions = set(war.get('regions'))
                auto_attack = war.get('auto_attack')

                status = player.get_war_status(war_id)
                if status.get('ended', False):
                    CONFIG['battle_launcher'].pop(war_id, None)
                    finished_war_ids.add(war_id)
                    continue
                elif not status.get('can_attack'):
                    continue

                if auto_attack or (player.now.hour > 20 or player.now.hour < 2):
                    for reg in war_regions:
                        if attacked:
                            break
                        if reg in status.get('regions', {}).keys():
                            player.launch_attack(war_id, reg, status.get('regions', {}).get(reg))
                            attacked = True
                            hits = 100
                            if player.energy.food_fights >= hits and player.config.fight:
                                for _ in range(120):
                                    player.update_war_info()
                                    battle_id = player.get_war_status(war_id).get("battle_id")
                                    if battle_id is not None and battle_id in player.all_battles:
                                        battle = player.all_battles.get(battle_id)
                                        for division in battle.div.values():
                                            if division.div == player.division:
                                                div = division
                                                break
                                        else:
                                            player.report_error("Players division not found in the first round!")
                                            break
                                        player.fight(battle, div, battle.invader, hits)
                                        break
                                    player.sleep(1)
                        if attacked:
                            break
                if attacked:
                    break
            war_ids -= finished_war_ids
            if attacked:
                next_attack_time = utils.good_timedelta(next_attack_time, timedelta(hours=1, minutes=30))
            else:
                next_attack_time = utils.good_timedelta(next_attack_time, timedelta(minutes=5))
            player.stop_threads.wait(utils.get_sleep_seconds(next_attack_time))
        except Exception as e:
            player.report_error(f"Task battle launcher ran into error {e}")


# noinspection DuplicatedCode
def main():
    player = Citizen(email=CONFIG['email'], password=CONFIG['password'], auto_login=False)
    player.config.interactive = CONFIG['interactive']
    player.config.fight = CONFIG['fight']
    player.set_debug(CONFIG.get('debug', False))
    player.login()
    if CONFIG.get('battle_launcher'):
        name = f"{player.name}-battle_launcher-{threading.active_count() - 1}"
        state_thread = threading.Thread(target=_battle_launcher, args=(player,), name=name)
        state_thread.start()


if __name__ == "__main__":
    main()
