# -*- coding: utf-8 -*-

"""Top-level package for eRepublik script."""

__author__ = """Eriks Karls"""
__email__ = 'eriks@72.lv'
__version__ = '0.24.0.1'

from erepublik import classes, constants, utils
from erepublik.citizen import Citizen

__all__ = ["classes", "utils", "Citizen", 'constants']
