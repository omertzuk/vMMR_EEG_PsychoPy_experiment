classdef LSLMarkerTimestamps < matlab.System
    % LSLMarkerTimestamps - second LSL inlet on 'experiment_markers' that also
    % outputs LSL timestamps, for use in a MATLAB System block in
    % HIamp_record_LSL_DD_vMMR.slx (Simulate using: Interpreted execution).
    %
    % Requires liblsl-Matlab on the MATLAB path (lsl_loadlib etc.).
    % Start the sender (computer B) BEFORE starting the Simulink model.
    %
    % Output y (1x6 double), one row per model step (= per EEG sample):
    %   1 marker      latest marker value received (0 when idle)
    %   2 edge_code   marker code if a 0->code rising edge arrived this step, else 0
    %   3 edge_ts_B   LSL timestamp of that edge, on computer B's clock (NaN if none)
    %   4 offset      inlet.time_correction(): add to B timestamps to get A clock
    %   5 t_A         lsl_local_clock() on computer A at this model step
    %   6 n_pulled    number of LSL samples pulled this step (diagnostic)
    %
    % Offline: edge_ts_A = edge_ts_B + offset. Regress t_A on EEG sample index
    % to map A's LSL clock onto the amplifier sample clock.

    properties (Nontunable)
        StreamName = 'experiment_markers'
        ResolveTimeout = 5          % s
        CorrectionInterval = 1      % s between time_correction() refreshes
    end

    properties (Access = private)
        lib
        inlet
        lastValue = 0
        offset = NaN
        nextCorrection = 0
    end

    methods
        function obj = LSLMarkerTimestamps(varargin)
            setProperties(obj, nargin, varargin{:});
        end
    end

    methods (Access = protected)
        function setupImpl(obj)
            obj.lib = lsl_loadlib();
            res = lsl_resolve_byprop(obj.lib, 'name', obj.StreamName, 1, ...
                                     obj.ResolveTimeout);
            if isempty(res)
                error('LSLMarkerTimestamps: stream "%s" not found.', ...
                      obj.StreamName);
            end
            obj.inlet = lsl_inlet(res{1});
            obj.inlet.open_stream();
            % First call blocks until an initial offset estimate exists;
            % later calls return the background-updated estimate quickly.
            obj.offset = obj.inlet.time_correction();
            obj.nextCorrection = lsl_local_clock(obj.lib) + obj.CorrectionInterval;
        end

        function y = stepImpl(obj)
            tA = lsl_local_clock(obj.lib);
            [chunk, stamps] = obj.inlet.pull_chunk();

            edgeCode = 0;
            edgeTs = NaN;
            for k = 1:numel(stamps)
                v = double(chunk(1, k));
                if v ~= 0 && v ~= obj.lastValue && edgeCode == 0
                    edgeCode = v;
                    edgeTs = stamps(k);
                end
                obj.lastValue = v;
            end

            if tA >= obj.nextCorrection
                obj.offset = obj.inlet.time_correction();
                obj.nextCorrection = tA + obj.CorrectionInterval;
            end

            y = [obj.lastValue, edgeCode, edgeTs, obj.offset, tA, numel(stamps)];
        end

        function releaseImpl(obj)
            if ~isempty(obj.inlet)
                obj.inlet.close_stream();
                obj.inlet = [];
            end
        end

        function num = getNumInputsImpl(~)
            num = 0;
        end

        function sz = getOutputSizeImpl(~)
            sz = [1 6];
        end

        function dt = getOutputDataTypeImpl(~)
            dt = 'double';
        end

        function c = isOutputComplexImpl(~)
            c = false;
        end

        function f = isOutputFixedSizeImpl(~)
            f = true;
        end
    end
end
