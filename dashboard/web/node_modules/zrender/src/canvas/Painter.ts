import {devicePixelRatio} from '../config';
import * as util from '../core/util';
import Layer, { isIncrementalLayer, LayerConfig, LayerDrawCursor } from './Layer';
import requestAnimationFrame from '../animation/requestAnimationFrame';
import env from '../core/env';
import Displayable from '../graphic/Displayable';
import {
    IncrementalIdCompat, NullUndefined, WXCanvasRenderingContext,
    ZLevel, ZLevel2, ZLEVEL2_INCREMENTAL, ZLEVEL2_NORMAL_ABOVE, ZLEVEL2_NORMAL_BELOW
} from '../core/types';
import { GradientObject } from '../graphic/Gradient';
import { ImagePatternObject } from '../graphic/Pattern';
import Storage from '../Storage';
import { brush, brushLoopFinalize, BrushScope, brushSingle } from './graphic';
import { PainterBase } from '../PainterBase';
import BoundingRect from '../core/BoundingRect';
import { REDRAW_BIT } from '../graphic/constants';
import { getSize } from './helper';
import { platformApi } from '../core/platform';


const HOVER_LAYER_ZLEVEL = 1e5;
// zlevel for the case that `Painter['_singleCanvas']` is `true`.
const CANVAS_ZLEVEL = 314159;

// Truthy value means dirty.
type HoverLayerDirty =
    typeof HOVER_LAYER_DIRTY_NO
    | typeof HOVER_LAYER_DIRTY_REPAINT_IF_EXISTING
    | typeof HOVER_LAYER_DIRTY_REPAINT
// Do noting to hover layer.
const HOVER_LAYER_DIRTY_NO: undefined = undefined;
// Repaint only if existing. In most cases hover layer is not used,
// do not need to travel one more time to detect hover state.
const HOVER_LAYER_DIRTY_REPAINT_IF_EXISTING = 1;
// Create a hover layer if not existing, and repaint.
const HOVER_LAYER_DIRTY_REPAINT = 2;



function isLayerValid(layer: Layer) {
    if (!layer) {
        return false;
    }

    if (layer.__builtin__) {
        return true;
    }

    if (typeof (layer.resize) !== 'function'
        || typeof (layer.refresh) !== 'function'
    ) {
        return false;
    }

    return true;
}

function createRoot(width: number, height: number) {
    const domRoot = document.createElement('div');

    // domRoot.onselectstart = returnFalse; // Avoid page selected
    domRoot.style.cssText = [
        'position:relative',
        // IOS13 safari probably has a compositing bug (z order of the canvas and the consequent
        // dom does not act as expected) when some of the parent dom has
        // `-webkit-overflow-scrolling: touch;` and the webpage is longer than one screen and
        // the canvas is not at the top part of the page.
        // Check `https://bugs.webkit.org/show_bug.cgi?id=203681` for more details. We remove
        // this `overflow:hidden` to avoid the bug.
        // 'overflow:hidden',
        'width:' + width + 'px',
        'height:' + height + 'px',
        'padding:0',
        'margin:0',
        'border-width:0'
    ].join(';') + ';';

    return domRoot;
}

function createBuiltinLayer(
    id: string | HTMLCanvasElement,
    painter: CanvasPainter,
    zlevel: ZLevel,
    zlevel2: ZLevel2
): Layer {
    const layer = new Layer(id, painter, painter.dpr);
    layer.zlevel = zlevel;
    layer.zlevel2 = zlevel2;
    layer.__builtin__ = true;
    resetLayerDrawCursors(layer);
    return layer;
}

interface CanvasPainterOption {
    devicePixelRatio?: number
    width?: number | string  // Can be 10 / 10px / auto
    height?: number | string
    useDirtyRect?: boolean
}

export type CanvasPainterRefreshOpt = {
    // repaint all displayable, rather than only dirty ones.
    paintAll?: boolean;

    // By default true. Can set to false to skip the normal repaint for
    // the case that only hover layer need to be repainted.
    refresh?: boolean;
    // By default false. If true, for repaint hover layer.
    // Note that a hover layer will also be repainted if normal layers are
    // repainted and mark dirty to hover layer, even if refreshHover is false.
    refreshHover?: boolean;
}

type LayerKey = {
    zl: ZLevel;
    zl2: ZLevel2;
};

// const LAYER_CURSOR_IDS_MAX = 1e3; // A safeguard

function resetLayerDrawCursors(layer: Layer): void {
    layer.__cursorStack = [];
    layer.__cursors = util.createHashMap();
}

function resetLayerDrawCursor(cursor: LayerDrawCursor): LayerDrawCursor {
    cursor.startIdx = cursor.drawIdx = cursor.endIdx = cursor.endIdxNew = 0;
    cursor.used = false;
    cursor.first = cursor.last = NaN;
    cursor.notClearIdx = -1;
    // cursor.idsLen = 0;
    // NOTE: cursor.key should not be modified after being created.
    return cursor;
}

// Get the cursor, create one if not exist.
function ensureLayerDrawCursor(layer: Layer, incrementalCompat: IncrementalIdCompat): LayerDrawCursor {
    const cursors = layer.__cursors;
    const incremental = +incrementalCompat;
    return cursors.get(incremental)
        || (
            layer.__cursorStack.push(incremental),
            cursors.set(incremental, resetLayerDrawCursor({key: incremental/*, ids: []*/} as LayerDrawCursor))
        );
}

function eachCursorInLayer(layer: Layer, cb: (cursor: LayerDrawCursor) => void): void {
    const cursorStack = layer.__cursorStack;
    for (let i = 0; i < cursorStack.length; i++) {
        cb(layer.__cursors.get(cursorStack[i]));
    }
}

function ensureLayerListInZLevel(internal: CanvasPainterInternal, zlevel: ZLevel): Layer[] {
    const layers = internal.layers;
    return layers[zlevel] || (layers[zlevel] = new Array(3)); // See `ZLevel2`
}

/**
 * Iterate existing layers in ascending z-order.
 */
