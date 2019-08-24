#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""The setup script."""

from setuptools import setup, find_packages

with open('README.rst') as readme_file:
    readme = readme_file.read()

with open('HISTORY.rst') as history_file:
    history = history_file.read()

requirements = ['pytz==2019.1', 'requests==2.22.0']

setup_requirements = [ ]

test_requirements = [ ]

setup(
    author="Eriks Karls",
    author_email='eriks@72.lv',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Natural Language :: English',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
    ],
    description="Python package for automated eRepublik playing",
    entry_points={},
    install_requires=requirements,
    license="MIT license",
    long_description=readme + '\n\n' + history,
    include_package_data=True,
    keywords='erepublik',
    name='eRepublik',
    packages=find_packages(include=['erepublik']),
    python_requires='>=3.7.*, <4',
    setup_requires=setup_requirements,
    test_suite='tests',
    tests_require=test_requirements,
    url='https://github.com/eeriks/erepublik_script',
    version='0.15.3',
    zip_safe=False,
)
