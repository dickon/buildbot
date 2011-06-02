# This file is part of Buildbot.  Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright Buildbot Team Members


from twisted.internet.utils import getProcessOutput, getProcessOutputAndValue

class UnexpectedExitCode(Exception):
    pass

def clean(text):
    """Convert all whitespace in to simple spaces"""
    return ' '.join(text.split())

    

def run(*kl, **kd):
    expected_return_code = kd.pop('expected_return_code', 0)
    d = getProcessOutputAndValue(*kl, **kd)
    def check((o,e,ec)):
        if ec != expected_return_code:
            raise UnexpectedExitCode(kl, kd, o, e, ec, expected_return_code)
        return (o,e)
    d.addCallback(check)
    return d

def find_ref(gitd, ref):
    d = run('git', ['show-ref', ref], path=gitd)
    def analyse((out, _)):
        for line in clean(out).split('\n'):
            return line.split()[0]
    return d.addCallback(analyse)

def get_metadata(gitd, hash):
    pass

class MultiGit:
    def __init__(self, repositories):
        self.repositories = repositories
