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

        self.type_to_name = {
            "community-day": "Community Days",
            "spotlight-hour": "Spotlight Hours",
            "event": "Regular Events",
            "default": "DEFAULT",
            "?": "Others"
        }
        self.default_time = datetime(2020, 1, 1, 0, 0, 0)

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

                max_time = self._pluginconfig.get("Quest Resets", "max_time").split(":")
                self.__quests_max_hour = int(max_time[0])
                self.__quests_max_minute = int(max_time[1])

                reset_for = self._pluginconfig.get("Quest Resets", "reset_for", fallback="event")
                self.__quests_reset_types = {}
                for etype in reset_for.split(" "):
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
                with open(self._rootdir + "/walker_settings.txt", "r", encoding="utf8") as f:
                    quests_walkers = f.read()
                self.__quests_walkers = {}
                for line in quests_walkers.strip("\n").split("\n"):
                    splits = line.split(" ")
                    self.__quests_walkers[splits[0]] = splits[1]
            except FileNotFoundError:
                self.__quests_walkers = {}

            self.autoeventThread()

        except Exception as e:
            self._mad['logger'].error("Exception initializing EventWatcher: {}", e)
            return False

        return True
    
    def _convert_time(self, time_string, local=True):
        if time_string is None:
            return self.default_time
        time = datetime.strptime(time_string, "%Y-%m-%d %H:%M")
        if not local:
            time = time + timedelta(hours=self.tz_offset)
        return time

    def _check_quest_resets(self):
        def to_timestring(time):
            return time.strftime("%H:%M")
        smallest_time = datetime(2100, 1, 1, 0, 0, 0)
        final_time = None

        now = datetime.now()
        for event in self._quest_events:
            timetype = event["time_type"]
            if not timetype in self.__quests_reset_types.get(event["type"], []):
                continue

            time = event["time"]
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
        
        found_any = False
        for walkerarea, timestring in self.__quests_walkers.items():
            elem = self._mad['data_manager'].get_resource('walkerarea', int(walkerarea))

            current_time = elem["walkervalue"].replace(timestring.replace("?", ""), "")
            if current_time != final_time:
                elem['walkervalue'] = timestring.replace("?", final_time)
                elem.save()
                self._mad['logger'].success(f"Event Watcher: Updated Quest areas to {final_time}")
                found_any = True
        
        if found_any:
            self._mad["mapping_manager"].update()
            self._mad["logger"].success("Even Watcher: Applied Settings")

    def _check_spawn_events(self):
        # get existing events from the db and bring them in a format that's easier to work with
        query = "select event_name, event_start, event_end from trs_event;"
        db_events = self._mad['db_wrapper'].autofetch_all(query)
        events_in_db = {}
        for db_event in db_events:
            events_in_db[db_event["event_name"]] = {
                "event_start": db_event["event_start"],
                "event_end": db_event["event_end"]
            }

        # check if there are missing event entries in the db and if so, create them
        for event_type_name in self.type_to_name.values():
            if event_type_name not in events_in_db.keys():
                vals = {
                    "event_name": event_type_name,
                    "event_start": self.default_time,
                    "event_end": self.default_time,
                    "event_lure_duration": 30
                }
                self._mad['db_wrapper'].autoexec_insert("trs_event", vals)
                self._mad['logger'].success(f"Event Watcher: Created event type {event_type_name}")

                events_in_db[event_type_name] = {
                    "event_start": self.default_time,
                    "event_end": self.default_time
                }
        
        # go through all events that boost spawns, check if their times differ from the event in the db
        # and if so, update the db accordingly
        finished_events = []
        for event_dict in self._spawn_events:
            if event_dict["type"] not in finished_events:
                type_name = self.type_to_name.get(event_dict["type"], "Others")
                db_entry = events_in_db[type_name]
                if db_entry["event_start"] != event_dict["start"] or db_entry["event_end"] != event_dict["end"]:
                    vals = {
                        "event_start": event_dict["start"].strftime('%Y-%m-%d %H:%M:%S'),
                        "event_end": event_dict["end"].strftime('%Y-%m-%d %H:%M:%S'),
                        "event_lure_duration": event_dict.get("lure_duratiion", 30)
                    }
                    where = {
                        "event_name": self.type_to_name.get(event_dict["type"], "Others")
                    }
                    self._mad['db_wrapper'].autoexec_update("trs_event", vals, where_keyvals=where)
                    self._mad['logger'].success(f"Event Watcher: Updated {event_dict['type']}")

                finished_events.append(event_dict["type"])
        
        # just deletes all events that aren't part of Event Watcher
        if self.__delete_events:
            for event_name in events_in_db:
                if not event_name in self.type_to_name.values():
                    vals = {
                        "event_name": event_name
                    }
                    self._mad['db_wrapper'].autoexec_delete("trs_event", vals)
                    self._mad['logger'].success(f"Event Watcher: Deleted event {event_name}")

    def _get_events(self):
        # get the event list from github
        raw_events = requests.get("https://raw.githubusercontent.com/ccev/pogoinfo/v2/active/events.json").json()
        self._spawn_events = []
        self._quest_events = []

        # sort out events that have ended, bring them into a format that's easier to work with
        # and put them into seperate lists depending if they boost spawns or reset quests
        # then sort those after their start time
        for raw_event in raw_events:
            start = self._convert_time(raw_event["start"])
            end = self._convert_time(raw_event["end"])
            if end < datetime.now():
                continue
            event_dict = {
                "start": start,
                "end": end,
                "type": raw_event["type"]
            }
            
            if raw_event["has_spawnpoints"]:
                self._spawn_events.append(event_dict)
            if raw_event["has_quests"]:
                for key in ["start", "end"]:
                    event_dict["time"] = event_dict[key]
                    event_dict["time_type"] = key
                    self._quest_events.append(event_dict)
        
        self._quest_events = sorted(self._quest_events, key=lambda e: e["time"])
        self._spawn_events = sorted(self._spawn_events, key=lambda e: e["start"])

    def EventWatcher(self):
        # the main loop of the plugin just calling the important functions
        while True:
            self._get_events()

            if self.__quests_enable and len(self._quest_events) > 0:
                self._mad['logger'].info("Event Watcher: Check Quest Resets")
                self._check_quest_resets()

            if len(self._spawn_events) > 0:
                self._mad['logger'].info("Event Watcher: Check Spawnpoint changing Events")
                self._check_spawn_events()

            time.sleep(self.__sleep)

    def autoeventThread(self):
        self._mad['logger'].info("Starting Event Watcher")

        ae_worker = Thread(name="EventWatcher", target=self.EventWatcher)
        ae_worker.daemon = True
        ae_worker.start()

    @auth_required
    def ewreadme_route(self):
        return render_template("eventwatcher.html", header="Event Watcher", title="Event Watcher")
