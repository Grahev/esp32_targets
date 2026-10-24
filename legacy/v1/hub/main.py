# Boot stub. The hub program lives in hub_app (uploaded as precompiled
# hub_app.mpy): compiling a large .py at boot would make MicroPython grow its
# heap out of the memory WiFi needs (REVIEW #36). Build: tools/build_hub.sh
import hub_app

hub_app.run()
