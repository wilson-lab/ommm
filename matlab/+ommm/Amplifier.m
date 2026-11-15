classdef Amplifier < handle
    % One headstage of the one MultiClamp 700B that the running MultiClamp Commander controls (1, or
    % Headstage=2), read and set through ommm's Python ommm.Amplifier by Commander's labels, a unit on
    % every value (docs/matlab.md; every check a write makes: docs/writes.md).
    %
    %   addpath <ommm>/matlab
    %   a = ommm.Amplifier();                  % or ommm.Amplifier(Fake="snapshot.json"), no Commander needed
    %   b = ommm.Amplifier(Headstage=2);       % headstage 2, beside a or on its own
    %   a.get("Holding", "mV")                 % one control, in your unit; a.get("Mode") is "V-Clamp"
    %   w = a.set("Holding", -60, "mV");       % checks, sends, reads back and logs; w.outcome is "ok"
    %   p = a.plan("Holding", -40, "mV");      % set's checks, sending nothing: p.outcome "planned",
    %                                          % p.reason "Holding -60 mV → -40 mV (V-Clamp)"
    %   a.enable("Seal Test", true);           % a checkbox, by its name on Commander's window
    %   a.set_mode("I-Clamp");                 % through I = 0
    %   a.press("Auto Bridge Balance");        % a button (I-Clamp's)
    %   s = a.snapshot();                      % every setting, SI units
    %
    % Each write returns a struct; a refused one is an error ommm:refused, one that did not take
    % ommm:writeError (err.write holds it for both), a control the active mode lacks
    % ommm:notApplicable, Commander failing ommm:commander, and an argument ommm cannot use, such as an
    % unknown label or a wrong unit in get, ommm:badArgument. Python runs out of process from ommm's own .venv
    % (`uv sync --locked` in the ommm folder); a JSON null comes out as [], a list of text as a cell array.

    properties (SetAccess = private)
        headstage   % Headstage=, 1 or 2 (its full record: the snapshot's headstage)
        serial      % the amplifier's serial, as Commander lists it
        fake        % the snapshot file served instead of Commander, "" for Commander
        log_path    % the write log: one JSON line per write and refusal, from every program (writes_since reads it)
    end

    properties (Dependent, SetAccess = private)
        gui         % with Fake=, the person at Commander's window: show_tab, mode, set, enable (Python's amp.gui)
    end

    properties (Access = private)
        logDir      % LogDir=, "" for ommm's default (~/ommm-logs; a new temporary folder on the fake); once
                    % connected, the full path Python logs to, so a reconnect after a cd keeps one log
        otherTab    % with Fake=, the snapshot file of the other tab, "" for none
    end

    properties (Access = private, Transient) % not saved: a loaded object connects again on its first call
        amp         % Python ommm.Amplifier
        pythonID    % pyenv's ProcessID when connected: another one, or none, means connect again
    end

    methods
        function obj = Amplifier(options)
            arguments
                options.LogDir (1,1) string = ""
                options.Fake (1,1) string = ""
                options.OtherTab (1,1) string = ""
                options.Headstage (1,1) double {mustBeMember(options.Headstage, [1 2])} = 1
            end
            if options.OtherTab ~= "" && options.Fake == ""
                error('ommm:fake', 'OtherTab= is the fake''s other tab: give Fake= too')
            end
            obj.logDir = options.LogDir;
            obj.fake = fullPath(options.Fake);
            obj.otherTab = fullPath(options.OtherTab);
            obj.headstage = options.Headstage;
            obj.start();
        end

        function gui = get.gui(obj)
            if obj.fake == ""
                error('ommm:fake', 'Only ommm.Amplifier(Fake=FILE) has a gui; with Commander, use its window')
            end
            gui = obj.call(@(amp) amp.gui); % the window outlives its handles, as Commander's does
        end

        % reads

        function value = get(obj, label, unit)
            % One control by Commander's label, in the unit given: get("Holding", "mV"). Without a unit: the
            % mode by name ("V-Clamp"), an output signal by Commander's name ("Membrane Current"), a
            % checkbox as true or false (get("Seal Test"), get("HoldingEnable")). The meters:
            % get("MeterValue1", "mV"), get("MeterValue2", "pA"); on headstage 2 MeterValue3 and 4.
            % Brings the active mode's tab to the front.
            arguments
                obj
                label (1,1) string
                unit (1,1) string = ""
            end
            value = obj.call(@(amp) amp.get(label, orNone(unit)));
            if isa(value, 'py.str')
                value = string(value);
            end
        end

        function s = snapshot(obj)
            % Every setting Commander reports for the headstage, in SI units, plus one telegraph packet
            % and ommm's version and commit (docs/install-and-testing.md, The snapshot), from the active
            % mode's tab, which it brings to the front first.
            s = ommm.Amplifier.fromPython(obj.call(@(amp) amp.snapshot()));
            s.disagreements = cellstr(string(s.disagreements));
            for name = ["errors", "not_applicable"]
                if isempty(fieldnames(s.(name))) % none: struct([]), so isempty is true, as for disagreements
                    s.(name) = struct([]);
                end
            end
        end

        function st = state(obj, snapshot)
            % What a snapshot (default: a new one; or one saved as JSON, read with jsondecode) says
            % about the two outputs, in SI: mode, feedback resistor (Ω), each output's signal
            % (Commander's name) and api_name, gain, scale at gain 1 (V/A or V/V) and low-pass (Hz),
            % and the blocking, problems and warnings found.
            arguments
                obj
                snapshot (1,1) struct = obj.snapshot()
            end
            st = ommm.Amplifier.fromPython(obj.call(@(~) py.ommm.state(toPython(snapshot))));
            for name = ["blocking", "problems", "warnings"]
                st.(name) = cellstr(string(st.(name)));
            end
        end

        function text = summary(obj, snapshot, options)
            % The box `ommm --summary` prints, for a snapshot (default: a new one). Manual: the
            % settings Commander cannot report, e.g. struct(lpf_type_v_clamp="bessel",
            % lpf_type_i_clamp="butterworth").
            arguments
                obj
                snapshot (1,1) struct = obj.snapshot()
                options.Manual (1,1) struct = struct()
            end
            text = string(obj.call(@(~) py.ommm.summary(toPython(snapshot), py.dict(options.Manual))));
        end

        function [writes, mark] = writes_since(obj, mark)
            % The write log's lines after byte offset `mark` (0: all), from every program, as a struct
            % array (struct([]) for none; a cell array of structs when lines differ in fields, as 0.1's
            % and 0.2's do), and the mark to pass next time
            arguments
                obj
                mark (1,1) double {mustBeInteger, mustBeNonnegative} = 0
            end
            result = obj.call(@(amp) amp.writes_since(int64(mark)));
            writes = ommm.Amplifier.fromPython(result{1});
            if isempty(writes)
                writes = struct([]);
            end
            mark = double(result{2});
        end

        function record = trial_record(obj, before, after, writes, options)
            % Two snapshots (a.snapshot(), [] for one that failed) and the write log's lines between
            % them (writes_since's struct array, or a cell array of such structs), as Python's
            % ommm.trial_record: before, after, what changed (changed) and, from Previous, the last
            % trial's after, since then (between), each field's source "ommm" or "gui"
            % (docs/writes.md, The log and trial records)
            arguments
                obj
                before {mustBeSnapshotOrEmpty}
                after {mustBeSnapshotOrEmpty}
                writes {mustBeA(writes, ["struct", "cell"])} = struct([])
                options.Previous {mustBeSnapshotOrEmpty} = []
            end
            if isstruct(writes)
                writes = num2cell(writes); % one line alone would be written as an object, not a list
            end
            record = ommm.Amplifier.fromPython(obj.call(@(~) py.ommm.trial_record(orNoneSnapshot(before), ...
                orNoneSnapshot(after), toPython(writes), orNoneSnapshot(options.Previous))));
        end

        % writes: each returns the write as a struct (docs/writes.md, Outcomes)

        function write = plan(obj, label, value, unit, options)
            % What set with these arguments would do, from fresh reads: outcome "planned", its reason the
            % question in your unit ("Holding 0 mV → -40 mV (V-Clamp)"), or "refused" and why. Sends and
            % logs nothing; set keeps the same reason. Before a question, with Expect= (docs/matlab.md).
            arguments
                obj
                label (1,1) string
                value
                unit (1,1) string = ""
                options.Expect {mustBeExpect} = []
                options.Step double {mustBeScalarOrEmpty} = []
            end
            [step, expect] = stepAndExpect(options);
            write = ommm.Amplifier.asStruct(obj.call(@(amp) amp.plan(label, value, orNone(unit), step=step, expect=expect)));
        end

        function write = set(obj, label, value, unit, options)
            % Set a value by Commander's label, in a unit of the active mode: set("Holding", -60, "mV");
            % an output signal by name: set("Primary Output", "Membrane Potential"). Checks first, sends,
            % reads back and logs. Step=5 moves there in steps of 5 (the call's unit), each read back;
            % Expect=-50 refuses unless Commander still shows -50 (a signal: its name), the value a
            % confirm dialog showed.
            arguments
                obj
                label (1,1) string
                value
                unit (1,1) string = ""
                options.Expect {mustBeExpect} = []
                options.Step double {mustBeScalarOrEmpty} = []
            end
            [step, expect] = stepAndExpect(options);
            write = ommm.Amplifier.asStruct(obj.call(@(amp) amp.set(label, value, orNone(unit), step=step, expect=expect)));
        end

        function write = enable(obj, name, on)
            % Turn a checkbox on or off by its name on Commander's window: enable("Seal Test", true),
            % enable("Holding", false), enable("Mode Switching", false)
            arguments
                obj
                name (1,1) string
                on (1,1) logical
            end
            write = ommm.Amplifier.asStruct(obj.call(@(amp) amp.enable(name, on)));
        end

        function write = press(obj, name)
            % Press one of Commander's buttons by its name: press("Zap"), press("Auto Bridge Balance").
            % Its values are settings, set first: set("Zap Duration", 0.5, "ms"). write.also is what a
            % snapshot shows changed, each field [before; after].
            arguments
                obj
                name (1,1) string
            end
            write = ommm.Amplifier.asStruct(obj.call(@(amp) amp.press(name)));
        end

        function write = set_mode(obj, mode)
            % "V-Clamp", "I-Clamp" or "I = 0", as Commander's buttons: V-Clamp and I-Clamp through I = 0.
            % write.after is the mode id read back, write.also what else a snapshot shows changed; the
            % new mode's Holding is yours to set.
            arguments
                obj
                mode (1,1) string
            end
            write = ommm.Amplifier.asStruct(obj.call(@(amp) amp.set_mode(mode)));
        end

        function writes = make_safe(obj)
            % Turns off, where the active mode has them, Pipette Capacitance Neutralization, Rs
            % Compensation, Seal Test (Tuning in I-Clamp) and the Resistance meter: the writes it sent, a
            % struct array (struct([]) when all were off)
            sent = cell(obj.call(@(amp) amp.make_safe()));
            writes = ommm.Amplifier.fromPython(py.list(cellfun(@(write) py.dataclasses.asdict(write), sent, UniformOutput=false)));
            if isempty(writes)
                writes = struct([]);
            end
        end

        function write = load_config(obj, path, options)
            % Close Commander and start it again with a .mcc file Commander saved (docs/mcc.md): the
            % route to the feedback resistor and the Options pages. Changes: one row per change,
            % {"Feedback Resistor", 500, "MΩ", "V-Clamp"}, patched in a copy. Without Confirmed=true it
            % returns the plan, write.reason saying what will change, and sends nothing; with it,
            % Commander is gone for about 15 s (30 s when its first start does not apply the file and
            % ommm starts it once more) and this object takes the new Commander; other programs
            % call reconnect(). The restart reaches both headstages: it is refused while the other one
            % holds a level, unless ReleaseOtherHeadstage=true.
            arguments
                obj
                path (1,1) string
                options.Changes (:,4) cell = cell(0, 4)
                options.Confirmed (1,1) logical = false
                options.ReleaseOtherHeadstage (1,1) logical = false
            end
            changes = py.list();
            for row = 1:size(options.Changes, 1)
                changes.append(py.tuple(options.Changes(row, :)));
            end
            if isfile(path) % Python's working folder is not MATLAB's
                path = fullPath(path);
            end
            write = ommm.Amplifier.asStruct(obj.call(@(amp) amp.load_config(path, changes=changes, confirmed=options.Confirmed, ...
                release_other_headstage=options.ReleaseOtherHeadstage)));
        end

        function reconnect(obj)
            % New handles after Commander was closed and started again, when calls fail with 6002 (a
            % read ommm:commander, a write ommm:refused): waits for Commander's window, up to 30 s.
            % After a Python restart the class reconnects by itself. After a restart Commander may
            % show Holding off while the amplifier still holds the last command: if Holding was on,
            % turn it on, enable("Holding", true), as your first write after reconnect(). Any other
            % write, set included, may make the amplifier follow the unchecked box, and the
            % output-signal re-select ommm sends before the first write after a start has not been
            % measured for this.
            environment = pyenv;
            if environment.ProcessID == obj.pythonID
                obj.call(@(amp) amp.reconnect());
            else
                obj.start();
            end
        end
    end

    methods (Access = private)
        function result = call(obj, request)
            % request(amp) on the Python Amplifier, connecting again first if Python restarted since;
            % its errors come out with an ommm: identifier. A call once sent is never retried.
            obj.reconnectIfPythonRestarted();
            try
                result = request(obj.amp);
            catch err
                throw(ommm.Amplifier.withIdentifier(err))
            end
        end

        function start(obj)
            % Python, then a new Python Amplifier. After the Python host died, a py.* call restarts it
            % without ommm's .venv, and MATLAB then caches the failed lookup of py.ommm: only a new
            % Python process clears it
            if pyenv().Status == "Terminated"
                terminate(pyenv) % after the host died MATLAB restarts Python only after this; a no-op otherwise
            end
            try
                obj.connect();
            catch err
                if err.identifier ~= "MATLAB:undefinedVarOrClass" || ~contains(err.message, "py.ommm")
                    rethrow(err)
                end
                terminate(pyenv)
                obj.connect();
            end
        end

        function connect(obj)
            ommm.Amplifier.startPython();
            try
                amp = py.ommm.Amplifier(int32(obj.headstage), log_dir=orNone(obj.logDir), fake=orNone(obj.fake), other_tab=orNone(obj.otherTab));
            catch err
                throw(ommm.Amplifier.withIdentifier(err))
            end
            obj.serial = string(amp.serial);
            obj.logDir = string(py.str(amp.log_dir));
            obj.log_path = string(py.str(amp.log_path));
            obj.amp = amp;
            obj.pythonID = pyenv().ProcessID;
        end

        function reconnectIfPythonRestarted(obj)
            % The Python Amplifier dies with the Python it lives in (terminate(pyenv), a crash); a
            % loaded object has none
            if ~isequal(pyenv().ProcessID, obj.pythonID)
                obj.start();
            end
        end
    end

    methods (Static, Access = private)
        function startPython()
            % Out of process, so a crash in Commander's DLL cannot take MATLAB down, on the interpreter
            % ommm's .venv was made from: uv's .venv\Scripts\python.exe is a launcher MATLAB cannot load
            root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
            venv = fullfile(root, '.venv');
            if ~isfile(fullfile(venv, 'pyvenv.cfg'))
                error('ommm:noVenv', 'No Python environment in %s: run `uv sync --locked` in %s', venv, root)
            end
            home = regexp(fileread(fullfile(venv, 'pyvenv.cfg')), 'home\s*=\s*([^\r\n]+)', 'tokens', 'once');
            if ispc
                python = fullfile(strtrim(home{1}), 'python.exe');
                site = fullfile(venv, 'Lib', 'site-packages');
            else
                python = fullfile(strtrim(home{1}), 'python3');
                found = dir(fullfile(venv, 'lib', 'python3*', 'site-packages'));
                site = found(1).folder;
            end

            environment = pyenv;
            if environment.Status == "Loaded" && environment.Executable ~= python
                error('ommm:otherPython', ['MATLAB''s Python is %s, but ommm needs %s (from %s): ' ...
                    'terminate(pyenv) or restart MATLAB, then try again; if uv run or uv sync rebuilt the .venv ' ...
                    'on another Python (older MATLAB releases), set UV_PYTHON as docs/matlab.md Requirements says, ' ...
                    'run uv sync --locked in %s, then restart MATLAB'], environment.Executable, python, venv, root)
            elseif environment.Status ~= "Loaded" && (environment.Executable ~= python || environment.ExecutionMode ~= "OutOfProcess")
                % Only when it differs: MATLAB may restart a terminated Python from its saved setting
                % at any moment (releasing old py objects), and then refuses pyenv(Version=...)
                mode = string(environment.ExecutionMode);
                if environment.Executable ~= "" % MATLAB found no Python before: nothing to put back
                    warning('ommm:pyenvChanged', ['ommm changes MATLAB''s saved Python from %s (%s) to %s (OutOfProcess), ' ...
                        'for later MATLAB sessions too; to put it back: terminate(pyenv); pyenv(Version="%s", ExecutionMode="%s")'], ...
                        environment.Executable, mode, python, environment.Executable, mode)
                end
                try
                    pyenv(Version=python, ExecutionMode="OutOfProcess");
                catch err
                    % MATLAB started its saved Python since the check above, as releasing py objects of
                    % a terminated Python does, at a moment of its choosing: nothing runs in it yet
                    if err.identifier ~= "MATLAB:Pyenv:PythonLoaded"
                        rethrow(err)
                    end
                    terminate(pyenv)
                    pyenv(Version=python, ExecutionMode="OutOfProcess");
                end
            end
            py.site.addsitedir(site);
            argv = cell(py.sys.argv);
            if isempty(argv) || string(argv{1}) == "" % no script: the write log's process.program says MATLAB
                py.setattr(py.importlib.import_module('sys'), 'argv', py.list({'MATLAB'}));
            end

            % Clones made by uv share one interpreter, and addsitedir puts this clone's folders behind
            % those of a clone added before, whose ommm Python would import, or has imported. find_spec
            % gives the loaded module's file once ommm is imported, else the file it would load
            imported = string(py.os.path.realpath(py.importlib.util.find_spec("ommm").origin));
            if ~startsWith(imported, string(py.os.path.realpath(root)) + filesep, IgnoreCase=ispc)
                error('ommm:otherClone', ['MATLAB''s Python imports ommm from %s, not from this clone, %s: ' ...
                    'one ommm clone per MATLAB session; terminate(pyenv) or restart MATLAB, then try again'], ...
                    fileparts(fileparts(fileparts(imported))), root)
            end
        end

        function err = withIdentifier(err)
            % A Python error as a MATLAB one with an ommm: identifier and Python's message: a write
            % refused (ommm:refused) or not taken (ommm:writeError), with the write as err.write; a
            % control the active mode lacks (ommm:notApplicable); Commander failing (ommm:commander);
            % Python's ValueError, an argument ommm cannot use (ommm:badArgument): an unknown label or a
            % wrong unit in get, a Fake= file that is not a snapshot, a LogDir= ommm cannot write to.
            % Any other error stays as it is.
            if ~isa(err, 'matlab.exception.PyException')
                return
            end
            exception = err.ExceptionObject{2};
            is = @(module, name) py.isinstance(exception, py.getattr(py.importlib.import_module(module), name));
            message = string(py.str(exception));
            if is('ommm', 'WriteError')
                write = ommm.Amplifier.asStruct(exception.write);
                if write.outcome == "refused"
                    err = ommm.WriteError('ommm:refused', message, write);
                else
                    err = ommm.WriteError('ommm:writeError', message, write);
                end
            elseif is('ommm', 'NotApplicable')
                err = MException('ommm:notApplicable', '%s', message);
            elseif is('ommm', 'CommanderError')
                err = MException('ommm:commander', '%s', message);
            elseif is('builtins', 'ValueError')
                err = MException('ommm:badArgument', '%s', message);
            end
        end

        function write = asStruct(write)
            write = ommm.Amplifier.fromPython(py.dataclasses.asdict(write));
        end

        function value = fromPython(object)
            value = jsondecode(char(py.json.dumps(object)));
        end
    end
end

function [step, expect] = stepAndExpect(options)
    % Step= (a number) and Expect= (a number, or an output signal's name), in the call's unit as
    % Python's step= and expect= are: None when not given, an Expect text as a string
    step = py.None;
    expect = py.None;
    if ~isempty(options.Step)
        step = options.Step;
    end
    if ~isnumeric(options.Expect)
        expect = string(options.Expect);
    elseif ~isempty(options.Expect)
        expect = options.Expect;
    end
end

function value = orNone(text)
    % "" as Python's None: no unit, no log folder, no fake
    value = text;
    if text == ""
        value = py.None;
    end
end

function path = fullPath(file)
    % A file's full path, as Python's working folder is not MATLAB's; "" stays ""
    path = file;
    if file == ""
        return
    end
    if ~isfile(file)
        error('ommm:fake', 'No snapshot file %s', file)
    end
    found = dir(file);
    path = string(fullfile(found.folder, found.name));
end

function mustBeExpect(expect)
    % A number, or an output signal's name as a string or a char vector
    mustBeA(expect, ["double", "string", "char"])
    if ischar(expect)
        mustBeTextScalar(expect)
    else
        mustBeScalarOrEmpty(expect)
    end
end

function object = toPython(value)
    % A snapshot struct or a cell array of log lines as Python has them: through JSON, each [] that
    % stands for a null, or for no errors, not_applicable or also, put back (ommm.without_matlab_empties)
    object = py.ommm.without_matlab_empties(py.json.loads(jsonencode(value)));
end

function object = orNoneSnapshot(snapshot)
    % [] (a snapshot that failed) as Python's None
    object = py.None;
    if ~isempty(snapshot)
        object = toPython(snapshot);
    end
end

function mustBeSnapshotOrEmpty(snapshot)
    if ~(isstruct(snapshot) && isscalar(snapshot)) && ~(isnumeric(snapshot) && isempty(snapshot))
        error('ommm:badArgument', 'A snapshot is the struct from a.snapshot() (or [] for one that failed), not %s', class(snapshot))
    end
end
