import time
import json
import string
import os, os.path
import BaseHTTPServer
import requests
import urlparse
import urllib
import semver
import requests_cache
from requests.auth import HTTPBasicAuth

requests_cache.install_cache('purescript-dep-analyzer')

HOST_NAME = '0.0.0.0' # !!!REMEMBER TO CHANGE THIS!!!
PORT_NUMBER = 8000 # Maybe set this to 9000.

LIBRARY_IO_APIKEY = os.getenv('LIBRARY_IO_APIKEY')
GITHUB_APIKEY = os.getenv('GITHUB_APIKEY')

types = {
    ".css": "text/css",
    ".html": "text/html",
    ".js": "text/javascript",
    ".json": "text/json"
}

def getExt(p):
    return os.path.splitext(p)[1]

def fileFromPath(p):
    stripped = p.split('?',1)[0]
    stripped = stripped[1:].split('/')
    pp = []
    for part in stripped:
        if part == '..':
            pp = pp[:-2]
        else:
            pp = pp + [part]
    cwd = os.getcwd()
    pp = '/'.join(pp)
    print cwd, pp, getQueryString(p)
    return os.path.join(cwd,pp)

def getQueryString(p):
    stripped = p.split('?',1)
    if len(stripped) > 1:
        return urlparse.parse_qs(stripped[1])
    else:
        return {}

class FileOnDiskObject:
    def __init__(self,s,content = None):
        self.s = s
        self.path = fileFromPath(s.path)
        if not content:
            try:
                self.stat = os.stat(self.path)
                self.content = open(self.path).read()
            except:
                self.path = 'notfound.html'
                self.stat = None
                self.content = '<html><body>Not found</body></html>';

    def HEAD(self):
        s = self.s
        if self.stat:
            s.send_response(200)
            s.send_header("Content-Type", types[getExt(self.path)])
            s.send_header("Content-Size", len(self.content))
            s.end_headers()
        else:
            s.send_response(404)
            s.end_headers()

    def GET(self):
        s = self.s
        if self.stat:
            s.send_response(200)
            s.send_header("Content-Type", types[getExt(self.path)])
            s.send_header("Content-Size", len(self.content))
            s.end_headers()
            s.wfile.write(self.content)
            s.wfile.close()
        else:
            s.send_response(404)
            s.end_headers()

class ApiCall:
    def __init__(self,s):
        self.s = s
        self.content = None
        self.content_type = None

    def GET(self):
        s = self.s
        if self.content_type:
            content_type = self.content_type
        else:
            content_type = types['.json']
        if self.content:
            s.send_response(200)
            s.send_header('Content-Type', content_type)
            s.send_header('Content-Size', len(self.content))
            s.end_headers()
            s.wfile.write(self.content)
            s.wfile.close()
        else:
            s.send_response(404)
            s.end_headers()

    def HEAD(self):
        s = self.s
        if self.content_type:
            content_type = self.content_type
        else:
            content_type = types['.json']
        if self.content:
            s.send_response(200)
            s.send_header('Content-Type', content_type)
            s.send_header('Content-Size', len(self.content))
            s.end_headers()
        else:
            s.send_response(404)
            s.end_headers()

def getLibraryDesc(package):
    url = 'https://libraries.io/api/bower/' + package + '?api_key=' + LIBRARY_IO_APIKEY
    result = requests.get(url)
    data = result.json()
    if 'repository_url' in data:
        git_url = data['repository_url']
    elif 'repository' in data:
        git_url = data['repository']['url']
    else:
        return None
    git_parsed = urlparse.urlparse(git_url)
    git_path = git_parsed.path[1:]
    git_path_split = git_path.split('/')
    github = { 'user': git_path_split[0], 'repo': git_path_split[1] }
    return {
        'repository_url': git_url,
        'github': github
    }

class LibraryRequest(ApiCall):
    def __init__(self,s):
        ApiCall.__init__(self,s)
        splitpath = s.path[1:].split('/')
        if splitpath[0] != "library":
            raise exception(s.path + " is not /library")
        self.term = splitpath[1]
        content = getLibraryDesc(self.term)
        self.content = json.dumps(content)

def getRepoTags(github):
    result = requests.get('https://api.github.com/repos/' + github['user'] + '/' + github['repo'] + '/tags', auth=HTTPBasicAuth('prozacchiwawa',GITHUB_APIKEY))
    data = result.json()
    return {
        'repository_url': 'https://github.com/' + github['user'] + '/' + github['repo'],
        'github': github,
        'tags': data
    }

