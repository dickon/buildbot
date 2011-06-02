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

from twisted.trial import unittest
from twisted.internet import defer
from twisted.internet.utils import getProcessOutput, getProcessOutputAndValue
from exceptions import Exception
from buildbot.changes.multigit import MultiGit
from buildbot.test.util import changesource, gpo
from buildbot.util import epoch2datetime
from tempfile import mkdtemp

class UnexpectedOutputValue(Exception):
    pass

def run(*kl, **kd):
    expected_return_code = kd.pop('expected_return_code', 0)
    d = getProcessOutputAndValue(*kl, **kd)
    def check((o,e,ec)):
        if ec != expected_return_code:
            raise UnexpectedOutputValue(kl, kd, o, e, ec, expected_return_code)
        return (o,e)
    d.addCallback(check)
    return d
    
class TestGitPoller(unittest.TestCase):
    def setUp(self):
        self.workd = mkdtemp('.testgit')
        self.multgit = MultiGit([self.workd])
        return run('git', ['init'], path=self.workd)
    def tearDown(self):
        return run('rm', ['-rf', self.workd])
    def testGetLog(self):
        d = run('git', ['log'], path=self.workd, expected_return_code=128)
        def check((o,e)):
            self.assertIn('foo', o)
        return d.addCallback(check)
