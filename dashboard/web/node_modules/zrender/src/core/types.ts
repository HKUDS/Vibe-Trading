export type Dictionary<T> = {
    [key: string]: T
}

/**
 * Not readonly ArrayLike
 * Include Array, TypedArray
 */
export type ArrayLike<T> = {
    [key: number]: T
    length: number
}

/**
 * NOTICE: For historical reason, zrender have not enabled TS config
 * `strictNullChecks` yet. Therefore, a explicitly declared `NullUndefined` can
 * indicate a variable can be `null` or `undefined` without more investigation,
 * but a variable without `NullUndefined` may also be `null` or `undefined`,
 * which has to be determined by the implementation.
 */
export type NullUndefined = null | undefined;

export type ImageLike = HTMLImageElement | HTMLCanvasElement | HTMLVideoElement

// subset of CanvasTextBaseline
export type TextVerticalAlign = 'top' | 'middle' | 'bottom'
    // | 'center' // DEPRECATED

// TODO: Have not support 'start', 'end' yet.
// subset of CanvasTextAlign
export type TextAlign = 'left' | 'center' | 'right'
    // | 'middle' // DEPRECATED

export type FontWeight = 'normal' | 'bold' | 'bolder' | 'lighter' | number;
export type FontStyle = 'normal' | 'italic' | 'oblique';

export type BuiltinTextPosition = 'left' | 'right' | 'top' | 'bottom' | 'inside'
    | 'insideLeft' | 'insideRight' | 'insideTop' | 'insideBottom'
    | 'insideTopLeft' | 'insideTopRight'| 'insideBottomLeft' | 'insideBottomRight';

export type WXCanvasRenderingContext = CanvasRenderingContext2D & {
    draw: () => void
};

export type ZRCanvasRenderingContext = CanvasRenderingContext2D & {
    dpr: number
    __attrCachedBy: boolean | number
}

// Properties zrender will extended to the raw event
type ZREventProperties = {
    zrX: number
    zrY: number
    zrDelta: number

    // 'no_globalout' means: do not trigger "globalout" event to zr user.
    // 'only_globalout" means: only trigger "globalout" event, but do not
    //     trigger other event to zr user.
    zrEventControl: 'no_globalout' | 'only_globalout'

    zrByTouch: boolean
}

export type ZRRawMouseEvent = MouseEvent & ZREventProperties
export type ZRRawTouchEvent = TouchEvent & ZREventProperties
export type ZRRawPointerEvent = TouchEvent & ZREventProperties

export type ZRRawEvent = ZRRawMouseEvent | ZRRawTouchEvent | ZRRawPointerEvent

export type ZRPinchEvent = ZRRawEvent & {
    pinchScale: number
    pinchX: number
    pinchY: number
    gestureEvent: string
}

export type ElementEventName = 'click' | 'dblclick' | 'mousewheel' | 'mouseout' |
    'mouseover' | 'mouseup' | 'mousedown' | 'mousemove' | 'contextmenu' |
    'drag' | 'dragstart' | 'dragend' | 'dragenter' | 'dragleave' | 'dragover' | 'drop' | 'globalout';

export type ElementEventNameWithOn = 'onclick' | 'ondblclick' | 'onmousewheel' | 'onmouseout' |
    'onmouseup' | 'onmousedown' | 'onmousemove' | 'oncontextmenu' |
    'ondrag' | 'ondragstart' | 'ondragend' | 'ondragenter' | 'ondragleave' | 'ondragover' | 'ondrop';

export type RenderedEvent = {
    elapsedTime: number
};

// Useful type methods
export type PropType<TObj, TProp extends keyof TObj> = TObj[TProp];

export type AllPropTypes<T> = PropType<T, keyof T>

export type FunctionPropertyNames<T> = {[K in keyof T]: T[K] extends Function ? K : never}[keyof T];

export type MapToType<T extends Dictionary<any>, S> = {
    [P in keyof T]: T[P] extends Dictionary<any> ? MapToType<T[P], S> : S
}

// See https://www.staging-typescript.org/docs/handbook/advanced-types.html#distributive-conditional-types
// For the case:
// `keyof A | B` does not equals to `Keyof A | Keyof B`
// KeyOfDistributive<A | B> equals to `KeyOfDistributive<A> | KeyOfDistributive<B>`
export type KeyOfDistributive<T> = T extends unknown ? keyof T : never;

export type WithThisType<Func extends (...args: any) => any, This> =
    (this: This, ...args: Parameters<Func>) => ReturnType<Func>;


/**
 * - `0` means incremental rendering is disabled.
 * - A positive integer enables increamental rendering,
 *  And distinguish different runs of consecutive incremental elements.
 * - `1` is preserved from backward compatibility - truthy value will be converted
 *   to `1`.
 *
 * @see DISPLAY_LIST_SORTING_AND_LAYERING for more details.
 */
export type IncrementalId = number;
// Previously `el.incremental` is boolean. This is only used
// for both TS type and value backward compatibility.
// Internal conversion: true => 1, false => 0.
export type IncrementalIdCompat = number | boolean;
export const INCREMENTAL_ID_FALSE = 0;
export const INCREMENTAL_ID_TRUE_COMPAT = 1;


export type ZLevel = number;
// zlevel2 can not be specified by users. It is assigned internally
// and always be 0, 1, 2; never be greater than 2.
export type ZLevel2 =
    typeof ZLEVEL2_NORMAL_ABOVE
    | typeof ZLEVEL2_INCREMENTAL
    | typeof ZLEVEL2_NORMAL_BELOW

export const ZLEVEL2_NORMAL_ABOVE = 2;
export const ZLEVEL2_INCREMENTAL = 1;
export const ZLEVEL2_NORMAL_BELOW = 0;
