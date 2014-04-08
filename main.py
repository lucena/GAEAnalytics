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

Example Genomics Map Reduce
"""

import datetime
import jinja2
import json
import logging
import os
import time
import webapp2

from google.appengine.api import users
from google.appengine.api.logservice import logservice
from collections import OrderedDict
from common import Common

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

class MainHandler(webapp2.RequestHandler):
  """The main page."""

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
    infoMessage = None
    errorMessage = None

    if self.request.get("submitCreate"):
      level = int(self.request.get("logLevel"))
      message = str(self.request.get("logMessage"))
      self._log_message(level, message)
      infoMessage = str.format("Logged the following: %s - %s" %
                               (LOG_LEVELS[level], message))
    # Render the page.
    self._render_page(infoMessage, errorMessage)

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

  def _get_log_messages(self):
    logs = []
    count = 20
    index = 1
    for log in logservice.fetch(end_time=time.time(), offset=None,
                                minimum_log_level=logservice.LOG_LEVEL_DEBUG,
                                include_app_logs=True):
      log.timestamp = datetime.datetime.fromtimestamp(log.start_time)
      for app_log in log.app_logs:
        app_log.timestamp = datetime.datetime.fromtimestamp(app_log.time)
        app_log.level_name = LOG_LEVELS[app_log.level]
      logs.append(log)
      index += 1
      if index > count:
        break
    return logs

  def _render_page(self, infoMessage, errorMessage):
    username = users.User().nickname()
    template = JINJA_ENVIRONMENT.get_template('index.html')
    logs = self._get_log_messages()
    self.response.out.write(template.render({
      "pages": PAGES,
      "path": self.request.path,
      "pagename": self._get_page_name(),
      "username": username,
      "version": self._get_version(),
      "infoMessage": infoMessage,
      "errorMessage": errorMessage,
      "logs": self._get_log_messages(),
    }))


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