class TagsRequest(ApiCall):
    def __init__(self,s):
        ApiCall.__init__(self,s)
        splitpath = s.path[1:].split('/')
        if splitpath[0] != 'tags':
            raise exception(s.path + ' is not /tags')
        owner = splitpath[1]
        repo = splitpath[2]
        content = getRepoTags({ 'user': owner, 'repo': repo })
        self.content = json.dumps(content)

def getFileFromRepo(owner,repo,tag,name):
    url = 'https://raw.githubusercontent.com/%s/%s/%s/%s' % (owner,repo,tag,name)
    print url
    result = requests.get(url, auth=HTTPBasicAuth('prozacchiwawa',GITHUB_APIKEY))
    content_type = result.headers['content-type'] if 'content-type' in result.headers else 'text/json'
    content = result.text
    return (content_type, content)

def semverMatch(have,want):
    try:
        if have.startswith('v'):
            have = have[1:]
        if want.startswith('~'):
            haveList = have.split('.')
            wantList = want[1:].split('.')
            return haveList[0] == wantList[0] and haveList[1] == wantList[1] and int(haveList[2]) >= int(wantList[2])
        elif want.startswith('^'):
            wantList = want[1:].split('.')
            greaterOrEqual = '>=%s.%s.%s' % (wantList[0], wantList[1], wantList[2])
            lessThan = '<%s.%s.%s' % (int(wantList[0]) + 1, 0, 0)
            return semver.match(have,greaterOrEqual) and semver.match(have, lessThan)
        else:
            return semver.match(have,want)
    except:
        return False

class FileFromRepo(ApiCall):
    def __init__(self,s):
        ApiCall.__init__(self,s)
        splitpath = s.path[1:].split('/')
        if splitpath[0] != 'file':
            raise exception(s.path + ' is not /file')
        owner = splitpath[1]
        repo = splitpath[2]
        tag = splitpath[3]
        file = '/'.join(splitpath[4:])
        content_type, content = getFileFromRepo(owner,repo,tag,file)
        self.content_type = content_type
        self.content = content

def getDepGraph(package,tag):
    libdesc = getLibraryDesc(package)
    print libdesc
    github = libdesc['github']
    print github
    bowerResult = getFileFromRepo(libdesc['github']['user'],libdesc['github']['repo'],tag,'bower.json')
    print bowerResult
    bowerJson = json.loads(bowerResult[1])
    rtags = getRepoTags(libdesc['github'])
    resver = [x['name'][1:] for x in rtags['tags']]
    print resver
    if not 'dependencies' in bowerJson:
        return {'name':package, 'ver':tag, 'deps': {}, 'vers': resver}
    deps = bowerJson['dependencies']
    resdep = {}
    result = {'name':package, 'ver':tag, 'deps': resdep, 'vers': resver}
    for dep in deps.keys():
        depver = deps[dep]
        libdesc = getLibraryDesc(dep)
        print 'dep','depver',libdesc
        tags = getRepoTags(libdesc['github'])
        print tags
        tag = {'name':'master'}
        for t in tags['tags']:
            match = semverMatch(t['name'], depver)
            print '%s vs %s => %s' % (t['name'], depver, match)
            if match:
                tag = t
        pkgDeps = getDepGraph(dep,tag['name'])
        resdep[dep] = pkgDeps
    return result

class DepGraph(ApiCall):
    def __init__(self,s):
        ApiCall.__init__(self,s)
        splitpath = s.path[1:].split('/')
        if splitpath[0] != 'deps':
            raise exception(s.path + ' is not /deps')
        name = splitpath[1]
        tag = splitpath[2]
        content = getDepGraph(name,tag)
        self.content = json.dumps(content)

def handleRequest(verb,s):
    if s.path == "/":
        s.send_response(302)
        s.send_header("Location", "/index.html")
        s.end_headers()
    else:
        for t in [LibraryRequest, TagsRequest, FileFromRepo, DepGraph, FileOnDiskObject]:
            print t,s.path
            try:
                f = t(s)
                break
            except:
                print 'not',t
        getattr(f, verb)()

class MyHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    def do_HEAD(s):
        handleRequest('HEAD',s)

    def do_GET(s):
        handleRequest('GET',s)

if __name__ == '__main__':
    server_class = BaseHTTPServer.HTTPServer
    httpd = server_class((HOST_NAME, PORT_NUMBER), MyHandler)
    print time.asctime(), "Server Starts - %s:%s" % (HOST_NAME, PORT_NUMBER)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    print time.asctime(), "Server Stops - %s:%s" % (HOST_NAME, PORT_NUMBER)
