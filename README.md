# pwntools - CTF toolkit
![pwntools logo](https://github.com/Gallopsled/pwntools/blob/stable/docs/source/logo.png?raw=true)

[![PyPI](https://img.shields.io/pypi/v/pwntools?style=flat)](https://pypi.python.org/pypi/pwntools/)
[![Docs](https://readthedocs.org/projects/pwntools/badge/?version=stable)](https://docs.pwntools.com/)
[![GitHub Workflow Status (dev)](https://img.shields.io/github/actions/workflow/status/Gallopsled/pwntools/ci.yml?branch=dev&logo=GitHub)](https://github.com/Gallopsled/pwntools/actions/workflows/ci.yml?query=branch%3Adev)
[![Coveralls](https://img.shields.io/coveralls/github/Gallopsled/pwntools/dev?logo=coveralls)](https://coveralls.io/github/Gallopsled/pwntools?branch=dev)
[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg?style=flat)](http://choosealicense.com/licenses/mit/)
[![Packaging status](https://img.shields.io/repology/repositories/python:pwntools)](https://repology.org/project/python:pwntools/versions)
[![Discord](https://img.shields.io/discord/809590285687980052?label=Discord&style=plastic)](https://discord.gg/96VA2zvjCB)
[![Twitter](https://img.shields.io/twitter/follow/Pwntools)](https://twitter.com/pwntools)

Pwntools is a CTF framework and exploit development library. Written in Python, it is designed for rapid prototyping and development, and intended to make exploit writing as simple as possible.

```python
from pwn import *
context(arch = 'i386', os = 'linux')

r = remote('exploitme.example.com', 31337)
# EXPLOIT CODE GOES HERE
r.send(asm(shellcraft.sh()))
r.interactive()
```

# Documentation

Our documentation is available at [docs.pwntools.com](https://docs.pwntools.com/)

A series of tutorials is also [available online](https://github.com/Gallopsled/pwntools-tutorial#readme)

To get you started, we've provided some example solutions for past CTF challenges in our [write-ups repository](https://github.com/Gallopsled/pwntools-write-ups).

# Installation

Pwntools is best supported on 64-bit Ubuntu LTS releases (22.04 and 24.04).  Most functionality should work on any Posix-like distribution (Debian, Arch, FreeBSD, OSX, etc.).  

Pwntools supports Python 3.10+ since version 5.0.0.  Use Pwntools 4.x for older versions as well as Python 2.7. Most of the functionality of pwntools is self-contained and Python-only.  You should be able to get running quickly with

```sh
sudo apt-get update
sudo apt-get install python3 python3-pip python3-dev git libssl-dev libffi-dev build-essential
python3 -m pip install --upgrade pip
python3 -m pip install --upgrade pwntools
```


However, some of the features (assembling/disassembling foreign architectures) require non-Python dependencies.  For more information, see the [complete installation instructions here](https://docs.pwntools.com/en/stable/install.html).


# Contribution

See [CONTRIBUTING.md](CONTRIBUTING.md)

# Contact and Community
If you have any questions not worthy of a [bug report](https://github.com/Gallopsled/pwntools/issues), join the Discord server at https://discord.gg/96VA2zvjCB
