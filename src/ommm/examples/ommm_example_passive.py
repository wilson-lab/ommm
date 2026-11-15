"""Passive: read and record the amplifier, changing no setting.

Nothing here sends a Set or presses a button, so it is safe with a cell on. Run it a cell (# %%) at a time in an
editor that runs cells (VS Code, Spyder, PyCharm), or whole with `uv run python ommm_example_passive.py` in
its folder. The same steps in MATLAB: ommm_example_passive.m. Changing things: ommm_example_active.py.
"""

# %% Open a handle on Commander
import json
from pathlib import Path

import ommm

# Headstage 1 of the one MultiClamp 700B the running Commander controls. Commander must already be running on this
# PC, in this desktop session (not over SSH); ommm does not start it. Opening a handle, like every read here, changes
# no setting; it brings the active mode's tab to the front.
amp = ommm.Amplifier()

# Without Commander (a Mac, say), every cell here runs on ommm's fake Commander, a saved snapshot:
# amp = ommm.Amplifier(fake=ommm.EXAMPLES / "fake/vclamp.json")

print(amp.serial)  # which amplifier
print(amp.log_path)  # where ommm logs every write, from every program (~/ommm-logs/<serial>.jsonl)

# %% Read one control, in the unit you name
# get() takes Commander's label for a control, as on its window, and a unit of the kind Commander shows it in for the
# active mode. Holding is a voltage in V-Clamp, a current in I-Clamp, and not in I = 0, so read the mode first.
mode = amp.get("Mode")  # "V-Clamp", "I-Clamp" or "I = 0"
resistor = amp.get("Feedback Resistor", "MΩ")
primary = amp.get("Primary Output")  # an output signal, by Commander's name: "Membrane Current"
gain = amp.get("Primary Output Gain", "x")
current = amp.get("MeterValue2", "pA")  # the current meter; MeterValue1 is the potential, in mV
print(f"{mode}, Rf {resistor} MΩ, {primary} ×{gain}, {current} pA")
if mode != "I = 0":
    unit = "mV" if mode == "V-Clamp" else "pA"
    holding_on = amp.get("HoldingEnable")  # a checkbox, True or False; plain "Holding" is the value
    print(f"Holding {amp.get('Holding', unit)} {unit} ({'on' if holding_on else 'off'})")

# A control the active mode does not have raises NotApplicable, and a wrong or missing unit raises ValueError:
try:
    amp.get("Bridge Balance", "MΩ")  # I-Clamp only
except ommm.NotApplicable as error:
    print(error)

# %% Take a snapshot: every setting at once
# A snapshot is a dict: every reading in SI units ("readings"), one telegraph packet ("telegraph"), where the API and
# telegraph disagree ("disagreements"), and which ommm took it ("ommm": version, git commit, dirty). It reads the
# active mode's tab; the other mode's values are read after a set_mode.
snapshot = amp.snapshot()
print(ommm.summary(snapshot))  # the box `ommm --summary` prints
print(snapshot["readings"]["Mode"], snapshot["ommm"])

# Save it with your data; it is plain JSON. ommm.load_snapshot() reads one back, and `ommm --summary snapshot.json` prints it
# on any computer.
Path("snapshot.json").write_text(json.dumps(snapshot, indent=1))
saved = ommm.load_snapshot("snapshot.json")

# %% Check the scaling before you record
# state() turns a snapshot into what a recording needs: each output's signal, gain and scale (V/A or V/V at gain 1),
# its low-pass, and anything wrong. `blocking` means don't trust the scales at all (e.g. the other mode's tab was in
# front); `problems` names one output's doubt. Which signal belongs on which output is yours to check.
st = ommm.state(snapshot)
print(st["blocking"], st["problems"], st["warnings"])
print(st["primary"])  # {'signal': 'Membrane Current', 'api_name': 'VC_MEMBCURRENT', 'gain': 2.0, 'scale': 5e9, ...}
if st["primary"]["signal"] != "Membrane Current":
    print("the primary output is not Membrane Current: set it before you record")

# %% Record what changed during a trial, and who changed it
# Take a snapshot before and after, and note where the write log ends. trial_record compares the two snapshots and
# puts each change down to "ommm" when a logged write (from any program using ommm) explains it, else to "gui": a click
# in Commander's window, the front panel, or a program that does not use ommm.
before = amp.snapshot()
_, mark = amp.writes_since()  # all the lines so far, and the end of the log now
# ... record a trial; change something in Commander's window to see it here ...
after = amp.snapshot()
writes, mark = amp.writes_since(mark)  # the lines written during the trial, and the mark for the next trial
record = ommm.trial_record(before, after, writes)  # save it with the trial; plain JSON
for section, fields in record["changed"].items():  # "readings" and "telegraph"; empty when nothing changed
    for key, change in fields.items():
        print(section, key, change["before"], "→", change["after"], change["source"])

# %% Close the handle
# This lets go of ommm's handle on Commander; Commander keeps running, as it was. `with ommm.Amplifier() as amp:`
# closes it at the end of the block. To close or start Commander itself: ommm_example_active.py.
amp.close()