function eachLayer(
    internal: CanvasPainterInternal,
    cb: (
        layer: Layer, // Never be null/undefined
        zlevel: number, zlevel2: number, idx: number
    ) => void,
    filter?: EachLayerFilter,
) {
    const layerStack = internal.layerStack;
    for (let i = 0; i < layerStack.length; i++) {
        const zlevel = layerStack[i].zl;
        const zlevel2 = layerStack[i].zl2;
        const layer = internal.layers[zlevel][zlevel2];
        if (!filter || (
            (!(filter & EACH_LAYER_BUILTIN) || layer.__builtin__)
            && (!(filter & EACH_LAYER_NOT_BUILTIN) || !layer.__builtin__)
            && (!(filter & EACH_LAYER_NOT_HOVER) || layer !== internal.hoverlayer)
        )) {
            cb(layer, zlevel, zlevel2, i);
        }
    }
}

// Can be `EACH_LAYER_BUILTIN | EACH_LAYER_NO_HOVER`,
// which means "built-in" and "not hover layer".
// By default `0` means no filter - iterate all layers.
type EachLayerFilter = number;
const EACH_LAYER_BUILTIN = 1;
const EACH_LAYER_NOT_BUILTIN = 2;
const EACH_LAYER_NOT_HOVER = 4;
const EACH_LAYER_BUILTIN_NOT_HOVER = EACH_LAYER_BUILTIN | EACH_LAYER_NOT_HOVER;


interface CanvasPainterInternal {
    // Order is maintained by zlevel and zlevel2.
    // This list represents the existing layers and the actual z-order.
    layerStack: LayerKey[];
    // structure: _layers[zlevel][zlevel2]
    // See more details in CANVAS_LAYER_STACKING
    // CAVEAT:
    //  Do not iterate `layers`; iterate `layerStack` instead.
    layers: Layer[][];

    hoverlayer?: Layer;
}

export default class CanvasPainter implements PainterBase {

    type = 'canvas'

    root: HTMLElement

    dpr: number

    storage: Storage

    private _i: CanvasPainterInternal;

    private _singleCanvas: boolean

    private _opts: CanvasPainterOption

    private _prevDisplayList: Displayable[] = []

    private _layerConfig: {[key: number]: LayerConfig} = {} // key is zlevel

    /**
     * zrender will do compositing when root is a canvas and have multiple zlevels.
     */
    private _needsManuallyCompositing = false

    private _width: number
    private _height: number

    private _domRoot: HTMLElement

    // hover layer is created only when needed, not save dirty flag separately.
    // We need to detect hover layer requirements in this cases:
    //  (A) Hover state exist when the element is drawing, especially in progressive case.
    //  (B) Hover state is applied after the element has been drawn and keep no dirty.
    // We need to avoid repeatedly drawing the hover layer, especially in progressive case.
    // Hover layer should be cleared whenever a normal layer is cleared.
    // otherwise it can not follow the elements changing.
    // For example, the original el may have been moved.
    private _hoverLayerDirty: HoverLayerDirty

    private _redrawId: number

    private _backgroundColor: string | GradientObject | ImagePatternObject


    constructor(root: HTMLElement, storage: Storage, opts: CanvasPainterOption, id: number) {

        this.type = 'canvas';

        this._i = {
            layerStack: [],
            layers: [],
        };

        // In node environment using node-canvas
        const singleCanvas = !root.nodeName // In node ?
            || root.nodeName.toUpperCase() === 'CANVAS';

        this._opts = opts = util.extend({}, opts || {}) as CanvasPainterOption;

        this.dpr = opts.devicePixelRatio || devicePixelRatio;

        this._singleCanvas = singleCanvas;

        this.root = root;

        const rootStyle = root.style;

        if (rootStyle) {
            util.disableUserSelect(root);
            root.innerHTML = '';
        }

        this.storage = storage;

        this._prevDisplayList = [];

        if (!singleCanvas) {
            this._width = getSize(root, 0, opts);
            this._height = getSize(root, 1, opts);

            const domRoot = this._domRoot = createRoot(
                this._width, this._height
            );
            root.appendChild(domRoot);
        }
        else {
            const rootCanvas = root as HTMLCanvasElement;
            let width = rootCanvas.width;
            let height = rootCanvas.height;

            if (opts.width != null) {
                // TODO sting?
                width = opts.width as number;
            }
            if (opts.height != null) {
                // TODO sting?
                height = opts.height as number;
            }
            this.dpr = opts.devicePixelRatio || 1;

            // Use canvas width and height directly
            rootCanvas.width = width * this.dpr;
            rootCanvas.height = height * this.dpr;

            this._width = width;
            this._height = height;

            // Create layer if only one given canvas
            // Device can be specified to create a high dpi image.
            const singleLayer = createBuiltinLayer(rootCanvas, this, CANVAS_ZLEVEL, ZLEVEL2_NORMAL_BELOW);
            singleLayer.initContext();
            // FIXME Use canvas width and height
            // singleLayer.resize(width, height);
            this._insertLayer(singleLayer, CANVAS_ZLEVEL, ZLEVEL2_NORMAL_BELOW, true);

            this._domRoot = root;
        }
    }

    getType() {
        return 'canvas';
    }

    /**
     * If painter use a single canvas
     */
    isSingleCanvas() {
        return this._singleCanvas;
    }

    getViewportRoot() {
        return this._domRoot;
    }

    getViewportRootOffset() {
        const viewportRoot = this.getViewportRoot();
        if (viewportRoot) {
            return {
                offsetLeft: viewportRoot.offsetLeft || 0,
                offsetTop: viewportRoot.offsetTop || 0
            };
        }
    }

