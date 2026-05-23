import { ThemeRiverSeriesOption } from './ThemeRiverSeries.js';
import { RectLike } from 'zrender/lib/core/BoundingRect.js';
export interface ThemeRiverLayoutInfo {
    rect: RectLike;
    boundaryGap: ThemeRiverSeriesOption['boundaryGap'];
}
export declare const themeRiverLayoutStageHandler: import("../../util/types").StageHandler;
