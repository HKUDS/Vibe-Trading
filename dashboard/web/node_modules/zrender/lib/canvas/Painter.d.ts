import Layer, { LayerConfig } from './Layer';
import Displayable from '../graphic/Displayable';
import { ZLevel } from '../core/types';
import { GradientObject } from '../graphic/Gradient';
import { ImagePatternObject } from '../graphic/Pattern';
import Storage from '../Storage';
import { PainterBase } from '../PainterBase';
interface CanvasPainterOption {
    devicePixelRatio?: number;
    width?: number | string;
    height?: number | string;
    useDirtyRect?: boolean;
}
export declare type CanvasPainterRefreshOpt = {
    paintAll?: boolean;
    refresh?: boolean;
    refreshHover?: boolean;
};
export default class CanvasPainter implements PainterBase {
    type: string;
    root: HTMLElement;
    dpr: number;
    storage: Storage;
    private _i;
    private _singleCanvas;
    private _opts;
    private _prevDisplayList;
    private _layerConfig;
    private _needsManuallyCompositing;
    private _width;
    private _height;
    private _domRoot;
    private _hoverLayerDirty;
    private _redrawId;
    private _backgroundColor;
    constructor(root: HTMLElement, storage: Storage, opts: CanvasPainterOption, id: number);
    getType(): string;
    isSingleCanvas(): boolean;
    getViewportRoot(): HTMLElement;
    getViewportRootOffset(): {
        offsetLeft: number;
        offsetTop: number;
    };
    refresh(optOrPaintAll?: CanvasPainterRefreshOpt | CanvasPainterRefreshOpt['paintAll']): this;
    private _paintHoverList;
    getHoverLayer(): Layer;
    paintOne(ctx: CanvasRenderingContext2D, el: Displayable): void;
    private _paintList;
    private _compositeManually;
    private _doPaintList;
    private _paintPerCursor;
    private _paintPerCursorInRect;
    getLayer(zlevel: ZLevel, virtual?: boolean): Layer;
    private _ensureLayer;
    insertLayer(zlevel: ZLevel, layer: Layer): void;
    private _insertLayer;
    eachLayer<T>(cb: (this: T, layer: Layer, zlevel: number) => void, context?: T): void;
    eachBuiltinLayer<T>(cb: (this: T, layer: Layer, zlevel: number) => void, context?: T): void;
    eachOtherLayer<T>(cb: (this: T, layer: Layer, z: number) => void, context?: T): void;
    getLayers(): Record<string, Layer>;
    private _updateLayerStatus;
    clear(): this;
    setBackgroundColor(backgroundColor: string | GradientObject | ImagePatternObject): void;
    configLayer(zlevel: number, config: LayerConfig): void;
    delLayer(zlevel: number): void;
    resize(width?: number | string, height?: number | string): this;
    clearLayer(zlevel: number): void;
    dispose(): void;
    getRenderedCanvas(opts?: {
        backgroundColor?: string | GradientObject | ImagePatternObject;
        pixelRatio?: number;
    }): HTMLCanvasElement;
    getWidth(): number;
    getHeight(): number;
}
export {};
