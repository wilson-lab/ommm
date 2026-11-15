classdef WriteError < MException
    % A write ommm refused, sending nothing (identifier ommm:refused), or that did not take
    % (ommm:writeError): err.write is the write as set returns it, with what was read, sent and read
    % back, its outcome and the reason (docs/matlab.md, Errors). Every ommm:refused is one; an
    % argument ommm cannot use is an MException ommm:badArgument, with no write.

    properties (SetAccess = private)
        write   % struct: label, stem, mode, before, target, after, outcome, reason, ...
    end

    methods
        function err = WriteError(identifier, message, write)
            err@MException(identifier, '%s', message);
            err.write = write;
        end
    end
end
