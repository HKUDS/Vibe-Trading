import ComponentView from '../../view/Component.js';
import ToolboxModel from './ToolboxModel.js';
import GlobalModel from '../../model/Global.js';
import ExtensionAPI from '../../core/ExtensionAPI.js';
import { Payload, NullUndefined } from '../../util/types.js';
import { ToolboxFeature, ToolboxFeatureOption, UserDefinedToolboxFeature } from './featureManager.js';
import { HashMap } from 'zrender/lib/core/util.js';
declare type FeatureName = string;
declare class ToolboxView extends ComponentView {
    static type: "toolbox";
    /**
     * Current enabled features, including only features having `show: true`.
     */
    _features: HashMap<ToolboxFeature | UserDefinedToolboxFeature | NullUndefined, FeatureName>;
    /**
     * Current enabled feature names, including only features having `show: true`.
     */
    _featureNames: FeatureName[];
    render(toolboxModel: ToolboxModel, ecModel: GlobalModel, api: ExtensionAPI, payload: Payload & {
        newTitle?: ToolboxFeatureOption['title'];
    }): void;
    updateView(toolboxModel: ToolboxModel, ecModel: GlobalModel, api: ExtensionAPI, payload: unknown): void;
    dispose(ecModel: GlobalModel, api: ExtensionAPI): void;
}
export default ToolboxView;
