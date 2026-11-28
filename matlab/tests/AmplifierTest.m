classdef AmplifierTest < matlab.unittest.TestCase
    % ommm.Amplifier on a saved snapshot (Fake=), so it runs without Commander, e.g. on a Mac:
    % runtests("<ommm>/matlab/tests"). Starts Python out of process from ommm's .venv and stops it
    % at the end.

    properties
        Data = fullfile(fileparts(fileparts(fileparts(mfilename('fullpath')))), 'src', 'ommm', 'examples', 'fake') % the snapshots the package ships
        Fixture = fullfile(fileparts(fileparts(fileparts(mfilename('fullpath')))), 'tests', 'data', ...
            'vclamp_stale_secondary_telegraph.json') % V-Clamp at 500 MΩ, its secondary output's telegraph stale
        Amp
    end

    methods (TestClassSetup)
        function addOmmmToPath(testCase)
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fileparts(fileparts(mfilename('fullpath')))));
            testCase.addTeardown(@() terminate(pyenv));
        end
    end

    methods (TestMethodSetup)
        function connect(testCase)
            testCase.Amp = ommm.Amplifier(Fake=testCase.Fixture); % some tests stop Python
        end
    end

    methods
        function a = bothTabs(testCase)
            % V-Clamp at 5 GΩ with its telegraph fresh, and the I-Clamp tab from its own snapshot
            a = ommm.Amplifier(Fake=fullfile(testCase.Data, 'vclamp.json'), OtherTab=fullfile(testCase.Data, 'iclamp.json'));
        end
    end

    methods (Test)
        function startsPythonOutOfProcessFromTheVenv(testCase)
            environment = pyenv;
            testCase.verifyEqual(string(environment.ExecutionMode), "OutOfProcess");
            testCase.verifyEqual(string(environment.Status), "Loaded");
            testCase.verifyEqual(testCase.Amp.headstage, 1);
            testCase.verifyEqual(testCase.Amp.serial, "00123456");
            testCase.verifyEqual(testCase.Amp.fake, string(testCase.Fixture));
        end

        function headstage2ReadsAndLogsAsItsOwn(testCase)
            % the fake serves the snapshot, taken on headstage 1, as headstage 2's
            a = ommm.Amplifier(Fake=fullfile(testCase.Data, 'vclamp.json'), OtherTab=fullfile(testCase.Data, 'iclamp.json'), Headstage=2);
            testCase.verifyEqual(a.headstage, 2);
            testCase.verifyEqual(a.snapshot().headstage.channel, 2); % the full record
            testCase.verifyEqual(a.snapshot().readings.FeedbackResistorVC2, 2);
            testCase.verifyEqual(a.get("Feedback Resistor", "GΩ"), 5);
            testCase.verifyError(@() a.get("MeterValue1", "mV"), 'ommm:badArgument');
            a.set("Holding", -40, "mV");
            testCase.verifyEqual(a.get("Holding", "mV"), -40);
            [~, name] = fileparts(a.log_path);
            testCase.verifyEqual(string(name), "00123456_headstage2");
            testCase.verifyError(@() ommm.Amplifier(Fake=testCase.Fixture, Headstage=3), 'MATLAB:validators:mustBeMember');
        end

        % reads

        function snapshotIsAStructInSI(testCase)
            s = testCase.Amp.snapshot();
            testCase.verifyEqual(s.readings.Mode, 0);
            testCase.verifyEqual(s.readings.ModeName, 'VCLAMP');
            testCase.verifyEqual(s.readings.FeedbackResistorVC1, 1);
            testCase.verifyEqual(s.telegraph.dExtCmdSens, 0.02);
            testCase.verifyClass(s.disagreements, 'cell');
            testCase.verifyEqual(numel(s.disagreements), 1); % the fixture's stale secondary telegraph
            testCase.verifyEqual([s.schema, s.demo], [1, false]);
            testCase.verifyEqual(fieldnames(s.ommm), {'version'; 'commit'; 'dirty'; 'git_error'});
        end

        function noErrorsAndNoNotApplicableAreEmpty(testCase)
            % none is struct([]), so isempty works on them as on disagreements
            s = ommm.Amplifier(Fake=fullfile(testCase.Data, 'vclamp.json')).snapshot();
            testCase.verifyEmpty(s.errors);
            testCase.verifyClass(s.errors, 'struct');
            testCase.verifyEmpty(s.disagreements);
            testCase.verifyEqual(s.not_applicable.BridgeBalResist, 'INVALIDPARAMETER (6004)'); % I-Clamp's, read in V-Clamp
            % saved as matlab.md says, where jsonencode writes struct([]) as [], it still serves Fake=
            file = fullfile(testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture).Folder, 'saved.json');
            writelines(jsonencode(s), file);
            testCase.verifyEmpty(ommm.Amplifier(Fake=file).snapshot().errors);
        end

        function stateIsSIWithListsAsCells(testCase)
            st = testCase.Amp.state();
            testCase.verifyEqual(st.mode, 'V-Clamp');
            testCase.verifyEqual(st.feedback_resistor, 500e6);
            testCase.verifyEqual({st.primary.signal, st.primary.api_name, st.primary.units}, {'Membrane Current', 'VC_MEMBCURRENT', 'V/A'});
            testCase.verifyEqual(st.primary.scale, 500e6);
            testCase.verifyEqual(st.secondary.scale, 10);
            testCase.verifyEqual(st.blocking, cell(0, 0));
            testCase.verifyEqual(st.problems, cell(0, 0));
            testCase.verifyEqual(numel(st.warnings), 1); % the fixture's stale secondary telegraph
            testCase.verifyTrue(startsWith(st.warnings{1}, "secondary signal: API VC_MEMBPOTENTIAL"));
        end

        function stateAndSummaryTakeAHeldSnapshot(testCase)
            held = testCase.Amp.snapshot();
            testCase.verifyEqual(testCase.Amp.state(held), testCase.Amp.state());
            box = testCase.Amp.summary(held, Manual=struct(lpf_type_v_clamp="bessel"));
            testCase.verifyClass(box, 'string');
            testCase.verifySubstring(box, 'Bessel');
            testCase.verifySubstring(box, '500 MΩ');
        end

        function stateAndSummaryTakeASnapshotSavedAsJson(testCase)
            % saved with jsonencode and read back with jsondecode: no errors is [] and {} there
            a = ommm.Amplifier(Fake=fullfile(testCase.Data, 'vclamp.json'));
            file = fullfile(testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture).Folder, 'snapshot.json');
            writelines(jsonencode(a.snapshot()), file);
            saved = jsondecode(fileread(file));
            testCase.verifyEqual(a.state(saved), a.state());
            testCase.verifyEqual(a.summary(saved), a.summary());
            testCase.verifyEqual(a.summary(jsondecode(fileread(fullfile(testCase.Data, 'vclamp.json')))), a.summary());
        end

        function aNullInASnapshotStructIsANullInPython(testCase)
            % jsondecode makes each null [], at any depth: no telegraph, a *Name reading no header constant matched
            s = testCase.Amp.snapshot();
            s.readings.SecondarySignalName = [];
            testCase.verifyEqual(testCase.Amp.state(s).blocking, {'incomplete snapshot: no SecondarySignalName'});
            s.telegraph = [];
            testCase.verifyEqual(testCase.Amp.state(s).blocking, {'incomplete snapshot: no telegraph, SecondarySignalName'});
            testCase.verifySubstring(testCase.Amp.summary(s), 'no telegraph');
        end

        function trialRecordTakesSnapshotsAndNoneOneOrManyWrites(testCase)
            a = testCase.bothTabs();
            previous = a.snapshot();
            a.gui.set("Seal Test Amplitude", 10, "mV"); % a click between trials
            before = a.snapshot();
            [~, mark] = a.writes_since();
            none = a.trial_record(before, a.snapshot(), a.writes_since(mark));
            testCase.verifyEmpty(fieldnames(none.changed)); % nothing changed: {}
            testCase.verifyEmpty(none.between); % no Previous
            a.set("Holding", -60, "mV");
            [writes, mark] = a.writes_since(mark);
            testCase.verifyTrue(isscalar(writes)); % one line: a 1x1 struct
            one = a.trial_record(before, a.snapshot(), writes, Previous=previous);
            testCase.verifyEqual(one.changed.readings.Holding.source, 'ommm');
            testCase.verifyEqual(one.between.readings.TestSignalAmplitude.source, 'gui');
            a.press("Auto Output Zero");
            a.set_mode("I-Clamp");
            after = a.snapshot();
            many = a.trial_record(before, after, [writes; a.writes_since(mark)]);
            sources = cellfun(@(name) many.changed.readings.(name).source, fieldnames(many.changed.readings), UniformOutput=false);
            testCase.verifyEqual(unique(sources), {'ommm'});
            testCase.verifyEqual(many.changed.readings.Mode.source, 'ommm');
            testCase.verifyEqual(many.after.readings.Mode, 1);
            failed = a.trial_record([], after, num2cell(a.writes_since()));
            testCase.verifyEmpty(failed.before);
            testCase.verifyEmpty(failed.changed);
        end

        function getReadsOneControlByLabelInTheUnitGiven(testCase)
            a = testCase.Amp;
            testCase.verifyEqual(a.get("Mode"), "V-Clamp");
            testCase.verifyEqual(a.get("Feedback Resistor", "MΩ"), 500);
            testCase.verifyEqual(a.get("Feedback Resistor", "GOhm"), 0.5);
            testCase.verifyEqual(a.get("Primary Output Gain", "x"), 2);
            testCase.verifyEqual(a.get("Holding", "mV"), 0);
            testCase.verifyEqual(a.get("Primary Output"), "Membrane Current");
            testCase.verifyEqual(a.get("Seal Test"), false); % a checkbox, by the name enable takes
            testCase.verifyEqual(a.get("HoldingEnable"), false); % or its API name
            testCase.verifyClass(a.get("MeterValue1", "mV"), 'double'); % the meters
            testCase.verifyClass(a.get("MeterValue2", "pA"), 'double');
        end

        function getWithoutTheRightUnitIsABadArgument(testCase)
            a = testCase.Amp;
            testCase.verifyError(@() a.get("Holding"), 'ommm:badArgument');
            testCase.verifyError(@() a.get("Holding", "pA"), 'ommm:badArgument');
            testCase.verifyError(@() a.get("MeterValue1", "pA"), 'ommm:badArgument');
            try
                a.get("Holding");
                testCase.verifyFail('get read Holding without a unit');
            catch err
                testCase.verifyEqual(err.message, 'Holding in V-Clamp is a voltage: give a unit: mV; its checkbox is get("HoldingEnable")'); % no Python None
            end
            try
                a.get("MeterValue1");
                testCase.verifyFail('get read a meter without a unit');
            catch err
                testCase.verifyEqual(err.message, 'MeterValue1 shows voltage now: give a unit: mV');
            end
            try
                a.get("Holdng", "mV");
                testCase.verifyFail('get read an unknown label');
            catch err
                testCase.verifyEqual(err.identifier, 'ommm:badArgument');
                testCase.verifyFalse(isa(err, 'ommm.WriteError')); % a read: no write
                testCase.verifySubstring(err.message, 'did you mean ''Holding''?');
            end
        end

        function getOfTheOtherModesSettingIsNotApplicable(testCase)
            % Bridge Balance is an I-Clamp setting and the fixture is in V-Clamp
            try
                testCase.Amp.get("Bridge Balance", "MΩ");
                testCase.verifyFail('get read a setting that does not apply');
            catch err
                testCase.verifyEqual(err.identifier, 'ommm:notApplicable');
                testCase.verifyEqual(err.message, 'Bridge Balance is not in V-Clamp: Commander has it in I-Clamp');
            end
        end

        function snapshotReadsTheActiveTab(testCase)
            a = ommm.Amplifier(Fake=testCase.Fixture, OtherTab=fullfile(testCase.Data, 'iclamp.json'));
            a.gui.show_tab("I-Clamp");
            s = a.snapshot();
            testCase.verifyEqual(s.readings.PrimarySignalName, 'VC_MEMBCURRENT');
            testCase.verifyFalse(any(startsWith(string(s.disagreements), "tab:")));
        end

        function getReadsTheActiveTab(testCase)
            a = ommm.Amplifier(Fake=testCase.Fixture, OtherTab=fullfile(testCase.Data, 'iclamp.json'));
            a.gui.show_tab("I-Clamp");
            testCase.verifyEqual([a.get("Primary Output"), a.get("Secondary Output")], ...
                ["Membrane Current", "Membrane Potential"]); % V-Clamp's, not I-Clamp's
        end

        % writes

        function setReturnsTheWriteAsAStruct(testCase)
            a = testCase.bothTabs();
            w = a.set("Holding", -60, "mV");
            testCase.verifyEqual(string({w.label, w.stem, w.mode, w.unit, w.outcome}), ["Holding", "Holding", "V-Clamp", "mV", "ok"]);
            testCase.verifyEqual([w.user_value, w.before, w.target, w.after], [-60, 0, -0.06, -0.06]);
            testCase.verifyEqual(w.depends.Mode, 0);
            testCase.verifyFalse(w.depends.HoldingEnable); % read for the note in reason
            testCase.verifyEqual(w.reason, ['Holding 0 mV → -60 mV (V-Clamp); Holding is off: the value applies ' ...
                'once it is on']); % the plan's question, kept
            testCase.verifyEqual(a.get("Holding", "mV"), -60);
        end

        function setTakesStepAndExpectInTheCallsUnit(testCase)
            a = testCase.bothTabs();
            w = a.set("Holding", -20, "mV", Step=5, Expect=0);
            testCase.verifyEqual(w.steps', [-0.005, -0.01, -0.015, -0.02]);
            testCase.verifyError(@() a.set("Holding", -40, "mV", Expect=0), 'ommm:refused'); % it shows -20 now
            w = a.set("Primary Output", "Membrane Potential", Expect="Membrane Current"); % a signal by its name
            testCase.verifyEqual(a.get("Primary Output"), "Membrane Potential");
            testCase.verifyEqual(w.outcome, 'ok');
            w = a.set("Primary Output", "Membrane Current", Expect='Membrane Potential'); % a char vector too
            testCase.verifyEqual(w.outcome, 'ok');
        end

        function aRefusalIsAnErrorWithTheWriteAndSendsNothing(testCase)
            a = testCase.bothTabs();
            try
                a.set("Holding", -60, "pA");
                testCase.verifyFail('set took a current for V-Clamp Holding');
            catch err
                testCase.verifyClass(err, 'ommm.WriteError');
                testCase.verifyEqual(err.identifier, 'ommm:refused');
                testCase.verifyEqual(err.message, 'Holding in V-Clamp is a voltage: mV, not pA');
                testCase.verifyEqual(err.write.outcome, 'refused');
                testCase.verifyEqual(err.write.reason, 'Holding in V-Clamp is a voltage: mV, not pA');
            end
            testCase.verifyEqual(a.get("Holding", "mV"), 0);
            testCase.verifyError(@() a.set("Bridge Balance", 10, "MΩ"), 'ommm:refused'); % not in V-Clamp
            testCase.verifyError(@() a.set("Holding", 2000, "mV"), 'ommm:refused');
            testCase.verifyError(@() a.set("Seal Test", true), 'ommm:refused'); % enable's
            testCase.verifyError(@() a.press("Holding"), 'ommm:refused');
            testCase.verifyError(@() a.set_mode("Voltage Clamp"), 'ommm:refused'); % not a mode; "VC", a button's name, is one
            lines = a.writes_since();
            testCase.verifyEqual(unique(string({lines.outcome})), "refused"); % each logged, none sent
        end

        function refusalsSayWhatToDoInWordsBothLanguagesRead(testCase)
            % no Python syntax in what a refusal says to do, and no Python object for a MATLAB value
            a = testCase.bothTabs();
            data = testCase.Data;
            calls = {
                @() a.set("Feedback Resistor", 500, "MΩ")
                @() a.set("Seal Test", true)
                @() a.press("Seal Test")
                @() a.set("Holding", -20, "mV", Expect="-40")
                @() a.set("Holding", -20, "mV", Expect=NaN)
                @() a.set("Holding", -20, "mV", Step=0)
                @() a.set("Holding", -20, "mV", Step=Inf)
                @() a.set("Primary Output", "Membrane Potential", Expect=0)
                @() a.press("Holding")
                @() a.enable("Seal Test Amplitude", true)
                @() ommm.Amplifier(Fake=fullfile(data, 'vclamp.json'), OtherTab=fullfile(data, 'vclamp.json'))
                };
            said = strings(0, 1);
            for k = 1:numel(calls)
                try
                    calls{k}();
                    testCase.verifyFail(func2str(calls{k}) + " was not refused");
                catch err
                    if k < numel(calls)
                        testCase.verifyEqual(err.identifier, 'ommm:refused', err.message);
                        testCase.verifyEqual(err.write.outcome, 'refused');
                    else
                        testCase.verifyEqual(err.identifier, 'ommm:badArgument', err.message); % no write: the fake's
                    end
                    said(end + 1) = err.message; %#ok<AGROW>
                end
            end
            a.set_mode("I-Clamp");
            said(end + 1) = a.load_config(fullfile(data, 'synthetic.mcc')).reason; % the file starts in V-Clamp
            for python = ["True", "changes=[", "confirmed=True", "amp.", "<memory at"]
                testCase.verifyEmpty(said(contains(said, python)), python);
            end
            testCase.verifySubstring(said(1), 'load_config with the file and the change (Feedback Resistor, 500, MΩ, V-Clamp)');
            testCase.verifySubstring(said(2), 'turn it on or off with enable("Seal Test", on)');
            testCase.verifySubstring(said(end), 'set_mode("I = 0") first, then load');
            % a vector or a cell is MATLAB's own validation error, before Python
            testCase.verifyError(@() a.set("Holding", -10, "mV", Expect=[-20 -10]), 'MATLAB:validators:mustBeScalarOrEmpty');
            testCase.verifyError(@() a.plan("Holding", -10, "mV", Step=[1 2]), 'MATLAB:validators:mustBeScalarOrEmpty');
            testCase.verifyError(@() a.set("Holding", -10, "mV", Expect={-20, "mV"}), 'MATLAB:validators:mustBeA');
        end

        function aWriteThatDoesNotTakeIsAWriteError(testCase)
            % 1.5 kHz is a cutoff of the other filter type: Commander keeps its nearest, 1.6 kHz
            try
                testCase.bothTabs().set("Primary Output Lowpass Filter", 1.5, "kHz");
                testCase.verifyFail('a mismatch returned');
            catch err
                testCase.verifyEqual(err.identifier, 'ommm:writeError');
                testCase.verifyEqual([string(err.write.outcome), err.write.after], ["mismatch", "1600"]);
                testCase.verifySubstring(err.message, 'Commander kept 1.6 kHz, not 1.5 kHz');
            end
        end

        function planSendsNothing(testCase)
            a = testCase.bothTabs();
            p = a.plan("Holding", -60, "mV");
            testCase.verifyEqual([string(p.outcome), p.target], ["planned", "-0.06"]);
            testCase.verifyEqual(p.reason, ['Holding 0 mV → -60 mV (V-Clamp); Holding is off: the value applies ' ...
                'once it is on']); % the question, in your unit
            refused = a.plan("Holding", -2000, "mV"); % returned, not raised
            testCase.verifyEqual(refused.outcome, 'refused');
            testCase.verifyEqual(refused.reason, 'Holding in V-Clamp is -1000 mV to 1000 mV, so not -2000 mV');
            testCase.verifyEqual(a.get("Holding", "mV"), 0);
            testCase.verifyEmpty(a.writes_since());
        end

        function enablePressAndSetMode(testCase)
            a = testCase.bothTabs();
            testCase.verifyEqual(a.enable("Seal Test", true).outcome, 'ok');
            testCase.verifyTrue(a.get("Seal Test"));
            zeroed = a.press("Auto Output Zero");
            testCase.verifyEmpty(zeroed.after); % a button has no value: what it changed is in also
            testCase.verifyEqual(zeroed.also.OutputZeroEnable', [false, true]);
            pressed = a.press("Auto Pipette Offset");
            testCase.verifyEqual(pressed.reason, ['it also moved the I-Clamp tab''s Pipette Offset, and its Slow ' ...
                'Current Injection level by a few µV, which ommm reads in I-Clamp']);
            moved = a.set_mode("I-Clamp");
            testCase.verifyEqual(moved.steps', [2, 1]); % through I = 0
            testCase.verifyEqual(a.get("Mode"), "I-Clamp");
            testCase.verifyEqual(moved.after, 1); % the mode id read back
            testCase.verifyEqual(moved.also.uOperatingMode', [0, 1]); % what else a snapshot shows changed
        end

        function makeSafeReturnsTheWritesItSent(testCase)
            a = testCase.bothTabs();
            a.enable("Seal Test", true);
            a.enable("Resistance Meter", true);
            sent = a.make_safe();
            testCase.verifyEqual(string({sent.label}), ["Seal Test", "Resistance Meter"]);
            testCase.verifyEqual(unique(string({sent.outcome})), "ok");
            again = a.make_safe();
            testCase.verifyEmpty(again);
            testCase.verifyClass(again, 'struct');
        end

        function aWriteSelectsStaleOutputSignalsFirst(testCase)
            % every write re-selects stale output signals first, each a logged write
            a = testCase.Amp;
            a.set("Holding", -10, "mV");
            testCase.verifyEqual(string({a.writes_since().stem}), ["PrimarySignal", "SecondarySignal", "Holding"]);
            testCase.verifyEmpty(a.snapshot().disagreements);
        end

        function writesSinceReadsTheLogFromAMark(testCase)
            folder = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture).Folder;
            a = ommm.Amplifier(Fake=fullfile(testCase.Data, 'vclamp.json'), LogDir=folder);
            testCase.verifyTrue(startsWith(a.log_path, folder));
            [lines, mark] = a.writes_since();
            testCase.verifyEqual([numel(lines), mark], [0, 0]);
            a.set("Holding", -10, "mV");
            [lines, mark] = a.writes_since(mark);
            testCase.verifyEqual(string(lines.label), "Holding");
            testCase.verifyEqual(lines.process.program, 'MATLAB'); % MATLAB's Python runs no script
            testCase.verifyEqual(mark, dir(a.log_path).bytes);
            a.enable("Holding", true);
            lines = a.writes_since(mark);
            testCase.verifyEqual([string(lines.stem), string(lines.outcome)], ["HoldingEnable", "ok"]);
            testCase.verifyEqual(numel(a.writes_since()), 2);
        end

        function theLogStaysPutAfterACdAndAPythonRestart(testCase)
            % a relative LogDir= is taken from the folder MATLAB is in when the object is made (its
            % Python follows MATLAB's cd); a reconnect logs to the same file, the fake's too
            folder = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture).Folder;
            mkdir(fullfile(folder, 'trial2'));
            testCase.applyFixture(matlab.unittest.fixtures.CurrentFolderFixture(folder));
            py.setattr(py.importlib.import_module('tempfile'), 'tempdir', folder); % the fake's folder, removed after
            given = ommm.Amplifier(Fake=fullfile(testCase.Data, 'vclamp.json'), LogDir="ommm-logs");
            fake = ommm.Amplifier(Fake=fullfile(testCase.Data, 'vclamp.json'));
            logs = [given.log_path, fake.log_path];
            given.set("Holding", -40, "mV");
            fake.set("Holding", -40, "mV");
            cd trial2
            terminate(pyenv)
            given.set("Holding", -60, "mV");
            fake.set("Holding", -60, "mV");
            testCase.verifyEqual([given.log_path, fake.log_path], logs);
            testCase.verifyEqual([given.writes_since().target], [-0.04, -0.06]);
            testCase.verifyEqual([fake.writes_since().target], [-0.04, -0.06]);
        end

        function loadConfigPlansOnTheFakeAndSendsNothing(testCase)
            a = testCase.bothTabs();
            p = a.load_config(fullfile(testCase.Data, 'synthetic.mcc'), Changes={"Feedback Resistor", 500, "MΩ", "V-Clamp"});
            testCase.verifyEqual(p.outcome, 'planned');
            testCase.verifyTrue(startsWith(p.reason, "Feedback Resistor (V-Clamp) 5 GΩ → 500 MΩ; the mode stays V-Clamp"));
            testCase.verifyEqual([p.before.FeedbackResistorVC1, p.target.FeedbackResistorVC1], [2, 1]);
            testCase.verifyEqual(a.get("Feedback Resistor", "MΩ"), 5000);
            testCase.verifyEmpty(a.writes_since());
            refused = a.load_config(fullfile(testCase.Data, 'synthetic.mcc'), Changes={"Holding", -60, "mV", "V-Clamp"});
            testCase.verifyEqual(refused.reason, 'Holding is set through the API, not in the file: load the file, then set it');
        end

        function loadConfigConfirmedTakesTheNewCommander(testCase)
            % about 5 s: ommm waits for Commander to settle after a start. Holding on before it comes
            % back off at 0 mV, as on the model cell, and the write says so; ommm does not turn
            % it on again
            a = testCase.bothTabs();
            a.set("Holding", -60, "mV");
            a.enable("Holding", true);
            w = a.load_config(fullfile(testCase.Data, 'synthetic.mcc'), Changes={"Feedback Resistor", 500, "MΩ", "V-Clamp"}, Confirmed=true);
            testCase.verifyEqual(w.outcome, 'ok');
            testCase.verifyEqual([w.before.FeedbackResistorVC1, w.after.FeedbackResistorVC1], [2, 1]);
            testCase.verifySubstring(w.reason, ['Holding was on at -60 mV before the restart; Commander came back ' ...
                'with it off at 0 mV: set Holding to -60 mV, then turn it on']);
            testCase.verifyEqual([a.get("Feedback Resistor", "MΩ"), a.get("Holding", "mV")], [500, 0]); % this object's new handle
            testCase.verifyFalse(a.get("HoldingEnable"));
            a.gui.enable("Holding", true); % the window of the Commander now running
            testCase.verifyTrue(a.get("HoldingEnable"));
            try
                a.load_config(fullfile(testCase.Data, 'no-such.mcc'), Confirmed=true);
                testCase.verifyFail('a load of a missing file returned');
            catch err
                testCase.verifyEqual(err.identifier, 'ommm:refused'); % a refused write, not a bad argument
                testCase.verifyEqual(err.write.outcome, 'refused');
                testCase.verifySubstring(err.write.reason, 'cannot read');
            end
        end

        function reconnectTakesANewHandleOnTheSameCommander(testCase)
            a = testCase.bothTabs();
            a.gui.set("Holding", -20, "mV");
            a.reconnect();
            testCase.verifyEqual(a.get("Holding", "mV"), -20);
            a.gui.set("Holding", -30, "mV");
            testCase.verifyEqual(a.get("Holding", "mV"), -30);
        end

        % Python and the fake

        function otherTabNeedsFake(testCase)
            testCase.verifyError(@() ommm.Amplifier(OtherTab=testCase.Fixture), 'ommm:fake');
        end

        function aCallAfterTerminatePyenvJustWorks(testCase)
            % each call that reaches Python reconnects first when Python restarted since
            terminate(pyenv)
            testCase.verifyEqual(testCase.Amp.snapshot().readings.Mode, 0);
            terminate(pyenv)
            testCase.verifyEqual(testCase.Amp.get("Mode"), "V-Clamp");
            terminate(pyenv)
            testCase.verifyEqual(testCase.Amp.state().mode, 'V-Clamp');
            terminate(pyenv)
            testCase.verifyEqual(testCase.Amp.set("Holding", -10, "mV").outcome, 'ok');
            terminate(pyenv)
            testCase.verifyEqual(testCase.Amp.plan("Holding", -10, "mV").outcome, 'planned'); % a new fake, from its file
            terminate(pyenv)
            testCase.Amp.gui.set("Holding", -20, "mV"); % the new fake's window
            testCase.verifyEqual(testCase.Amp.get("Holding", "mV"), -20);
        end

        function aCallAfterPythonDiedJustWorks(testCase)
            testCase.assumeFalse(ispc, 'kills the Python host with kill -9');
            system("kill -9 " + pyenv().ProcessID);
            testCase.verifyEqual(testCase.Amp.snapshot().readings.Mode, 0);
        end

        function aLoadedAmplifierConnectsAgainOnItsFirstCall(testCase)
            % a .mat holds no Python handle, so save and load do not warn, and the loaded object
            % connects again on its first call, as after a Python restart (with Fake=, a new fake)
            file = fullfile(testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture).Folder, 'trial.mat');
            a = testCase.Amp;
            a.set("Holding", -10, "mV");
            lastwarn("");
            save(file, "a");
            loaded = load(file);
            testCase.verifyEmpty(lastwarn);
            testCase.verifyEqual(loaded.a.get("Holding", "mV"), 0); % the same session: its own new fake
            testCase.verifyEqual(a.get("Holding", "mV"), -10); % the saved one still connected
            terminate(pyenv)
            loaded = load(file);
            testCase.verifyEqual(loaded.a.set("Holding", -20, "mV").outcome, 'ok');
            testCase.verifyEqual(loaded.a.fake, string(testCase.Fixture));
        end

        function recoversFromTheCachedFailedLookup(testCase)
            % a py.* call after the host died restarts Python without the .venv, and MATLAB caches
            % the failed py.ommm lookup (seen on Windows, MATLAB R2026b)
            terminate(pyenv)
            py.list();
            testCase.verifyError(@() py.ommm.provenance(), ?MException);
            testCase.verifyError(@() py.ommm.provenance(), 'MATLAB:undefinedVarOrClass');
            amp = ommm.Amplifier(Fake=testCase.Fixture);
            testCase.verifyEqual(amp.get("Mode"), "V-Clamp");
        end

        function refusesAnotherLoadedPython(testCase)
            testCase.assumeFalse(ispc, 'uses the .venv''s bin/python link as the other interpreter');
            venv = fullfile(fileparts(fileparts(fileparts(mfilename('fullpath')))), '.venv');
            ommmPython = pyenv().Executable;
            terminate(pyenv)
            pyenv(Version=fullfile(venv, 'bin', 'python'), ExecutionMode="OutOfProcess");
            py.list();
            % Put ommm's Python back as MATLAB's saved one, or the next test's leftover py objects
            % restart the other Python before ommm.Amplifier can switch
            testCase.addTeardown(@() pyenv(Version=ommmPython, ExecutionMode="OutOfProcess"));
            testCase.addTeardown(@() terminate(pyenv));
            testCase.verifyError(@() ommm.Amplifier(Fake=testCase.Fixture), 'ommm:otherPython');
        end

        function warnsWhenItChangesTheSavedPython(testCase)
            % pyenv's setting outlasts the MATLAB session, so ommm never changes it silently
            testCase.assumeFalse(ispc, 'uses the .venv''s bin/python link as the other interpreter');
            venv = fullfile(fileparts(fileparts(fileparts(mfilename('fullpath')))), '.venv');
            testCase.Amp = []; % its py objects released while Python runs
            terminate(pyenv)
            pyenv(Version=fullfile(venv, 'bin', 'python'), ExecutionMode="OutOfProcess");
            testCase.verifyWarning(@() ommm.Amplifier(Fake=testCase.Fixture), 'ommm:pyenvChanged');
            terminate(pyenv)
            testCase.verifyWarningFree(@() ommm.Amplifier(Fake=testCase.Fixture));
        end

        function refusesAnotherClonesOmmm(testCase)
            % a second clone's class in the same MATLAB session, after this clone's ommm was imported:
            % uv clones share one interpreter, so ommm:otherPython cannot tell them apart. The other
            % clone is the class and a .venv made from the same interpreter, all startPython reads
            root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
            other = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture).Folder;
            mkdir(fullfile(other, 'matlab', '+ommm'));
            copyfile(fullfile(root, 'matlab', '+ommm', '*.m'), fullfile(other, 'matlab', '+ommm'));
            if ispc
                mkdir(fullfile(other, '.venv', 'Lib', 'site-packages'));
            else
                mkdir(fullfile(other, '.venv', 'lib', 'python3', 'site-packages'));
            end
            copyfile(fullfile(root, '.venv', 'pyvenv.cfg'), fullfile(other, '.venv'));
            testCase.Amp = []; % no object of this clone's class while the other's shadows it
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(other, 'matlab')));
            testCase.verifyEqual(string(which('ommm.Amplifier')), string(fullfile(other, 'matlab', '+ommm', 'Amplifier.m')));
            try
                ommm.Amplifier(Fake=testCase.Fixture);
                testCase.verifyFail('another clone''s class ran this clone''s ommm');
            catch err
                testCase.verifyEqual(err.identifier, 'ommm:otherClone');
                testCase.verifySubstring(err.message, sprintf('imports ommm from %s, not from this clone, %s:', root, other));
            end
        end

        function offWindowsSaysToUseFake(testCase)
            testCase.assumeFalse(ispc, 'Commander runs on Windows');
            try
                ommm.Amplifier();
                testCase.verifyFail('ommm.Amplifier() connected off Windows');
            catch err
                testCase.verifyEqual(err.identifier, 'ommm:commander');
                testCase.verifySubstring(err.message, 'ommm.Amplifier(Fake=FILE) in MATLAB');
            end
        end

        function missingFakeFileIsAnError(testCase)
            testCase.verifyError(@() ommm.Amplifier(Fake="no/such/snapshot.json"), 'ommm:fake');
            testCase.verifyError(@() ommm.Amplifier(Fake=testCase.Fixture, OtherTab="no/such/snapshot.json"), 'ommm:fake');
        end

        function anArgumentOmmmCannotUseIsABadArgument(testCase)
            % Python's ValueError: no write, so not ommm:refused
            testCase.verifyError(@() ommm.Amplifier(Fake=fullfile(testCase.Data, 'synthetic.mcc')), 'ommm:badArgument');
            folder = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture).Folder;
            file = fullfile(folder, 'a file');
            writelines("x", file);
            try
                ommm.Amplifier(Fake=testCase.Fixture, LogDir=file);
                testCase.verifyFail('a file took the write log');
            catch err
                testCase.verifyEqual(err.identifier, 'ommm:badArgument');
                testCase.verifySubstring(err.message, 'cannot hold the write log');
            end
        end
    end
end
