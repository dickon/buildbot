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
    """Add a commit to workd which sets filename to contain
    contents with commit message"""
    with file(workd+'/'+filename, 'w') as fobj:
        fobj.write(contents)
    deferred = git(workd, 'add', filename)
    def commit(_):
        """Perform the commit"""
        return git(workd, 'commit', '-m', message)
    return deferred.addCallback(commit)

class PopulatedRepository:
    """Create a test git repository in temporary space with a known
    commit and tag, and delete it when the test is done
    """
    def git(self, *arguments):
        """Run a git command with arguments on our test repository"""
        return git(self.workd, *arguments)
    def setUp(self):
        """Prepare the test repsotiroy"""
        self.workd = mkdtemp('.testgit')
        self.multgit = MultiGit([self.workd])
        deferred = self.git('init')
        deferred.addCallback(lambda _: add_commit(self.workd, 'bar', 
                                     'spong', 'foo'))
        deferred.addCallback(lambda _: git(self.workd, 'tag', 'tag1'))
        return deferred
    def tearDown(self):
        """Remove the test repository"""
        return run('rm', ['-rf', self.workd])

class TestGitPoller(PopulatedRepository, unittest.TestCase):
    """Test some basic operations"""
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
    def testGetTag(self):
        """Can we find the known tag"""
        return find_ref(self.workd, 'refs/tags/tag1')

