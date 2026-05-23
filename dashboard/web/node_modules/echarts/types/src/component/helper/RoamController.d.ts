import Eventful from 'zrender/lib/core/Eventful.js';
import { ZRenderType } from 'zrender/lib/zrender.js';
import { ZRElementEvent, RoamOptionMixin, NullUndefined } from '../../util/types.js';
import { Bind3 } from 'zrender/lib/core/util.js';
import type Component from '../../model/Component.js';
import ExtensionAPI from '../../core/ExtensionAPI.js';
export interface RoamOption {
    zInfo: {
        component: Component;
        z2?: number;
    };
    triggerInfo: {
        roamTrigger: RoamOptionMixin['roamTrigger'] | NullUndefined;
        isInSelf: RoamPointerChecker;
        isInClip?: RoamPointerChecker;
    };
    api: ExtensionAPI;
    zoomOnMouseWheel?: boolean | 'ctrl' | 'shift' | 'alt';
    moveOnMouseMove?: boolean | 'ctrl' | 'shift' | 'alt';
    moveOnMouseWheel?: boolean | 'ctrl' | 'shift' | 'alt';
    /**
     * If fixed the page when pan
     */
    preventDefaultMouseMove?: boolean;
    /**
     * Cursor styles
     */
    cursorGrab?: string;
    cursorGrabbing?: string;
}
declare type RoamBehavior = 'zoomOnMouseWheel' | 'moveOnMouseMove' | 'moveOnMouseWheel';
export interface RoamEventParams {
    'zoom': {
        scale: number;
        originX: number;
        originY: number;
        isAvailableBehavior: Bind3<typeof isAvailableBehavior, null, RoamBehavior, ZRElementEvent>;
    };
    'scrollMove': {
        scrollDelta: number;
        originX: number;
        originY: number;
        isAvailableBehavior: Bind3<typeof isAvailableBehavior, null, RoamBehavior, ZRElementEvent>;
    };
    'pan': {
        dx: number;
        dy: number;
        oldX: number;
        oldY: number;
        newX: number;
        newY: number;
        isAvailableBehavior: Bind3<typeof isAvailableBehavior, null, RoamBehavior, ZRElementEvent>;
    };
}
export declare type RoamEventDefinition = {
    [key in keyof RoamEventParams]: (params: RoamEventParams[key]) => void | undefined;
};
declare type RoamPointerChecker = (e: ZRElementEvent, x: number, y: number) => boolean;
/**
 * An manager of zoom and pan(darg) hehavior.
 * But it is not responsible for updating the view, since view updates vary and can
 * not be handled in a uniform way.
 *
 * Note: regarding view updates:
 *  - Transformabe views typically use `coord/View` (e.g., geo and series.graph roaming).
 *    Some commonly used view update logic has been organized into `roamHelper.ts`.
 *  - Non-transformable views handle updates themselves, possibly involving re-layout,
 *    (e.g., treemap).
 *  - Some scenarios do not require transformation (e.g., dataZoom roaming for cartesian,
 *    brush component).
 */
declare class RoamController extends Eventful<RoamEventDefinition> {
    private _zr;
    private _opt;
    private _dragging;
    private _pinching;
    private _x;
    private _y;
    private _controlType;
    private _enabled;
    readonly enable: (this: this, controlType: RoamOptionMixin['roam'], opt: RoamOption) => void;
    readonly disable: () => void;
    constructor(zr: ZRenderType);
    isDragging(): boolean;
    isPinching(): boolean;
    _checkPointer(e: ZRElementEvent, x: number, y: number): boolean;
    private _decideCursorStyle;
    dispose(): void;
    private _mousedownHandler;
    private _mousemoveHandler;
    private _mouseupHandler;
    private _mousewheelHandler;
    private _pinchHandler;
    private _checkTriggerMoveZoom;
}
declare function isAvailableBehavior(behaviorToCheck: RoamBehavior, e: ZRElementEvent, settings: Pick<RoamOption, RoamBehavior>): boolean;
export default RoamController;
