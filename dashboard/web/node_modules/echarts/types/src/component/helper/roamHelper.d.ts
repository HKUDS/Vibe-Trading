import ExtensionAPI from '../../core/ExtensionAPI.js';
import Group from 'zrender/lib/graphic/Group.js';
import RoamController, { RoamOption } from './RoamController.js';
import View from '../../coord/View.js';
import { NullUndefined, ComponentMainType, ComponentSubType, RoamPayload, RoamHostComponentOrSeries, RoamOptionMixin } from '../../util/types.js';
import { BoundingRect } from '../../util/graphic.js';
import { EChartsExtensionInstallRegisters } from '../../extension.js';
import { RectLike } from 'zrender/lib/core/BoundingRect.js';
/**
 * An abstraction for some similar impl in roaming.
 *
 * Require action like `registerRoamActionSimply`.
 */
export declare function updateRoamControllerSimply(componentOrSeries: RoamHostComponentOrSeries, api: ExtensionAPI, controller: RoamController, isInSelf: RoamOption['triggerInfo']['isInSelf'], clipRect: BoundingRect | NullUndefined, extraOnRoam?: ((roamOp: 'zoom' | 'pan') => void) | NullUndefined, roamTypeDefault?: RoamOptionMixin['roam'], geoBackwardCompat?: boolean): void;
export declare function createIsInSelfByPointerCheckerEl(pointerCheckerEl: Group): RoamOption['triggerInfo']['isInSelf'];
export declare function registerRoamActionSimply(registers: EChartsExtensionInstallRegisters, mainType: ComponentMainType, subType: ComponentSubType | NullUndefined): void;
export declare function isRoamPayloadHasZoom(payload: RoamPayload): boolean;
export declare function createViewCoordSysSimply(componentOrSeries: RoamHostComponentOrSeries, api: ExtensionAPI, x: number, y: number, width: number, height: number, viewRect?: RectLike | NullUndefined): View;
