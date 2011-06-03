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

def git(gitd, *kl):
    return run('git', kl, path=gitd).addCallback( lambda (o,e):o)

def linesplitdropsplit(text):
    return [x.split() for x in text.split('\n') if x]

def find_ref(gitd, ref):
    d = git(gitd, 'show-ref', ref)
    def analyse(out):
        for line in clean(out).split('\n'):
            return line.split()[0]
    return d.addCallback(analyse)

def get_metadata(gitd, hash):
    d = git(gitd, 'show', '--summary', hash)
    def decode(outs):
        out = outs.split('\n')
        author_lines = [x for x in out if x.startswith('Author:')]
        result = {'revision':hash}
        if author_lines:
            result['author'] = ' '.join( author_lines[0].split()[1:-1])
            result['email'] = author_lines[0].split()[-1]
        date_lines = [x for x in out if x.startswith('Date:')]
        if date_lines:
            result['date'] = ' '.join(date_lines[0].split()[1:])
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
    return d.addCallback(decode)

def untagged_revisions(gitd):
    deferred = git(gitd, 'rev-list', 'HEAD', '--not', '--tags')
    return deferred.addCallback(clean).addCallback(linesplitdropsplit)

class MultiGit:
    def __init__(self, repositories):
        self.repositories = repositories
        
