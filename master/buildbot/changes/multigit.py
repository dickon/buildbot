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
"""A git change source which creates tags on branches across multiple
repositories and passes tags up as the revisions we tag."""

from twisted.internet.utils import getProcessOutputAndValue
from time import strptime, mktime, time
from twisted.internet.defer import DeferredList, succeed, Deferred, maybeDeferred
from pprint import pprint
from sys import stdout
from buildbot.changes.base import PollingChangeSource
from os.path import join, isdir, isfile
from os import listdir
from re import match

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
    def __str__(self):
        return 'UnexpectedExcitCode(%r, %r, %r, %r, %r, %d) ' % (
            self.args_list, self.args_dict, self.out, self.err,
            self.exit_code, self.expected_return_code)

def clean(text):
    """Convert all whitespace in to simple spaces"""
    return ' '.join(text.split())

def run(*kl, **kd):
    """Run shell command and return a deferred, which will errback
    with UnexpectedExitCode if the exit code is not expected_return_code
    (which defualts to 0)"""
    verbose = kd.pop('verbose', False)
    expected_return_code = kd.pop('expected_return_code', 0)
    deferred = getProcessOutputAndValue(*kl, **kd)
    if verbose:
        print '+',kl, kd
    def check((out, err, exitcode)):
        """Verify exit code"""
        if verbose:
            print 'exit code', exitcode, 'from', kl, kd
        if exitcode != expected_return_code:
            raise UnexpectedExitCode(kl, kd, out, err, exitcode, 
                                     expected_return_code)
        return (out, err)
    return deferred.addCallback(check)

class ListProcessor:
    def __init__(self, defl, **kd):
        self.defl = defl
        self.out = []
        self.arguments = kd.pop('arguments', [])
        self.callback = kd.pop('callback', None)
        self.kd = kd
    def tick(self, n=2):
        todo = self.defl[:n]
        self.defl = self.defl[n:]
        todo_mapped = []
        for x in todo:
            if isinstance(x, Deferred):
                y = x
            elif self.callback:
                y = maybeDeferred(self.callback, *([x]+list(self.arguments)))
            else:
                y = maybeDeferred(x, *self.arguments)
            todo_mapped.append(y)
                                               
        deferred = DeferredList(todo_mapped, **self.kd)
        def record(me):
            self.out += me
            if self.defl == []:
                return self.out
            else:
                return self.tick(n)
        return deferred.addCallback(record)
    
                 
def sequencer(input, arguments = [], callback=None, n = 2):
    """Return a deferred which contains a result for each item in input.
    If the item is a deferred, the result of it is returned. 

    Otherwise, if callback is defined, then callback is called with the item,
    otherwise the item itself is called. Whether or not callback is defined,
    arguments are supplied to the callback, and the callback result
    is turned into a deferred if it is not already one.

    At most n items in the list are run in parallel.
    """ 
    lp = ListProcessor(input, callback=callback, 
                       arguments=arguments, consumeErrors=True)
    return lp.tick(n=n).addCallback(check_list)

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
        """Use None for the particular failure we get for missing tags"""
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
    return sequencer(revisions, callback=lambda r: get_metadata(gitd, r[0]))

def get_branch_list(repositories, ignoreBranchesRegexp=None):
    """Return a deferred which gives (repository path, branch_name)* 
    across repositories"""
    def get_list_for_repo(repository):
        subd = git(repository, 'branch').addCallback(linesplitdropsplit)
        def convert(seq, repository):
            """Turn [(_,x)] -> [(repository, x[-1])]"""
            out = []
            for brl in seq:
                branch = brl[-1]
                if ignoreBranchesRegexp and match(ignoreBranchesRegexp, branch):
                    continue
                out.append ( (repository, branch))
            return out
        return subd.addCallback(convert, repository)
    deferred = sequencer(repositories, callback=get_list_for_repo)
    return deferred.addCallback(lambda listlist: reduce(list.__add__, listlist, []))

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