    refresh(optOrPaintAll?: CanvasPainterRefreshOpt | CanvasPainterRefreshOpt['paintAll']) {
        let opt: CanvasPainterRefreshOpt;
        if (optOrPaintAll && !util.isObject(optOrPaintAll)) {
            opt = {paintAll: !!optOrPaintAll}; // Backward compatible
        }
        else {
            opt = (optOrPaintAll as CanvasPainterRefreshOpt) || {};
        }
        const refresh = util.retrieve2(opt.refresh, true);
        const refreshHover = util.retrieve2(opt.refreshHover, false);

        if (refreshHover) {
            this._hoverLayerDirty = HOVER_LAYER_DIRTY_REPAINT;
        }

        if (!refresh) {
            if (refreshHover) {
                this._paintHoverList(this.storage.getDisplayList(false));
            }
            return this;
        }

        const list = this.storage.getDisplayList(true);
        this._updateLayerStatus(list, opt.paintAll);

        this._redrawId = Math.random();
        const prevList = this._prevDisplayList;
        this._paintList(list, prevList, this._redrawId);

        // Paint custom layers
        const bgColor = this._backgroundColor;
        eachLayer(this._i, function (layer, zlevel, zlevel2, idx) {
            if (layer.refresh) {
                layer.refresh(idx === 0 ? bgColor : null);
            }
        }, EACH_LAYER_NOT_BUILTIN);

        if (this._opts.useDirtyRect) {
            this._prevDisplayList = list.slice();
        }

        return this;
    }

    private _paintHoverList(list: Displayable[]): void {
        let hoverLayer = this._i.hoverlayer;
        const hoverLayerDirty = this._hoverLayerDirty;
        // Always clear dirty flag before return.
        this._hoverLayerDirty = HOVER_LAYER_DIRTY_NO;

        if (hoverLayerDirty === HOVER_LAYER_DIRTY_NO) {
            return;
        }

        if (!hoverLayer && hoverLayerDirty === HOVER_LAYER_DIRTY_REPAINT) {
            hoverLayer = this._i.hoverlayer = this._ensureLayer(HOVER_LAYER_ZLEVEL);
        }

        if (!hoverLayer) {
            return;
        }

        // Clear the previous content. But use _hoverLayerDirty to avoid
        // unnecessarily repeated clearing.
        hoverLayer.clear();

        const scope: BrushScope = {
            inHover: true,
            viewWidth: this._width,
            viewHeight: this._height,
            beforeBrushParam: {},
        };

        let ctx;
        for (let i = 0, len = list.length; i < len; i++) {
            const el = list[i];
            if (!el.__inHover) {
                continue;
            }
            if (!ctx) {
                ctx = hoverLayer.ctx;
                ctx.save();
            }
            // `el.style` is replaced with `el.__hoverStyle` when and only when hover layer is brushing.
            // Any omission or any over replacing may cause incorrect result.
            // Consider a problematic case:
            //  Suppose an element fades out via `opacity:0`, which is set into `this.style` via `el.attr()`,
            //  and then new styles (including `opacity: 0.8`) are assigned to `this.__hoverStyle` via
            //  `el.useStyle()`, but `saveCurrentToNormalState` uses `this.style`, the element will never be
            //  displayed.
            // And notice upstream libraries, such as echarts, typically call `useStyle()` in every update
            // cycle. It should write to `this.style` as normal, rather than to `__hoverStyle`, since
            // `this.style` is the source of `saveCurrentToNormalState` when state switching.
            const hoverStyle = el.__hoverStyle;
            let originalStyle: Displayable['style'];
            if (hoverStyle) {
                originalStyle = el.style;
                el.style = hoverStyle;
            }
            brush(ctx, el, scope);
            if (hoverStyle) {
                el.style = originalStyle;
            }
        }
        if (ctx) {
            brushLoopFinalize(ctx, scope);
            ctx.restore();
        }
    }

    /**
     * @deprecated
     */
    getHoverLayer() {
        return this._ensureLayer(HOVER_LAYER_ZLEVEL);
    }

    /**
     * @deprecated
     */
    paintOne(ctx: CanvasRenderingContext2D, el: Displayable) {
        brushSingle(ctx, el);
    }

    private _paintList(list: Displayable[], prevList: Displayable[], redrawId?: number) {
        if (this._redrawId !== redrawId) {
            return;
        }

        const finished = this._doPaintList(list, prevList);

        if (this._needsManuallyCompositing) {
            this._compositeManually();
        }

        if (!finished) {
            const self = this;
            requestAnimationFrame(function () {
                self._paintList(list, prevList, redrawId);
            });
        }
        else {
            eachLayer(this._i, function (layer) {
                layer.afterBrush && layer.afterBrush();
            }, EACH_LAYER_BUILTIN_NOT_HOVER);
            // Hover layer may be dirty by user interactions before progressive rendering
            // finished. Therefore we do NOT paint hover layer per frame following _doPaintList,
            // instead, we simply repaint it once after finished.
            this._paintHoverList(list);
        }
    }

    private _compositeManually() {
        const ctx = this._ensureLayer(CANVAS_ZLEVEL).ctx;
        const width = (this._domRoot as HTMLCanvasElement).width;
        const height = (this._domRoot as HTMLCanvasElement).height;
        ctx.clearRect(0, 0, width, height);
        // PENDING, Whether only builtin layer?
        eachLayer(this._i, function (layer) {
            if (layer.virtual) {
                ctx.drawImage(layer.dom, 0, 0, width, height);
            }
        }, EACH_LAYER_BUILTIN);
    }

    private _doPaintList(
        list: Displayable[],
        prevList: Displayable[],
        // Return: `finished`
    ): boolean {
        const painter = this;
        let finished = true;

        eachLayer(this._i, function (layer) {
            let needDraw = false;
            eachCursorInLayer(layer, function (cursor) {
                if (cursor.drawIdx < cursor.endIdx
                    || cursor.notClearIdx >= 0
                ) {
                    needDraw = true;
                }
            });

            if (!needDraw && !layer.__dirty) {
                return;
            }

            const repaintRects = (painter._opts.useDirtyRect && !isIncrementalLayer(layer))
                ? layer.createRepaintRects(list, prevList, painter._width, painter._height) : null;

            const firstLayerKey = painter._i.layerStack[0];
            let contentRetained = true;

            if (layer.__dirty) { // Perform layer clear.
                contentRetained = false;
                layer.__dirty = false;
                const clearColor = (layer.zlevel === firstLayerKey.zl && layer.zlevel2 === firstLayerKey.zl2)
                    ? painter._backgroundColor : null;
                layer.clear(false, clearColor, repaintRects);
            }

            eachCursorInLayer(layer, function (cursor) {
                const cursorFinished = painter._paintPerCursor(
                    layer, cursor, list, repaintRects, contentRetained
                );
                finished = finished && cursorFinished;
            });
        }, EACH_LAYER_BUILTIN_NOT_HOVER);

        if (env.wxa) {
            // Flush for weixin application
            eachLayer(this._i, function (layer) {
                if (layer && layer.ctx && (layer.ctx as WXCanvasRenderingContext).draw) {
                    (layer.ctx as WXCanvasRenderingContext).draw();
                }
            });
        }

        return finished;
    }

