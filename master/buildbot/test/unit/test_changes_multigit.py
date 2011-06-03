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
        deferred = self.git('log')
        commits = []
        def check((o,e)):
            self.assertIn('foo', o)
            return find_ref(self.workd, 'refs/heads/master')
        deferred.addCallback(check)
        def check_ref(hash):
            """Check the hash is the length we expect"""
            self.assertEquals(len(hash), 40)
            return get_metadata(self.workd, hash)
        deferred.addCallback(check_ref)
        def verify_metadata(data):
            """Check the message is what we expect"""
            self.assertIn('foo', data['message'])
            commits.append(data)
            return add_commit(self.workd, 'a', 'b', 'xyzzy')
        deferred.addCallback(verify_metadata)
        def check_new(commit2):
            """Stash away the second commit"""
            commits.append(commit2)
            return find_ref(self.workd, 'refs/heads/master')
        deferred.addCallback(check_new)
        def compare_commits(_):
            """Check the commits are like we expect"""
            self.assertEqauls(commits[1]['message'], 'xyzzy\n')
            self.assertNotEqual(commits[0]['revision'], commits[1]['revision'])
        return deferred
    def testGetTag(self):
        """Can we find the known tag"""
        return find_ref(self.workd, 'refs/tags/tag1')

