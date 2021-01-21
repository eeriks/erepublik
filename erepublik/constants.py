import datetime
from typing import Dict, Optional, Union

import pytz

__all__ = ['erep_tz', 'min_datetime', 'max_datetime', 'Country', 'AIR_RANKS', 'COUNTRIES', 'FOOD_ENERGY',
           'GROUND_RANKS', 'GROUND_RANK_POINTS', 'INDUSTRIES', 'TERRAINS']

erep_tz = pytz.timezone('US/Pacific')
min_datetime = erep_tz.localize(datetime.datetime(2007, 11, 20))
max_datetime = erep_tz.localize(datetime.datetime(2281, 9, 4))


class Country:
    id: int
    name: str
    link: str
    iso: str

    def __init__(self, country_id: int, name: str, link: str, iso: str):
        self.id = country_id
        self.name = name
        self.link = link
        self.iso = iso

    def __hash__(self):
        return hash((self.id, self.name))

    def __repr__(self):
        return f"Country({self.id}, '{self.name}', '{self.link}', '{self.iso}')"

    def __str__(self):
        return f"#{self.id} {self.name}"

    def __format__(self, format_spec):
        return self.iso

    def __int__(self):
        return self.id

    def __eq__(self, other):
        if isinstance(other, (int, float)):
            return self.id == int(other)
        else:
            try:
                return self.id == int(other)
            except ValueError:
                return self == other

    @property
    def as_dict(self):
        return dict(id=self.id, name=self.name, iso=self.iso)


class Industries:
    __by_name = {'food': 1, 'weapon': 2, 'ticket': 3, 'house': 4, 'aircraft': 23,
                 'foodraw': 7, 'weaponraw': 12, 'houseraw': 18, 'aircraftraw': 24, 'airplaneraw': 24,
                 'frm': 7, 'wrm': 12, 'hrm': 18, 'arm': 24,
                 'frm q1': 7, 'frm q2': 8, 'frm q3': 9, 'frm q4': 10, 'frm q5': 11,
                 'wrm q1': 12, 'wrm q2': 13, 'wrm q3': 14, 'wrm q4': 15, 'wrm q5': 16,
                 'hrm q1': 18, 'hrm q2': 19, 'hrm q3': 20, 'hrm q4': 21, 'hrm q5': 22,
                 'arm q1': 24, 'arm q2': 25, 'arm q3': 26, 'arm q4': 27, 'arm q5': 28}
    __by_id = {1: 'Food', 2: 'Weapon', 3: 'Ticket', 4: 'House', 23: 'Aircraft',
               7: 'foodRaw', 8: 'FRM q2', 9: 'FRM q3', 10: 'FRM q4', 11: 'FRM q5',
               12: 'weaponRaw', 13: 'WRM q2', 14: 'WRM q3', 15: 'WRM q4', 16: 'WRM q5',
               17: 'houseRaw', 18: 'houseRaw', 19: 'HRM q2', 20: 'HRM q3', 21: 'HRM q4', 22: 'HRM q5',
               24: 'aircraftRaw', 25: 'ARM q2', 26: 'ARM q3', 27: 'ARM q4', 28: 'ARM q5'}

    def __getitem__(self, item) -> Optional[Union[int, str]]:
        if isinstance(item, int):
            return self.__by_id.get(item, None)
        elif isinstance(item, str):
            return self.__by_name.get(item.lower(), None)
        return

    def __getattr__(self, item) -> Optional[Union[int, str]]:
        return self[item]

    @property
    def as_dict(self):
        return dict(by_id=self.__by_id, by_name=self.__by_name)


