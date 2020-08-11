## Usage:
You can import this like any other MAD Plugin.

If this is the first time you're setting up a MAD Plugin:
- Download the EventWatcher.mp file ([can be found here](https://raw.githubusercontent.com/ccev/mp-eventwatcher/master/EventWatcher.mp) - if the site shows text, you can create an empty EventWatcher.mp file and paste that text into it)
- Open {madmin.com}/plugins, click "Choose file" and choose the EventWatcher.mp file you just downloaded. Or drag&drop it there.
- go to MAD/plugins/EventWatcher/ and `cp plugin.ini plugin.ini.example`
- Restart MAD

There's one config option: `sleep` to define the time to wait in-between checking for new events. By default it's one hour.

please also join [this discord](https://discord.gg/cMZs5tk)

## How does it work?
To not put unnecessary load on cool community-made websites, the Plugin pulls data from [this file](https://raw.githubusercontent.com/ccev/pogoinfo/info/events/mad.json). A list I automatically update and commit to github.

The Plugin then grabs that file and checks if an event is missing for you or changed information and then updates your database accordingly.
