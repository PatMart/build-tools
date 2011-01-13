import time
import socket

from slavealloc.data import model

tac_template = """\
# AUTOMATICALLY GENERATED - DO NOT MODIFY
# generated: %(gendate)s on %(genhost)s
from twisted.application import service
from buildbot.slave.bot import BuildSlave
from twisted.python.logfile import LogFile
from twisted.python.log import ILogObserver, FileLogObserver

maxdelay = 300
buildmaster_host = %(buildmaster_host)r
passwd = %(passwd)r
maxRotatedFiles = None
basedir = %(basedir)r
umask = 002
slavename = %(slavename)r
usepty = 1
rotateLength = 1000000
port = %(port)r
keepalive = None

application = service.Application('buildslave')
logfile = LogFile.fromFullPath("twistd.log", rotateLength=rotateLength,
                             maxRotatedFiles=maxRotatedFiles)
application.setComponent(ILogObserver, FileLogObserver(logfile).emit)
s = BuildSlave(buildmaster_host, port, slavename, passwd, basedir,
               keepalive, usepty, umask=umask, maxdelay=maxdelay)
s.setServiceParent(application)
"""

def make_buildbot_tac(allocation):
    info = dict()

    info['gendate'] = time.ctime()
    info['genhost'] = socket.getfqdn()
    info['buildmaster_host'] = allocation.master_row.fqdn
    info['port'] = allocation.master_row.pb_port
    info['slavename'] = allocation.slavename
    info['basedir'] = allocation.slave_row.basedir
    info['passwd'] = allocation.slave_password

    return tac_template % info
