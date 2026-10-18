# README screenshots

The images in `docs/images/` are taken from a local Home Assistant instance. Template
sensors stand in for the room and outdoor sensors, the humidifier plug is a template
switch, and `simulate.py` lets the humidity follow the plug. Home Keeper is installed
alongside, as an optional companion.

1. Link the integrations into the config folder and start Home Assistant (Home Keeper:
   copy or link `custom_components/home_keeper` from its repository first):

   ```bash
   ln -s "$PWD/../../custom_components" config/custom_components
   hass -c config
   ```

2. Onboard, create the area and set up Home Keeper and the room through the real config
   flows, shorten the demo timings and save the dashboard:

   ```bash
   python setup_demo.py     # writes session.json (token, device id, entry id)
   python demo_options.py   # minimum on/off 1 min, tank detection after 15 min
   python dashboard.py
   ```

3. Let the simulation run (about 40 minutes: humidifier cycles, a window opening, then an
   empty tank until the refill problem shows):

   ```bash
   python simulate.py
   ```

4. Take the screenshots (Playwright with Chromium):

   ```bash
   node shoot.js ../../docs/images                       # all
   node shoot.js ../../docs/images dashboard,more-info   # some
   ```

`session.json` contains an access token for the throwaway instance; do not commit it.
