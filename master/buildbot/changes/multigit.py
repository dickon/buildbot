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


from twisted.internet.utils import getProcessOutputAndValue
from time import strptime, mktime, time
from twisted.internet.defer import DeferredList

class UnexpectedExitCode(Exception):
    """A subprocess exited with an unexpected exit code"""
    pass

def clean(text):
    """Convert all whitespace in to simple spaces"""
    return ' '.join(text.split())

def run(*kl, **kd):
    """Run shell command and return a deferred, which will errback
    with UnexpectedExitCode if the exit code is not expected_return_code
    (which defualts to 0)"""
    expected_return_code = kd.pop('expected_return_code', 0)
    deferred = getProcessOutputAndValue(*kl, **kd)
    def check((out, err, exitcode)):
        """Verify exit code"""
        if exitcode != expected_return_code:
            raise UnexpectedExitCode(kl, kd, out, err, exitcode, 
                                     expected_return_code)
        return (out, err)
    return deferred.addCallback(check)

def git(gitd, *kl):
    """Run a git command and return its stdout, throwing away
    its stderr, but failing with UnexpectedExitCode if it does not exit 
    cleanly"""
    return run('git', kl, path=gitd).addCallback( lambda (o, e): o)

def linesplitdropsplit(text):
    """Convert text to a list of non-empty word lists"""
    return [x.split() for x in text.split('\n') if x]

def find_ref(gitd, ref):
    """Find the revision hash for ref in gitd"""
    deferred = git(gitd, 'show-ref', ref)
    deferred.addCallback(linesplitdropsplit)
    return deferred.addCallback(lambda x: x[0][0])

def get_metadata(gitd, revision):
    """Get a metadata dictionary containg revision, author, email,
    date, and message for revision"""
    deferred = git(gitd, 'show', '--summary', revision)
    def decode(outs):
        """Parse the git summary"""
        out = outs.split('\n')
        author_lines = [x for x in out if x.startswith('Author:')]
        result = {'revision':revision, 'gitd':gitd}
        if author_lines:
            result['author'] = ' '.join( author_lines[0].split()[1:-1])
            result['email'] = author_lines[0].split()[-1]
        date_lines = [x for x in out if x.startswith('Date:')]
        if date_lines:
            result['date'] = ' '.join(date_lines[0].split()[1:])
            hours = int(result['date'][-4:-2])
            minutes = int(result['date'][-2:])
            magn = 3600 * hours + 60 * minutes
            sign = result['date'][-5]
            tzoffset = -magn if sign == '+' else magn
            ttup = strptime(result['date'][:-6], '%a %b %d %H:%M:%S %Y')
            result['commit_time'] = mktime(tuple(list(ttup[:8])+[0]))+tzoffset
        i = 0
        while i < len(out) and out[i]:
            i += 1
        i += 1
        j = i
        while j < len(out) and out[j]:
            j += 1
        message = '\n'.join(out[i:j])

        if len(message) > 4000:
            message = message[:4000]+'...'
        while message.startswith(' ') or  message.startswith('\t'):
            message = message[1:]
        result['message'] = message
        return result
    return deferred.addCallback(decode)

def untagged_revisions(gitd):
    """Return the revisions reachable from branches but not from tags"""
    deferred = git(gitd, 'rev-list', '--branches', '--not', '--tags')
    return deferred.addCallback(linesplitdropsplit)

def get_metadata_for_revisions(revisions, gitd):
    """Convert list of revisions to list of revision descriptions"""
    return DeferredList([get_metadata(gitd, revision[0]) for 
                         revision in revisions])


class MultiGit:
    """Track multiple repositories, tagging when new revisions appear
    in some."""
    def __init__(self, repositories, master, tag_format='tag%d',
                 age_requirement=0, tag_starting_index = 1):
        self.repositories = repositories
        self.master = master
        self.age_requirement = 0
        self.tag_starting_index = tag_starting_index
        self.tag_format = tag_format

    def find_fresh_tag(self):
        """Find a fresh tag across all repositories based on self.tag_format"""
        tag = self.tag_format % (self.tag_starting_index,)
        deferreds = [find_ref(gitd, 'refs/tags/'+tag) for gitd in 
                     self.repositories]
        deferred = DeferredList(deferreds, consumeErrors=True)
        def check(dlo):
            """Check that all tag lookups failed, or try a higher tag number"""
            all_fresh = True
            for found, _ in dlo:
                if found:
                    all_fresh = False # this repository has the tag
            if all_fresh:
                return tag
            else:
                self.tag_starting_index += 1
                return self.find_fresh_tag()
        return deferred.addCallback(check)

    def poll(self):
        """Look for untagged revisions at least age_requirement seconds old, 
        and tag and record them."""
        defl = []
        for repository in self.repositories:
            subd = untagged_revisions(repository)
            subd.addCallback(get_metadata_for_revisions, repository)
            defl.append(subd)
        deferred = DeferredList(defl)
        def flatten2(newrevs):
            """newrevs is a list of (status, revs) where
            revs is a list of (status, rev) objects. We assert all those
            status fields are true and flatten out to a list of rev objects"""
            revseq = []
            latestrev = []
            for status, reporevs in newrevs:
                assert status
                for statusr, rev in reporevs:
                    assert statusr
                    revseq.append(rev)
                if reporevs:
                    latestrev.append( reporevs[0][1])
            return revseq, latestrev

        deferred.addCallback(flatten2)
        def determine_tag((newrevs, latestrev)):
            """Figure out if a tag is warranted"""
            latest = time() - self.age_requirement
            oldrevs = [rev for rev in newrevs if rev['commit_time'] <= latest]
            if oldrevs == []:
                return (None, newrevs, latestrev)
            return self.find_fresh_tag().addCallback(
                lambda tag: (tag, newrevs, latestrev))
        deferred.addCallback(determine_tag)
        def apply_tag((tag, newrevs, latestrev)):
            """Tag all repositories"""
            if tag is None:
                return
            def tag_done(dlo):
                """Tagging complete or failed; retry if necessary"""
                if [dlr for dlr in dlo if not dlr[0]]:
                    # we were not able to tag; the tag must have
                    # appeared while we are thinking about adding it ourselves
                    return determine_tag( (newrevs, latestrev) )
                else:
                    return self.master.addChange(comments = repr(newrevs),
                                                 revision = tag)

            return DeferredList( 
                [git(rev['gitd'], 'tag', tag, rev['revision']) for rev in
                 latestrev], consumeErrors=True).addCallback(tag_done)
        return deferred.addCallback(apply_tag)

