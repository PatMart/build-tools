#!/usr/bin/env python2
"""Idle Slave Rebooter

Usage: reboot-idle-slaves.py [-h] [-v] [--dryrun] [-w <num workers>] [-x pattern ...] -s SERVER

-h --help         Show this help message.
-v --verbose      More verbose output.
-s --server=<url> Set the SlaveAPI Server to speak with. Required.
-w --workers=<n>  Maximum number of slaves to kick at once. Maximum: 4. [default: 4]
-x --exclude=<pattern> Ignore hosts matching pattern (can be specified multiple times).
--dryrun          Don't do any reboots, just print what would've been done.
"""

from datetime import datetime
from furl import furl
from os import path
import requests
import site
from threading import Thread
import time

import logging
log = logging.getLogger(__name__)

site.addsitedir(path.join(path.dirname(path.realpath(__file__)), "../../lib/python"))

from util.retry import retry

MAX_WORKERS = 4
IDLE_THRESHOLD = 5*60*60
PENDING, RUNNING, SUCCESS, FAILURE = range(4)

def get_production_slaves(slaveapi):
    url = furl(slaveapi)
    url.path.add("slaves")
    url.args["environment"] = "prod"
    url.args["enabled"] = 1
    r = retry(requests.get, args=(str(url),))
    return r.json()["slaves"]

def get_slave(slaveapi, slave):
    url = furl(slaveapi)
    url.path.add("slaves").add(slave)
    return retry(requests.get, args=(str(url),)).json()

def get_formatted_time(dt):
    return dt.strftime("%A, %B %d, %H:%M")

def process_slave(slaveapi, slave, dryrun=False):
    try:
        info = get_slave(slaveapi, slave)
        # Ignore slaves without recent job information
        if not info["recent_jobs"]:
            log.info("%s - Skipping reboot because no recent jobs found", slave)
            return
        last_job_time = datetime.fromtimestamp(info["recent_jobs"][0]["endtime"])
        # And also slaves that haven't been idle for more than the threshold
        if not (now - last_job_time).total_seconds() > IDLE_THRESHOLD:
            log.info("%s - Skipping reboot because last job ended recently at %s", slave, get_formatted_time(last_job_time))
            return
        if dryrun:
            log.info("%s - Last job ended at %s, would've rebooted", slave, get_formatted_time(last_job_time))
            return
        else:
            log.info("%s - Last job ended at %s, rebooting", slave, get_formatted_time(last_job_time))
        # We need to set a graceful shutdown for the slave on the off chance that
        # it picks up a job before us making the decision to reboot it, and the
        # reboot actually happening. In most cases this will happen nearly
        # instantly.
        log.debug("%s - Setting graceful shutdown", slave)
        url = furl(slaveapi)
        url.path.add("slaves").add(slave).add("actions").add("shutdown_buildslave")
        url.args["waittime"] = 30
        r = retry(requests.post, args=(str(url),)).json()
        while r["state"] not in (PENDING, RUNNING):
            url.args["requestid"] = r["requestid"]
            time.sleep(30)
            r = retry(requests.get, args=(str(url),)).json()

        if r["state"] == FAILURE:
            log.info("%s - Graceful shutdown failed, aborting reboot", slave)
            return

        log.info("%s - Graceful shutdown finished, rebooting", slave)
        url = furl(slaveapi)
        url.path.add("slaves").add(slave).add("actions").add("reboot")
        retry(requests.post, args=(str(url),))
        # Because SlaveAPI fully escalates reboots (all the way to IT bug filing),
        # there's no reason for us to watch for it to complete.
        log.info("%s - Reboot queued")
    except:
        log.exception("%s - Caught exception while processing", slave)


if __name__ == "__main__":
    from docopt import docopt, DocoptExit
    args = docopt(__doc__)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    logging.getLogger("util.retry").setLevel(logging.WARN)

    slaveapi = args["--server"]
    n_workers = int(args["--workers"])
    excludes = args["--exclude"]
    dryrun = args["--dryrun"]
    verbose = args["--verbose"]

    if verbose:
        logging.getLogger("requests").setLevel(logging.DEBUG)
    else:
        logging.getLogger("requests").setLevel(logging.WARN)

    now = datetime.now()

    if n_workers > MAX_WORKERS:
        raise DocoptExit("Number of workers requested (%d) exceeds maximum (%d)" % (n_workers, MAX_WORKERS))

    def is_excluded(name):
        for pattern in excludes:
            if pattern in name:
                return True
        return False

    workers = {}

    try:
        for slave in get_production_slaves(slaveapi):
            name = slave["name"]
            if is_excluded(name):
                log.debug("%s - Excluding because it matches an excluded pattern.", name)
                continue
            while len(workers) >= n_workers:
                time.sleep(.5)
                for wname, w in workers.items():
                    if not w.is_alive():
                        del workers[wname]
            t = Thread(target=process_slave, args=(slaveapi, name, dryrun))
            t.start()
            workers[name] = t

        # Wait for all of the workers to finish before exiting.
        for w in workers.values():
            while w.is_alive():
                w.join(1)
    except KeyboardInterrupt:
        raise
