import type * as graphic from '../../util/graphic.js';
import type SingleAxisModel from '../../coord/single/AxisModel.js';
import type CartesianAxisModel from '../../coord/cartesian/AxisModel.js';
import type { AxisBaseModel } from '../../coord/AxisBaseModel.js';
import type ExtensionAPI from '../../core/ExtensionAPI.js';
import type CartesianAxisView from './CartesianAxisView.js';
import type { PathProps } from 'zrender/lib/graphic/Path.js';
import type SingleAxisView from './SingleAxisView.js';
import type { AxisBuilderCfg } from './AxisBuilder.js';
import type { BaseAxisBreakPayload } from './axisAction.js';
import type { AxisBaseOption } from '../../coord/axisCommonTypes.js';
import type { AxisBreakOptionIdentifierInAxis, NullUndefined } from '../../util/types.js';
import { LabelLayoutWithGeometry } from '../../label/labelLayoutHelper.js';
import type ComponentModel from '../../model/Component.js';
/**
 * @file The facade of axis break view and mode.
 *  Separate the impl to reduce code size.
 *
 * @caution
 *  Must not import `axis/breakImpl.ts` directly or indirctly.
 *  Must not implement anything in this file.
 */
export declare type AxisBreakHelper = {
    adjustBreakLabelPair(axisInverse: boolean, axisRotation: AxisBuilderCfg['rotation'], layoutPair: (LabelLayoutWithGeometry | NullUndefined)[]): void;
    buildAxisBreakLine(axisModel: AxisBaseModel, group: graphic.Group, transformGroup: graphic.Group, pathBaseProp: PathProps): void;
    rectCoordBuildBreakAxis(axisGroup: graphic.Group, axisView: CartesianAxisView | SingleAxisView, axisModel: CartesianAxisModel | SingleAxisModel, coordSysRect: graphic.BoundingRect, api: ExtensionAPI): void;
    updateModelAxisBreak(model: ComponentModel<AxisBaseOption>, payload: BaseAxisBreakPayload): AxisBreakUpdateResult;
};
export declare type AxisBreakUpdateResult = {
    breaks: (AxisBreakOptionIdentifierInAxis & {
        isExpanded: boolean;
        old: {
            isExpanded: boolean;
        };
    })[];
};
export declare function registerAxisBreakHelperImpl(impl: AxisBreakHelper): void;
export declare function getAxisBreakHelper(): AxisBreakHelper | NullUndefined;
