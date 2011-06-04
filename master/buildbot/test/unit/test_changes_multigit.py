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
from buildbot.changes.multigit import untagged_revisions
from buildbot.test.util import changesource
from tempfile import mkdtemp
from time import time

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
        deferred = self.git('init')
        deferred.addCallback(lambda _: add_commit(self.workd, 'bar', 
                                     'spong', 'foo'))
        deferred.addCallback(lambda _: git(self.workd, 'tag', 'tag1'))
        return deferred
    def tearDown(self):
        """Remove the test repository"""
        return run('rm', ['-rf', self.workd])

class TestGitFunctions(PopulatedRepository, unittest.TestCase):
    """Test some basic operations"""
    def test_get_log(self):
        deferred = self.git('log')
        def check(o):
            self.assertIn('foo', o)
        return deferred.addCallback(check)
    def test_commit_detection(self):
        """Test that we see refs/heads/master change,
        and can read back commit messages"""
        commits = []
        deferred = find_ref(self.workd, 'refs/heads/master')
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
            return find_ref(self.workd, 'refs/heads/master')
        deferred.addCallback(check_new)
        deferred.addCallback(lambda rev: get_metadata(self.workd, rev))
        def compare_commits(commit2):
            """Check the commits are like we expect"""
            commits.append(commit2)
            self.assertEquals(commits[1]['message'], 'xyzzy')
            self.assertNotEqual(commits[0]['revision'], commits[1]['revision'])
        deferred.addCallback(compare_commits)
        return deferred
    def test_commit_watcher(self):
        """Test that we see refs/heads/master change,
        and can read back commit messages"""
        deferred = untagged_revisions(self.workd)
        def check_none_unmatched(unmatched):
            self.assertEquals(unmatched, [])
            return add_commit(self.workd, 'a', 'b', 'xyzzy')
        deferred.addCallback(check_none_unmatched)
        deferred.addCallback(lambda _: untagged_revisions(self.workd))
        deferred.addCallback(lambda unmatched: self.assertEquals(
                len(unmatched),1))
        
        return deferred
    def test_get_tag(self):
        """Can we find the known tag"""
        return find_ref(self.workd, 'refs/tags/tag1')
    def test_commit_age(self):
        """Check that the head of master is less than 10 seconds old"""
        deferred = find_ref(self.workd, 'refs/heads/master').addCallback(
            lambda rev: get_metadata(self.workd, rev))
        def check_commit_time(metadata):
            self.failUnless(metadata['commit_time'] > time()-10)
            self.failUnless(metadata['commit_time'] < time())
        return deferred.addCallback(check_commit_time)

class TestMultiGit(PopulatedRepository, unittest.TestCase,
                   changesource.ChangeSourceMixin):
    def setUp(self):
        deferred = PopulatedRepository.setUp(self)
        deferred.addCallback(lambda _: self.setUpChangeSource())
        def create(_):
            self.multigit = MultiGit([self.workd], self.master)
        return deferred.addCallback(create)
    def test_poll_nothing_untagged(self):
        deferred = self.multigit.poll()
        def check1(_):
            self.assertEqual(len(self.changes_added), 0)
        return deferred.addCallback(check1)
    def test_poll_two_commits(self):
        deferred = add_commit(self.workd, 'a', 'b', 'xyzzy')
        deferred.addCallback(
            lambda _: add_commit(self.workd, 'c', 'd', 'e'))
        self.multigit.age_requirement = 0
        deferred.addCallback(lambda _: self.multigit.poll())
        def check2(_):
            self.assertEqual(len(self.changes_added), 1)
            self.failUnless('xyzzy' in self.changes_added[0]['comments'])
            self.assertEqual('tag2', self.changes_added[0]['revision'])
        return deferred.addCallback(check2)
    def test_poll_one_recent_commit(self):
        deferred = add_commit(self.workd, 'a', 'b', 'xyzzy')
        self.multigit.age_requirement = 600
        deferred.addCallback(lambda _: self.multigit.poll())
        def check(_):
            self.assertEqual(len(self.changes_added), 0)
        return deferred.addCallback(check)
    def test_poll_multi_branches(self):
        deferred = add_commit(self.workd, 'a', 'b', 'xyzzy')
        deferred.addCallback(self.workd, 'd', 'e', 'erer', branch='branch2')
        self.multigit.age_requirement = 0
        deferred.addCallback(lambda _: self.multigit.poll())
        def check(_):
            self.assertEqual(len(self.changes_added), 2)
        return deferred.addCallback(check)
        
    
