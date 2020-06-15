# -*- coding: utf-8 -*-

"""Top-level package for eRepublik script."""

__author__ = """Eriks Karls"""
__email__ = 'eriks@72.lv'
__version__ = '0.20.0'
__commit_id__ = "f83df44"

from erepublik import classes, utils
from erepublik.citizen import Citizen

__all__ = ["classes", "utils", "Citizen"]
