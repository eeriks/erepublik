# -*- coding: utf-8 -*-

"""Top-level package for eRepublik script."""

__author__ = """Eriks Karls"""
__email__ = 'eriks@72.lv'
__version__ = '0.20.1'
__commit_id__ = "a825917"

from erepublik import classes, utils
from erepublik.citizen import Citizen

__all__ = ["classes", "utils", "Citizen"]
