"""
Copyright 2014 Google Inc. All rights reserved.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

Example Google App Engine Analytics integration.
"""

import datetime
import jinja2
import json
import logging
import os
import time
import webapp2
import urllib

from collections import OrderedDict
from common import Common
from google.appengine.api import users
from google.appengine.api import urlfetch
from google.appengine.api.logservice import logservice
from google.appengine.ext import ndb

Common.initialize()

JINJA_ENVIRONMENT = jinja2.Environment(
  loader=jinja2.FileSystemLoader('templates'),
  autoescape=True,
  extensions=['jinja2.ext.autoescape'])

LOG_LEVELS = {
              logservice.LOG_LEVEL_DEBUG: "Debug",
              logservice.LOG_LEVEL_INFO: "Info",
              logservice.LOG_LEVEL_WARNING: "Warning",
              logservice.LOG_LEVEL_ERROR: "Error",
              logservice.LOG_LEVEL_CRITICAL: "Critical",
              }

PAGES = OrderedDict([
         ('/', "Home"),
         ('/products', "Products"),
         ('/purchase', "Purchase"),
         ('/login', "Login"),
         ('/contact', "Contact"),
         ])

GA_URL_ENDPOINT = "http://www.google-analytics.com/collect"
GA_ANONYMOUS_CLIENT_ID = "1234567890"  # ???

class AnalyticsStatus(ndb.Model):
  lastpushtime = ndb.FloatProperty()
  offset = ndb.StringProperty()


