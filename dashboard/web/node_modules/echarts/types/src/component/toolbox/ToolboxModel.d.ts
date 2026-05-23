import * as featureManager from './featureManager.js';
import ComponentModel from '../../model/Component.js';
import { ComponentOption, BoxLayoutOptionMixin, LayoutOrient, ZRColor, BorderOptionMixin, ItemStyleOption, LabelOption, CommonTooltipOption, Dictionary, ComponentOnCalendarOptionMixin, ComponentOnMatrixOptionMixin } from '../../util/types.js';
import type GlobalModel from '../../model/Global.js';
import type Model from '../../model/Model.js';
export interface ToolboxTooltipFormatterParams {
    componentType: 'toolbox';
    name: string;
    title: string;
    $vars: ['name', 'title'];
}
export interface ToolboxOption extends ComponentOption, ComponentOnCalendarOptionMixin, ComponentOnMatrixOptionMixin, BoxLayoutOptionMixin, BorderOptionMixin {
    mainType?: 'toolbox';
    show?: boolean;
    orient?: LayoutOrient;
    backgroundColor?: ZRColor;
    borderRadius?: number | number[];
    padding?: number | number[];
    itemSize?: number;
    itemGap?: number;
    showTitle?: boolean;
    iconStyle?: ItemStyleOption;
    emphasis?: {
        iconStyle?: ItemStyleOption;
    };
    textStyle?: LabelOption;
    tooltip?: CommonTooltipOption<ToolboxTooltipFormatterParams>;
    /**
     * Write all supported features in the final export option.
     */
    feature?: Partial<Dictionary<featureManager.ToolboxFeatureOption>>;
}
declare class ToolboxModel extends ComponentModel<ToolboxOption> {
    static type: "toolbox";
    type: "toolbox";
    static layoutMode: {
        readonly type: "box";
        readonly ignoreSize: true;
    };
    private _themeFeatureOption;
    init(option: ToolboxOption, parentModel: Model, ecModel: GlobalModel): void;
    optionUpdated(): void;
    static defaultOption: ToolboxOption;
}
export default ToolboxModel;
