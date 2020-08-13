import os
import requests
import json
import time

from threading import Thread
from flask import render_template, Blueprint, jsonify
from datetime import datetime, timedelta

from mapadroid.madmin.functions import auth_required
import mapadroid.utils.pluginBase

class EventWatcher(mapadroid.utils.pluginBase.Plugin):
    def __init__(self, mad):
        super().__init__(mad)

        self._rootdir = os.path.dirname(os.path.abspath(__file__))

        self._mad = mad

        self._pluginconfig.read(self._rootdir + "/plugin.ini")
        self._versionconfig.read(self._rootdir + "/version.mpl")
        self.author = self._versionconfig.get("plugin", "author", fallback="ccev")
        self.url = self._versionconfig.get("plugin", "url", fallback="https://github.com/ccev/mp-eventwatcher")
        self.description = self._versionconfig.get("plugin", "description", fallback="Automatically put Events that boost Spawns in your database")
        self.version = self._versionconfig.get("plugin", "version", fallback="1.0")
        self.pluginname = self._versionconfig.get("plugin", "pluginname", fallback="EventWatcher")

        self.templatepath = self._rootdir + "/template/"
        self.staticpath = self._rootdir + "/static/"

        self._routes = [
            ("/eventwatcher", self.ewreadme_route),
        ]
        self._hotlink = [
            ("Plugin Page", "/eventwatcher", ""),
        ]

        if self._pluginconfig.getboolean("plugin", "active", fallback=False):
            self._plugin = Blueprint(str(self.pluginname), __name__, static_folder=self.staticpath, template_folder=self.templatepath)

            for route, view_func in self._routes:
                self._plugin.add_url_rule(route, route.replace("/", ""), view_func=view_func)

            for name, link, description in self._hotlink:
                self._mad['madmin'].add_plugin_hotlink(name, self._plugin.name+"."+link.replace("/", ""),
                                                       self.pluginname, self.description, self.author, self.url,
                                                       description, self.version)

    def perform_operation(self):
        """The actual implementation of the identity plugin is to just return the
        argument
        """

        # do not change this part ▽▽▽▽▽▽▽▽▽▽▽▽▽▽▽
        if not self._pluginconfig.getboolean("plugin", "active", fallback=False):
            return False
        self._mad['madmin'].register_plugin(self._plugin)
        # do not change this part △△△△△△△△△△△△△△△

        # dont start plugin in config mode
        if self._mad['args'].config_mode == True:
            return False

        self.tz_offset = datetime.now().hour - datetime.utcnow().hour
        self.__sleep = self._pluginconfig.getint("plugin", "sleep", fallback=3600)

        self.autoeventThread()

        return True
    
    def _convert_time(self, time_string, local):
        if time_string is None:
            return datetime(2020, 1, 1, 0, 0, 0)
        time = datetime.strptime(time_string, "%Y-%m-%d %H:%M")
        if not local:
            time = time + timedelta(hours=self.tz_offset)
        return time
    
    def _update_event(self, event):
        vals = {
            "event_start": event["start"].strftime('%Y-%m-%d %H:%M:%S'),
            "event_end": event["end"].strftime('%Y-%m-%d %H:%M:%S'),
            "event_lure_duration": event.get("lure_duratiion", 30)
        }
        where = {
            "event_name": event["type_name"]
        }
        self._mad['db_wrapper'].autoexec_update("trs_event", vals, where_keyvals=where)
        self._mad['logger'].success(f"Auto Events: Put {event['name']} in your DB")

    def EventWatcher(self):
        while True:
            query = "select event_name, event_start, event_end from trs_event;"
            db_events = self._mad['db_wrapper'].autofetch_all(query)
            events_in_db = {}
            for db_event in db_events:
                events_in_db[db_event["event_name"]] = {
                    "event_start": db_event["event_start"],
                    "event_end": db_event["event_end"]
                }
            
            gh_events = requests.get("https://raw.githubusercontent.com/ccev/pogoinfo/info/events/mad.json").json()
            mad_events_old = gh_events["events"]
            self.event_types = gh_events["types"]

            for event_type_name in self.event_types.values():
                if event_type_name not in events_in_db.keys():
                    vals = {
                        "event_name": event_type_name,
                        "event_start": datetime(2020, 1, 1, 0, 0, 0),
                        "event_end": datetime(2020, 1, 1, 0, 0, 0),
                        "event_lure_duration": 30
                    }
                    self._mad['db_wrapper'].autoexec_insert("trs_event", vals)
                    self._mad['logger'].success(f"Auto Events: Created event type {event_type_name}")

                    events_in_db[event_type_name] = {
                        "event_start": None,
                        "event_end": None
                    }

            mad_events = []
            for mad_event in mad_events_old:
                start = self._convert_time(mad_event["start"], mad_event["local_times"])
                end = self._convert_time(mad_event["end"], mad_event["local_times"])

                if end > datetime.now():
                    mad_events.append({
                        "name": mad_event["name"],
                        "type": mad_event["type"],
                        "lure_duration": mad_event["lure_duration"],
                        "start": start,
                        "end": end
                    })
            
            def sortkey(s):
                return s["start"]
            
            mad_events.sort(key=sortkey)
            finished_events = []

            for mad_event in mad_events:
                if mad_event["type"] not in finished_events:
                    mad_event["type_name"] = self.event_types.get(mad_event["type"])

                    if events_in_db[mad_event["type_name"]]["event_start"] != mad_event["start"] or events_in_db[mad_event["type_name"]]["event_end"] != mad_event["end"]:
                        self._update_event(mad_event)
                    finished_events.append(mad_event["type"])

            time.sleep(self.__sleep)

    def autoeventThread(self):
        self._mad['logger'].info("Starting Event Watcher")

        ae_worker = Thread(name="EventWatcher", target=self.EventWatcher)
        ae_worker.daemon = True
        ae_worker.start()

    @auth_required
    def ewreadme_route(self):
        return render_template("eventwatcher.html", header="Event Watcher", title="Event Watcher")