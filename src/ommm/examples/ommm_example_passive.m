%% Passive: read and record the amplifier, changing no setting
% Nothing here sends a Set or presses a button, so it is safe with a cell on. Run it a section at a
% time (Run Section, Ctrl+Enter) or whole. The same steps in Python: ommm_example_passive.py.
% Changing things: ommm_example_active.m. Every method: docs/matlab.md.

%% Open a handle on Commander
% ommm.Amplifier is a MATLAB class over ommm's Python package; it starts Python from ommm's own
% .venv, so run `uv sync --locked` in the ommm folder once first. Commander must already be running
% on this PC, in this desktop session; ommm does not start it. Opening a handle, like every read
% here, changes no setting; it brings the active mode's tab to the front.
ommmFolder = "C:\Users\you\repos\ommm";        % where you cloned ommm
addpath(fullfile(ommmFolder, "matlab"))
examples = fullfile(ommmFolder, "src", "ommm", "examples");  % this file's folder in the clone: mcc/ and fake/
a = ommm.Amplifier();                           % headstage 1 of the one 700B Commander runs

% Without Commander (a Mac, say), every section runs on ommm's fake Commander, a saved snapshot:
% a = ommm.Amplifier(Fake=fullfile(examples, "fake", "vclamp.json"));

disp(a.serial)              % which amplifier
disp(a.log_path)            % where ommm logs every write, from every program

%% Read one control, in the unit you name
% get takes Commander's label for a control, as on its window, and a unit of the kind Commander
% shows it in for the active mode. Holding is a voltage in V-Clamp, a current in I-Clamp, and not
% in I = 0, so read the mode first.
mode = a.get("Mode");                           % "V-Clamp", "I-Clamp" or "I = 0"
resistor = a.get("Feedback Resistor", "MΩ");
primary = a.get("Primary Output");              % an output signal by Commander's name: "Membrane Current"
gain = a.get("Primary Output Gain", "x");
current = a.get("MeterValue2", "pA");           % the current meter; MeterValue1 is the potential, in mV
fprintf("%s, Rf %g MΩ, %s ×%g, %g pA\n", mode, resistor, primary, gain, current)
if mode ~= "I = 0"
    unit = "pA";
    if mode == "V-Clamp"
        unit = "mV";
    end
    holdingOn = a.get("HoldingEnable");         % a checkbox, true or false; plain "Holding" is the value
    fprintf("Holding %g %s (on: %d)\n", a.get("Holding", unit), unit, holdingOn)
end

% A control the active mode does not have is an error, ommm:notApplicable; a wrong or missing unit,
% or an unknown label, is ommm:badArgument.
try
    a.get("Bridge Balance", "MΩ");              % I-Clamp only
catch err
    fprintf("%s: %s\n", err.identifier, err.message)
end

%% Take a snapshot: every setting at once
% A struct: every reading in SI units (s.readings), one telegraph packet (s.telegraph), where the
% API and the telegraph disagree (s.disagreements), and which ommm took it (s.ommm: version, git
% commit, dirty). It reads the active mode's tab; the other mode's values are read after a set_mode.
s = a.snapshot();
disp(a.summary())                               % the box `ommm --summary` prints
disp(s.ommm)

% Save the snapshot with your data, not the object a: a saved ommm.Amplifier holds no connection.
% As JSON it reads anywhere; `ommm --summary snapshot.json` prints it on any computer.
writelines(jsonencode(s), "snapshot.json")

%% Check the scaling before you record
% state turns a snapshot into what a recording needs: each output's signal, gain and scale (V/A or
% V/V at gain 1), its low-pass, and anything wrong. blocking means don't trust the scales at all
% (e.g. the other mode's tab was in front); problems names one output's doubt. Which signal belongs
% on which output is yours to check.
st = a.state(s);                                          % the snapshot above; a.state() takes a new one
disp(st.blocking), disp(st.problems), disp(st.warnings)   % cell arrays of text, empty when all is well
disp(st.primary)                                          % signal "Membrane Current", gain 2, scale 5e9 V/A, lpf 8000 Hz, trusted
if a.get("Primary Output") ~= "Membrane Current"
    disp("The primary output is not Membrane Current: set it before you record")
end

%% Record what changed during a trial, and who changed it
% Take a snapshot before and after, and note where the write log ends. trial_record compares the
% two snapshots and puts each change down to "ommm" when a logged write (from any program using
% ommm) explains it, else to "gui": a click in Commander's window, the front panel, or a program
% that does not use ommm.
before = a.snapshot();
[~, mark] = a.writes_since();                   % the end of the log now
% ... record a trial; change something in Commander's window to see it here ...
after = a.snapshot();
[writes, mark] = a.writes_since(mark);          % the lines written during the trial, and the mark for the next trial
record = a.trial_record(before, after, writes); % save it with the trial
for section = string(fieldnames(record.changed))'             % readings and telegraph; none when nothing changed
    for key = string(fieldnames(record.changed.(section)))'
        change = record.changed.(section).(key);
        fprintf("%s %s: %s → %s (%s)\n", section, key, string(change.before), string(change.after), change.source)
    end
end

%% Close the handle
% Lets go of ommm's handle; Commander keeps running as it is. Python keeps running in the
% background until terminate(pyenv) or MATLAB exits. To close or start Commander itself:
% ommm_example_active.m.
clear a