AIR_RANKS: Dict[int, str] = {
    1: 'Airman', 2: 'Airman 1st Class', 3: 'Airman 1st Class*', 4: 'Airman 1st Class**', 5: 'Airman 1st Class***',
    6: 'Airman 1st Class****', 7: 'Airman 1st Class*****', 8: 'Senior Airman', 9: 'Senior Airman*',
    10: 'Senior Airman**', 11: 'Senior Airman***', 12: 'Senior Airman****', 13: 'Senior Airman*****',
    14: 'Staff Sergeant', 15: 'Staff Sergeant*', 16: 'Staff Sergeant**', 17: 'Staff Sergeant***',
    18: 'Staff Sergeant****', 19: 'Staff Sergeant*****', 20: 'Aviator', 21: 'Aviator*', 22: 'Aviator**',
    23: 'Aviator***', 24: 'Aviator****', 25: 'Aviator*****', 26: 'Flight Lieutenant', 27: 'Flight Lieutenant*',
    28: 'Flight Lieutenant**', 29: 'Flight Lieutenant***', 30: 'Flight Lieutenant****', 31: 'Flight Lieutenant*****',
    32: 'Squadron Leader', 33: 'Squadron Leader*', 34: 'Squadron Leader**', 35: 'Squadron Leader***',
    36: 'Squadron Leader****', 37: 'Squadron Leader*****', 38: 'Chief Master Sergeant', 39: 'Chief Master Sergeant*',
    40: 'Chief Master Sergeant**', 41: 'Chief Master Sergeant***', 42: 'Chief Master Sergeant****',
    43: 'Chief Master Sergeant*****', 44: 'Wing Commander', 45: 'Wing Commander*', 46: 'Wing Commander**',
    47: 'Wing Commander***', 48: 'Wing Commander****', 49: 'Wing Commander*****', 50: 'Group Captain',
    51: 'Group Captain*', 52: 'Group Captain**', 53: 'Group Captain***', 54: 'Group Captain****',
    55: 'Group Captain*****', 56: 'Air Commodore', 57: 'Air Commodore*', 58: 'Air Commodore**', 59: 'Air Commodore***',
    60: 'Air Commodore****', 61: 'Air Commodore*****',
}

