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
from pprint import pprint
from sys import stdout

class UnexpectedExitCode(Exception):
    """A subprocess exited with an unexpected exit code"""
    def __init__(self, args_list, args_dict, out, err, exit_code,
                 expected_return_code):
        self.args_list = args_list
        self.args_dict = args_dict
        self.out = out
        self.err = err
        self.exit_code = exit_code
        self.expected_return_code = expected_return_code

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

def failing_deferred_list(list_of_deferreds):
    """Return a DeferredList which will print tracebacks and
    raise the first exception"""
    defl = DeferredList(list_of_deferreds, consumeErrors=True)
    return defl.addCallback(check_list)

def annotate_list(sequence, **assignments):
    """Take sequence, a list of dictionaries, and return
    a new list of dictionaries with keyword parameters adding 
    or replacing items in the dictionary"""
    return [dict(item, **assignments) for item in sequence]

def git(gitd, *kl):
    """Run a git command and return its stdout, throwing away
    its stderr, but failing with UnexpectedExitCode if it does not exit 
    cleanly"""
    return run('git', kl, path=gitd).addCallback( lambda (o, e): o)

def linesplitdropsplit(text):
    """Convert text to a list of non-empty word lists"""
    return [x.split() for x in text.split('\n') if x]

def find_ref(gitd, ref):
    """Find the revision hash for ref in gitd, or None if not found"""
    deferred = git(gitd, 'show-ref', ref)
    deferred.addCallback(linesplitdropsplit)
    deferred.addCallback(lambda x: x[0][0])
    def handle_failure(failure):
        failure.trap(UnexpectedExitCode)
        if failure.value.exit_code == 1 and failure.value.out == '':
            return
        return failure
    return deferred.addErrback(handle_failure)
    

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

def untagged_revisions(gitd, branch='master'):
    """Return the revisions reachable from branch but not from tags"""
    deferred = git(gitd, 'rev-list', branch, '--not', '--tags')
    return deferred.addCallback(linesplitdropsplit)

def get_metadata_for_revisions(revisions, gitd):
    """Convert list of revisions to list of revision descriptions"""
    return failing_deferred_list([get_metadata(gitd, revision[0]) for 
                                  revision in revisions])

def get_branch_list(repositories):
    """Return a deferred which gives (repository path, branch_name)* 
    across repositories"""
    defl = []
    for repository in repositories:
        subd = git(repository, 'branch').addCallback(linesplitdropsplit)
        def convert(seq, repository):
            """Turn [(_,x)] -> [(repository, x[-1])]"""
            return [ (repository, brl[-1]) for brl in seq]
        subd.addCallback(convert, repository)
        defl.append(subd)
    deferred = failing_deferred_list(defl)
    return deferred.addCallback(lambda listlist: reduce(list.__add__, listlist))

def check_list(deferred_list_output):
    """Remove the status fields from a deferred_list_output, 
    raising the first error if there is one"""
    bad = None
    out = []
    for status, value in deferred_list_output:
        if not status:
            value.printTraceback()
            if bad is None:
                bad = value
        else:
            out.append(value)
    if bad:
        bad.raiseException()
    return out


class MultiGit:
    """Track multiple repositories, tagging when new revisions appear
    in some."""
    def __init__(self, repositories, master, tag_format='%(branch)s-%(index)d',
                 age_requirement=0, tag_starting_index = 1):
        self.repositories = repositories
        self.master = master
        self.age_requirement = 0
        self.tag_starting_index = tag_starting_index
        self.tag_format = tag_format

    def find_fresh_tag(self, branch='master'):
        """Find a fresh tag across all repositories based on self.tag_format"""
        tag = self.tag_format % ( {'branch': branch,
                                   'index': self.tag_starting_index})
        deferreds = [find_ref(gitd, 'refs/tags/'+tag) for gitd in 
                     self.repositories]
        deferred = failing_deferred_list(deferreds)
        def check(hashes):
            """Check that tag did not exist in all repositories,
            or try a higher tag number"""
            if hashes == [None]*len(self.repositories):
                return tag
            else:
                self.tag_starting_index += 1
                return self.find_fresh_tag(branch)
        return deferred.addCallback(check)

    def poll(self):
        """Look for untagged revisions at least age_requirement seconds old, 
        and tag and record them."""
        deferred = get_branch_list(self.repositories)
        def look_for_untagged(repobranchlist):
            defl2 = []
            for repository, branch in repobranchlist:
                subd = untagged_revisions(repository, branch)
                subd.addCallback(get_metadata_for_revisions, repository)
                subd.addCallback(annotate_list, branch=branch)
                defl2.append(subd)
            return failing_deferred_list(defl2)
        deferred.addCallback(look_for_untagged)
        def flatten2(newrevs):
            """newrevs is a list of revs where
            We assert all those
            status fields are true and flatten out to a list of rev objects"""
            revseq = []
            latestrevs = []
            branches = set()
            for reporevs in newrevs:
                revseq += reporevs
                seen = set()
                for rev in reporevs:
                    if rev['branch'] not in seen:
                        seen.add(rev['branch'])
                        latestrevs.append(rev)
                        branches.add(rev['branch'])
            return revseq, latestrevs, branches

        deferred.addCallback(flatten2)
        def determine_tag((newrevs, latestrev, branches)):
            """Figure out if a tag is warranted for each branch"""
            latest = time() - self.age_requirement
            defl = []
            for branch in branches:
                branchrevs = [rev for rev in newrevs if rev['branch'] == branch]
                oldrevs = [rev for rev in branchrevs if rev['commit_time'] <= latest]
                branchlatestrev = [rev for rev in latestrev if rev['branch'] == branch]
                if oldrevs:
                    defl.append(  self.apply_tag(branch, branchlatestrev, branchrevs))
            return failing_deferred_list(defl)
        return deferred.addCallback(determine_tag)

    def apply_tag(self, branch, latestrev, branchrevs):
        """Tag all latestrev revisions with tag,
        including branchrevs in comments"""
        deferred = self.find_fresh_tag(branch)
        def set_tag(tag):
            """Apply tag to all of latestrev"""
            defl = [git(rev['gitd'], 'tag', tag, 
                        rev['revision']) for rev in latestrev]
            return DeferredList( defl, consumeErrors=True).addCallback(
                lambda dlo: (dlo, tag))
        deferred.addCallback(set_tag)
        def tag_done((dlo, tag)):
            """Tagging complete or failed; retry if necessary"""
            self.tag_starting_index += 1
            allgood = True
            for status, outcome in dlo:
                if not status:
                    outcome.printTraceback(stdout)
                    allgood = False
            if allgood:
                return self.master.addChange(comments = repr(branchrevs),
                                             revision = tag)
            else:
                return self.apply_tag( branch, latestrev, branchrevs)
                
        return deferred.addCallback(tag_done)

