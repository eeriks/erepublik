=======
History
=======

0.23.4 (2021-01-05)
-------------------
* Added expiration data to inventory items
* Inventory is now based on `classes.Inventory`
* Requirement update to make them more flexible regarding versions required
* Restructured inventory

0.23.3 (2020-12-17)
-------------------
* Fixed carpet bombing
* Fixed hits done amount when fighting on ground
* Minor requirement updates
* Minor tweaks to method signatures
* Fixed buy food if unable to work or train because not enough energy and not enough food
* Fixed applications for party presidency and congress if not a party member
* Removed tox
* Updates to github.io config generator
* Fixed `Citizen.concurrency_available` stuck in unset state if exception is being raised while doing concurrency task

0.23.2 (2020-12-01)
-------------------
* Added concurrency checks to guard against simultaneous fighting/wam'ing/traveling
* For concurrency checking use `utils.wait_for_lock` decorator

0.23.1 (2020-12-01)
-------------------
* Separated battle finding logic from CitizenMilitary.find_battle_and_fight method
* Base dmg calculations
* Get max hit value for divisions on current side
* Added method to get division stats
* Wheel of fortune updates

0.23.0 (2020-11-26)
-------------------
* ***0.23 - last officially supported version for Python 3.7.***
* Added `Config.maverick` switch, to allow/deny automated fighting in non native divisions if the player has MaverickPack
* Added `CitizenMedia.get_article(article_id:int)` method to get article data
* Added `CitizenMedia.delete_article(article_id:int)` method to delete article
* Fixed `CitizenTravel.travel_to_region(region_id:int)` method
* Added `CitizenAnniversary.collect_map_quest_node(node_id:int, extra:bool=False)` to collect also extra rewards
* Fixed `CitizenTasks.work()` when employer out of money - resign and find a new job
* Fixed `CitizenEconomy.post_market_offer()`

0.22.3 (2020-11-16)
-------------------
* Fixed round to even bug when doing wam and not enough raw.
* Added meta industry airplaneRaw
* Added method `Citizen.buy_market_offer(OfferItem, amount=None)` to directly buy market offer with included travel to country and back.

0.22.2 (2020-11-09)
-------------------
* Allow querying market offers for q2-q5 aircrafts
* Added "Ticket" industry

0.22.1 (2020-11-04)
-------------------
* Requirement update
* Unified product naming in inventory and other places based on `erepublik.constants.INDUSTRIES` values
* `erepublik.Citizen` parameter `auto_login` now defaults to `False`
* Continued work on more verbose action and result logging

0.22.0 (2020-10-22)
-------------------
* Ability to dump session and restore from file
* Proxy support
* Inventory updates
* Remove market offers
* Memory and network optimizations
* Python 3.6 supported

0.20.0 (2020-06-15)
-------------------
* Massive restructuring
* Restricted IP check
* Bomb deploy improvements
* More verbose action logging
* Division switching for maverick scripts
* New medal endpoint is correctly parsed
* WAM/Employ modularized


0.19.0 (2020-01-13)
-------------------
* Created method for current products on sale.
* Updated inventory to also include products on sale
* set_default_weapon() - eRepublik should return list with all available weapon qualities, but when a battle is just launched, they return only dict with barehands
* fight() - no longer calls self.set_default_weapon()
* find_battle_and_fight() - now calls self.set_default_weapon() just before fighting
* update_war_info() - returns previous battle list if responses 'last_updated' isn't more than 30s old
* get_battle_for_war(war_id) - returns Battle instance for specific war, if battle is active for given war
* Citizen.get_raw_surplus() fixed and moved to Citizen.my_companies.get_wam_raw_usage()
* Implemented division switching
* improved multi bomb deploy with auto traveling,
* Citizen.fight() simplified battle data gathering logic -> Citizen.shoot logic improved


0.17.0 (2019-11-21)
-------------------

* 12th anniversary's endpoints added
* Telegram message queue optimisation
* WC end fighting energy bugfix
* More strict fighting limiting before week change
* Improved and fixed ground damage booster usage


0.16.0 (2019-09-29)
-------------------

* Telegram notification integration
* Improved serialization to JSON
* When failing to do WAM because of not enough food - buy food
* Buy food buys 48h worth instead of 24h energy


0.15.3 (2019-08-24)
-------------------

* Update after eRepublik changed campaign apis


0.15.0 (2019-07-30)
-------------------

* CitizenAPI class methods renamed to "private", they are intended to be used internally.
* TODO: None of the Citizen class's methods should return Response object - CitizenAPI is meant for that.


0.14.4 (2019-07-23)
-------------------

* Wall post comment endpoints updated with comment create endpoints.


0.1.0 (2019-07-19)
------------------

* First release on PyPI.