    private _paintPerCursor(
        layer: Layer,
        layerCursor: LayerDrawCursor,
        list: Displayable[],
        repaintRects: BoundingRect[] | NullUndefined,
        contentRetained: boolean
        // Return `finished`
    ): boolean {
        const ctx = layer.ctx;

        if (repaintRects) {
            if (!repaintRects.length) {
                layerCursor.drawIdx = layerCursor.endIdx; // Nothing to repaint, mark as finished
            }
            else {
                const dpr = this.dpr;
                // Set repaintRect as clipPath
                for (let r = 0; r < repaintRects.length; ++r) {
                    const rect = repaintRects[r];

                    ctx.save();
                    ctx.beginPath();
                    ctx.rect(
                        rect.x * dpr,
                        rect.y * dpr,
                        rect.width * dpr,
                        rect.height * dpr
                    );
                    ctx.clip();
                    this._paintPerCursorInRect(layer, layerCursor, list, rect, contentRetained);
                    ctx.restore();
                }
            }
        }
        else {
            // Paint all once
            ctx.save();
            this._paintPerCursorInRect(layer, layerCursor, list, null, contentRetained);
            ctx.restore();
        }

        return layerCursor.drawIdx >= layerCursor.endIdx;
    }

    private _paintPerCursorInRect(
        layer: Layer,
        layerCursor: LayerDrawCursor,
        list: Displayable[],
        repaintRect: BoundingRect | NullUndefined,
        contentRetained: boolean,
    ): void {
        const scope: BrushScope = {
            inHover: false,
            allClipped: false,
            prevEl: null,
            viewWidth: this._width,
            viewHeight: this._height,
            beforeBrushParam: {contentRetained}
        };
        const ctx = layer.ctx;
        const useTimer = isIncrementalLayer(layer);
        const startTime = useTimer && platformApi.getTime();

        // NOTICE: This loop is performance-sensitive, especially for large data.
        const drawIdxBegin = layerCursor.drawIdx;
        const notClearIdx = layerCursor.notClearIdx;
        let idx = notClearIdx >= 0 ? Math.min(notClearIdx, drawIdxBegin) : drawIdxBegin;
        for (; idx < layerCursor.endIdx; idx++) {
            const el = list[idx];

            if (idx < drawIdxBegin && !el.notClear) {
                // In this portion, all non-`notClear` elements do not need to be painted.
                continue;
            }

            if (el.__inHover) {
                // To avoid repeatedly repaint hover layer in progressive rendering,
                // set HOVER_LAYER_DIRTY_REPAINT only when needed.
                // Notice rendered el may not be traveled here again if the layer is not dirty,
                // in this case HOVER_LAYER_DIRTY_REPAINT is set via markRedraw() calling
                // zr.refreshHover().
                this._hoverLayerDirty = HOVER_LAYER_DIRTY_REPAINT;
                // NOTE: To ensure a consistent composited visual effect, `el` should be
                // always painted to normal layers regardless of whether it will be painted
                // to a hover layer.
            }

            if (repaintRect != null) {
                const paintRect = el.getPaintRect();
                if (paintRect && paintRect.intersect(repaintRect)) {
                    brush(ctx, el, scope);
                    el.setPrevPaintRect(paintRect);
                }
            }
            else {
                brush(ctx, el, scope);
            }

            if (useTimer) {
                const dTime = platformApi.getTime() - startTime;
                // Give 15 millisecond to draw.
                // The rest elements will be drawn in the next frame.
                // FIXME:
                //  This 15 is unreasonable enough - draw operations execution time is
                //  considerable but not a part of JS execution time here.
                //  We may change to record the last frame end time and compare it here.
                if (dTime > 15) {
                    idx++;
                    break;
                }
            }
        }
        brushLoopFinalize(ctx, scope);

        layerCursor.drawIdx = Math.max(idx, drawIdxBegin); // `idx` may < `drawIdxBegin` due to `notClearIdx`.
    }

    /**
     * FIXME:
     *  Currently layer remove or reuse in different zlevel is not supported due to
     *  the external link.
     *
     * Obtain a layer; create one if not exist.
     *
     * Keep backward compatibile - this method may be called from outside of zrender.
     * i.e., get a webGL layer, or built-in layer in some special cases.
     *
     * A virtual layer can be used in _singleCanvas case.
     * A virtual layer can also be a WebGL layer and assigned to a ZRImage element
     * But it still under management of zrender.
     */
    getLayer(zlevel: ZLevel, virtual?: boolean) {
        return this._ensureLayer(zlevel, 0, virtual);
    }

    /**
     * Obtain a layer; create one if not exist.
     */
    private _ensureLayer(zlevel: ZLevel, zlevel2?: ZLevel2, virtual?: boolean) {
        zlevel2 = zlevel2 || 0;
        const singleCanvas = this._singleCanvas;

        if (singleCanvas && !this._needsManuallyCompositing) {
            zlevel = CANVAS_ZLEVEL;
            zlevel2 = 0;
        }

        let layer = ensureLayerListInZLevel(this._i, zlevel)[zlevel2];

        if (!layer) {
            layer = createBuiltinLayer('zr_' + zlevel + '.' + zlevel2, this, zlevel, zlevel2);

            if (this._layerConfig[zlevel]) {
                util.merge(layer, this._layerConfig[zlevel], true);
            }

            if (virtual
                || (singleCanvas && zlevel !== CANVAS_ZLEVEL)
            ) {
                layer.virtual = true;
            }

            this._insertLayer(layer, zlevel, zlevel2, false);

            // Context is created after dom inserted to document
            // Or excanvas will get 0px clientWidth and clientHeight
            layer.initContext();
        }

        return layer;
    }

    /**
     * Keep backward compatibile - this method may be called from outside of zrender.
     * e.g., insert a webGL layer by echarts-gl.
     */
    insertLayer(zlevel: ZLevel, layer: Layer) {
        this._insertLayer(layer, zlevel, 0, false);
    }