COUNTRIES: Dict[int, Country] = {
    1: Country(1, 'Romania', 'Romania', 'ROU'), 9: Country(9, 'Brazil', 'Brazil', 'BRA'),
    10: Country(10, 'Italy', 'Italy', 'ITA'), 11: Country(11, 'France', 'France', 'FRA'),
    12: Country(12, 'Germany', 'Germany', 'DEU'), 13: Country(13, 'Hungary', 'Hungary', 'HUN'),
    14: Country(14, 'China', 'China', 'CHN'), 15: Country(15, 'Spain', 'Spain', 'ESP'),
    23: Country(23, 'Canada', 'Canada', 'CAN'), 24: Country(24, 'USA', 'USA', 'USA'),
    26: Country(26, 'Mexico', 'Mexico', 'MEX'), 27: Country(27, 'Argentina', 'Argentina', 'ARG'),
    28: Country(28, 'Venezuela', 'Venezuela', 'VEN'), 29: Country(29, 'United Kingdom', 'United-Kingdom', 'GBR'),
    30: Country(30, 'Switzerland', 'Switzerland', 'CHE'), 31: Country(31, 'Netherlands', 'Netherlands', 'NLD'),
    32: Country(32, 'Belgium', 'Belgium', 'BEL'), 33: Country(33, 'Austria', 'Austria', 'AUT'),
    34: Country(34, 'Czech Republic', 'Czech-Republic', 'CZE'), 35: Country(35, 'Poland', 'Poland', 'POL'),
    36: Country(36, 'Slovakia', 'Slovakia', 'SVK'), 37: Country(37, 'Norway', 'Norway', 'NOR'),
    38: Country(38, 'Sweden', 'Sweden', 'SWE'), 39: Country(39, 'Finland', 'Finland', 'FIN'),
    40: Country(40, 'Ukraine', 'Ukraine', 'UKR'), 41: Country(41, 'Russia', 'Russia', 'RUS'),
    42: Country(42, 'Bulgaria', 'Bulgaria', 'BGR'), 43: Country(43, 'Turkey', 'Turkey', 'TUR'),
    44: Country(44, 'Greece', 'Greece', 'GRC'), 45: Country(45, 'Japan', 'Japan', 'JPN'),
    47: Country(47, 'South Korea', 'South-Korea', 'KOR'), 48: Country(48, 'India', 'India', 'IND'),
    49: Country(49, 'Indonesia', 'Indonesia', 'IDN'), 50: Country(50, 'Australia', 'Australia', 'AUS'),
    51: Country(51, 'South Africa', 'South-Africa', 'ZAF'),
    52: Country(52, 'Republic of Moldova', 'Republic-of-Moldova', 'MDA'),
    53: Country(53, 'Portugal', 'Portugal', 'PRT'), 54: Country(54, 'Ireland', 'Ireland', 'IRL'),
    55: Country(55, 'Denmark', 'Denmark', 'DNK'), 56: Country(56, 'Iran', 'Iran', 'IRN'),
    57: Country(57, 'Pakistan', 'Pakistan', 'PAK'), 58: Country(58, 'Israel', 'Israel', 'ISR'),
    59: Country(59, 'Thailand', 'Thailand', 'THA'), 61: Country(61, 'Slovenia', 'Slovenia', 'SVN'),
    63: Country(63, 'Croatia', 'Croatia', 'HRV'), 64: Country(64, 'Chile', 'Chile', 'CHL'),
    65: Country(65, 'Serbia', 'Serbia', 'SRB'), 66: Country(66, 'Malaysia', 'Malaysia', 'MYS'),
    67: Country(67, 'Philippines', 'Philippines', 'PHL'), 68: Country(68, 'Singapore', 'Singapore', 'SGP'),
    69: Country(69, 'Bosnia and Herzegovina', 'Bosnia-Herzegovina', 'BiH'),
    70: Country(70, 'Estonia', 'Estonia', 'EST'), 80: Country(80, 'Montenegro', 'Montenegro', 'MNE'),
    71: Country(71, 'Latvia', 'Latvia', 'LVA'), 72: Country(72, 'Lithuania', 'Lithuania', 'LTU'),
    73: Country(73, 'North Korea', 'North-Korea', 'PRK'), 74: Country(74, 'Uruguay', 'Uruguay', 'URY'),
    75: Country(75, 'Paraguay', 'Paraguay', 'PRY'), 76: Country(76, 'Bolivia', 'Bolivia', 'BOL'),
    77: Country(77, 'Peru', 'Peru', 'PER'), 78: Country(78, 'Colombia', 'Colombia', 'COL'),
    79: Country(79, 'Republic of Macedonia (FYROM)', 'Republic-of-Macedonia-FYROM', 'MKD'),
    81: Country(81, 'Republic of China (Taiwan)', 'Republic-of-China-Taiwan', 'TWN'),
    82: Country(82, 'Cyprus', 'Cyprus', 'CYP'), 167: Country(167, 'Albania', 'Albania', 'ALB'),
    83: Country(83, 'Belarus', 'Belarus', 'BLR'), 84: Country(84, 'New Zealand', 'New-Zealand', 'NZL'),
    164: Country(164, 'Saudi Arabia', 'Saudi-Arabia', 'SAU'), 165: Country(165, 'Egypt', 'Egypt', 'EGY'),
    166: Country(166, 'United Arab Emirates', 'United-Arab-Emirates', 'UAE'),
    168: Country(168, 'Georgia', 'Georgia', 'GEO'), 169: Country(169, 'Armenia', 'Armenia', 'ARM'),
    170: Country(170, 'Nigeria', 'Nigeria', 'NGA'), 171: Country(171, 'Cuba', 'Cuba', 'CUB')
}

FOOD_ENERGY: Dict[str, int] = dict(q1=2, q2=4, q3=6, q4=8, q5=10, q6=12, q7=20)

