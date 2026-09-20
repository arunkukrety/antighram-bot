"""
gui/ — Antighram Bot desktop control-center package.

Modules:
    constants.py    app metadata, platform flags, theme palette, geometry
    paths.py        frozen/dev path resolution (config dir, .env location)
    env_store.py    read/write of the user .env file
    startup.py      "start on system startup" registration (registry / autostart)
    tray_image.py   programmatic tray-icon rendering
    app_window.py   AgyBotApp — main control-panel window + system tray
    setup_wizard.py first-run credential wizard
"""