    private _insertLayer(
        layer: Layer,
        zlevel: ZLevel,
        zlevel2: ZLevel2,
        suppressDOMInsert: boolean
    ) {
        const internal = this._i;
        const layersMap = internal.layers;
        const layerStack = internal.layerStack;
        const domRoot = this._domRoot;
        let prevLayer = null;

        if (layersMap[zlevel] && layersMap[zlevel][zlevel2]) {
            if (process.env.NODE_ENV !== 'production') {
                util.logError('ZLevel ' + zlevel + '.' + zlevel2 + ' has been used already');
            }
            return;
        }

        if (!isLayerValid(layer)) {
            if (process.env.NODE_ENV !== 'production') {
                util.logError('Layer of zlevel ' + zlevel + ' is not valid');
            }
            return;
        }

        const len = layerStack.length;
        let i = 0;
        while (i < len
            && (layerStack[i].zl < zlevel
                || (layerStack[i].zl === zlevel && layerStack[i].zl2 < zlevel2)
            )
        ) {
            i++;
        }
        if (i > 0) {
            prevLayer = ensureLayerListInZLevel(internal, layerStack[i - 1].zl)[layerStack[i - 1].zl2];
        }
        layerStack.splice(i, 0, {zl: zlevel, zl2: zlevel2});
        ensureLayerListInZLevel(internal, zlevel)[zlevel2] = layer;

        // Virtual layer will not directly show on the screen.
        // (It can be a WebGL layer and assigned to a ZRImage element)
        // But it still under management of zrender.
        if (!suppressDOMInsert && !layer.virtual) {
            if (prevLayer) {
                const prevDom = prevLayer.dom;
                if (prevDom.nextSibling) {
                    domRoot.insertBefore(
                        layer.dom,
                        prevDom.nextSibling
                    );
                }
                else {
                    domRoot.appendChild(layer.dom);
                }
            }
            else {
                if (domRoot.firstChild) {
                    domRoot.insertBefore(layer.dom, domRoot.firstChild);
                }
                else {
                    domRoot.appendChild(layer.dom);
                }
            }
        }

        layer.painter || (layer.painter = this);
    }

    /**
     * @deprecated
     */
    eachLayer<T>(cb: (this: T, layer: Layer, zlevel: number) => void, context?: T) {
        return eachLayer(this._i, function (layer, zlevel) {
            cb.call(context, layer, zlevel); // zlevel2 should not be exposed.
        });
    }

    /**
     * @deprecated
     * FIXME: built-in layer should not be exposed.
     *
     * Iterate each built-in layer (including hover layer)
     */
    eachBuiltinLayer<T>(cb: (this: T, layer: Layer, zlevel: number) => void, context?: T) {
        return eachLayer(this._i, function (layer, zlevel) {
            cb.call(context, layer, zlevel);
        }, EACH_LAYER_BUILTIN);
    }

    /**
     * Iterate each other layer except built-in layer
     * e.g., get webGL layers by echarts-gl.
     */
    eachOtherLayer<T>(cb: (this: T, layer: Layer, z: number) => void, context?: T) {
        return eachLayer(this._i, function (layer, zlevel) {
            cb.call(context, layer, zlevel);
        }, EACH_LAYER_NOT_BUILTIN);
    }

    /**
     * @deprecated
     * NOTICE: Only for debugging or testing.
     */
    getLayers() {
        const layers: Record<string, Layer> = {};
        eachLayer(this._i, function (layer, zlevel, zlevel2) {
            layers[layer.id] = layer;
        });
        return layers;
    }