class MainHandler(webapp2.RequestHandler):
  """The main page."""

  # Number of log messages to display in the web page.
  LOG_MESSAGES_NUM_TO_DISPLAY = 20

  def get(self):
    user = users.get_current_user()
    if user:
      self._render_page(None, None)
    else:
      template = JINJA_ENVIRONMENT.get_template('grantaccess.html')
      self.response.write(template.render({
        'url': users.create_login_url('/')
      }))

  def post(self):
    alertMessage = None
    alertLevel = None

    # Log a message if requested.
    if self.request.get("submitCreateLog"):
      logLevel = int(self.request.get("logLevel"))
      logMessage = str(self.request.get("logMessage"))
      self._log_message(logLevel, logMessage)
      alertMessage = str.format("Logged the following: %s - %s" %
                               (LOG_LEVELS[logLevel], logMessage))
      alertLevel = "alert-info"

    # Log a message if requested.
    if self.request.get("submitCreateEvent"):
      eventCategory = str(self.request.get("eventCategory"))
      eventAction = str(self.request.get("eventAction"))
      eventLabel = str(self.request.get("eventLabel"))
      eventValue = str(self.request.get("eventValue"))
      self._post_event_to_ga(eventCategory, eventAction, eventLabel, eventValue)
      alertMessage = str.format("Created the following event in Google "
          "Analytics %s : %s : %s : %s" %
          (eventCategory, eventAction, eventLabel, eventValue))
      alertLevel = "alert-info"

    # Crash the page if requested.
    if self.request.get('crashPage'):
      raise Exception("Aw Snap! You just crashed my app.")

    # Push logs if requested.
    if self.request.get("submitPush"):
      count = self._push_logs_to_ga()
      alertMessage = str.format("Pushed %d app logs to Google Analytics." %
                                (count))
      alertLevel = "alert-info"

    # Render the page.
    self._render_page(alertMessage, alertLevel)

  def _get_version(self):
    version = self.request.environ["CURRENT_VERSION_ID"].split('.')
    name = version[0]
    date = datetime.datetime.fromtimestamp(long(version[1]) >> 28)
    if os.environ['SERVER_SOFTWARE'].startswith('Development'):
      date = datetime.datetime.now()
    return name + " as of " + date.strftime("%Y-%m-%d %X")

  def _get_page_name(self):
    return PAGES[self.request.path] if self.request.path in PAGES else "Unknown"

  def _log_message(self, level, message):
    if level == logservice.LOG_LEVEL_DEBUG:
      logging.debug(message)
    elif level == logservice.LOG_LEVEL_INFO:
      logging.info(message)
    elif level == logservice.LOG_LEVEL_WARNING:
      logging.warning(message)
    elif level == logservice.LOG_LEVEL_ERROR:
      logging.error(message)
    elif level == logservice.LOG_LEVEL_CRITICAL:
      logging.critical(message)
    else:
      raise Exception("Unknown Logging Level %s", str(level))

  def _get_log_messages(self, offset, count,
                        min_level=logservice.LOG_LEVEL_DEBUG):
    logs = []
    index = 1
    for log in logservice.fetch(end_time=time.time(), offset=None,
                                minimum_log_level=min_level,
                                include_app_logs=True):
      if log.offset == offset:
        break
      log.timestamp = datetime.datetime.fromtimestamp(log.start_time)
      for app_log in log.app_logs:
        app_log.timestamp = datetime.datetime.fromtimestamp(app_log.time)
        app_log.level_name = LOG_LEVELS[app_log.level]
      logs.append(log)
      index += 1
      if index > count:
        break
    return logs

  def _render_page(self, alertMessage, alertLevel):
    propertyId = os.getenv('GA_PROPERTY_ID', None)
    if propertyId is None:
      alertMessage = ("Please set the GA_PROPERTY_ID field in your app.yaml "
                      "file.")
      alertLevel = "alert-danger"
    hostname = os.getenv('GA_DEFAULT_HOSTAME', None)
    username = users.User().nickname()
    template = JINJA_ENVIRONMENT.get_template('index.html')
    logs = self._get_log_messages(None, self.LOG_MESSAGES_NUM_TO_DISPLAY)
    lastpushtime, offset = self._get_analytics_status()
    self.response.out.write(template.render({
      "propertyId": propertyId,
      "hostname": hostname,
      "pages": PAGES,
      "path": self.request.path,
      "pagename": self._get_page_name(),
      "username": username,
      "version": self._get_version(),
      "lastpush": datetime.datetime.fromtimestamp(lastpushtime),
      "alertMessage": alertMessage,
      "alertLevel": alertLevel,
      "logs": logs,
    }))

  def _get_current_analytics_status(self):
    return AnalyticsStatus.get_or_insert("CurrentStatus")

  def _update_analytics_status(self, lastpushtime, offset):
    analytics = self._get_current_analytics_status()
    analytics.populate(lastpushtime=lastpushtime, offset=offset)
    analytics.put()

  def _get_analytics_status(self):
    analytics = self._get_current_analytics_status()
    lastpushtime = analytics.lastpushtime
    offset = analytics.offset
    # If the record doesn't exist then bootstrap the value
    if offset == None:
      logs = self._get_log_messages(None, 1, logservice.LOG_LEVEL_INFO)
      if (len(logs) == 1):
        lastpushtime = logs[0].start_time
        offset = logs[0].offset
      else:
        # Only need to set the last push time, leave offset as None.
        lastpushtime = 0
    return lastpushtime, offset

  def _push_logs_to_ga(self):
    lastpushtime, offset = self._get_analytics_status()
    logs = self._get_log_messages(offset, 100, logservice.LOG_LEVEL_INFO)
    count = 0
    firstTime = True
    for log in logs:
      if firstTime:
        lastpushtime = log.start_time
        offset = log.offset
        firstTime = False
      # Update GA with every app log
      for app_log in log.app_logs:
        timestamp = str(datetime.datetime.fromtimestamp(app_log.time))
        level = LOG_LEVELS[app_log.level]
        message = app_log.message
        description = str.format("%s - %s - %s" % (timestamp, level, message))
        isFatal = 1 if app_log.level == logservice.LOG_LEVEL_CRITICAL else 0
        count += 1
        self._post_exception_to_ga(description, isFatal)
    # Save your place.
    self._update_analytics_status(lastpushtime, offset)
    return count

  def _post_event_to_ga(self, category, action, label, value):
    additional_fields = {
      "t": "event",
      "ec": category,
      "ea": action,
      "el": label,
      "ev": value,
    }
    self._post_to_ga(additional_fields)

  def _post_exception_to_ga(self, description, isFatal):
    additional_fields = {
      "t": "exception",
      "exd": description,
      "exf": isFatal,
    }
    self._post_to_ga(additional_fields)

  def _post_to_ga(self, additional_fields):
    form_fields = {
      "v": "1",
      "tid": os.environ['GA_PROPERTY_ID'],
      "cid": GA_ANONYMOUS_CLIENT_ID,
    }
    form_fields.update(additional_fields)
    form_data = urllib.urlencode(form_fields)
    result = urlfetch.fetch(url=GA_URL_ENDPOINT,
        payload=form_data,
        method=urlfetch.POST,
        headers={'Content-Type': 'application/x-www-form-urlencoded'})
    logging.debug("Post to Google Analytics returned: %s", result.status_code)

# For demo purposes, map many sample pages to this handler.
app = webapp2.WSGIApplication(
  [
    ('/', MainHandler),
    ('/products', MainHandler),
    ('/purchase', MainHandler),
    ('/login', MainHandler),
    ('/contact', MainHandler),
  ],
  debug=True)

