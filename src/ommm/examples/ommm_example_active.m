%% Active: change the amplifier, and close and start Commander
% Each write acts on the amplifier at once, as Commander's own control does, so run this a section
% at a time (Run Section, Ctrl+Enter) and read each section before you run it; try it on the fake
% first (the commented line in the first section). Start in V-Clamp, with a model cell or the
% pipette in the bath, not a cell you want to keep. Every write is checked before it is sent, read
% back after and logged (docs/writes.md). The same steps in Python: ommm_example_active.py. Reading
% only: ommm_example_passive.m. Every method: docs/matlab.md.

%% Open a handle on Commander
ommmFolder = "C:\Users\you\repos\ommm";        % where you cloned ommm
addpath(fullfile(ommmFolder, "matlab"))
examples = fullfile(ommmFolder, "src", "ommm", "examples");  % this file's folder in the clone: mcc/ and fake/
a = ommm.Amplifier();                           % headstage 1 of the one 700B; Commander must be running

% Without Commander, every section runs on ommm's fake, which changes as Commander would and logs to
% a temporary folder:
% a = ommm.Amplifier(Fake=fullfile(examples, "fake", "vclamp.json"));

assert(a.get("Mode") == "V-Clamp", "these sections are written for V-Clamp: switch in Commander's window first")

%% Set a value
% set takes Commander's label, a value and a unit. It checks first (the mode, the unit, the vendor's
% range, Mode Switching off, the telegraph agreeing on the mode), sends, reads back and logs. It
% returns the write, a struct: outcome "ok", or "adjusted" when Commander stored the value on its
% own step; before and after are the API's values, in SI (volts here).
w = a.set("Holding", -60, "mV");
fprintf("%s: %g V → %g V\n", w.outcome, w.before, w.after)

% Holding applies only once its checkbox is on, as in Commander's window. Checkboxes go by their
% name on the window.
a.enable("Holding", true);

%% Ask before a write
% plan makes every check set makes and sends nothing; its reason is the question to ask. Expect=, in
% the call's unit, makes the set refuse, sending nothing, if Commander no longer shows what the
% question showed (someone clicked meanwhile).
shown = a.get("Holding", "mV");
p = a.plan("Holding", -40, "mV", Expect=shown);
disp(p.reason)                                  % Holding -60 mV → -40 mV (V-Clamp)
if p.outcome == "planned" && questdlg(p.reason, "Commander", "Go", "Cancel", "Cancel") == "Go"
    a.set("Holding", -40, "mV", Expect=shown);
end

%% When a write is refused
% Errors: ommm:refused, nothing sent (still logged); ommm:writeError, sent but did not take; a
% write's error of either kind carries err.write, the write with its outcome and reason.
% ommm:notApplicable, a control the active mode lacks; ommm:commander, Commander failing;
% ommm:badArgument, an argument ommm cannot use, such as an unknown label in get.
try
    a.set("Holding", -60, "pA");                % Holding is a voltage in V-Clamp
catch err
    fprintf("%s: %s\n", err.identifier, err.message)
end

%% Output gain, a checkbox, a button
a.set("Primary Output Gain", 5, "x");
a.enable("Seal Test", true);
a.enable("Seal Test", false);

% A button, by its name on the window. An Auto can take longer than the 3 s Commander has to answer:
% the press then fails with ommm:writeError, outcome "unknown" (it may have run, and ommm does not
% press again), and its also still shows what a snapshot then shows changed, each field
% [before; after]. A button has no value, so its before and after are empty.
try
    w = a.press("Auto Cp Fast");
catch err
    if err.identifier ~= "ommm:writeError" || err.write.outcome ~= "unknown"
        rethrow(err)
    end
    w = err.write;
end
disp(w.outcome), disp(w.also)

%% Change mode
% V-Clamp ↔ I-Clamp always goes through I = 0; ommm does that step for you. Each mode has its own
% Holding, in its own unit, and the new mode's Holding is yours to set. The write's after is the
% new mode's id; its also holds everything else the switch changed.
a.set_mode("I-Clamp");
a.set("Holding", 0, "pA");
a.set_mode("V-Clamp");

%% Turn off what can harm a cell left alone
% make_safe turns off, where the active mode has them, Pipette Capacitance Neutralization, Rs
% Compensation, Seal Test (Tuning in I-Clamp) and the Resistance meter. It turns nothing on and
% leaves Holding as it is. It returns the writes it sent, struct([]) when everything was already off.
writes = a.make_safe();
disp(numel(writes))

%% Load a settings file: Commander closes and starts again
% What the API cannot set (the feedback resistor and the rest of the Options dialog) comes from a
% .mcc settings file, which Commander reads as it starts (docs/mcc.md). A load sets every value the
% file holds, the Options pages included, and Commander keeps them, so save your own setup first
% (Save Configuration, F5) and load that file; mcc/ here holds one lab's setup, 5 GΩ in both
% modes. Changes= patches the Feedback Resistor, the only Options-page setting it takes, in a copy
% of the file, one row per change: {label, value, unit, mode}. Without Confirmed=true, load_config
% only plans: its reason says what will change.
setup = fullfile(examples, "mcc", "vclamp_5gohm.mcc");    % on an amplifier, your own file
plan = a.load_config(setup, Changes={"Feedback Resistor", 500, "MΩ", "V-Clamp"});
disp(plan.reason)

% With Confirmed=true, Commander closes, starts again with the copy and is checked, about 15 s. The
% file sets every value it holds, Holding included (off in ommm's examples), so a held cell is
% released: not with a cell you want to keep. This object takes the new Commander; any other
% program or MATLAB session using ommm calls reconnect. On an amplifier (a.fake is "" there), the
% section stops here while setup is still ommm's example file.
assert(a.fake ~= "" || ~startsWith(setup, examples), "on an amplifier, load your own setup, not " + ...
    "ommm's example: save it in Commander (Save Configuration, F5) and point setup at that file")
w = a.load_config(setup, Changes={"Feedback Resistor", 500, "MΩ", "V-Clamp"}, Confirmed=true);
disp(w.reason)
a.load_config(setup, Confirmed=true);           % and back to the file unchanged

% After Commander was closed or restarted any other way (its own window, another program), every
% call on this object fails until reconnect, which waits up to 30 s for Commander and takes a new
% handle: a get or snapshot as ommm:commander, a write as ommm:refused (nothing sent). Commander may
% then show Holding off while the amplifier still holds: if Holding was on, turn it on again as
% your first write (docs/quirks.md).
% a.reconnect();

%% Close the handle
% Lets go of ommm's handle; Commander keeps running as it is.
clear a
