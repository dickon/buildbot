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
from buildbot.changes.multigit import MultiGit, find_ref, get_metadata, run, git
from tempfile import mkdtemp

def add_commit(workd, filename, contents, message):
    with file(workd+'/'+filename, 'w') as f:
        f.write(contents)
    d = git(workd, 'add', filename)
    def commit(_):
        return git(workd, 'commit', '-m', message)
    return d.addCallback(commit)

class PopulatedRepository:
    def git(self, *l):
        return git(self.workd, *l)
    def setUp(self):
        self.workd = mkdtemp('.testgit')
        self.multgit = MultiGit([self.workd])
        d = self.git('init')
        d.addCallback(lambda _: add_commit(self.workd, 'bar', 'spong', 'foo'))
        return d.addCallback(lambda _: git(self.workd, 'tag', 'tag1'))
    def tearDown(self):
        return run('rm', ['-rf', self.workd])

class TestGitPoller(PopulatedRepository, unittest.TestCase):
    def testGetLog(self):
        d = self.git('log')
        def check((o,e)):
            self.assertIn('foo', o)
            return find_ref(self.workd, 'refs/heads/master')
        d.addCallback(check)
        def check_ref(hash):
            self.assertEquals(len(hash),40)
            return get_metadata(self.workd, hash)
        d.addCallback(check_ref)
        def verify_metadata(data):
            self.assertIn('foo', data['message'])
            self.commit1 = data
            return add_commit(self.workd, 'a', 'b', 'xyzzy')
        d.addCallback(verify_metadata)
        def check_new(commit2):
            self.commit2 = commit2
            return find_ref(self.workd, 'refs/heads/master')
        d.addCallback(check_new)
        def compare_commits(_):
            self.assertEqauls(self.commit2['message'], 'xyzzy\n')
            self.assertNotEqual(self.commit1['revision'], self.commit2['revision'])
        return d

class TestTag(PopulatedRepository, unittest.TestCase):
    def testGetTag(self):
        return find_ref(self.workd, 'refs/tags/tag1')
