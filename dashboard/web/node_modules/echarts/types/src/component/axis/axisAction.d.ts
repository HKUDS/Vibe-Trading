import { ModelFinderIdQuery, ModelFinderIndexQuery, ModelFinderNameQuery } from '../../util/model.js';
import { Payload, AxisBreakOptionIdentifierInAxis, ECActionRefinedEvent } from '../../util/types.js';
import type { EChartsExtensionInstallRegisters } from '../../extension.js';
export interface BaseAxisBreakPayload extends Payload {
    xAxisIndex?: ModelFinderIndexQuery;
    xAxisId?: ModelFinderIdQuery;
    xAxisName?: ModelFinderNameQuery;
    yAxisIndex?: ModelFinderIndexQuery;
    yAxisId?: ModelFinderIdQuery;
    yAxisName?: ModelFinderNameQuery;
    singleAxisIndex?: ModelFinderIndexQuery;
    singleAxisId?: ModelFinderIdQuery;
    singleAxisName?: ModelFinderNameQuery;
    breaks: AxisBreakOptionIdentifierInAxis[];
}
export interface ExpandAxisBreakPayload extends BaseAxisBreakPayload {
    type: typeof AXIS_BREAK_EXPAND_ACTION_TYPE;
}
export interface CollapseAxisBreakPayload extends BaseAxisBreakPayload {
    type: typeof AXIS_BREAK_COLLAPSE_ACTION_TYPE;
}
export interface ToggleAxisBreakPayload extends BaseAxisBreakPayload {
    type: typeof AXIS_BREAK_TOGGLE_ACTION_TYPE;
}
export declare type AxisBreakChangedEventBreak = AxisBreakOptionIdentifierInAxis & {
    xAxisIndex?: ModelFinderIndexQuery;
    yAxisIndex?: ModelFinderIndexQuery;
    singleAxisIndex?: ModelFinderIndexQuery;
    isExpanded: boolean;
    old: {
        isExpanded: boolean;
    };
};
export interface AxisBreakChangedEvent extends ECActionRefinedEvent {
    type: typeof AXIS_BREAK_CHANGED_EVENT_TYPE;
    fromAction: typeof AXIS_BREAK_EXPAND_ACTION_TYPE | typeof AXIS_BREAK_COLLAPSE_ACTION_TYPE | typeof AXIS_BREAK_TOGGLE_ACTION_TYPE;
    fromActionPayload: ExpandAxisBreakPayload | CollapseAxisBreakPayload | ToggleAxisBreakPayload;
    breaks: AxisBreakChangedEventBreak[];
}
export declare const AXIS_BREAK_EXPAND_ACTION_TYPE: "expandAxisBreak";
export declare const AXIS_BREAK_COLLAPSE_ACTION_TYPE: "collapseAxisBreak";
export declare const AXIS_BREAK_TOGGLE_ACTION_TYPE: "toggleAxisBreak";
declare const AXIS_BREAK_CHANGED_EVENT_TYPE: "axisbreakchanged";
export declare function registerAction(registers: EChartsExtensionInstallRegisters): void;
export {};
