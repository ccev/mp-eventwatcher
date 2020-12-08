## Usage:
You can import this like any other MAD Plugin.

If this is the first time you're setting up a MAD Plugin:
- Download Eventwatcher.mp on the [releases page](https://github.com/ccev/mp-eventwatcher/releases)
- Open {madmin.com}/plugins, click "Choose file" and choose the EventWatcher.mp file you just downloaded. Or drag&drop it there.
- go to MAD/plugins/EventWatcher/ and `cp plugin.ini.example plugin.ini && cp walker_settings.json.example walker_settings.json`
- Restart MAD

There's two config options:
- `sleep` to define the time to wait in-between checking for new events. By default it's one hour.
- `delete_events` if you want Event Watcher to delete non-needed events (including basically all you've created yourself) - by default it's set to False.

please also join [this discord](https://discord.gg/cMZs5tk)

## How does it work?
To not put unnecessary load on cool community-made websites, the Plugin pulls data from [this file](https://raw.githubusercontent.com/ccev/pogoinfo/info/events/mad.json). A list I automatically update and commit to github.

The Plugin then grabs that file and checks if an event is missing for you or changed information and then updates your database accordingly.

## Quest Resets
Event Watcher can automatically adjust Quest scan times based on on-going events.

### Config options
```
enable: Whether or not to enable this
default_time: The time you want Quest scans to start on normal days
max_time: Ignore reset times that are bigger than this
min_event_length: The minimum length an event must have to re-scan events (max = 24, cdays = 6) 
min_confidence: (10 = cdays, 9 = events with special quests)
```

### walker_settings.json
```json
{
    "walkerarea_id": "?"
}
```
get your walkerarea id by opening MADmin, then go to Settings > Walkers > The walker you want > edit the area the time must be edited for. The URL will now look something like this: `https://madmin.com/settings/walker/areaeditor?id=10&walkerarea=101`. In this case, the 101 is what you want.

The `?` will be replaced with the correct quest reset time. Depending on your walker setup, the format of the value will lokk different. I have a mon area on `period` and the value `00:00-02:00`, then the quest area following it. In this case, my json would look like this:

```json
{
    "id": "00:00-?"
}
```