def describe_tag(tag_format, format_data, index, repositories, offset=-1):
    """Return a string describing changes between tag with index and
    format data and the previous tag on this branch, across repositories"""
    tag = tag_format % dict(format_data, index=index)
    prev = tag_format % dict(format_data, index=index+offset)
    def silence(failure):
        failure.trap(UnexpectedExitCode)
        return ''
    def git_supress(*args):
        deferred = git(*args)
        return deferred.addErrback(silence)
    deferred = sequencer(repositories, callback=git_supress, 
                         arguments=['log', prev+'..'+tag])
    def annotate(textlist):
        return 'Differences between %s and %s:\n%s' % (
            prev, tag, reduce(str.__add__, textlist))
    deferred.addCallback(annotate)
    def again(failure):
        failure.trap(UnexpectedExitCode)
        if (failure.value.exit_code != 128 or 
            'unknown revision' not in failure.value.err):
            return failure
        if offset > -10000 and index + offset > 0:
            return describe_tag(tag_format, format_data, index, repositories, offset-1)
    return deferred.addErrback( again)

def tag_branch_if_exists(gitd, tag, branch):
    """Tag branch with tag if it exists"""
    deferred = git(gitd, 'branch').addCallback(linesplitdropsplit)
    def check(branchlistlist):
        if [x for x in branchlistlist if x[-1] == branch]:
            return git(gitd, 'tag', '-m', tag, tag, branch)
    return deferred.addCallback(check)


def scan_for_repositories(repositories_directory, ignoreRepositoriesRegexp=None):
    """Scan for git directories directly within repositories_directory and
    return a list of full path names"""
    seq = []
    for item in listdir(repositories_directory):
        if ignoreRepositoriesRegexp and match(ignoreRepositoriesRegexp, item):
            continue
        pathname = join(repositories_directory, item)
        if not isdir(pathname): 
            continue
        if ((isfile(join(pathname, 'config')) and isdir(
                    join(pathname, 'refs'))) or
            (isfile(join(pathname, '.git', 'config')) and isdir(
                    join(pathname, '.git', 'refs')))):
            seq.append(pathname)
    return seq

def safe_branch(x):
    return x.replace(' ', '_').replace('.', '_')