    /**
     * @tutorial [CANVAS_INCREMENTAL_LAYER_USE_CASES]
     *  Two use patterns are covered per incremental layer:
     *  [CANVAS_INCREMENTAL_CASE_SINGLE_ELEMENT]
     *    An single incremental element with a customized `buildPath`, using `Displayable['notClear']`
     *    to retain the rendered content.
     *  [CANVAS_INCREMENTAL_CASE_MULTIPLE_ELEMENTS]
     *    A run of consecutive incremental elements, progressively drawing per frame in `_paintList`. This
     *    is not an optimal approach for rendering due to the increasing cost of updating and sorting
     *    `displayList`. However, it support varying styles and can balance the cost between rendering and
     *    hit testing during hover (which may degrade with excessive points in single shape).
     *  Notice, these two patterns can exist simultaneously in the same incremental layer.
     *
     * @tutorial [CANVAS_LAYER_STACKING]
     *  - An `Layer` instance represents a physical layer, typically a HTML Canvas.
     *  - Each `zlevel` will be splitted to 2 or 3 physical layers if incremental elements occur,
     *    designated by `zlevel2`. A full version can be like this:
     *      [[ layer_hover         zlevel:100000                                          ]]
     *      [[ layer_normal_above  zlevel:0, zlevel2:2  (normal el after incremental el)  ]]
     *      [[ layer_incremental   zlevel:0, zlevel2:1  (incremental el)                  ]]
     *      [[ layer_normal_below  zlevel:0, zlevel2:0  (normal el before incremental el) ]]
     *    (But layer_normal_below may be omitted if not needed.)
     *  - Physical layers (HTML Canvas) should not be created excessively, therefore, within a single
     *    `zlevel`, multiple runs of incremental elements share one physical layer (i.e., `zlevel2: 1`).
     *  - Theoretically, a physical layer can switch bettween incremental or non-incremental. But currently
     *    we do not support it.
     *  - [LIMITED_TO_3_CANVAS_LAYERS_PER_ZLEVEL]
     *    To avoid excessive HTML Canvas creation, at most 3 layers can be created for a single `zlevel`.
     *    If two runs of consecutive incremental elements are separated by some normal elements, those normal
     *    elements are painted on `zlevel: 2`, and all incremental elements are painted on `zlevel: 1`,
     *    regardless of `el.z` and `el.z2` settings.
     *    Users can explicitly specify a higher `zlevel` to allow more incremental layers to be created.
     *  - NOTE: Elements do not necessarily have different z or z2 - even if all z or z2 are 0, z-order is
     *    determined by `add(el)` order.
     *
     * @tutorial [DISPLAY_LIST_SORTING_AND_LAYERING]
     *  Currently there are 5 parameters to determine the layer and z-order for each element:
     *      <zlevel, zlevel2, incremental(LayerDrawCursor), z, z2>
     *  Only `zlevel`, `z` and `z2` are user specified.
     *  The `displayList` is sorted only by `zlevel`, `z` and `z2`.
     *  A <`zlevel`, `zlevel2`> pair determines a layer.
     *  A `incremental(LayerDrawCursor)` acts like a "soft layer", representing a run of consecutive
     *  incremental elements. Multiple `LayerDrawCursor`s share one layer.
     *  Users must use different `el.incremental` (a number) to distinguish different runs of consecutive
     *  incremental elements. And each `el.incremental` has its exclusive `LayerDrawCursor`. Take echarts
     *  as an example: if there are multiple "series" requiring incremental, e.g., a bar series and a
     *  candlestick series in a Cartesian, and their zlevel/z/z2 are typicall the same.
     *  See CANVAS_LAYER_SAMPLE_CASE_3 for more details.
     *
     * Consider sample cases below to check the implementation:
     *  - [CANVAS_LAYER_SAMPLE_CASE_1]:
     *    `zlevel:5` is explicitly specified by users.
     *    `zlevel:0` is the default.
     *      [[ layer_hover           zlevel:100000       ]]
     *      [[ layer_normal_above_2  zlevel:5, zlevel2:2 ]]
     *      [[ layer_incremental_2   zlevel:5, zlevel2:1 ]]
     *      [[ layer_normal_below_2  zlevel:5, zlevel2:0 ]]
     *      [[ layer_normal_above_1  zlevel:0, zlevel2:2 ]]
     *      [[ layer_incremental_1   zlevel:0, zlevel2:1 ]]
     *      [[ layer_normal_below_1  zlevel:0, zlevel2:0 ]]
     *  - [CANVAS_LAYER_SAMPLE_CASE_2]:
     *    No elements are before incremental elements.
     *      [[ layer_hover         zlevel: 100000      ]]
     *      [[ layer_normal_above  zlevel:0, zlevel2:2 ]]
     *      [[ layer_incremental   zlevel:0, zlevel2:1 ]]
     *  - [CANVAS_LAYER_SAMPLE_CASE_3]:
     *    Multiple runs of consecutive incremental elements, may (or not) be separated by some normal elements.
     *    Suppose a sorted `displayList` is:
     *      `[{a_nor}, {b_inc:7}, {c_inc:7}, {d_nor}, {e_inc:9}, {f_inc:9}, {g_nor}]`.
     *    Then both incremental:7 and incremental:9 have new elements added.
     *    The sorted `displayList` become:
     *      `[{a_nor}, {b_inc:7}, {c_inc:7}, {m_inc:7}, {d_nor}, {e_inc:9}, {f_inc:9}, {n_inc:9}, {g_nor}]`.
     *    The order can not match the original `displayList` - new elements are inserted in the middle rather
     *    than at the end. Therefore, multiple `layerDrawCursor`s are introduced to manage the pointers separately,
     *    enabling them to share one physical layer.
     *    They are arranged into layers like this:
     *      [[ layer_hover         zlevel:100000                                                         ]]
     *      [[ layer_normal_above  zlevel:0, zlevel2:2 layerDrawCursor:0 {d_nor}, {g_nor}                ]]
     *      [[ layer_incremental   zlevel:0, zlevel2:1 layerDrawCursor:9 {e_inc:9}, {f_inc:9} {n_inc:9}  ]]
     *      [[                                         layerDrawCursor:7 {b_inc:7}, {c_inc:7} {m_inc:7}  ]]
     *      [[ layer_normal_below  zlevel:0, zlevel2:0 layerDrawCursor:0 {a_nor}                         ]]
     *
     * @tutorial [CANVAS_LAYER_DIRTY_RULES]:
     *  Only dirty layer will be cleared and repaint later. `layer.__dirty` is set by:
     *  - REDRAW_BIT of every element. [CANVAS_LAYER_DIRTY_BY_REDRAW_BIT]
     *    For normal layers, currently REDRAW_BIT is the only reliable way to make sure repainting, since
     *    reorder is not checked. So we conservatively always dirty the layers if any REDRAW_BIT occur.
     *    For incremental layers, we aggressively dirty the layer only if drawn elements have REDRAW_BIT,
     *    since redorder of incremental elements hardly occurs.
     *  - Mismatching of `layerDrawCursor.first` and `layerDrawCursor.endIdx`.
     *    [CANVAS_LAYER_CONTENT_RETAINED]:
     *      This strategy is mainly required by progressive rendering, where typicall new elements are
     *      appended, and repaint from the start per frame should be prevented. Otherwise, increasing
     *      draw calls can significantly block rendering. Additionally, If displayList indices of incremental
     *      elements are changed due to preceding elements of other layers, the drawing should not be restarted.
     *      Therefore, we record the first element to shift indices for this case.
     *    [CANVAS_LAYER_FAIL_TO_DIRTY_IF_ONLY_REORDER]:
     *      This strategy has also been applied to normal layers to prevent them from repainting in progressive
     *      frames. Upstream applications should remain the order of elements unchanged if no REDRAW_BIT is
     *      set - no checking for this currently. Otherwise, layers fail to dirty unexpectedly.
     *      Take echarts as an example, consider common patterns: "remove some elements", "modify z/z2 typically
     *      via useState", "clear and recreate all elements per user interaction", "reuse elements if possible
     *      but update attributes and styles per user interaction". Layer dirty can be triggered. If bad cases
     *      occur, more mechanism can be introduced (e.g., record el ids in layerDrawCursor for checking).
     *
     * PENDING:
     *  - [PENDING_SEPARATE_DISPLAY_LIST]:
     *    In CANVAS_INCREMENTAL_CASE_MULTIPLE_ELEMENTS, displayList sorting and `_updateAndAddDisplayable` will be
     *    executed per frame and significantly consume time in high element counts (indicatively, 1e6 in
     *    certain environments). Perhaps displayList can be separated by Layer or by LayerDrawCursor,
     *    and perform targeted optimization - omitting unnecessary sorting and `update()`.
     *  - Also sort displayList by `el.incremental` to automatically ensure consecutive?
     *    Currently, the contiguity can only be ensured by the order of `add()` call.
     */
    private _updateLayerStatus(list: Displayable[], paintAll: boolean): void {
        const painter = this;

        if (painter._singleCanvas) {
            for (let i = 1; i < list.length; i++) {
                const el = list[i];
                if (el.zlevel !== list[i - 1].zlevel || el.incremental) {
                    painter._needsManuallyCompositing = true;
                    break;
                }
            }
        }

        eachLayer(painter._i, function (layer) { // Reset flags
            layer.__dirty = false;
            eachCursorInLayer(layer, function (cursor) {
                cursor.used = false;
                cursor.endIdxNew = 0;
                cursor.notClearIdx = -1;
            });
        }, EACH_LAYER_BUILTIN_NOT_HOVER);

        let prevZLevel: ZLevel;
        let currLayer: Layer = null;
        let currCursor: LayerDrawCursor = null;
        let aboveIncrementalInCurrZLevel = false;

        // NOTE: this loop is performance-sensitive, especially for large data.
        for (let idx = 0, len = list.length; idx < len; idx++) {
            const el = list[idx];
            const zlevel = el.zlevel;
            const elIncremental = el.incremental;
            let zlevel2: ZLevel2;

            if (prevZLevel !== zlevel) { // Then `el` is the first element in this zlevel.
                prevZLevel = zlevel;
                aboveIncrementalInCurrZLevel = false;
            }

            if (elIncremental) {
                aboveIncrementalInCurrZLevel = true;
                zlevel2 = ZLEVEL2_INCREMENTAL;
            }
            else {
                // See LIMITED_TO_3_CANVAS_LAYERS_PER_ZLEVEL
                // If incremental elements appear, all subsequent normal elements use `zlevel2: 2`.
                // else use `zlevel2: 0`.
                zlevel2 = aboveIncrementalInCurrZLevel ? ZLEVEL2_NORMAL_ABOVE : ZLEVEL2_NORMAL_BELOW;
            }

            if (!currLayer || zlevel !== currLayer.zlevel || zlevel2 !== currLayer.zlevel2) {
                // NOTE: now `el` is not necessarily the first element of `currLayer` in this pass, since
                // `zlevel2` is not a sort key of `displayList`. See DISPLAY_LIST_SORTING_AND_LAYERING.
                currLayer = painter._ensureLayer(zlevel, zlevel2);
                currCursor = null;
                if (!currLayer.__builtin__) {
                    util.logError('ZLevel ' + zlevel + ' has been used by unknown layer ' + currLayer.id);
                    continue;
                }
            }
            // Else `currLayer` is not changed, keep using it. This is the most common case,
            // so we retain this past path for performance.

            if (!currCursor || elIncremental !== currCursor.key) {
                // NOTE: now `el` is not necessarily the first element of `currCursor` in this pass, since
                // `incremental` is not a sort key of `displayList`. See DISPLAY_LIST_SORTING_AND_LAYERING.
                currCursor = ensureLayerDrawCursor(currLayer, elIncremental);

                if (!currCursor.used) { // Now `el` is the first element in `currCursor` in this pass.
                    currCursor.used = true;
                    if (!paintAll && currCursor.first === el.id) { // See CANVAS_LAYER_CONTENT_RETAINED
                        const idxShift = idx - currCursor.startIdx;
                        currCursor.startIdx = idx;
                        currCursor.drawIdx += idxShift; // May be further modified at last.
                        currCursor.endIdx += idxShift; // May be further modified at last.
                    }
                    else {
                        currLayer.__dirty = true;
                        currCursor.first = el.id;
                        currCursor.startIdx = currCursor.drawIdx = idx;
                        currCursor.endIdx = idx + 1;
                        // Hereafter, `startIdx` should not changed in this pass.
                    }
                }
            }
            // Else `currCursor` is not changed, keep using it. This is the most common case,
            // so we retain this past path for performance.

            // See CANVAS_LAYER_FAIL_TO_DIRTY_IF_ONLY_REORDER
            // if (zlevel2 !== 1) { // Only for non-incremental layer
            //     const idxInCursor = idx - currCursor.startIdx;
            //     if (idxInCursor < LAYER_CURSOR_IDS_MAX && currCursor.ids[idxInCursor] !== el.id) {
            //         currLayer.__dirty = true;
            //         currCursor.idsLen = idxInCursor;
            //     }
            //     if (currCursor.idsLen < LAYER_CURSOR_IDS_MAX) {
            //         currCursor.ids[currCursor.idsLen++] = el.id;
            //     }
            // }

            currCursor.endIdxNew = idx + 1; // Use `endIdxNew` to further check the retained render at last.

            // See CANVAS_LAYER_DIRTY_BY_REDRAW_BIT
            if ((el.__dirty & REDRAW_BIT)
                && !el.__inHover // Ignore dirty elements in hover layer.
            ) {
                if (!elIncremental // Always dirty the entire normal layer if any dirty occurs.
                    || (!el.notClear && idx < currCursor.drawIdx)
                ) {
                    currLayer.__dirty = true;
                }
                if (elIncremental && el.notClear && currCursor.notClearIdx < 0) {
                    // If `notClear` elements are dirty, do not clear the layer, but they need to be repainted.
                    currCursor.notClearIdx = idx;
                }
            }
        } // The end of displayList travel.

        eachLayer(painter._i, function (layer) {
            const cursorStack = layer.__cursorStack;
            const cursors = layer.__cursors;

            for (let i = cursorStack.length - 1; i >= 0; i--) {
                const cursor = cursors.get(cursorStack[i]);

                if (!cursor.used) { // `cursor` is used in the last pass but not in this pass - need clear.
                    layer.__dirty = true;
                    cursors.removeKey(cursorStack[i]);
                    cursorStack.splice(i, 1);
                }
                else { // `cursor` is newly created or is retained from the last pass.
                    // Layers with the same `zlevel` may be written alternately, and `layerDrawCursor` within
                    // the same layer may be writter alternately, since `zlevel2` and `incremental` are not
                    // sort keys of `displayList`. Therefore, their handling has to be finished at last.
                    const endIdxNew = cursor.endIdxNew;
                    if (isIncrementalLayer(layer)
                        ? endIdxNew < cursor.drawIdx
                        : ( // See CANVAS_LAYER_FAIL_TO_DIRTY_IF_ONLY_REORDER
                            endIdxNew !== cursor.endIdx
                            || !endIdxNew
                            || list[endIdxNew - 1].id !== cursor.last
                        )
                    ) {
                        layer.__dirty = true;
                    }
                    // Otherwise, only drawn tail elements that are not drawn; preserve the drawn ones.
                    cursor.endIdx = cursor.endIdxNew;
                    cursor.last = endIdxNew ? list[endIdxNew - 1].id : NaN;
                }
            }

            if (layer.__dirty) {
                // Once a layer is dirty, all of its layerDrawCursors need to be reset.
                eachCursorInLayer(layer, function (cursor) {
                    // Once dirty, they need to be repainted from the start, since opacity and z-order
                    // should be respected.
                    cursor.drawIdx = cursor.startIdx;
                });
                if (painter._hoverLayerDirty === HOVER_LAYER_DIRTY_NO) {
                    painter._hoverLayerDirty = HOVER_LAYER_DIRTY_REPAINT_IF_EXISTING;
                }
            }

        }, EACH_LAYER_BUILTIN_NOT_HOVER);
    }

