import { GradientObject } from './graphic/Gradient';
import { PatternObject } from './graphic/Pattern';
import { Dictionary, NullUndefined } from './core/types';
import { CanvasPainterRefreshOpt } from './canvas/Painter';
export interface PainterBase {
    type: string;
    root?: HTMLElement;
    ssrOnly?: boolean;
    resize(width?: number | string, height?: number | string): void;
    refresh(opt?: CanvasPainterRefreshOpt | NullUndefined): void;
    clear(): void;
    renderToString?(): string;
    getType: () => string;
    getWidth(): number;
    getHeight(): number;
    dispose(): void;
    getViewportRoot: () => HTMLElement;
    getViewportRootOffset: () => {
        offsetLeft: number;
        offsetTop: number;
    };
    configLayer(zlevel: number, config: Dictionary<any>): void;
    setBackgroundColor(backgroundColor: string | GradientObject | PatternObject): void;
}
