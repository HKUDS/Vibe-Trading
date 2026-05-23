import { Group } from '../../util/graphic.js';
import { RoamOptionMixin } from '../../util/types.js';
import { ThumbnailBridge, ThumbnailTargetTransformRawToViewport } from '../helper/thumbnailBridge.js';
import ExtensionAPI from '../../core/ExtensionAPI.js';
import type { ThumbnailModel } from './ThumbnailModel.js';
import BoundingRect from 'zrender/lib/core/BoundingRect.js';
export interface ThumbnailBridgeRendered {
    roamType: RoamOptionMixin['roam'];
    group: Group;
    targetTrans: ThumbnailTargetTransformRawToViewport;
    z2Range: {
        min: number;
        max: number;
    };
    viewportRect: BoundingRect;
    renderVersion: number;
}
/**
 * [CAVEAT]: the call order of `ThumbnailView['render']` and other
 *  `ChartView['render']/ComponentView['render']` is not guaranteed.
 */
export declare class ThumbnailBridgeImpl implements ThumbnailBridge {
    private _thumbnailModel;
    private _renderVersion;
    constructor(thumbnailModel: ThumbnailModel);
    reset(api: ExtensionAPI): void;
    renderContent(opt: {
        roamType: RoamOptionMixin['roam'];
        viewportRect: BoundingRect;
        group: Group;
        targetTrans: ThumbnailTargetTransformRawToViewport;
        api: ExtensionAPI;
    }): void;
    updateWindow(targetTrans: ThumbnailTargetTransformRawToViewport, api: ExtensionAPI): void;
}
