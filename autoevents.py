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

        try:
            self.tz_offset = datetime.now().hour - datetime.utcnow().hour
            self.__sleep = self._pluginconfig.getint("plugin", "sleep", fallback=3600)
            self.__delete_events = self._pluginconfig.getboolean("plugin", "delete_events", fallback=False)

            if "Quest Resets" in self._pluginconfig.sections():
                self.__quests_enable = self._pluginconfig.getboolean("Quest Resets", "enable", fallback=False)
                self.__quests_default_time = self._pluginconfig.get("Quest Resets", "default_time")
                self.__quests_confidence = self._pluginconfig.getint("Quest Resets", "min_confidence")

                max_time = self._pluginconfig.get("Quest Resets", "max_time").split(":")
                self.__quests_max_hour = int(max_time[0])
                self.__quests_max_minute = int(max_time[1])

                reset_for = self._pluginconfig.get("Quest Resets", "reset_for", fallback="event")
                self.__quests_reset_types = {}
                for etype in reset_for:
                    etype = etype.strip()
                    if ":" in etype:
                        split = etype.split(":")
                        etype = split[0]
                        if "start" in split[1]:
                            times = ["start"]
                        elif "end" in split[1]:
                            times = ["end"]
                    else:
                        times = ["start", "end"]
                    self.__quests_reset_types[etype] = times
            else:
                self.__quests_enable = False

            try:
                with open(self._rootdir + "/walker_settings.json", "r", encoding="utf8") as f:
                    self.__quests_walkers = json.load(f)
            except FileNotFoundError:
                self.__quests_walkers = []

            self.autoeventThread()

        except Exception as e:
            self._mad['logger'].error("Exception initializing EventWatcher: {}", e)
            return False

        return True
    
    def _convert_time(self, time_string, local=True):
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

    def _check_quest_resets(self):
        def to_timestring(time):
            return time.strftime("%H:%M")
        all_quest_resets = requests.get("https://raw.githubusercontent.com/ccev/pogoinfo/info/events/quest_resets.json").json()
        self._mad['logger'].success(all_quest_resets)
        smallest_time = datetime(2100, 1, 1, 0, 0, 0)
        final_time = None

        now = datetime.now()
        for event in all_quest_resets:
            etype = event["type"]
            if not etype[1] in self.__quests_reset_types.get(etype[0], []):
                continue
            if event["confidence"] < self.__quests_confidence:
                continue

            time = self._convert_time(event["time"])
            if time < now:
                continue
            if time.hour > self.__quests_max_hour and time.minute >= self.__quests_max_minute:
                continue

            if time < smallest_time:
                smallest_time = time

        if smallest_time.year == 2100:
            final_time = self.__quests_default_time
        else:
            if smallest_time.date() == (datetime.today() + timedelta(days=1)).date() or smallest_time.date() == datetime.today().date():
                final_time = to_timestring(smallest_time)
            else:
                final_time = self.__quests_default_time

        if final_time is None:
            return

        for walkerarea, timestring in self.__quests_walkers.items():
            """vals = {
                "algo_value": timestring.replace("?", final_time)
            }
            where = {
                "walkerarea_id": walkerarea
            }

            self._mad['db_wrapper'].autoexec_update("settings_walkerarea", vals, where_keyvals=where)"""


            elem = self._mad['data_manager'].get_resource('walkerarea', walkerarea)
            elem['walkervalue'] = timestring.replace("?", final_time)
            elem.save()
            self._mad['logger'].success(f"Auto Events: Updated Quest areas to {final_time}")


    def EventWatcher(self):
        while True:
            if self.__quests_enable:
                self._check_quest_resets()

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
                        "event_start": datetime(2020, 1, 1, 0, 0, 0),
                        "event_end": datetime(2020, 1, 1, 0, 0, 0)
                    }

            mad_events = []
            for mad_event in mad_events_old:
                start = self._convert_time(mad_event["start"], mad_event["local_times"])
                end = self._convert_time(mad_event["end"], mad_event["local_times"])

                if end > datetime.now():
                    mad_events.append({
                        "name": mad_event["name"],
                        "type": mad_event["type"],
                        "type_name": self.event_types.get(mad_event["type"]),
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
                    if events_in_db[mad_event["type_name"]]["event_start"] != mad_event["start"] or events_in_db[mad_event["type_name"]]["event_end"] != mad_event["end"]:
                        self._update_event(mad_event)
                    finished_events.append(mad_event["type"])
            
            if self.__delete_events:
                for event_name in events_in_db.keys():
                    if not event_name in self.event_types.values():
                        vals = {
                            "event_name": event_name
                        }
                        self._mad['db_wrapper'].autoexec_delete("trs_event", vals)
                        self._mad['logger'].success(f"Auto Events: Deleted event {event_name}")

            time.sleep(self.__sleep)

    def autoeventThread(self):
        self._mad['logger'].info("Starting Event Watcher")

        ae_worker = Thread(name="EventWatcher", target=self.EventWatcher)
        ae_worker.daemon = True
        ae_worker.start()

    @auth_required
    def ewreadme_route(self):
        return render_template("eventwatcher.html", header="Event Watcher", title="Event Watcher")
