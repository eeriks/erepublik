#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""The setup script."""

from setuptools import find_packages, setup

with open("README.rst") as readme_file:
    readme = readme_file.read()

with open("HISTORY.rst") as history_file:
    history = history_file.read()

with open("requirements.txt") as requirements_file:
    requirements = requirements_file.read()
    requirements = requirements.split()

setup_requirements = []

with open("requirements-tests.txt") as test_req_file:
    test_requirements = test_req_file.read()
    test_requirements = [
        line.strip() for line in test_requirements.split() if line.strip()[:2].strip() not in ("#", "-r")
    ]

setup(
    author="Eriks Karls",
    author_email="eriks@72.lv",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Natural Language :: English",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
    ],
    description="Python package for automated eRepublik playing",
    entry_points={},
    install_requires=requirements,
    license="GPLv3",
    long_description=readme + "\n\n" + history,
    include_package_data=True,
    keywords="erepublik",
    name="eRepublik",
    packages=find_packages(include=["erepublik"]),
    python_requires=">=3.8, <4",
    setup_requires=setup_requirements,
    test_suite="tests",
    tests_require=test_requirements,
    url="https://github.com/eeriks/erepublik/",
    version="0.29.1",
    zip_safe=False,
)
