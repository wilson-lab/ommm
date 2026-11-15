"""Active: change the amplifier, and close and start Commander.

Each write acts on the amplifier at once, as Commander's own control does, so run this a cell (# %%) at a time and
read each cell before you run it; try it on the fake first (the commented line in the first cell). Start in V-Clamp,
with a model cell or the pipette in the bath, not a cell you want to keep. Every write is checked before it is sent,
read back after and logged (docs/writes.md). The same steps in MATLAB: ommm_example_active.m. Reading only:
ommm_example_passive.py.
"""

# %% Open a handle on Commander
import ommm

amp = ommm.Amplifier()  # headstage 1 of the one 700B; Commander must be running on this PC

# Without Commander, every cell runs on ommm's fake, which changes as Commander would and logs to a temporary folder:
# amp = ommm.Amplifier(fake=ommm.EXAMPLES / "fake/vclamp.json")

assert amp.get("Mode") == "V-Clamp", "these cells are written for V-Clamp: switch in Commander's window first"

# %% Set a value
# set() takes Commander's label, a value and a unit. It checks first (the mode, the unit, the vendor's range, Mode
# Switching off, the telegraph agreeing on the mode), sends, reads back and logs. It returns a Write: outcome "ok", or
# "adjusted" when Commander stored the value on its own step. before and after are the API's values, in SI (volts here).
w = amp.set("Holding", -60, "mV")
print(w.outcome, w.before, "→", w.after)

# Holding applies only once its checkbox is on, as in Commander's window. Checkboxes go by their name on the window.
amp.enable("Holding", True)

# %% Ask before a write
# plan() makes every check set() makes and sends nothing; its reason is the question to ask. expect=, in the call's
# unit, makes the set refuse, sending nothing, if Commander no longer shows what the question showed (someone clicked
# meanwhile).
shown = amp.get("Holding", "mV")
p = amp.plan("Holding", -40, "mV", expect=shown)
print(p.outcome, p.reason)  # planned Holding -60 mV → -40 mV (V-Clamp)
if p.outcome == "planned" and input(f"{p.reason}? [y/N] ") == "y":
    amp.set("Holding", -40, "mV", expect=shown)

# %% When a write is refused
# A write ommm will not send, or one that did not take, raises WriteError, and error.write says why. A refused write
# sent nothing; it is still logged.
try:
    amp.set("Holding", -60, "pA")  # Holding is a voltage in V-Clamp
except ommm.WriteError as error:
    print(error.write.outcome, error.write.reason)

# %% Output gain, a checkbox, a button
amp.set("Primary Output Gain", 5, "x")
amp.enable("Seal Test", True)
amp.enable("Seal Test", False)

# A button, by its name on the window. An Auto can take longer than the 3 s Commander has to answer: the press then
# raises WriteError with outcome "unknown" (it may have run, and ommm does not press again), and its also still shows
# what a snapshot then shows changed, {name: [before, after]}. A button has no value, so its before and after are None.
try:
    w = amp.press("Auto Cp Fast")
except ommm.WriteError as error:
    if error.write.outcome != "unknown":
        raise
    w = error.write
print(w.outcome, w.also)

# %% Change mode
# V-Clamp ↔ I-Clamp always goes through I = 0; ommm does that step for you. Each mode has its own Holding, in its own
# unit, and the new mode's Holding is yours to set. The Write's after is the new mode's id; its also holds everything
# else the switch changed.
amp.set_mode("I-Clamp")
amp.set("Holding", 0, "pA")
amp.set_mode("V-Clamp")

# %% Turn off what can harm a cell left alone
# make_safe() turns off, where the active mode has them, Pipette Capacitance Neutralization, Rs Compensation, Seal
# Test (Tuning in I-Clamp) and the Resistance meter. It turns nothing on and leaves Holding as it is.
print([w.label for w in amp.make_safe()])  # the writes it sent; none when everything was already off

# %% Load a settings file: Commander closes and starts again
# What the API cannot set (the feedback resistor and the rest of the Options dialog) comes from a .mcc settings file,
# which Commander reads as it starts (docs/mcc.md). A load sets every value the file holds, the Options pages included,
# and Commander keeps them, so save your own setup first (Save Configuration, F5) and load that file; ommm.EXAMPLES / "mcc"
# holds one lab's setup, 5 GΩ in both modes. changes= patches the Feedback Resistor, the only Options-page setting it
# takes, in a copy of the file, one per row: (label, value, unit, mode). Without confirmed=True, load_config only
# plans: its reason says what will change.
setup = ommm.EXAMPLES / "mcc/vclamp_5gohm.mcc"  # on an amplifier, your own file
plan = amp.load_config(setup, changes=[("Feedback Resistor", 500, "MΩ", "V-Clamp")])
print(plan.reason)

# With confirmed=True, Commander closes, starts again with the copy and is checked, about 15 s. The file sets every
# value it holds, Holding included (off in ommm's examples), so a held cell is released: not with a cell you want to
# keep. This handle takes the new Commander; any other program using ommm (MATLAB, another Python) calls reconnect().
w = amp.load_config(setup, changes=[("Feedback Resistor", 500, "MΩ", "V-Clamp")], confirmed=True)
print(w.outcome, w.reason)
amp.load_config(setup, confirmed=True)  # and back to the file unchanged

# After Commander was closed or restarted any other way (its own window, another program), every call on this handle
# fails with 6002 (a write refuses, sending nothing) until reconnect(), which waits up to 30 s for Commander and takes
# a new handle. Commander may then show Holding off while the amplifier still holds: if Holding was on, turn it on
# again as your first write (docs/quirks.md).
# amp.reconnect()

# %% Close the handle
# Lets go of ommm's handle; Commander keeps running as it is.
amp.close()
