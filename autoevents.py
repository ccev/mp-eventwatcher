import os
import requests
import json
import time
import re

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
        self.description = self._versionconfig.get(
            "plugin", "description", fallback="Automatically put Events that boost Spawns in your database")
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
        self.default_time = datetime(2030, 1, 1, 0, 0, 0)
        self._last_pokemon_reset_date = datetime(2000, 1, 1, 0, 0, 0)

        if self._pluginconfig.getboolean("plugin", "active", fallback=False):
            self._plugin = Blueprint(
                str(self.pluginname), __name__, static_folder=self.staticpath, template_folder=self.templatepath)

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
        if self._mad['args'].config_mode:
            return False

        try:
            self.tz_offset = round((datetime.now() - datetime.utcnow()).total_seconds() / 3600)
            self.__sleep = self._pluginconfig.getint("plugin", "sleep", fallback=3600)
            self.__sleep_mainloop_in_s = 60
            self.__delete_events = self._pluginconfig.getboolean("plugin", "delete_events", fallback=False)
            self.__ignore_events_duration_in_days = self._pluginconfig.getint("plugin", "max_event_duration", fallback=999)
            self.__reset_pokemons_enable = self._pluginconfig.getboolean("plugin", "reset_pokemons", fallback=False)
            self.__reset_pokemons_truncate = self._pluginconfig.getboolean("plugin", "reset_pokemons_truncate", fallback=False)
            self.__reset_pokemons_cooldown_in_s = 1800 # minimum cooldown time between 2 pokemon resets. 30 minutes
            
            if "Quest Resets" in self._pluginconfig.sections():
                self.__quests_enable = self._pluginconfig.getboolean("Quest Resets", "enable", fallback=False)
                self.__quests_default_time = self._pluginconfig.get("Quest Resets", "default_time")
                self.__quest_timeframe = self._pluginconfig.get("Quest Resets", "check_timeframe", fallback=False)
                if self.__quest_timeframe:
                    self.__quest_timeframe = list(map(int, self.__quest_timeframe.split("-")))

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
                    splits = line.split(" ", 1)
                    self.__quests_walkers[splits[0]] = splits[1]
            except FileNotFoundError:
                self.__quests_walkers = {}

            self.autoeventThread()

        except Exception as e:
            self._mad['logger'].error("Exception initializing EventWatcher: ")
            self._mad['logger'].exception(e)
            return False

        return True

    def _convert_time(self, time_string, local=True):
        if time_string is None:
            return None
        time = datetime.strptime(time_string, "%Y-%m-%d %H:%M")
        if not local:
            time = time + timedelta(hours=self.tz_offset)
        return time

    def _reset_pokemon(self, eventchange_datetime_UTC):
        if self.__reset_pokemons_truncate:
            sql_query = "TRUNCATE pokemon"
            sql_args = None
        else:
            sql_query = "DELETE FROM pokemon WHERE last_modified < %s AND disappear_time > %s"
            datestring = eventchange_datetime_UTC.strftime("%Y-%m-%d %H:%M:%S")
            sql_args = (
                datestring,
                datestring
            )
        dbreturn = self._mad['db_wrapper'].execute(sql_query, args=sql_args, commit=True)
        self._mad['logger'].info(f'Event Watcher: pokemon deleted by SQL query: {sql_query} arguments: {sql_args} return: {dbreturn}')

    def _check_pokemon_resets(self):
        if self._pokemon_events:
            #get current time to check for event start and event end
            now = datetime.now()
            
            #cooldown check (only check for event start / end, if last pokemon reset is > __reset_pokemons_cooldown_in_s)
            if (self._last_pokemon_reset_date + timedelta(seconds=self.__reset_pokemons_cooldown_in_s)) > now:
                self._mad['logger'].info(f"Event Watcher: no check of pokemon changing events, because of cooldown (last reset:{self._last_pokemon_reset_date})")
                return
            self._mad['logger'].info("Event Watcher: check pokemon changing events")
            # check, if one of the pokemon event is just started or ended
            for event in self._pokemon_events:
                # event start during last 2 mainloop cycles?
                if event["start"] <= now <= (event["start"] + timedelta(seconds=2*self.__sleep_mainloop_in_s)):
                    self._mad['logger'].info(f'Event Watcher: event start detected for event type: {event["type"]} -> reset pokemon')
                    # remove pokemon from MAD DB, which are scanned before event start and needs to be rescanned, adapt time from local to UTC time
                    self._reset_pokemon(event["start"] - timedelta(hours=self.tz_offset))
                    self._last_pokemon_reset_date = now
                    return
                # event end during last 2 mainloop cycles?
                if event["end"] <= now <= (event["end"] + timedelta(seconds=2*self.__sleep_mainloop_in_s)):
                    self._mad['logger'].info(f'Event Watcher: event end detected for event type: {event["type"]} -> reset pokemon')
                    # remove pokemon from MAD DB, which are scanned before event end and needs to be rescanned, adapt time from local to UTC time
                    self._reset_pokemon(event["end"] - timedelta(hours=self.tz_offset))
                    self._last_pokemon_reset_date = now
                    return

    def _check_quest_resets(self):
        now = datetime.now()

        if self.__quest_timeframe and not self.__quest_timeframe[0] <= now.hour < self.__quest_timeframe[1]:
            return

        if 0 < now.hour < self.__quests_max_hour + 1:
            return

        def to_timestring(time):
            return time.strftime("%H:%M")
        smallest_time = datetime(2100, 1, 1, 0, 0, 0)
        final_time = None

        for event in self._quest_events:
            timetype = event["time_type"]
            if timetype not in self.__quests_reset_types.get(event["type"], []):
                continue

            time = event["time"]
            if time < now:
                continue
            if time.hour > self.__quests_max_hour and time.minute >= self.__quests_max_minute:
                continue

            if time < smallest_time:
                smallest_time = time

        smallest_date = smallest_time.date()
        today = datetime.today()
        if smallest_time.year == 2100:
            final_time = self.__quests_default_time
        else:
            if (
                    (
                        smallest_date == (today + timedelta(days=1)).date()
                        and now.hour > self.__quests_max_hour
                    )
                    or
                    (
                        smallest_date == today.date()
                        and now.hour <= self.__quests_max_hour
                    )
             ):
                final_time = to_timestring(smallest_time)
            else:
                final_time = self.__quests_default_time

        if final_time is None:
            return

        found_any = False
        for walkerarea, timestring in self.__quests_walkers.items():
            try:
                elem = self._mad['data_manager'].get_resource('walkerarea', int(walkerarea))
            except Exception:
                self._mad['logger'].warning(f"Event Watcher: Couldn't find Walkerarea {walkerarea}")
                continue

            def _wildcard_options(content):
                parts = []
                current_word = ""
                bracket = 0
                for char in content:
                    if char == "," and bracket == 0:
                        parts.append(current_word)
                        current_word = ""
                        char = ""
                    elif char == "(":
                        bracket += 1
                    elif char == ")":
                        bracket -= 1

                    current_word += char
                parts.append(current_word)
                return list(map(process_part, parts))

            def wildcard_add(content):
                parts = list(map(int, content.split(":")))
                if len(parts) == 1:
                    hour = parts[0]
                    minute = 0
                elif len(parts) == 2:
                    hour, minute = parts
                else:
                    hour, minute = 0, 0
                    print("?????????????????")

                final_hour, final_minute = tuple(map(int, final_time.split(":")))

                new_minute = final_minute + minute
                new_hour = final_hour + hour + new_minute // 60
                return f"{new_hour % 24:02}:{new_minute % 60:02}"

            def wildcard_min(options):
                return min(options)

            def wildcard_max(options):
                return max(options)

            def wildcard_ifevent(options):
                if final_time == self.__quests_default_time:
                    return options[1]
                else:
                    return options[0]

            wildcards = {
                "add": wildcard_add,
                "min": wildcard_min,
                "max": wildcard_max,
                "ifevent": wildcard_ifevent
            }

            def process_part(part):
                part = part.strip()
                part = part.replace("?", final_time)

                match0 = re.match(r"^\d*$", part)
                if match0:
                    part += ":00"
                match = re.match(r"\d*:\d*", part)
                if match:
                    numbers = part.split(":")
                    new_numbers = []
                    for number in numbers:
                        new_numbers.append(number.zfill(2))
                    part = ":".join(new_numbers)

                for wildcard, func in wildcards.items():
                    pattern = "^" + wildcard + r"\((.*)\)$"
                    match = re.match(pattern, part)
                    if match:
                        content = match.groups()[-1]
                        options = _wildcard_options(content)
                        if len(options) == 1:
                            func_content = process_part(options[0])
                        else:
                            func_content = list(map(process_part, options))
                        result = func(func_content)
                        part = re.sub(pattern, result, part)
                return part

            time_for_area = '-'.join(map(process_part, timestring.split('-')))

            current_time = elem["walkervalue"]
            if current_time != time_for_area:
                elem['walkervalue'] = time_for_area
                elem.save()
                self._mad['logger'].success(f"Event Watcher: Updated Walkerarea {walkerarea} to {time_for_area}")
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
                        "event_lure_duration": event_dict.get("lure", 30)
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
        self._pokemon_events = []

        # sort out events that have ended, bring them into a format that's easier to work with
        # and put them into seperate lists depending if they boost spawns or reset quests
        # then sort those after their start time
        for raw_event in raw_events:
            start = self._convert_time(raw_event["start"])
            end = self._convert_time(raw_event["end"])
            
            if start is None or end is None:
                continue
            if end < datetime.now():
                continue
            # season workaround: ignore events with long duration
            if (end - start) > timedelta(days=self.__ignore_events_duration_in_days):
                self._mad['logger'].info(f'Event Watcher: Ignore following event because duration exceed configurated limit of {self.__ignore_events_duration_in_days} days: {raw_event["name"]}')
                continue
            event_dict = {
                "start": start,
                "end": end,
                "type": raw_event["type"]
            }

            for bonus in raw_event["bonuses"]:
                if bonus.get("template", "") == "longer-lure":
                    event_dict["lure"] = bonus["value"]*60
                    break
            # get events with changed spawnpoints
            if raw_event["has_spawnpoints"] or event_dict.get("lure"):
                self._spawn_events.append(event_dict)
            # get events with changed quests
            if raw_event["has_quests"]:
                for key in ["start", "end"]:
                    spawn_dict = event_dict.copy()
                    spawn_dict["time"] = spawn_dict[key]
                    spawn_dict["time_type"] = key
                    self._quest_events.append(spawn_dict)
            # get events which has changed pokemon pool
            if raw_event["type"] == 'spotlight-hour' or raw_event["type"] == 'community-day' or raw_event["spawns"]:
                self._pokemon_events.append(event_dict)

        self._quest_events = sorted(self._quest_events, key=lambda e: e["time"])
        self._spawn_events = sorted(self._spawn_events, key=lambda e: e["start"])
        self._pokemon_events = sorted(self._pokemon_events, key=lambda e: e["start"])

    def EventWatcher(self):
        last_checked_events = datetime(2000, 1, 1, 0, 0, 0)
        
        while True:
            # check for new events on event website only with configurated event check time
            if (datetime.now() - last_checked_events) >= timedelta(seconds=self.__sleep):
                try:
                    self._get_events()
                except Exception as e:
                    self._mad['logger'].error(f"Event Watcher: Error while getting events: {e}")

                if self.__quests_enable and len(self._quest_events) > 0:
                    self._mad['logger'].info("Event Watcher: Check Quest Resets")
                    try:
                        self._check_quest_resets()
                    except Exception as e:
                        self._mad['logger'].error(f"Event Watcher: Error while checking Quest Resets")
                        self._mad['logger'].exception(e)

                if len(self._spawn_events) > 0:
                    self._mad['logger'].info("Event Watcher: Check Spawnpoint changing Events")
                    try:
                        self._check_spawn_events()
                    except Exception as e:
                        self._mad['logger'].error(f"Event Watcher: Error while checking Spawn Events: {e}")

                last_checked_events = datetime.now()
            
            #if enabled, run pokemon reset check every cycle to ensure pokemon rescan just after spawn event change
            if self.__reset_pokemons_enable:
                try:
                    self._check_pokemon_resets()
                except Exception as e:
                    self._mad['logger'].error(f"Event Watcher: Error while checking Pokemon Resets")
                    self._mad['logger'].exception(e)
            
            time.sleep(self.__sleep_mainloop_in_s)

    def autoeventThread(self):
        self._mad['logger'].info("Starting Event Watcher")

        ae_worker = Thread(name="EventWatcher", target=self.EventWatcher)
        ae_worker.daemon = True
        ae_worker.start()

    @auth_required
    def ewreadme_route(self):
        return render_template("eventwatcher.html", header="Event Watcher", title="Event Watcher")