    clear() {
        eachLayer(this._i, function (layer) {
            layer.clear();
            resetLayerDrawCursors(layer);
        }, EACH_LAYER_BUILTIN);
        return this;
    }

    setBackgroundColor(backgroundColor: string | GradientObject | ImagePatternObject) {
        this._backgroundColor = backgroundColor;
        eachLayer(this._i, function (layer) {
            layer.setUnpainted();
        });
    }

    configLayer(zlevel: number, config: LayerConfig) {
        if (config) {
            const layerConfig = this._layerConfig;
            if (!layerConfig[zlevel]) {
                layerConfig[zlevel] = config;
            }
            else {
                util.merge(layerConfig[zlevel], config, true);
            }

            eachLayer(this._i, function (layer, zlevel) {
                util.merge(layer, layerConfig[zlevel], true);
            });
        }
    }

    /**
     * Delete all layers of the specified zlevel.
     * e.g., delete a webGL layer by echarts-gl.
     */
    delLayer(zlevel: number) {
        const layerStack = this._i.layerStack;
        const layersMap = this._i.layers;

        for (let i = layerStack.length - 1; i >= 0; i--) {
            const key = layerStack[i];
            if (key.zl === zlevel) {
                const layer = layersMap[zlevel][key.zl2];
                if (layer.__builtin__) {
                    continue;
                }
                layerStack.splice(i, 1);
                layersMap[zlevel][key.zl2] = undefined;
                if (!layer.virtual) {
                    const parentNode = layer.dom.parentNode;
                    parentNode && parentNode.removeChild(layer.dom);
                }
            }
        }
    }

