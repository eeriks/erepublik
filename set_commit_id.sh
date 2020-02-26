#!/bin/bash

commit=$(git log -1 --pretty=format:%h)
sed -i.bak -E "s|COMMIT_ID = \".+\"|COMMIT_ID = \"${commit}\"|g" erepublik/utils.py
rm erepublik/utils.py.bak
