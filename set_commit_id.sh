#!/bin/bash

commit=$(git log -1 --pretty=format:%h)
sed -i.bak -E "s|__commit_id__ = \".+\"|__commit_id__ = \"${commit}\"|g" erepublik/__init__.py
rm erepublik/__init__.py.bak