    /**
     * 区域大小变化后重绘
     */
    resize(
        width?: number | string,
        height?: number | string
    ) {
        if (!this._domRoot.style) { // Maybe in node or worker
            if (width == null || height == null) {
                return;
            }
            // TODO width / height may be string
            this._width = width as number;
            this._height = height as number;

            this._ensureLayer(CANVAS_ZLEVEL).resize(width as number, height as number);
        }
        else {
            const domRoot = this._domRoot;
            // FIXME Why ?
            domRoot.style.display = 'none';

            // Save input w/h
            const opts = this._opts;
            const root = this.root;
            width != null && (opts.width = width);
            height != null && (opts.height = height);

            width = getSize(root, 0, opts);
            height = getSize(root, 1, opts);

            domRoot.style.display = '';

            // 优化没有实际改变的resize
            if (this._width !== width || height !== this._height) {
                domRoot.style.width = width + 'px';
                domRoot.style.height = height + 'px';

                eachLayer(this._i, function (layer) {
                    layer.resize(width as number, height as number);
                });

                this.refresh({paintAll: true});
            }

            this._width = width;
            this._height = height;

        }
        return this;
    }

    /**
     * @deprecated
     */
    clearLayer(zlevel: number) {
        util.each(this._i.layers[zlevel], function (layer) {
            if (layer && !layer.__builtin__) {
                layer.clear();
            }
        });
    }

    dispose() {
        this.root.innerHTML = '';

        this.root =
        this.storage =
        this._domRoot =
        this._i = null;
    }

    /**
     * Get canvas which has all thing rendered
     */
    getRenderedCanvas(opts?: {
        backgroundColor?: string | GradientObject | ImagePatternObject
        pixelRatio?: number
    }) {
        opts = opts || {};
        if (this._singleCanvas && !this._compositeManually) {
            return this._i.layers[CANVAS_ZLEVEL][0].dom;
        }

        const imageLayer = new Layer('image', this, opts.pixelRatio || this.dpr);
        imageLayer.initContext();
        imageLayer.clear(false, opts.backgroundColor || this._backgroundColor);

        const ctx = imageLayer.ctx;

        if (opts.pixelRatio <= this.dpr) {
            this.refresh();

            const width = imageLayer.dom.width;
            const height = imageLayer.dom.height;
            eachLayer(this._i, function (layer) {
                if (layer.__builtin__) {
                    ctx.drawImage(layer.dom, 0, 0, width, height);
                }
                else if (layer.renderToCanvas) {
                    ctx.save();
                    layer.renderToCanvas(ctx);
                    ctx.restore();
                }
            });
        }
        else {
            // PENDING, echarts-gl and incremental rendering.
            const scope: BrushScope = {
                inHover: false,
                viewWidth: this._width,
                viewHeight: this._height,
                beforeBrushParam: {},
            };
            const displayList = this.storage.getDisplayList(true);
            for (let i = 0, len = displayList.length; i < len; i++) {
                const el = displayList[i];
                brush(ctx, el, scope);
            }
            brushLoopFinalize(ctx, scope);
        }

        return imageLayer.dom;
    }

    getWidth() {
        return this._width;
    }

    getHeight() {
        return this._height;
    }
};
