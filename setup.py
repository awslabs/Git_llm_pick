"""
Git_llm_pick packaging setup.
"""

__authors__ = "Norbert Manthey <nmanthey@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
# SPDX-License-Identifier: Apache-2.0

import os
from setuptools import setup

# Declare your non-python data files:
# Files underneath configuration/ will be copied into the build preserving the
# subdirectory structure if they exist.
data_files = []
if os.path.exists("configuration"):
    for root, dirs, files in os.walk("configuration"):
        data_files.append((os.path.relpath(root, "configuration"), [os.path.join(root, f) for f in files]))

# Also include the scripts in bin
if os.path.exists("bin"):
    for root, dirs, files in os.walk("bin"):
        data_files.append((root, [os.path.join(root, f) for f in files]))

setup(
    # include data files
    data_files=data_files,
)
