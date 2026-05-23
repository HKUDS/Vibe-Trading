import type Group from 'zrender/lib/graphic/Group.js';
import type ComponentModel from '../../model/Component.js';
import { NullUndefined, RoamOptionMixin } from '../../util/types.js';
import ExtensionAPI from '../../core/ExtensionAPI.js';
import BoundingRect from 'zrender/lib/core/BoundingRect.js';
import { MatrixArray } from 'zrender/lib/core/matrix.js';
export declare function getThumbnailBridge(model: ComponentModel): ThumbnailBridge | NullUndefined;
export declare function injectThumbnailBridge(model: ComponentModel, thumbnailBridge: ThumbnailBridge | NullUndefined): void;
/**
 * This is the transform from the rendered target elements (e.g., the graph elements, the geo map elements)
 * in their local unit (e.g., geo in longitude-latitude) to screen coord.
 * Typically it is `View['transform']` if `coord/View` is used.
 */
export declare type ThumbnailTargetTransformRawToViewport = MatrixArray;
export interface ThumbnailBridge {
    /**
     * Must be called in `ChartView['render']`/`ComponentView['render']`
     */
    reset(api: ExtensionAPI): void;
    /**
     * Trigger content rendering.
     * Some series, such graph force layout, will update elements asynchronously,
     * therefore rendering and register are separated.
     */
    renderContent(opt: {
        roamType: RoamOptionMixin['roam'];
        viewportRect: BoundingRect;
        group: Group;
        targetTrans: ThumbnailTargetTransformRawToViewport;
        api: ExtensionAPI;
    }): void;
    updateWindow(targetTrans: ThumbnailTargetTransformRawToViewport, api: ExtensionAPI): void;
}