GROUND_RANKS: Dict[int, str] = {
    1: 'Recruit', 2: 'Private', 3: 'Private*', 4: 'Private**', 5: 'Private***',
    6: 'Corporal', 7: 'Corporal*', 8: 'Corporal**', 9: 'Corporal***',
    10: 'Sergeant', 11: 'Sergeant*', 12: 'Sergeant**', 13: 'Sergeant***',
    14: 'Lieutenant', 15: 'Lieutenant*', 16: 'Lieutenant**', 17: 'Lieutenant***',
    18: 'Captain', 19: 'Captain*', 20: 'Captain**', 21: 'Captain***',
    22: 'Major', 23: 'Major*', 24: 'Major**', 25: 'Major***',
    26: 'Commander', 27: 'Commander*', 28: 'Commander**', 29: 'Commander***',
    30: 'Lt Colonel', 31: 'Lt Colonel*', 32: 'Lt Colonel**', 33: 'Lt Colonel***',
    34: 'Colonel', 35: 'Colonel*', 36: 'Colonel**', 37: 'Colonel***',
    38: 'General', 39: 'General*', 40: 'General**', 41: 'General***',
    42: 'Field Marshal', 43: 'Field Marshal*', 44: 'Field Marshal**', 45: 'Field Marshal***',
    46: 'Supreme Marshal', 47: 'Supreme Marshal*', 48: 'Supreme Marshal**', 49: 'Supreme Marshal***',
    50: 'National Force', 51: 'National Force*', 52: 'National Force**', 53: 'National Force***',
    54: 'World Class Force', 55: 'World Class Force*', 56: 'World Class Force**', 57: 'World Class Force***',
    58: 'Legendary Force', 59: 'Legendary Force*', 60: 'Legendary Force**', 61: 'Legendary Force***',
    62: 'God of War', 63: 'God of War*', 64: 'God of War**', 65: 'God of War***',
    66: 'Titan', 67: 'Titan*', 68: 'Titan**', 69: 'Titan***',
    70: 'Legends I', 71: 'Legends II', 72: 'Legends III', 73: 'Legends IV', 74: 'Legends V', 75: 'Legends VI',
    76: 'Legends VII', 77: 'Legends VIII', 78: 'Legends IX', 79: 'Legends X', 80: 'Legends XI', 81: 'Legends XII',
    82: 'Legends XIII', 83: 'Legends XIV', 84: 'Legends XV', 85: 'Legends XVI', 86: 'Legends XVII', 87: 'Legends XVIII',
    88: 'Legends XIX', 89: 'Legends XX',
}

GROUND_RANK_POINTS: Dict[int, int] = {
    1: 0, 2: 15, 3: 45, 4: 80, 5: 120, 6: 170, 7: 250, 8: 350, 9: 450, 10: 600, 11: 800, 12: 1000,
    13: 1400, 14: 1850, 15: 2350, 16: 3000, 17: 3750, 18: 5000, 19: 6500, 20: 9000, 21: 12000,
    22: 15500, 23: 20000, 24: 25000, 25: 31000, 26: 40000, 27: 52000, 28: 67000, 29: 85000,
    30: 110000, 31: 140000, 32: 180000, 33: 225000, 34: 285000, 35: 355000, 36: 435000, 37: 540000,
    38: 660000, 39: 800000, 40: 950000, 41: 1140000, 42: 1350000, 43: 1600000, 44: 1875000,
    45: 2185000, 46: 2550000, 47: 3000000, 48: 3500000, 49: 4150000, 50: 4900000, 51: 5800000,
    52: 7000000, 53: 9000000, 54: 11500000, 55: 14500000, 56: 18000000, 57: 22000000, 58: 26500000,
    59: 31500000, 60: 37000000, 61: 43000000, 62: 50000000, 63: 100000000, 64: 200000000,
    65: 500000000, 66: 1000000000, 67: 2000000000, 68: 4000000000, 69: 10000000000, 70: 20000000000,
    71: 30000000000, 72: 40000000000, 73: 50000000000, 74: 60000000000, 75: 70000000000,
    76: 80000000000, 77: 90000000000, 78: 100000000000, 79: 110000000000, 80: 120000000000,
    81: 130000000000, 82: 140000000000, 83: 150000000000, 84: 160000000000, 85: 170000000000,
    86: 180000000000, 87: 190000000000, 88: 200000000000, 89: 210000000000
}

INDUSTRIES = Industries()

TERRAINS: Dict[int, str] = {0: 'Standard', 1: 'Industrial', 2: 'Urban', 3: 'Suburbs', 4: 'Airport', 5: 'Plains',
                            6: 'Wasteland', 7: 'Mountains', 8: 'Beach', 9: 'Swamp', 10: 'Mud', 11: 'Hills',
                            12: 'Jungle', 13: 'Forest', 14: 'Desert'}
