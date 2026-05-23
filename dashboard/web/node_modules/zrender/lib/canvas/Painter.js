import { devicePixelRatio } from '../config.js';
import * as util from '../core/util.js';
import Layer, { isIncrementalLayer } from './Layer.js';
import requestAnimationFrame from '../animation/requestAnimationFrame.js';
import env from '../core/env.js';
import { ZLEVEL2_INCREMENTAL, ZLEVEL2_NORMAL_ABOVE, ZLEVEL2_NORMAL_BELOW } from '../core/types.js';
import { brush, brushLoopFinalize, brushSingle } from './graphic.js';
import { REDRAW_BIT } from '../graphic/constants.js';
import { getSize } from './helper.js';
import { platformApi } from '../core/platform.js';
var HOVER_LAYER_ZLEVEL = 1e5;
var CANVAS_ZLEVEL = 314159;
var HOVER_LAYER_DIRTY_NO = undefined;
var HOVER_LAYER_DIRTY_REPAINT_IF_EXISTING = 1;
var HOVER_LAYER_DIRTY_REPAINT = 2;
function isLayerValid(layer) {
    if (!layer) {
        return false;
    }
    if (layer.__builtin__) {
        return true;
    }
    if (typeof (layer.resize) !== 'function'
        || typeof (layer.refresh) !== 'function') {
        return false;
    }
    return true;
}
function createRoot(width, height) {
    var domRoot = document.createElement('div');
    domRoot.style.cssText = [
        'position:relative',
        'width:' + width + 'px',
        'height:' + height + 'px',
        'padding:0',
        'margin:0',
        'border-width:0'
    ].join(';') + ';';
    return domRoot;
}
function createBuiltinLayer(id, painter, zlevel, zlevel2) {
    var layer = new Layer(id, painter, painter.dpr);
    layer.zlevel = zlevel;
    layer.zlevel2 = zlevel2;
    layer.__builtin__ = true;
    resetLayerDrawCursors(layer);
    return layer;
}
function resetLayerDrawCursors(layer) {
    layer.__cursorStack = [];
    layer.__cursors = util.createHashMap();
}
function resetLayerDrawCursor(cursor) {
    cursor.startIdx = cursor.drawIdx = cursor.endIdx = cursor.endIdxNew = 0;
    cursor.used = false;
    cursor.first = cursor.last = NaN;
    cursor.notClearIdx = -1;
    return cursor;
}
function ensureLayerDrawCursor(layer, incrementalCompat) {
    var cursors = layer.__cursors;
    var incremental = +incrementalCompat;
    return cursors.get(incremental)
        || (layer.__cursorStack.push(incremental),
            cursors.set(incremental, resetLayerDrawCursor({ key: incremental })));
}
function eachCursorInLayer(layer, cb) {
    var cursorStack = layer.__cursorStack;
    for (var i = 0; i < cursorStack.length; i++) {
        cb(layer.__cursors.get(cursorStack[i]));
    }
}
function ensureLayerListInZLevel(internal, zlevel) {
    var layers = internal.layers;
    return layers[zlevel] || (layers[zlevel] = new Array(3));
}
function eachLayer(internal, cb, filter) {
    var layerStack = internal.layerStack;
    for (var i = 0; i < layerStack.length; i++) {
        var zlevel = layerStack[i].zl;
        var zlevel2 = layerStack[i].zl2;
        var layer = internal.layers[zlevel][zlevel2];
        if (!filter || ((!(filter & EACH_LAYER_BUILTIN) || layer.__builtin__)
            && (!(filter & EACH_LAYER_NOT_BUILTIN) || !layer.__builtin__)
            && (!(filter & EACH_LAYER_NOT_HOVER) || layer !== internal.hoverlayer))) {
            cb(layer, zlevel, zlevel2, i);
        }
    }
}
var EACH_LAYER_BUILTIN = 1;
var EACH_LAYER_NOT_BUILTIN = 2;
var EACH_LAYER_NOT_HOVER = 4;
var EACH_LAYER_BUILTIN_NOT_HOVER = EACH_LAYER_BUILTIN | EACH_LAYER_NOT_HOVER;
var CanvasPainter = (function () {
    function CanvasPainter(root, storage, opts, id) {
        this.type = 'canvas';
        this._prevDisplayList = [];
        this._layerConfig = {};
        this._needsManuallyCompositing = false;
        this.type = 'canvas';
        this._i = {
            layerStack: [],
            layers: []
        };
        var singleCanvas = !root.nodeName
            || root.nodeName.toUpperCase() === 'CANVAS';
        this._opts = opts = util.extend({}, opts || {});
        this.dpr = opts.devicePixelRatio || devicePixelRatio;
        this._singleCanvas = singleCanvas;
        this.root = root;
        var rootStyle = root.style;
        if (rootStyle) {
            util.disableUserSelect(root);
            root.innerHTML = '';
        }
        this.storage = storage;
        this._prevDisplayList = [];
        if (!singleCanvas) {
            this._width = getSize(root, 0, opts);
            this._height = getSize(root, 1, opts);
            var domRoot = this._domRoot = createRoot(this._width, this._height);
            root.appendChild(domRoot);
        }
        else {
            var rootCanvas = root;
            var width = rootCanvas.width;
            var height = rootCanvas.height;
            if (opts.width != null) {
                width = opts.width;
            }
            if (opts.height != null) {
                height = opts.height;
            }
            this.dpr = opts.devicePixelRatio || 1;
            rootCanvas.width = width * this.dpr;
            rootCanvas.height = height * this.dpr;
            this._width = width;
            this._height = height;
            var singleLayer = createBuiltinLayer(rootCanvas, this, CANVAS_ZLEVEL, ZLEVEL2_NORMAL_BELOW);
            singleLayer.initContext();
            this._insertLayer(singleLayer, CANVAS_ZLEVEL, ZLEVEL2_NORMAL_BELOW, true);
            this._domRoot = root;
        }
    }
    CanvasPainter.prototype.getType = function () {
        return 'canvas';
    };
    CanvasPainter.prototype.isSingleCanvas = function () {
        return this._singleCanvas;
    };
    CanvasPainter.prototype.getViewportRoot = function () {
        return this._domRoot;
    };
    CanvasPainter.prototype.getViewportRootOffset = function () {
        var viewportRoot = this.getViewportRoot();
        if (viewportRoot) {
            return {
                offsetLeft: viewportRoot.offsetLeft || 0,
                offsetTop: viewportRoot.offsetTop || 0
            };
        }
    };
    CanvasPainter.prototype.refresh = function (optOrPaintAll) {
        var opt;
        if (optOrPaintAll && !util.isObject(optOrPaintAll)) {
            opt = { paintAll: !!optOrPaintAll };
        }
        else {
            opt = optOrPaintAll || {};
        }
        var refresh = util.retrieve2(opt.refresh, true);
        var refreshHover = util.retrieve2(opt.refreshHover, false);
        if (refreshHover) {
            this._hoverLayerDirty = HOVER_LAYER_DIRTY_REPAINT;
        }
        if (!refresh) {
            if (refreshHover) {
                this._paintHoverList(this.storage.getDisplayList(false));
            }
            return this;
        }
        var list = this.storage.getDisplayList(true);
        this._updateLayerStatus(list, opt.paintAll);
        this._redrawId = Math.random();
        var prevList = this._prevDisplayList;
        this._paintList(list, prevList, this._redrawId);
        var bgColor = this._backgroundColor;
        eachLayer(this._i, function (layer, zlevel, zlevel2, idx) {
            if (layer.refresh) {
                layer.refresh(idx === 0 ? bgColor : null);
            }
        }, EACH_LAYER_NOT_BUILTIN);
        if (this._opts.useDirtyRect) {
            this._prevDisplayList = list.slice();
        }
        return this;
    };
    CanvasPainter.prototype._paintHoverList = function (list) {
        var hoverLayer = this._i.hoverlayer;
        var hoverLayerDirty = this._hoverLayerDirty;
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
        hoverLayer.clear();
        var scope = {
            inHover: true,
            viewWidth: this._width,
            viewHeight: this._height,
            beforeBrushParam: {}
        };
        var ctx;
        for (var i = 0, len = list.length; i < len; i++) {
            var el = list[i];
            if (!el.__inHover) {
                continue;
            }
            if (!ctx) {
                ctx = hoverLayer.ctx;
                ctx.save();
            }
            var hoverStyle = el.__hoverStyle;
            var originalStyle = void 0;
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
    };
    CanvasPainter.prototype.getHoverLayer = function () {
        return this._ensureLayer(HOVER_LAYER_ZLEVEL);
    };
    CanvasPainter.prototype.paintOne = function (ctx, el) {
        brushSingle(ctx, el);
    };
    CanvasPainter.prototype._paintList = function (list, prevList, redrawId) {
        if (this._redrawId !== redrawId) {
            return;
        }
        var finished = this._doPaintList(list, prevList);
        if (this._needsManuallyCompositing) {
            this._compositeManually();
        }
        if (!finished) {
            var self_1 = this;
            requestAnimationFrame(function () {
                self_1._paintList(list, prevList, redrawId);
            });
        }
        else {
            eachLayer(this._i, function (layer) {
                layer.afterBrush && layer.afterBrush();
            }, EACH_LAYER_BUILTIN_NOT_HOVER);
            this._paintHoverList(list);
        }
    };
    CanvasPainter.prototype._compositeManually = function () {
        var ctx = this._ensureLayer(CANVAS_ZLEVEL).ctx;
        var width = this._domRoot.width;
        var height = this._domRoot.height;
        ctx.clearRect(0, 0, width, height);
        eachLayer(this._i, function (layer) {
            if (layer.virtual) {
                ctx.drawImage(layer.dom, 0, 0, width, height);
            }
        }, EACH_LAYER_BUILTIN);
    };
    CanvasPainter.prototype._doPaintList = function (list, prevList) {
        var painter = this;
        var finished = true;
        eachLayer(this._i, function (layer) {
            var needDraw = false;
            eachCursorInLayer(layer, function (cursor) {
                if (cursor.drawIdx < cursor.endIdx
                    || cursor.notClearIdx >= 0) {
                    needDraw = true;
                }
            });
            if (!needDraw && !layer.__dirty) {
                return;
            }
            var repaintRects = (painter._opts.useDirtyRect && !isIncrementalLayer(layer))
                ? layer.createRepaintRects(list, prevList, painter._width, painter._height) : null;
            var firstLayerKey = painter._i.layerStack[0];
            var contentRetained = true;
            if (layer.__dirty) {
                contentRetained = false;
                layer.__dirty = false;
                var clearColor = (layer.zlevel === firstLayerKey.zl && layer.zlevel2 === firstLayerKey.zl2)
                    ? painter._backgroundColor : null;
                layer.clear(false, clearColor, repaintRects);
            }
            eachCursorInLayer(layer, function (cursor) {
                var cursorFinished = painter._paintPerCursor(layer, cursor, list, repaintRects, contentRetained);
                finished = finished && cursorFinished;
            });
        }, EACH_LAYER_BUILTIN_NOT_HOVER);
        if (env.wxa) {
            eachLayer(this._i, function (layer) {
                if (layer && layer.ctx && layer.ctx.draw) {
                    layer.ctx.draw();
                }
            });
        }
        return finished;
    };
    CanvasPainter.prototype._paintPerCursor = function (layer, layerCursor, list, repaintRects, contentRetained) {
        var ctx = layer.ctx;
        if (repaintRects) {
            if (!repaintRects.length) {
                layerCursor.drawIdx = layerCursor.endIdx;
            }
            else {
                var dpr = this.dpr;
                for (var r = 0; r < repaintRects.length; ++r) {
                    var rect = repaintRects[r];
                    ctx.save();
                    ctx.beginPath();
                    ctx.rect(rect.x * dpr, rect.y * dpr, rect.width * dpr, rect.height * dpr);
                    ctx.clip();
                    this._paintPerCursorInRect(layer, layerCursor, list, rect, contentRetained);
                    ctx.restore();
                }
            }
        }
        else {
            ctx.save();
            this._paintPerCursorInRect(layer, layerCursor, list, null, contentRetained);
            ctx.restore();
        }
        return layerCursor.drawIdx >= layerCursor.endIdx;
    };
    CanvasPainter.prototype._paintPerCursorInRect = function (layer, layerCursor, list, repaintRect, contentRetained) {
        var scope = {
            inHover: false,
            allClipped: false,
            prevEl: null,
            viewWidth: this._width,
            viewHeight: this._height,
            beforeBrushParam: { contentRetained: contentRetained }
        };
        var ctx = layer.ctx;
        var useTimer = isIncrementalLayer(layer);
        var startTime = useTimer && platformApi.getTime();
        var drawIdxBegin = layerCursor.drawIdx;
        var notClearIdx = layerCursor.notClearIdx;
        var idx = notClearIdx >= 0 ? Math.min(notClearIdx, drawIdxBegin) : drawIdxBegin;
        for (; idx < layerCursor.endIdx; idx++) {
            var el = list[idx];
            if (idx < drawIdxBegin && !el.notClear) {
                continue;
            }
            if (el.__inHover) {
                this._hoverLayerDirty = HOVER_LAYER_DIRTY_REPAINT;
            }
            if (repaintRect != null) {
                var paintRect = el.getPaintRect();
                if (paintRect && paintRect.intersect(repaintRect)) {
                    brush(ctx, el, scope);
                    el.setPrevPaintRect(paintRect);
                }
            }
            else {
                brush(ctx, el, scope);
            }
            if (useTimer) {
                var dTime = platformApi.getTime() - startTime;
                if (dTime > 15) {
                    idx++;
                    break;
                }
            }
        }
        brushLoopFinalize(ctx, scope);
        layerCursor.drawIdx = Math.max(idx, drawIdxBegin);
    };
    CanvasPainter.prototype.getLayer = function (zlevel, virtual) {
        return this._ensureLayer(zlevel, 0, virtual);
    };
    CanvasPainter.prototype._ensureLayer = function (zlevel, zlevel2, virtual) {
        zlevel2 = zlevel2 || 0;
        var singleCanvas = this._singleCanvas;
        if (singleCanvas && !this._needsManuallyCompositing) {
            zlevel = CANVAS_ZLEVEL;
            zlevel2 = 0;
        }
        var layer = ensureLayerListInZLevel(this._i, zlevel)[zlevel2];
        if (!layer) {
            layer = createBuiltinLayer('zr_' + zlevel + '.' + zlevel2, this, zlevel, zlevel2);
            if (this._layerConfig[zlevel]) {
                util.merge(layer, this._layerConfig[zlevel], true);
            }
            if (virtual
                || (singleCanvas && zlevel !== CANVAS_ZLEVEL)) {
                layer.virtual = true;
            }
            this._insertLayer(layer, zlevel, zlevel2, false);
            layer.initContext();
        }
        return layer;
    };
    CanvasPainter.prototype.insertLayer = function (zlevel, layer) {
        this._insertLayer(layer, zlevel, 0, false);
    };
    CanvasPainter.prototype._insertLayer = function (layer, zlevel, zlevel2, suppressDOMInsert) {
        var internal = this._i;
        var layersMap = internal.layers;
        var layerStack = internal.layerStack;
        var domRoot = this._domRoot;
        var prevLayer = null;
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
        var len = layerStack.length;
        var i = 0;
        while (i < len
            && (layerStack[i].zl < zlevel
                || (layerStack[i].zl === zlevel && layerStack[i].zl2 < zlevel2))) {
            i++;
        }
        if (i > 0) {
            prevLayer = ensureLayerListInZLevel(internal, layerStack[i - 1].zl)[layerStack[i - 1].zl2];
        }
        layerStack.splice(i, 0, { zl: zlevel, zl2: zlevel2 });
        ensureLayerListInZLevel(internal, zlevel)[zlevel2] = layer;
        if (!suppressDOMInsert && !layer.virtual) {
            if (prevLayer) {
                var prevDom = prevLayer.dom;
                if (prevDom.nextSibling) {
                    domRoot.insertBefore(layer.dom, prevDom.nextSibling);
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
    };
    CanvasPainter.prototype.eachLayer = function (cb, context) {
        return eachLayer(this._i, function (layer, zlevel) {
            cb.call(context, layer, zlevel);
        });
    };
    CanvasPainter.prototype.eachBuiltinLayer = function (cb, context) {
        return eachLayer(this._i, function (layer, zlevel) {
            cb.call(context, layer, zlevel);
        }, EACH_LAYER_BUILTIN);
    };
    CanvasPainter.prototype.eachOtherLayer = function (cb, context) {
        return eachLayer(this._i, function (layer, zlevel) {
            cb.call(context, layer, zlevel);
        }, EACH_LAYER_NOT_BUILTIN);
    };
    CanvasPainter.prototype.getLayers = function () {
        var layers = {};
        eachLayer(this._i, function (layer, zlevel, zlevel2) {
            layers[layer.id] = layer;
        });
        return layers;
    };
    CanvasPainter.prototype._updateLayerStatus = function (list, paintAll) {
        var painter = this;
        if (painter._singleCanvas) {
            for (var i = 1; i < list.length; i++) {
                var el = list[i];
                if (el.zlevel !== list[i - 1].zlevel || el.incremental) {
                    painter._needsManuallyCompositing = true;
                    break;
                }
            }
        }
        eachLayer(painter._i, function (layer) {
            layer.__dirty = false;
            eachCursorInLayer(layer, function (cursor) {
                cursor.used = false;
                cursor.endIdxNew = 0;
                cursor.notClearIdx = -1;
            });
        }, EACH_LAYER_BUILTIN_NOT_HOVER);
        var prevZLevel;
        var currLayer = null;
        var currCursor = null;
        var aboveIncrementalInCurrZLevel = false;
        for (var idx = 0, len = list.length; idx < len; idx++) {
            var el = list[idx];
            var zlevel = el.zlevel;
            var elIncremental = el.incremental;
            var zlevel2 = void 0;
            if (prevZLevel !== zlevel) {
                prevZLevel = zlevel;
                aboveIncrementalInCurrZLevel = false;
            }
            if (elIncremental) {
                aboveIncrementalInCurrZLevel = true;
                zlevel2 = ZLEVEL2_INCREMENTAL;
            }
            else {
                zlevel2 = aboveIncrementalInCurrZLevel ? ZLEVEL2_NORMAL_ABOVE : ZLEVEL2_NORMAL_BELOW;
            }
            if (!currLayer || zlevel !== currLayer.zlevel || zlevel2 !== currLayer.zlevel2) {
                currLayer = painter._ensureLayer(zlevel, zlevel2);
                currCursor = null;
                if (!currLayer.__builtin__) {
                    util.logError('ZLevel ' + zlevel + ' has been used by unknown layer ' + currLayer.id);
                    continue;
                }
            }
            if (!currCursor || elIncremental !== currCursor.key) {
                currCursor = ensureLayerDrawCursor(currLayer, elIncremental);
                if (!currCursor.used) {
                    currCursor.used = true;
                    if (!paintAll && currCursor.first === el.id) {
                        var idxShift = idx - currCursor.startIdx;
                        currCursor.startIdx = idx;
                        currCursor.drawIdx += idxShift;
                        currCursor.endIdx += idxShift;
                    }
                    else {
                        currLayer.__dirty = true;
                        currCursor.first = el.id;
                        currCursor.startIdx = currCursor.drawIdx = idx;
                        currCursor.endIdx = idx + 1;
                    }
                }
            }
            currCursor.endIdxNew = idx + 1;
            if ((el.__dirty & REDRAW_BIT)
                && !el.__inHover) {
                if (!elIncremental
                    || (!el.notClear && idx < currCursor.drawIdx)) {
                    currLayer.__dirty = true;
                }
                if (elIncremental && el.notClear && currCursor.notClearIdx < 0) {
                    currCursor.notClearIdx = idx;
                }
            }
        }
        eachLayer(painter._i, function (layer) {
            var cursorStack = layer.__cursorStack;
            var cursors = layer.__cursors;
            for (var i = cursorStack.length - 1; i >= 0; i--) {
                var cursor = cursors.get(cursorStack[i]);
                if (!cursor.used) {
                    layer.__dirty = true;
                    cursors.removeKey(cursorStack[i]);
                    cursorStack.splice(i, 1);
                }
                else {
                    var endIdxNew = cursor.endIdxNew;
                    if (isIncrementalLayer(layer)
                        ? endIdxNew < cursor.drawIdx
                        : (endIdxNew !== cursor.endIdx
                            || !endIdxNew
                            || list[endIdxNew - 1].id !== cursor.last)) {
                        layer.__dirty = true;
                    }
                    cursor.endIdx = cursor.endIdxNew;
                    cursor.last = endIdxNew ? list[endIdxNew - 1].id : NaN;
                }
            }
            if (layer.__dirty) {
                eachCursorInLayer(layer, function (cursor) {
                    cursor.drawIdx = cursor.startIdx;
                });
                if (painter._hoverLayerDirty === HOVER_LAYER_DIRTY_NO) {
                    painter._hoverLayerDirty = HOVER_LAYER_DIRTY_REPAINT_IF_EXISTING;
                }
            }
        }, EACH_LAYER_BUILTIN_NOT_HOVER);
    };
    CanvasPainter.prototype.clear = function () {
        eachLayer(this._i, function (layer) {
            layer.clear();
            resetLayerDrawCursors(layer);
        }, EACH_LAYER_BUILTIN);
        return this;
    };
    CanvasPainter.prototype.setBackgroundColor = function (backgroundColor) {
        this._backgroundColor = backgroundColor;
        eachLayer(this._i, function (layer) {
            layer.setUnpainted();
        });
    };
    CanvasPainter.prototype.configLayer = function (zlevel, config) {
        if (config) {
            var layerConfig_1 = this._layerConfig;
            if (!layerConfig_1[zlevel]) {
                layerConfig_1[zlevel] = config;
            }
            else {
                util.merge(layerConfig_1[zlevel], config, true);
            }
            eachLayer(this._i, function (layer, zlevel) {
                util.merge(layer, layerConfig_1[zlevel], true);
            });
        }
    };
    CanvasPainter.prototype.delLayer = function (zlevel) {
        var layerStack = this._i.layerStack;
        var layersMap = this._i.layers;
        for (var i = layerStack.length - 1; i >= 0; i--) {
            var key = layerStack[i];
            if (key.zl === zlevel) {
                var layer = layersMap[zlevel][key.zl2];
                if (layer.__builtin__) {
                    continue;
                }
                layerStack.splice(i, 1);
                layersMap[zlevel][key.zl2] = undefined;
                if (!layer.virtual) {
                    var parentNode = layer.dom.parentNode;
                    parentNode && parentNode.removeChild(layer.dom);
                }
            }
        }
    };
    CanvasPainter.prototype.resize = function (width, height) {
        if (!this._domRoot.style) {
            if (width == null || height == null) {
                return;
            }
            this._width = width;
            this._height = height;
            this._ensureLayer(CANVAS_ZLEVEL).resize(width, height);
        }
        else {
            var domRoot = this._domRoot;
            domRoot.style.display = 'none';
            var opts = this._opts;
            var root = this.root;
            width != null && (opts.width = width);
            height != null && (opts.height = height);
            width = getSize(root, 0, opts);
            height = getSize(root, 1, opts);
            domRoot.style.display = '';
            if (this._width !== width || height !== this._height) {
                domRoot.style.width = width + 'px';
                domRoot.style.height = height + 'px';
                eachLayer(this._i, function (layer) {
                    layer.resize(width, height);
                });
                this.refresh({ paintAll: true });
            }
            this._width = width;
            this._height = height;
        }
        return this;
    };
    CanvasPainter.prototype.clearLayer = function (zlevel) {
        util.each(this._i.layers[zlevel], function (layer) {
            if (layer && !layer.__builtin__) {
                layer.clear();
            }
        });
    };
    CanvasPainter.prototype.dispose = function () {
        this.root.innerHTML = '';
        this.root =
            this.storage =
                this._domRoot =
                    this._i = null;
    };
    CanvasPainter.prototype.getRenderedCanvas = function (opts) {
        opts = opts || {};
        if (this._singleCanvas && !this._compositeManually) {
            return this._i.layers[CANVAS_ZLEVEL][0].dom;
        }
        var imageLayer = new Layer('image', this, opts.pixelRatio || this.dpr);
        imageLayer.initContext();
        imageLayer.clear(false, opts.backgroundColor || this._backgroundColor);
        var ctx = imageLayer.ctx;
        if (opts.pixelRatio <= this.dpr) {
            this.refresh();
            var width_1 = imageLayer.dom.width;
            var height_1 = imageLayer.dom.height;
            eachLayer(this._i, function (layer) {
                if (layer.__builtin__) {
                    ctx.drawImage(layer.dom, 0, 0, width_1, height_1);
                }
                else if (layer.renderToCanvas) {
                    ctx.save();
                    layer.renderToCanvas(ctx);
                    ctx.restore();
                }
            });
        }
        else {
            var scope = {
                inHover: false,
                viewWidth: this._width,
                viewHeight: this._height,
                beforeBrushParam: {}
            };
            var displayList = this.storage.getDisplayList(true);
            for (var i = 0, len = displayList.length; i < len; i++) {
                var el = displayList[i];
                brush(ctx, el, scope);
            }
            brushLoopFinalize(ctx, scope);
        }
        return imageLayer.dom;
    };
    CanvasPainter.prototype.getWidth = function () {
        return this._width;
    };
    CanvasPainter.prototype.getHeight = function () {
        return this._height;
    };
    return CanvasPainter;
}());
export default CanvasPainter;
;
