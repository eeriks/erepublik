# -*- coding: utf-8 -*-

"""Top-level package for eRepublik script."""

__author__ = """Eriks Karls"""
__email__ = 'eriks@72.lv'
__version__ = '0.20.2'
__commit_id__ = "d07334f"

from erepublik import classes, utils
from erepublik.citizen import Citizen

__all__ = ["classes", "utils", "Citizen"]
