# -*- coding: utf-8-*-
from __future__ import print_function
import logging
from pytz import timezone
import time
import subprocess

def getTimezone(profile):
    """
    Returns the pytz timezone for a given profile.

    Arguments:
        profile -- contains information related to the user (e.g., email
                   address)
    """
    try:
        return timezone(profile['timezone'])
    except Exception:
        return None


def create_reminder(remind_event, remind_time):
    _logger = logging.getLogger(__name__)
    if len(remind_time) == 14:
        cmd = 'task add ' + remind_event + ' due:' +\
            remind_time[:4] + '-' + remind_time[4:6] + '-' + \
            remind_time[6:8] + 'T' + remind_time[8:10] + ':' + \
            remind_time[10:12] + ':' + remind_time[12:]
        print(cmd)
        try:
            res = subprocess.call(
                [cmd],
                stdout=subprocess.PIPE, shell=True)
            print(res)
            return(res == 0)
        except Exception as e:
            _logger.error(e)
            return False
    else:
        return False


def get_due_reminders():
    task_ids = []
    due_tasks = []
    _logger = logging.getLogger(__name__)
    try:
        p = subprocess.Popen(
            'task status:pending count',
            stdout=subprocess.PIPE, shell=True)
        p.wait()

        pending_task_num = int(p.stdout.readline())

        p = subprocess.Popen(
            'task list',
            stdout=subprocess.PIPE, shell=True)
        p.wait()
        lines = p.stdout.readlines()[3:(3 + pending_task_num)]
        for line in lines:
            task_ids.append(line.split()[0])

        now = int(time.strftime('%Y%m%d%H%M%S'))

        for id in task_ids:
            p = subprocess.Popen(
                'task _get ' + id + '.due',
                stdout=subprocess.PIPE, shell=True)
            p.wait()
            due_time = p.stdout.readline()
            due_time_format = int(
                due_time[:4] + due_time[5:7] + due_time[8:10] +
                due_time[11:13] + due_time[14:16] + due_time[17:19])
            if due_time_format <= now:
                p = subprocess.Popen(
                    'task _get ' + id + '.description',
                    stdout=subprocess.PIPE, shell=True)
                p.wait()
                event = p.stdout.readline()
                due_tasks.append(event.strip('\n') + u',时间到了')
                cmd = 'task delete ' + id
                p = subprocess.Popen(
                    cmd.split(),
                    stdout=subprocess.PIPE,
                    stdin=subprocess.PIPE)
                p.stdin.write('yes\n')

    except Exception as e:
        _logger.error(e)

    return due_tasks
