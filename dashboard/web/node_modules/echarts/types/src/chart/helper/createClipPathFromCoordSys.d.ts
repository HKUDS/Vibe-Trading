import * as graphic from '../../util/graphic.js';
import SeriesModel from '../../model/Series.js';
import { NullUndefined, SeriesOption } from '../../util/types.js';
import type Cartesian2D from '../../coord/cartesian/Cartesian2D.js';
import type Polar from '../../coord/polar/Polar.js';
import { CoordinateSystem, CoordinateSystemClipArea } from '../../coord/CoordinateSystem.js';
import type Element from 'zrender/lib/Element.js';
declare type SeriesModelWithLineWidth = SeriesModel<SeriesOption & {
    lineStyle?: {
        width?: number;
    };
}>;
export declare function createGridClipPath(cartesian: Cartesian2D, hasAnimation: boolean, seriesModel: SeriesModelWithLineWidth, done?: () => void, during?: (percent: number, clipRect: graphic.Rect) => void): graphic.Rect;
export declare function createPolarClipPath(polar: Polar, hasAnimation: boolean, seriesModel: SeriesModelWithLineWidth): graphic.Sector;
export declare function createClipPath(coordSys: CoordinateSystem, hasAnimation: boolean, seriesModel: SeriesModelWithLineWidth, done?: () => void, during?: (percent: number) => void): graphic.Rect | graphic.Sector;
export declare type ShapeClipKind = typeof SHAPE_CLIP_KIND_NOT_CLIPPED | typeof SHAPE_CLIP_KIND_PARTIALLY_CLIPPED | typeof SHAPE_CLIP_KIND_FULLY_CLIPPED;
export declare const SHAPE_CLIP_KIND_NOT_CLIPPED = 0;
export declare const SHAPE_CLIP_KIND_PARTIALLY_CLIPPED = 1;
export declare const SHAPE_CLIP_KIND_FULLY_CLIPPED = 2;
export declare function updateClipPath(clip: boolean, symbolEl: Element, clipPath: graphic.Path | NullUndefined): void;
export declare function createCoordSysClipAreaSimply(seriesModel: SeriesModel<SeriesOption & {
    clip?: boolean;
}>): CoordinateSystemClipArea | NullUndefined;
export {};