class MultiGit(PollingChangeSource):
    """Track multiple repositories, tagging when new revisions appear
    in some."""
    def __init__(self, repositories_directory, tagFormat='%(branch)s-%(index)d',
                 ageRequirement=0, tagStartingIndex = 1, pollInterval=10*60,
                 autoFetch=False, ignoreRepositoriesRegexp=None, newRevisionCallback=None,
                 newTagCallback = None, newBranchCallback = None, 
                 ignoreBranchesRegexp=None):
        self.repositories_directory = repositories_directory
        self.ageRequirement = ageRequirement
        self.pollInterval = pollInterval
        self.tagStartingIndex = tagStartingIndex
        self.newRevisionCallback = newRevisionCallback
        self.newBranchCallback = newBranchCallback
        self.newTagCallback = newTagCallback
        self.tagFormat = tagFormat
        self.autoFetch = autoFetch
        self.ignoreBranchesRegexp = ignoreBranchesRegexp
        self.ignoreRepositoriesRegexp = ignoreRepositoriesRegexp
        self.repositories = scan_for_repositories(self.repositories_directory)
        self.status = 'idle'
        self.lastFinish = None
        self.branches = {} # branch name -> latest revision on that branch
        self.tags = {} # branch name -> latest tag on that branch
        self.repositories = []
    def find_fresh_tag(self, branch='master'):
        """Find a fresh tag across all repositories based on self.tagFormat"""
        tag = self.tagFormat % ( {'branch': safe_branch(branch),
                                  'index': self.tagStartingIndex})
        tag_index = self.tagStartingIndex
        deferred = sequencer(self.repositories, callback=find_ref,
                             arguments = ['refs/tags/'+tag])
        def check(hashes):
            """Check that tag did not exist in all repositories,
            or try a higher tag number"""
            if hashes == [None]*len(self.repositories):
                return tag, tag_index
            else:
                return self.find_fresh_tag(branch)
        self.tagStartingIndex += 1
        return deferred.addCallback(check)

    def poll(self):
        """Look for untagged revisions at least ageRequirement seconds old, 
        and tag and record them."""
        self.pollRunning = True
        self.repositories = list(sorted(scan_for_repositories(
                    self.repositories_directory, self.ignoreRepositoriesRegexp)))
        deferred = succeed(None)
        def auto_fetch(_):
            self.status = 'fetching'
            return sequencer(self.repositories, callback=git, 
                             arguments=['fetch'])
        if self.autoFetch:
            deferred.addCallback(auto_fetch)
        def get_branches(_):
            self.status = 'examining branches'
            return get_branch_list(self.repositories, self.ignoreBranchesRegexp)
        deferred.addCallback(get_branches)
        def look_for_untagged(repobranchlist):
            """Find untagged revisions"""
            self.status = 'looking for untagged revisions'
            def look_at_branch( (repository, branch)):
                """Look for untagged revisions on branch of repository"""
                self.status = 'looking for untagged revisions (at %s)'  % \
                    (repository)
                self.branches.setdefault(branch, None)
                subd = untagged_revisions(repository, branch)
                subd.addCallback(get_metadata_for_revisions, repository)
                return subd.addCallback(annotate_list, branch=branch)
            return sequencer(repobranchlist, callback=look_at_branch)
        deferred.addCallback(look_for_untagged)
        def determine_tags(newrevs):
            """Figure out if a tag is warranted for each branch"""
            latest = time() - self.ageRequirement
            branches = set()
            for rev in reduce( list.__add__, newrevs) if newrevs else []:
                if self.newRevisionCallback:
                    self.newRevisionCallback(rev)
                current =self.branches.get(rev['branch'])
                if current is None or current['commit_time'] < rev['commit_time']:
                    if self.newTagCallback and rev['branch'] not in self.branches:
                        self.newTagCallback( rev['branch'], rev)
                    self.branches[rev['branch']] = current
                if rev['commit_time'] <= latest:
                    branches.add(rev['branch'])
            return sequencer(list(sorted(branches)), callback=self.create_tag)
        deferred.addCallback(determine_tags)
        def finish(result):
            """Report errors, update status record"""
            self.status = 'finished '+repr(result).replace('<', '&lt;')+\
                ' after '+self.status
            try:
                result.printTraceback(stdout)
            except AttributeError:
                pass
            self.lastFinish = time()
            return result
        return deferred.addCallbacks(finish, finish)
    def create_tag(self, branch):
        """Create tag on branch"""
        self.status = 'creating tag for %s' % (branch)
        deferred = self.find_fresh_tag(branch)
        def set_tag((tag, tag_index)):
            self.status = 'creating tag %s' % (tag)
            """Apply tag to all of latestrev"""
            assert str(tag_index) in tag
            subd = sequencer(self.repositories, callback=tag_branch_if_exists,
                             arguments = [tag, branch])
            # we nest our callbacks so that tag stays in scope
            def tag_done(_):
                """Tagging complete"""
                return describe_tag(
                    self.tagFormat, {'branch':safe_branch(branch)}, 
                    tag_index, self.repositories)
            subd.addCallback(tag_done)
            def store_change(description):
                """Declare change to upstream"""
                self.tags[branch] = tag
                if self.newTagCallback:
                    self.newTagCallback( (tag, branch))
                authors = ', '.join([line.split()[-1] for line in description.split('\n') if 
                           line.startswith('Author')])
                extras = {} if description is None else {'comments':description}
                return self.master.addChange(revision = tag, author=authors,
                                             **extras)
            subd.addCallback(store_change)
            def again(failure):
                """tag again on failure"""
                print 'WARNING: failed to set tag', tag,
                print 'so will try again with higher tag number'
                failure.printTraceback(stdout)
                return self.create_tag(branch)
            return subd.addErrback(again)
        return deferred.addCallback(set_tag)
        
    def describe(self):
        return """MultiGit on %s %s %s%s%s.<h2>Tags I made</h2>%r 
                  <h2>Branches</h2><div> %r</div>""" \
            '<h2>Repositories</h2> <div>%s</div>' % (
            self.repositories_directory, self.status, 
            'unrun' if self.lastFinish is None else 
            '%d seconds ago' % (time() - self.lastFinish), 
            ' ignoring repositories matching '+self.ignoreRepositoriesRegexp if
            self.ignoreRepositoriesRegexp else '',
            ' ignoring branches matching '+self.ignoreBranchesRegexp if
            self.ignoreBranchesRegexp else '',
            self.tags, self.branches,
            ', '.join(
                [x[len(self.repositories_directory)+1:] for 
                 x in self.repositories]))
    
