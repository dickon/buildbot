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
from buildbot.changes import multigit
from buildbot.test.util import changesource, gpo
from buildbot.util import epoch2datetime
from tempfile import mkdtemp

class TestGitPoller(unittest.TestCase):

    def setUp(self):
        self.workd = mkdtemp('.testgit')
        d = getProcessOutputAndValue('git', ['init'], path=self.workd)
        return d
    def tearDown(self):
        d = getProcessOutputAndValue('rm', ['-rf', self.workd])
        return d
    def testGetLog(self):
        d = getProcessOutputAndValue('git', ['log'], path=self.workd)
        def check((o,e,ec)):
            self.assertIn('bad default revision', e)
            self.assertEquals(ec, 128)
        d.addCallback(check)
        return d
