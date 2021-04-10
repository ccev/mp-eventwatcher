## Usage:
You can import this like any other MAD Plugin.

If this is the first time you're setting up a MAD Plugin:
- Download Eventwatcher.mp on the [releases page](https://github.com/ccev/mp-eventwatcher/releases)
- Open {madmin.com}/plugins, click "Choose file" and choose the EventWatcher.mp file you just downloaded. Or drag&drop it there.
- go to MAD/plugins/EventWatcher/ and `cp plugin.ini.example plugin.ini && cp walker_settings.txt.example walker_settings.txt`
- Restart MAD

There's two config options:
- `sleep` to define the time to wait in-between checking for new events. By default it's one hour.
- `delete_events` if you want Event Watcher to delete non-needed events (including basically all you've created yourself) - by default it's set to False.

please also join [this discord](https://discord.gg/cMZs5tk)

## How does it work?
To not put unnecessary load on cool community-made websites, the Plugin pulls data from [this file](https://github.com/ccev/pogoinfo/blob/v2/active/events.json). A list I automatically update and commit to github.

The Plugin then grabs that file and checks if an event is missing for you or changed information and then updates your database accordingly.

## Quest Resets
Event Watcher can automatically adjust Quest scan times based on on-going events. It does it by checking the file above for events that reset Quests and then changes your walkerarea values with the event times.

### Config options
- **enable**: Whether or not to enable auto Quest resets
default_time: The time you want Quest scans to start on normal days
- **max_time**: Ignore reset times that are later than this
- **reset_for**: Define event types and if you want quests to reset for their start, end or both.
  - `event community-day` - if you want to rescan quests for every start and end of an event and cday
  - `event:start` - only rescan quests for event starts (my personal recommendation)
  - `community-day event:end` - Rescan quests for cday starts and ends, but only for event ends
  - Available event types are `event`, `community-day`, `spotlight-hour` and `raid-hour`. The last 2 are less relevant. Most events are of type `event`.


### walker_settings.txt
```
walkerarea_id ?
```
get your walkerarea_id by opening MADmin, then go to Settings > Walkers > The walker you want > edit the area the time should be edited for. The URL will now look something like this: `https://madmin.com/settings/walker/areaeditor?id=10&walkerarea=101`. In this case, the 101 is what you want.

The `?` will be replaced with the correct quest reset time. Depending on your walker setup, the format of the value will look different. I have a mon area on `period` and the value `00:00-03:00`, then the quest area following it. Say the walkerarea_id is 10, then my walker_settings would look like this:

```
10 00:00-?
```

#### Wildcards

Wildcards can be used to further refine walkervalues. Their syntax work the same way most functions work in programming languages. E.g. `max(10:00, 12:00)` would return `12:00`. The following wildcards can be used:

- `add(X)` adds X to the reset time. If quests reset at 9am and you use `add(1)` in your walker settings, it would turn to `10:00`. If you use `add(2:30)`, it would become `11:30`.
- `min(X, Y)` and `max(X, Y)` are replaced either with the smaller or the higher value. If quests reste at 10am, `max(?, 2)` would become `10:00`.
- `ifevent(X, Y)` uses X if there's an event and Y if there's not.