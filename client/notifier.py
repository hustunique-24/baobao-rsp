# -*- coding: utf-8-*-
from __future__ import absolute_import
import Queue
import atexit
from apscheduler.schedulers.background import BackgroundScheduler
import logging
from . import app_utils
import time


class Notifier(object):

    class NotificationClient(object):

        def __init__(self, gather, timestamp):
            self.gather = gather
            self.timestamp = timestamp

        def run(self):
            self.timestamp = self.gather(self.timestamp)

    def __init__(self, profile, brain):
        self._logger = logging.getLogger(__name__)
        self.q = Queue.Queue()
        self.profile = profile
        self.notifiers = []
        self.brain = brain

        if 'robot' in profile and profile['robot'] == 'emotibot':
            self.notifiers.append(self.NotificationClient(
                self.handleRemenderNotifications, None))

        sched = BackgroundScheduler(daemon=True)
        sched.start()
        sched.add_job(self.gather, 'interval', seconds=120)
        atexit.register(lambda: sched.shutdown(wait=False))

    def gather(self):
        [client.run() for client in self.notifiers]

    def handleRemenderNotifications(self, lastDate):
        lastDate = time.strftime('%d %b %Y %H:%M:%S')
        due_reminders = app_utils.get_due_reminders()
        for reminder in due_reminders:
            self.q.put(reminder)

        return lastDate

    def getNotification(self):
        """Returns a notification. Note that this function is consuming."""
        try:
            notif = self.q.get(block=False)
            return notif
        except Queue.Empty:
            return None

    def getAllNotifications(self):
        """
            Return a list of notifications in chronological order.
            Note that this function is consuming, so consecutive calls
            will yield different results.
        """
        notifs = []

        notif = self.getNotification()
        while notif:
            notifs.append(notif)
            notif = self.getNotification()

        return notifs
