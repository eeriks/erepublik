#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""The setup script."""

from setuptools import setup, find_packages

with open('README.rst') as readme_file:
    readme = readme_file.read()

with open('HISTORY.rst') as history_file:
    history = history_file.read()

requirements = ['Click>=6.0', 'pytz==2018.9', 'requests==2.21.0', 'python-slugify==2.0.1']

setup_requirements = [ ]

test_requirements = [ ]

setup(
    author="Eriks Karls",
    author_email='eriks@72.lv',
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Natural Language :: English',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
    ],
    description="Python package for eRepublik automated playing",
    entry_points={
        'console_scripts': [
            'erepublik_script=erepublik_script.cli:main',
        ],
    },
    install_requires=requirements,
    license="MIT license",
    long_description=readme + '\n\n' + history,
    include_package_data=True,
    keywords='erepublik_script',
    name='erepublik_script',
    packages=find_packages(include=['erepublik_script']),
    setup_requires=setup_requirements,
    test_suite='tests',
    tests_require=test_requirements,
    url='https://github.com/eeriks/erepublik_script',
    version='0.1.2',
    zip_safe=False,
)
